#!/usr/bin/env python3
"""Índice Angus: el Top 10 con CEDEAR registrado hacia adelante, como un índice.

Reglas
------
- Arranca en un fin de mes (`inception`) con base 100. Cada último día hábil del
  mes se arma el Top 10 con los datos hasta ese cierre (sin look-ahead) y se
  mantiene, en partes iguales al entrar, hasta el fin de mes siguiente.
- Es un índice de precio: no suma dividendos (la línea del SPY tampoco).
- La historia no se reescribe. Cada mes que termina queda congelado en el
  archivo (`periods[].level_end` y sus puntos diarios). Solo el mes en curso se
  recalcula en cada corrida, con las series ajustadas por splits de ese día, así
  que un split no aparece como una caída.
- Si un nombre del mes en curso se queda sin datos (sale del universo, deja de
  cotizar), conserva el último retorno conocido.

Persistencia: `indice_angus.json`, publicado con el sitio y commiteado por el
workflow en las corridas de cierre. Al arrancar se lee primero el publicado y,
si esa descarga falla, la copia local. Si no hay ninguna copia usable y la
descarga falló, no se escribe nada y se deja `.indice_fetch_failed` para que el
workflow no publique un sitio que borre el índice.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
INDEX_PATH = ROOT / "indice_angus.json"
FLAG_PATH = ROOT / ".indice_fetch_failed"
PUBLISHED_INDEX_URL = "https://tabaqueriaparanaarg-beep.github.io/desk-dashboard/indice_angus.json"

INDEX_NAME = "Índice Angus"
INDEX_VARIANT = "cedear"
INDEX_SIZE = 10
BASE = 100.0
LEDGER_VERSION = 1
CHANGES_LIMIT = 12
RULES = (
    "Desk Score v3 (momentum 12-1), solo acciones con CEDEAR, revisión el último día hábil "
    "de cada mes. Entra si está en el Top 10 y sale solo si cae debajo del puesto 20. "
    "Como mucho 3 del mismo sector. Partes iguales."
)
EXPLAINER = (
    "Es el Top 10 con CEDEAR tratado como un índice propio: arrancó el {inception} en 100 "
    "y se compara con el SPY desde ese mismo día. Cada fin de mes se revisa: entran las mejores "
    "del Desk Score y una empresa se queda mientras siga entre las 20 primeras, con como mucho "
    "3 del mismo sector. Todas pesan lo mismo. Lo que ya pasó no se recalcula: "
    "es un registro, no una simulación. No suma dividendos (el SPY tampoco). "
    "Sirve para seguir empresas con fuerza, no es una recomendación de compra."
)


# ── Carga y guardado ─────────────────────────────────────────────────────────


class LoadResult:
    def __init__(self, ledger: dict | None, source: str, write: bool, block_deploy: bool) -> None:
        self.ledger = ledger
        self.source = source
        self.write = write
        self.block_deploy = block_deploy


def empty_ledger() -> dict[str, Any]:
    return {
        "version": LEDGER_VERSION,
        "name": INDEX_NAME,
        "variant": INDEX_VARIANT,
        "base": BASE,
        "inception": None,
        "periods": [],
        "points": [],
    }


def _usable(ledger: Any) -> bool:
    return (
        isinstance(ledger, dict)
        and isinstance(ledger.get("periods"), list)
        and bool(ledger["periods"])
        and isinstance(ledger.get("points"), list)
    )


def resolve_load(
    *,
    published_status: str,
    published_data: Any,
    local_exists: bool,
    local_data: Any,
    local_error: bool,
) -> LoadResult:
    """`published_status`: ok | missing | failed. Mismo criterio que el historial."""
    if published_status == "ok" and _usable(published_data):
        return LoadResult(published_data, "publicado", True, False)
    if local_exists and not local_error and _usable(local_data):
        return LoadResult(local_data, "local", True, False)
    if published_status == "failed" or local_error:
        return LoadResult(None, "sin_copia", False, True)
    if published_status == "ok" and local_exists:
        # Hay un publicado pero vacío o roto, y una copia local que tampoco sirve.
        return LoadResult(None, "publicado_vacio", False, True)
    return LoadResult(None, "nuevo", True, False)


def fetch_published(url: str = PUBLISHED_INDEX_URL, timeout: int = 12) -> tuple[str, Any]:
    """Un intento. 404 es «todavía no existe»; cualquier otro fallo no borra nada."""
    req = urllib.request.Request(url, headers={"User-Agent": "desk-dashboard/1.0"}, method="GET")
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return "ok", json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return ("missing", None) if e.code == 404 else ("failed", None)
    except Exception as e:
        print(f"  índice publicado no disponible ({type(e).__name__})")
        return "failed", None


def read_local(path: Path) -> tuple[bool, Any, bool]:
    if not path.is_file():
        return False, None, False
    try:
        return True, json.loads(path.read_text(encoding="utf-8")), False
    except Exception as e:
        print(f"  índice local ilegible ({type(e).__name__})")
        return True, None, True


def load_previous(
    path: Path = INDEX_PATH,
    fetch: Callable[[], tuple[str, Any]] | None = None,
) -> LoadResult:
    status, data = (fetch or fetch_published)()
    exists, local, error = read_local(path)
    return resolve_load(
        published_status=status,
        published_data=data,
        local_exists=exists,
        local_data=local,
        local_error=error,
    )


def save_ledger(path: Path, ledger: dict, loaded: LoadResult, flag_path: Path = FLAG_PATH) -> bool:
    if not loaded.write or not _usable(ledger):
        if loaded.block_deploy:
            flag_path.write_text(loaded.source + "\n", encoding="utf-8")
        return False
    flag_path.unlink(missing_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)
    return True


# ── Cálculo ──────────────────────────────────────────────────────────────────


def _closes(bars: list[dict] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for b in bars or []:
        d = str(b.get("t") or "")[:10]
        c = b.get("c")
        if len(d) == 10 and c is not None:
            out[d] = float(c)
    return out


def _close_at_or_before(series: dict[str, float], dates: list[str], day: str) -> float | None:
    """Cierre de `day` o, si ese día no cotizó, el último anterior (dentro de `dates`)."""
    if day in series:
        return series[day]
    for d in reversed(dates):
        if d < day and d in series:
            return series[d]
    return None


def pick_holdings(ranked: list[dict], previous: list[str] | None) -> list[str]:
    """Los nombres del índice en un fin de mes, con la regla de la cartera (banda y tope)."""
    import build

    return build.portfolio_pick(ranked, previous, INDEX_VARIANT, size=INDEX_SIZE)


def _period_levels(
    period: dict,
    sessions: list[str],
    closes: dict[str, dict[str, float]],
    upto: str,
) -> list[dict[str, Any]]:
    """Puntos diarios del período, del día siguiente a `start` hasta `upto` inclusive.

    Actualiza `period["last_rets"]` con el último retorno conocido de cada nombre.
    """
    start = period["start"]
    days = [d for d in sessions if start < d <= upto]
    spy = closes.get("SPY") or {}
    spy0 = spy.get(start)
    last_rets: dict[str, float] = dict(period.get("last_rets") or {})
    base: dict[str, float | None] = {s: (closes.get(s) or {}).get(start) for s in period["holdings"]}
    points: list[dict[str, Any]] = []
    for d in days:
        rets: list[float] = []
        for sym in period["holdings"]:
            c0 = base.get(sym)
            c1 = (closes.get(sym) or {}).get(d)
            if c0 and c1:
                last_rets[sym] = c1 / c0 - 1.0
            if sym in last_rets:
                rets.append(last_rets[sym])
            else:
                rets.append(0.0)  # sin ningún dato todavía: queda en el precio de entrada
        level = period["level_start"] * (1.0 + sum(rets) / len(rets)) if rets else period["level_start"]
        s1 = _close_at_or_before(spy, sessions, d)
        spy_level = period["spy_start"] * (s1 / spy0) if spy0 and s1 else None
        points.append({"date": d, "index": round(level, 4), "spy": round(spy_level, 4) if spy_level else None})
    period["last_rets"] = {k: round(v, 6) for k, v in last_rets.items()}
    return points


def update_ledger(
    ledger: dict | None,
    meta_by: dict[str, dict],
    all_bars: dict[str, list[dict]],
    *,
    live_session: str | None = None,
) -> dict:
    """Agrega los cierres nuevos y los fines de mes que falten. Devuelve el ledger.

    Solo usa ruedas cerradas: `live_session` (la rueda abierta) no entra.
    """
    import build

    sessions = [d for d in build.session_dates_from_bars(all_bars.get("SPY") or []) if d != live_session]
    if not sessions:
        return ledger or empty_ledger()
    ends = build.month_end_sessions(sessions)
    closes = {sym: _closes(bars) for sym, bars in all_bars.items()}
    ledger = ledger if _usable(ledger) else empty_ledger()
    periods: list[dict] = ledger["periods"]

    def open_period(day: str, level: float, spy_level: float, previous: list[str] | None) -> dict:
        ranked = build.rank_universe_asof(meta_by, all_bars, day, require_exact_session=True)
        return {
            "start": day,
            "end": None,
            "rules": RULES,
            "holdings": pick_holdings(ranked, previous),
            "level_start": round(level, 4),
            "spy_start": round(spy_level, 4),
        }

    if not periods:
        if not ends:
            return ledger
        inception = ends[-1]
        first = open_period(inception, BASE, BASE, None)
        if not first["holdings"]:
            return ledger
        ledger["inception"] = inception
        periods.append(first)
        ledger["points"] = [{"date": inception, "index": BASE, "spy": BASE}]

    frozen = [p for p in ledger["points"] if p["date"] <= periods[-1]["start"]]
    last = sessions[-1]
    for end in [e for e in ends if e > periods[-1]["start"]]:
        current = periods[-1]
        if end not in sessions:
            break
        pts = _period_levels(current, sessions, closes, end)
        frozen.extend(pts)
        close_pt = pts[-1] if pts else {"index": current["level_start"], "spy": current["spy_start"]}
        current["end"] = end
        current["level_end"] = close_pt["index"]
        current["spy_end"] = close_pt["spy"] if close_pt["spy"] is not None else current["spy_start"]
        current.pop("last_rets", None)
        nxt = open_period(end, current["level_end"], current["spy_end"], current["holdings"])
        if not nxt["holdings"]:
            # Sin ranking ese día (datos incompletos): se mantiene la cartera anterior.
            nxt["holdings"] = list(current["holdings"])
            nxt["note"] = "Sin ranking ese cierre: se mantuvo la cartera anterior."
        periods.append(nxt)
    frozen.extend(_period_levels(periods[-1], sessions, closes, last))
    ledger["points"] = frozen
    ledger["updated_through"] = ledger["points"][-1]["date"] if ledger["points"] else None
    return ledger


# ── Bloque público (datos.json) ──────────────────────────────────────────────


def _max_drawdown(values: list[float]) -> float:
    peak = None
    worst = 0.0
    for v in values:
        if v is None:
            continue
        peak = v if peak is None or v > peak else peak
        if peak:
            worst = min(worst, (v / peak - 1.0) * 100.0)
    return round(worst, 2)


def _ddmmyyyy(iso: str | None) -> str:
    if not iso or len(iso) < 10:
        return "—"
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def public_block(ledger: dict | None, meta_by: dict[str, dict] | None = None) -> dict[str, Any] | None:
    if not _usable(ledger):
        return None
    meta_by = meta_by or {}
    periods = ledger["periods"]
    points = ledger.get("points") or []
    current = periods[-1]
    last = points[-1] if points else {"index": BASE, "spy": BASE, "date": ledger.get("inception")}
    level = float(last["index"])
    spy_level = float(last["spy"]) if last.get("spy") is not None else None

    rets = current.get("last_rets") or {}
    holdings = []
    for sym in current["holdings"]:
        meta = meta_by.get(sym) or {}
        r = rets.get(sym)
        holdings.append(
            {
                "symbol": sym,
                "name": meta.get("name"),
                "sector": meta.get("sector"),
                "return_pct": round(r * 100.0, 2) if r is not None else None,
            }
        )
    holdings.sort(key=lambda h: (-(h["return_pct"] if h["return_pct"] is not None else -1e9), h["symbol"]))

    changes = []
    for prev, nxt in zip(periods, periods[1:]):
        added = [s for s in nxt["holdings"] if s not in prev["holdings"]]
        removed = [s for s in prev["holdings"] if s not in nxt["holdings"]]
        changes.append({"date": nxt["start"], "in": added, "out": removed})
    changes = list(reversed(changes))[:CHANGES_LIMIT]

    month_index = (level / current["level_start"] - 1.0) * 100.0 if current["level_start"] else None
    month_spy = (
        (spy_level / current["spy_start"] - 1.0) * 100.0
        if spy_level is not None and current["spy_start"]
        else None
    )
    total = (level / BASE - 1.0) * 100.0
    total_spy = (spy_level / BASE - 1.0) * 100.0 if spy_level is not None else None
    return {
        "name": ledger.get("name") or INDEX_NAME,
        "inception": ledger.get("inception"),
        "asof": last.get("date"),
        "rules": current.get("rules") or RULES,
        "explainer": EXPLAINER.format(inception=_ddmmyyyy(ledger.get("inception"))),
        "level": round(level, 2),
        "spy_level": round(spy_level, 2) if spy_level is not None else None,
        "return_pct": round(total, 2),
        "spy_return_pct": round(total_spy, 2) if total_spy is not None else None,
        "excess_pct": round(total - total_spy, 2) if total_spy is not None else None,
        "max_drawdown_pct": _max_drawdown([p.get("index") for p in points]),
        "spy_max_drawdown_pct": _max_drawdown([p.get("spy") for p in points]),
        "months": len(periods) - 1,
        "period_start": current["start"],
        "period_return_pct": round(month_index, 2) if month_index is not None else None,
        "period_spy_return_pct": round(month_spy, 2) if month_spy is not None else None,
        "holdings": holdings,
        "members": list(current["holdings"]),
        "prev_members": list(periods[-2]["holdings"]) if len(periods) > 1 else None,
        "changes": changes,
        "curve": [{"date": p["date"], "index": p["index"], "spy": p.get("spy")} for p in points],
    }


def publish(
    *,
    meta_by: dict[str, dict],
    all_bars: dict[str, list[dict]],
    write: bool,
    live_session: str | None = None,
    path: Path = INDEX_PATH,
    flag_path: Path = FLAG_PATH,
    fetch: Callable[[], tuple[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Actualiza el índice y arma el bloque para datos.json. No lanza hacia el build.

    `write`: solo las corridas de cierre guardan el archivo.
    """
    loaded = load_previous(path, fetch=fetch)
    if not loaded.write:
        # Sin la copia anterior no se muestra un índice armado de cero: no sería el registro.
        if write:
            save_ledger(path, empty_ledger(), loaded, flag_path)
        return None, f"Índice Angus: no se pudo leer la copia anterior ({loaded.source}). No se escribe."
    ledger = update_ledger(loaded.ledger, meta_by, all_bars, live_session=live_session)
    saved = save_ledger(path, ledger, loaded, flag_path) if write else False
    block = public_block(ledger, meta_by)
    if block is None:
        return None, "Índice Angus: todavía sin un fin de mes para arrancar."
    verb = "guardado" if saved else "sin guardar (corrida en vivo)" if not write else "sin guardar"
    return block, (
        f"Índice Angus ({loaded.source}, {verb}): {block['level']} desde {_ddmmyyyy(block['inception'])}, "
        f"SPY {block['spy_level']}."
    )
