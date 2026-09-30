#!/usr/bin/env python3
"""Historial del semáforo de entrada.

Cada build guarda una foto por fecha de rueda (veredicto, Desk Score, puesto
y cierre). Una corrida posterior del mismo día pisa esa foto, así el build de
después del cierre se queda con el dato.

Persistencia: archivo `historial_semaforo.json`, publicado junto al sitio y,
si el workflow puede, commiteado de vuelta al repo. Al arrancar se lee primero
el archivo publicado (el más nuevo) y, si esa descarga falla, la copia local.
Si no se puede leer ninguna copia usable, no se reescribe el archivo: mejor
perder la foto de hoy que pisar la historia con una vacía. La primera vez, si
el publicado responde 404 y no hay copia local, se crea el archivo.

La reconstrucción de ~6 meses corre una sola vez y se guarda aparte, en la
clave `reconstructed`, nunca mezclada con las fotos reales. Es provisoria:
cada horizonte (5, 10 o 20 ruedas) la muestra solo mientras haya menos de
PROVISIONAL_MIN_CLOSED_SIGNALS señales verdes reales ya cerradas. A las
PROVISIONAL_PURGE_REAL_DAYS ruedas reales se borra del archivo y de lo publicado.
"""
from __future__ import annotations

import json
import math
import statistics
import time
import urllib.error
import urllib.request
import ssl
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import signals

ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "historial_semaforo.json"
FLAG_PATH = ROOT / ".historial_fetch_failed"
PUBLISHED_HISTORY_URL = (
    "https://tabaqueriaparanaarg-beep.github.io/desk-dashboard/historial_semaforo.json"
)

HORIZONS = (5, 10, 20)
BACKFILL_CALENDAR_DAYS = 183
BACKFILL_WARMUP_SESSIONS = 200
RECENT_LIMIT = 25
FICHA_LIMIT = 8
# Por horizonte: con menos señales verdes reales ya cerradas, se muestran
# las métricas reconstruidas, marcadas como provisorias.
PROVISIONAL_MIN_CLOSED_SIGNALS = 10
# A esta cantidad de ruedas reales la reconstrucción se borra del archivo y del sitio.
PROVISIONAL_PURGE_REAL_DAYS = 60
VERDICTS = ("verde", "ambar", "rojo")

DISCLAIMER = "Resultados pasados no garantizan resultados futuros."
EARNINGS_NOTE = (
    "En los días reconstruidos el chequeo de resultados se tomó como aprobado, "
    "porque ese calendario no se puede armar hacia atrás."
)
DEDUP_RULE = (
    "Se cuenta una señal nueva cuando el ticker pasa a ese color después de una rueda "
    "en la que no lo tenía. Los días seguidos del mismo color no se suman. "
    "El universo cuenta cada nombre, menos SPY, en cada rueda."
)


class LoadResult:
    def __init__(self, history: dict | None, source: str, write: bool, block_deploy: bool) -> None:
        self.history = history
        self.source = source
        self.write = write
        self.block_deploy = block_deploy


def empty_history() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "backfill": {"done": False},
        "snapshots": {},
        "reconstructed": {},
    }


def _num(value: Any, ndigits: int | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    if ndigits is None:
        return number
    return round(number, ndigits)


def _iso(value: Any) -> str | None:
    text = str(value or "")[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            date.fromisoformat(text)
        except ValueError:
            return None
        return text
    return None


def _clean_row(row: dict) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    sym = str(row.get("symbol") or "").upper()
    verdict = str(row.get("verdict") or "")
    close = _num(row.get("close"))
    if not sym or verdict not in VERDICTS or close is None:
        return None
    out: dict[str, Any] = {
        "symbol": sym,
        "verdict": verdict,
        "close": round(close, 4),
    }
    score = _num(row.get("desk_score"), 1)
    if score is not None:
        out["desk_score"] = score
    rank = _num(row.get("rank"))
    if rank is not None:
        out["rank"] = int(rank)
    return out


def make_snapshot(
    session: str,
    rows: list[dict],
    *,
    after_close: bool,
    reconstruido: bool,
) -> dict[str, Any] | None:
    day = _iso(session)
    if day is None:
        return None
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        item = _clean_row(row)
        if item is None or item["symbol"] in seen:
            continue
        seen.add(item["symbol"])
        clean.append(item)
    if not clean:
        return None
    clean.sort(key=lambda r: (r.get("rank") is None, r.get("rank") or 0, r["symbol"]))
    return {
        "date": day,
        "after_close": bool(after_close),
        "reconstruido": bool(reconstruido),
        "earnings_check": "omitido" if reconstruido else "publicado",
        "rows": clean,
    }


def snapshot_from_rows(
    rows: list[dict] | None,
    session: str,
    *,
    after_close: bool,
    reconstruido: bool,
) -> dict[str, Any] | None:
    """Foto del ranking ya calculado (el del día, con calendario real)."""
    packed: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        entry = row.get("entry")
        if not isinstance(entry, dict):
            continue
        packed.append(
            {
                "symbol": row.get("symbol"),
                "verdict": entry.get("verdict"),
                "desk_score": row.get("desk_score"),
                "rank": row.get("rank"),
                "close": row.get("close"),
            }
        )
    return make_snapshot(session, packed, after_close=after_close, reconstruido=reconstruido)


def session_date_from_rows(rows: list[dict] | None) -> str | None:
    """Fecha de rueda del ranking. El `asof` de Alpaca ya trae el día de la sesión."""
    spy = None
    fallback = None
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("asof"):
            continue
        if str(row.get("symbol") or "").upper() == "SPY":
            spy = row
            break
        if fallback is None:
            fallback = row
    raw = (spy or fallback or {}).get("asof")
    return _iso(raw)


def taken_after_close(session: str, now: datetime) -> bool:
    """True si `now` es el cierre de Nueva York (16:00) o un momento posterior de esa rueda."""
    day = _iso(session)
    if day is None:
        return False
    try:
        from zoneinfo import ZoneInfo

        ny = ZoneInfo("America/New_York")
    except Exception:
        ny = timezone(timedelta(hours=-4))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_ny = now.astimezone(ny)
    sess = date.fromisoformat(day)
    if now_ny.date() > sess:
        return True
    if now_ny.date() < sess:
        return False
    close = datetime(sess.year, sess.month, sess.day, 16, 0, tzinfo=ny)
    return now_ny >= close


def upsert_snapshot(history: dict, snapshot: dict | None) -> dict:
    """Una foto real por fecha. La última escritura de ese día gana.

    Nunca entra en la reconstrucción. Si esa fecha estaba ahí, se saca.
    """
    if not snapshot or not snapshot.get("date"):
        return history
    snaps = history.setdefault("snapshots", {})
    if not isinstance(snaps, dict):
        history["snapshots"] = {}
        snaps = history["snapshots"]
    stored = dict(snapshot)
    stored["reconstruido"] = False
    stored["earnings_check"] = "publicado"
    day = str(stored["date"])
    snaps[day] = stored
    recon = history.get("reconstructed")
    if isinstance(recon, dict):
        recon.pop(day, None)
    else:
        history["reconstructed"] = {}
    return history


def needs_backfill(history: dict) -> bool:
    backfill = history.get("backfill")
    return not (isinstance(backfill, dict) and backfill.get("done"))


def apply_backfill(history: dict, snaps: list[dict]) -> int:
    """Guarda la reconstrucción aparte. No toca las fotos reales ni las pisa."""
    added = 0
    real = history.setdefault("snapshots", {})
    if not isinstance(real, dict):
        history["snapshots"] = {}
        real = history["snapshots"]
    book = history.get("reconstructed")
    if not isinstance(book, dict):
        history["reconstructed"] = {}
        book = history["reconstructed"]
    ordered = [s for s in snaps if isinstance(s, dict) and s.get("date")]
    ordered.sort(key=lambda s: s["date"])
    for snap in ordered:
        day = str(snap["date"])
        if day in real:
            continue
        stored = dict(snap)
        stored["reconstruido"] = True
        stored["earnings_check"] = "omitido"
        book[day] = stored
        added += 1
    if ordered:
        history["backfill"] = {
            "done": True,
            "from": ordered[0]["date"],
            "to": ordered[-1]["date"],
            "sessions": len(ordered),
            "added": added,
            "earnings": "omitido",
            "provisional": True,
            "note": (
                "Reconstruido solo con precios hasta esa fecha, en un bloque aparte. "
                "El chequeo de resultados se tomó como aprobado. "
                "Se borra al llegar a "
                f"{PROVISIONAL_PURGE_REAL_DAYS} ruedas reales."
            ),
        }
    else:
        history["backfill"] = {"done": False, "reason": "sin_sesiones"}
    return added


def real_snapshot_count(history: dict) -> int:
    snaps = history.get("snapshots")
    if isinstance(snaps, dict):
        return len(snaps)
    if isinstance(snaps, list):
        return len([s for s in snaps if isinstance(s, dict)])
    return 0


def maybe_purge_reconstructed(history: dict) -> bool:
    """Borra la reconstrucción al llegar a PROVISIONAL_PURGE_REAL_DAYS ruedas reales."""
    if real_snapshot_count(history) < PROVISIONAL_PURGE_REAL_DAYS:
        return False
    history["reconstructed"] = {}
    backfill = history.get("backfill") if isinstance(history.get("backfill"), dict) else {}
    backfill = dict(backfill)
    backfill["done"] = True
    backfill["purged"] = True
    backfill["provisional"] = False
    backfill["reason"] = "ruedas_reales"
    history["backfill"] = backfill
    return True


def _raw_items(raw: Any) -> list[dict] | None:
    if isinstance(raw, dict):
        return [item for item in raw.values() if isinstance(item, dict)]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return None


def _snap_from_item(item: dict, *, reconstruido: bool) -> dict[str, Any] | None:
    day = _iso(item.get("date"))
    rows = item.get("rows")
    if day is None or not isinstance(rows, list):
        return None
    return make_snapshot(
        day,
        [r for r in rows if isinstance(r, dict)],
        after_close=bool(item.get("after_close")),
        reconstruido=reconstruido,
    )


def normalize(data: Any) -> dict | None:
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if version not in (1, None):
        return None
    real_items = _raw_items(data.get("snapshots"))
    recon_items = _raw_items(data.get("reconstructed"))
    if real_items is None and recon_items is None:
        return None
    snaps: dict[str, dict] = {}
    reconstructed: dict[str, dict] = {}
    for item in real_items or []:
        snap = _snap_from_item(item, reconstruido=bool(item.get("reconstruido")))
        if snap is None:
            continue
        if snap["reconstruido"]:
            reconstructed[snap["date"]] = snap
        else:
            snaps[snap["date"]] = snap
    for item in recon_items or []:
        snap = _snap_from_item(item, reconstruido=True)
        if snap is None or snap["date"] in snaps:
            continue
        reconstructed[snap["date"]] = snap
    for day in snaps:
        reconstructed.pop(day, None)
    backfill = data.get("backfill") if isinstance(data.get("backfill"), dict) else {"done": False}
    return {
        "version": 1,
        "updated_at": data.get("updated_at"),
        "backfill": dict(backfill),
        "snapshots": snaps,
        "reconstructed": reconstructed,
    }


def _usable(history: dict | None) -> bool:
    if not isinstance(history, dict):
        return False
    return bool(history.get("snapshots")) or bool(history.get("reconstructed"))


def resolve_load(
    *,
    published_status: str,
    published_data: Any,
    local_exists: bool,
    local_data: Any,
    local_error: bool,
) -> LoadResult:
    """Elige la historia anterior y si está permitido escribir el archivo.

    `published_status`: ok | missing | failed.
    Si la descarga falla y no hay copia usable, `write` es False y `block_deploy`
    es True: no se publica un sitio que borre el historial de Pages.
    """
    published = normalize(published_data) if published_status == "ok" else None
    local = normalize(local_data) if local_exists and not local_error else None
    if _usable(published):
        return LoadResult(published, "publicado", True, False)
    if _usable(local):
        return LoadResult(local, "local", True, False)
    if published_status == "failed" or local_error:
        return LoadResult(None, "sin_copia", False, True)
    if published is not None and not _usable(published) and local_exists:
        return LoadResult(None, "publicado_vacio", False, True)
    return LoadResult(None, "nuevo", True, False)


def fetch_published(url: str = PUBLISHED_HISTORY_URL, timeout: int = 12) -> tuple[str, Any]:
    """Un intento. 404 es «todavía no existe»; cualquier otro fallo no borra nada."""
    req = urllib.request.Request(url, headers={"User-Agent": "desk-dashboard/1.0"}, method="GET")
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return "ok", payload
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "missing", None
        return "failed", None
    except Exception as e:
        print(f"  historial publicado no disponible ({type(e).__name__})")
        return "failed", None


def read_local(path: Path) -> tuple[bool, Any, bool]:
    if not path.is_file():
        return False, None, False
    try:
        return True, json.loads(path.read_text(encoding="utf-8")), False
    except Exception as e:
        print(f"  historial local ilegible ({type(e).__name__})")
        return True, None, True


def load_previous(
    path: Path = HISTORY_PATH,
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


def save_history(
    path: Path,
    history: dict,
    loaded: LoadResult,
    flag_path: Path = FLAG_PATH,
) -> bool:
    """Escribe el archivo solo si hay fotos y la carga anterior lo permite.

    La reconstrucción va en otra clave. Si está vacía, no se publica.
    """
    snaps = history.get("snapshots") if isinstance(history, dict) else None
    recon = history.get("reconstructed") if isinstance(history, dict) else None
    has_real = isinstance(snaps, dict) and bool(snaps)
    has_recon = isinstance(recon, dict) and bool(recon)
    if not loaded.write or not (has_real or has_recon):
        if loaded.block_deploy or (path.is_file() and not loaded.write):
            flag_path.write_text(loaded.source + "\n", encoding="utf-8")
        return False
    payload: dict[str, Any] = {
        "version": 1,
        "updated_at": history.get("updated_at"),
        "backfill": history.get("backfill") or {"done": False},
        "snapshots": [snaps[key] for key in sorted(snaps or {})],
    }
    if has_recon:
        payload["reconstructed"] = [recon[key] for key in sorted(recon or {})]
    flag_path.unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)
    return True


def _stamp(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone(timedelta(hours=-3))).isoformat(timespec="seconds")


def evaluate_session(meta_by: dict[str, dict], all_bars: dict[str, list[dict]], session: str) -> list[dict]:
    """Ranking y semáforo con barras truncadas en `session` (inclusive). Sin look-ahead.

    El chequeo de resultados va como reconstruido: aprobado y etiquetado.
    """
    import build

    day = _iso(session)
    if day is None:
        return []
    try:
        ranked = build.rank_universe_asof(meta_by, all_bars, day, require_exact_session=True)
    except Exception as e:
        print(f"  historial {day}: ranking {type(e).__name__}")
        return []
    if not ranked:
        return []
    sliced = {sym: build.bars_through(bars, day) for sym, bars in all_bars.items()}
    for row in ranked:
        sym = row.get("symbol")
        try:
            row["patterns"] = signals.detect_patterns(sliced.get(sym) or [])
        except Exception:
            row["patterns"] = []
    try:
        weekly = build.compute_rs_weekly(sliced)
        build.attach_rs_weekly(ranked, weekly)
    except Exception as e:
        print(f"  historial {day}: rs semanal {type(e).__name__}")
        for row in ranked:
            row["rs_weekly"] = []
    try:
        sectors = build.compute_sector_view(ranked)
    except Exception as e:
        print(f"  historial {day}: sectores {type(e).__name__}")
        sectors = {"rows": []}
    try:
        signals.attach_entry_lights(
            ranked,
            sectors,
            [],
            today=date.fromisoformat(day),
            earnings_known=False,
            earnings_backfill=True,
        )
    except Exception as e:
        print(f"  historial {day}: semáforo {type(e).__name__}")
        return []
    return ranked


def backfill_dates(spy_dates: list[str], *, months_days: int = BACKFILL_CALENDAR_DAYS, warmup: int = BACKFILL_WARMUP_SESSIONS) -> list[str]:
    if warmup < 1 or not spy_dates:
        return []
    last = _iso(spy_dates[-1])
    if last is None:
        return []
    start = (date.fromisoformat(last) - timedelta(days=months_days)).isoformat()
    out: list[str] = []
    for i, raw in enumerate(spy_dates):
        day = _iso(raw)
        if day is None:
            continue
        if i + 1 < warmup:
            continue
        if day >= start:
            out.append(day)
    return out


def backfill_snapshots(
    meta_by: dict[str, dict],
    all_bars: dict[str, list[dict]],
    *,
    months_days: int = BACKFILL_CALENDAR_DAYS,
    warmup: int = BACKFILL_WARMUP_SESSIONS,
) -> list[dict]:
    """Fotos diarias reconstruidas. Cada día solo ve barras hasta ese cierre."""
    import build

    spy = all_bars.get("SPY") or []
    dates = backfill_dates(build.session_dates_from_bars(spy), months_days=months_days, warmup=warmup)
    out: list[dict] = []
    for day in dates:
        try:
            ranked = evaluate_session(meta_by, all_bars, day)
        except Exception as e:
            print(f"  historial {day}: {type(e).__name__}")
            continue
        snap = snapshot_from_rows(ranked, day, after_close=True, reconstruido=True)
        if snap:
            out.append(snap)
    return out


def _sorted_snaps(history: dict) -> list[dict]:
    snaps = history.get("snapshots") or {}
    if isinstance(snaps, dict):
        items = list(snaps.values())
    elif isinstance(snaps, list):
        items = [s for s in snaps if isinstance(s, dict)]
    else:
        items = []
    items.sort(key=lambda s: str(s.get("date") or ""))
    return items


def iter_signals(history: dict, verdict: str, *, dedup: bool) -> list[dict[str, Any]]:
    """Señales de un color. Con dedup, solo el primer día de cada racha."""
    prev: dict[str, str | None] = {}
    out: list[dict[str, Any]] = []
    for index, snap in enumerate(_sorted_snaps(history)):
        rows = {}
        for row in snap.get("rows") or []:
            if isinstance(row, dict) and row.get("symbol"):
                rows[str(row["symbol"]).upper()] = row
        current: dict[str, str] = {}
        for sym, row in rows.items():
            color = str(row.get("verdict") or "")
            current[sym] = color
            if color != verdict:
                continue
            if dedup and prev.get(sym) == verdict:
                continue
            out.append(
                {
                    "symbol": sym,
                    "date": snap.get("date"),
                    "index": index,
                    "reconstruido": bool(snap.get("reconstruido")),
                    "desk_score": row.get("desk_score"),
                    "rank": row.get("rank"),
                }
            )
        prev = {sym: current.get(sym) for sym in set(prev) | set(current)}
    return out


def iter_universe(history: dict) -> list[dict[str, Any]]:
    """Cada nombre distinto de SPY, en cada rueda, sin deduplicar."""
    out: list[dict[str, Any]] = []
    for index, snap in enumerate(_sorted_snaps(history)):
        for row in snap.get("rows") or []:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper()
            if not sym or sym == "SPY":
                continue
            out.append(
                {
                    "symbol": sym,
                    "date": snap.get("date"),
                    "index": index,
                    "reconstruido": bool(snap.get("reconstruido")),
                }
            )
    return out


def _close_matrix(history: dict) -> tuple[list[str], dict[str, list[float | None]]]:
    snaps = _sorted_snaps(history)
    dates = [str(s.get("date") or "") for s in snaps]
    symbols: set[str] = set()
    for snap in snaps:
        for row in snap.get("rows") or []:
            if isinstance(row, dict) and row.get("symbol"):
                symbols.add(str(row["symbol"]).upper())
    closes: dict[str, list[float | None]] = {sym: [None] * len(dates) for sym in symbols}
    for i, snap in enumerate(snaps):
        for row in snap.get("rows") or []:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper()
            if sym not in closes:
                continue
            closes[sym][i] = _num(row.get("close"))
    return dates, closes


def _pair_at(ticker: list[float | None], spy: list[float | None], i: int, j: int) -> tuple[float, float] | None:
    if i < 0 or j >= len(ticker) or j >= len(spy):
        return None
    t0, t1 = ticker[i], ticker[j]
    s0, s1 = spy[i], spy[j]
    if t0 in (None, 0) or t1 in (None, 0) or s0 in (None, 0) or s1 in (None, 0):
        return None
    assert t0 is not None and t1 is not None and s0 is not None and s1 is not None
    return ((t1 / t0 - 1.0) * 100.0, (s1 / s0 - 1.0) * 100.0)


def window_return(
    ticker: list[float | None],
    spy: list[float | None],
    i: int,
    horizon: int,
) -> dict[str, Any] | None:
    """Retorno a `horizon` ruedas. None si la ventana no está cerrada o falta un cierre."""
    return _closed_window(ticker, spy, i, horizon)


def _closed_window(
    ticker: list[float | None],
    spy: list[float | None],
    i: int,
    horizon: int,
) -> dict[str, Any] | None:
    pair = _pair_at(ticker, spy, i, i + horizon)
    if pair is None:
        return None
    ticker_ret, spy_ret = pair
    return {
        "status": "cerrada",
        "return_pct": ticker_ret,
        "spy_return_pct": spy_ret,
        "excess_pct": ticker_ret - spy_ret,
        "sessions": horizon,
    }


def _pending_window(ticker: list[float | None], spy: list[float | None], i: int) -> dict[str, Any]:
    """Retorno hasta el último cierre disponible. Si no hay rueda posterior, sigue en curso."""
    last = None
    for j in range(len(ticker) - 1, i, -1):
        if _pair_at(ticker, spy, i, j) is not None:
            last = j
            break
    if last is None:
        return {
            "status": "en curso",
            "return_pct": None,
            "spy_return_pct": None,
            "excess_pct": None,
            "sessions": 0,
        }
    pair = _pair_at(ticker, spy, i, last)
    assert pair is not None
    ticker_ret, spy_ret = pair
    return {
        "status": "en curso",
        "return_pct": ticker_ret,
        "spy_return_pct": spy_ret,
        "excess_pct": ticker_ret - spy_ret,
        "sessions": last - i,
    }


def signal_outcome(
    ticker: list[float | None],
    spy: list[float | None],
    i: int,
    horizon: int = 20,
) -> dict[str, Any]:
    """Para la lista: la ventana de 20 ruedas si ya cerró; si no, el retorno a hoy."""
    closed = _closed_window(ticker, spy, i, horizon)
    if closed is not None:
        return closed
    return _pending_window(ticker, spy, i)


def _agg(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    if not pairs:
        return {
            "n": 0,
            "avg": None,
            "median": None,
            "spy_avg": None,
            "excess": None,
            "hit_pct": None,
            "beat_pct": None,
            "best": None,
            "worst": None,
        }
    ticker = [p[0] for p in pairs]
    spy = [p[1] for p in pairs]
    excess = [a - b for a, b in pairs]
    return {
        "n": len(pairs),
        "avg": round(sum(ticker) / len(ticker), 2),
        "median": round(float(statistics.median(ticker)), 2),
        "spy_avg": round(sum(spy) / len(spy), 2),
        "excess": round(sum(excess) / len(excess), 2),
        "hit_pct": round(sum(1 for v in ticker if v > 0) / len(ticker) * 100.0, 1),
        "beat_pct": round(sum(1 for v in excess if v > 0) / len(excess) * 100.0, 1),
        "best": round(max(ticker), 2),
        "worst": round(min(ticker), 2),
    }


def _stats(signals: list[dict], closes: dict[str, list[float | None]], spy: list[float | None], horizon: int, *, reconstructed: bool | None = None) -> dict[str, Any]:
    pairs: list[tuple[float, float]] = []
    for sig in signals:
        if reconstructed is not None and bool(sig.get("reconstruido")) is not reconstructed:
            continue
        series = closes.get(sig["symbol"])
        if not series:
            continue
        closed = _closed_window(series, spy, int(sig["index"]), horizon)
        if closed is None:
            continue
        pairs.append((closed["return_pct"], closed["spy_return_pct"]))
    return _agg(pairs)


def _is_etf(symbol: str, meta_by: dict[str, dict]) -> bool:
    kind = str((meta_by.get(symbol) or {}).get("kind") or "").lower()
    return kind == "etf"


def _step_return(symbols: list[str], i: int, closes: dict[str, list[float | None]]) -> float:
    rets: list[float] = []
    for sym in symbols:
        series = closes.get(sym) or []
        if i + 1 >= len(series):
            continue
        c0, c1 = series[i], series[i + 1]
        if c0 in (None, 0) or c1 in (None, 0):
            continue
        assert c0 is not None and c1 is not None
        rets.append(c1 / c0 - 1.0)
    if not rets:
        return 0.0
    return sum(rets) / len(rets)


def equity_curve(history: dict, meta_by: dict[str, dict]) -> dict[str, Any]:
    """Cartera equiponderada de lo que estaba en verde al cierre anterior, contra SPY."""
    snaps = _sorted_snaps(history)
    dates, closes = _close_matrix(history)
    note = (
        "Cada rueda se mantiene, en partes iguales, lo que estaba en verde al cierre anterior. "
        "La serie de acciones deja afuera los ETF. Si ese día no hay ninguna, el tramo queda en efectivo. "
        "SPY es comprar y mantener entre las mismas fechas. Sin comisiones."
    )
    if len(dates) < 2:
        return {
            "base": 100,
            "stocks_return_pct": None,
            "all_return_pct": None,
            "spy_return_pct": None,
            "note": note,
            "curve": [],
        }
    eq_s = 100.0
    eq_a = 100.0
    eq_spy = 100.0
    curve = [{"date": dates[0], "stocks": 100.0, "all": 100.0, "spy": 100.0}]
    for i, snap in enumerate(snaps[:-1]):
        stocks: list[str] = []
        everyone: list[str] = []
        for row in snap.get("rows") or []:
            if not isinstance(row, dict) or row.get("verdict") != "verde":
                continue
            sym = str(row.get("symbol") or "").upper()
            if not sym:
                continue
            everyone.append(sym)
            if not _is_etf(sym, meta_by):
                stocks.append(sym)
        eq_s *= 1.0 + _step_return(stocks, i, closes)
        eq_a *= 1.0 + _step_return(everyone, i, closes)
        eq_spy *= 1.0 + _step_return(["SPY"], i, closes)
        curve.append(
            {
                "date": dates[i + 1],
                "stocks": round(eq_s, 2),
                "all": round(eq_a, 2),
                "spy": round(eq_spy, 2),
            }
        )
    return {
        "base": 100,
        "stocks_return_pct": round(eq_s - 100.0, 2),
        "all_return_pct": round(eq_a - 100.0, 2),
        "spy_return_pct": round(eq_spy - 100.0, 2),
        "note": note,
        "curve": curve,
    }


def _fmt_pct(value: float | None) -> str:
    text = signals._fmt_pct_signed(value)
    return text if text is not None else "s/d"


def _ddmm(iso: str | None) -> str:
    text = str(iso or "")
    if len(text) >= 10 and text[4] == "-":
        return f"{text[8:10]}/{text[5:7]}"
    return text


def panel_sentence(stats: dict | None, *, provisional: bool = False) -> str:
    if not stats or not stats.get("n") or stats.get("avg") is None or stats.get("spy_avg") is None:
        base = "Todavía no hay señales verdes con la ventana de 20 ruedas cerrada."
    else:
        base = (
            f"En las últimas {stats['n']} señales, las verdes rindieron {_fmt_pct(stats['avg'])} "
            f"en 20 ruedas contra {_fmt_pct(stats['spy_avg'])} de SPY."
        )
    if provisional:
        return "Provisorio (reconstruido). " + base
    return base


def _provisional_note(real_closed: int) -> str:
    if real_closed == 1:
        cuantas = "Hay 1 señal verde real con esta ventana cerrada."
    else:
        cuantas = f"Hay {real_closed} señales verdes reales con esta ventana cerrada."
    return (
        cuantas
        + f" El provisorio desaparece al llegar a {PROVISIONAL_MIN_CLOSED_SIGNALS}."
    )


def resumen_sentence(block: dict | None) -> str | None:
    """Una oración para el resumen del día, solo si hoy cerró alguna ventana de 20 ruedas."""
    closed = [item for item in ((block or {}).get("closed_today") or []) if item.get("return_pct") is not None]
    if not closed:
        return None
    bits: list[str] = []
    for item in closed[:3]:
        bits.append(
            f"{item.get('symbol')} (verde el {_ddmm(item.get('date'))}, "
            f"{_fmt_pct(item.get('return_pct'))} contra {_fmt_pct(item.get('spy_return_pct'))} de SPY)"
        )
    sentence = "Cerró la ventana de 20 ruedas " + signals._es_join(bits)
    extra = len(closed) - 3
    if extra > 0:
        sentence += f", y {extra} más"
    return sentence + "."


def append_resumen_sentence(resumen: dict | None, block: dict | None) -> None:
    sentence = resumen_sentence(block)
    if not sentence or not isinstance(resumen, dict):
        return
    sentences = [s for s in (resumen.get("sentences") or []) if s]
    sentences.append(sentence)
    if len(sentences) > 10:
        sentences = sentences[:9] + [" ".join(sentences[9:])]
    resumen["sentences"] = sentences
    resumen["text"] = " ".join(sentences)


def _round_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    out = dict(outcome)
    for key in ("return_pct", "spy_return_pct", "excess_pct"):
        if out.get(key) is not None:
            out[key] = round(float(out[key]), 2)
    return out


def _metrics_bundle(history: dict) -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[str], dict[str, list[float | None]], list[float | None]]:
    """Tabla, variante de todos los días, señales verdes deduplicadas, fechas, cierres y SPY."""
    dates, closes = _close_matrix(history)
    spy = closes.get("SPY") or [None] * len(dates)
    groups = {
        "verde": iter_signals(history, "verde", dedup=True),
        "ambar": iter_signals(history, "ambar", dedup=True),
        "rojo": iter_signals(history, "rojo", dedup=True),
        "universo": iter_universe(history),
    }
    table: dict[str, dict[str, Any]] = {}
    for name, signals_ in groups.items():
        table[name] = {str(h): _stats(signals_, closes, spy, h) for h in HORIZONS}
    verde_all = iter_signals(history, "verde", dedup=False)
    all_days = {str(h): _stats(verde_all, closes, spy, h) for h in HORIZONS}
    return table, all_days, groups["verde"], dates, closes, spy


def _book_history(book: dict) -> dict:
    return {"snapshots": book, "reconstructed": {}}


def build_report(history: dict, meta_by: dict[str, dict] | None = None) -> dict[str, Any]:
    """Informe para la UI. Cada horizonte sale de una sola fuente, real o reconstruida."""
    meta_by = meta_by or {}
    real_book = history.get("snapshots") if isinstance(history.get("snapshots"), dict) else {}
    recon_book = history.get("reconstructed") if isinstance(history.get("reconstructed"), dict) else {}
    purged = real_snapshot_count({"snapshots": real_book}) >= PROVISIONAL_PURGE_REAL_DAYS
    if purged:
        recon_book = {}
    real_hist = _book_history(real_book)
    recon_hist = _book_history(recon_book)
    real_table, real_all, real_verde, real_dates, real_closes, real_spy = _metrics_bundle(real_hist)
    recon_table, recon_all, _recon_verde, _recon_dates, _recon_closes, _recon_spy = _metrics_bundle(recon_hist)
    table: dict[str, dict[str, Any]] = {name: {} for name in ("verde", "ambar", "rojo", "universo")}
    horizons_meta: dict[str, dict[str, Any]] = {}
    any_provisional = False
    for horizon in HORIZONS:
        key = str(horizon)
        real_closed = int(real_table["verde"][key]["n"])
        provisional = bool(recon_book) and real_closed < PROVISIONAL_MIN_CLOSED_SIGNALS
        source = recon_table if provisional else real_table
        for name in table:
            table[name][key] = source[name][key]
        any_provisional = any_provisional or provisional
        horizons_meta[key] = {
            "provisional": provisional,
            "real_closed": real_closed,
            "threshold": PROVISIONAL_MIN_CLOSED_SIGNALS,
            "label": "Provisorio (reconstruido)" if provisional else "",
            "note": _provisional_note(real_closed) if provisional else "",
        }
    twenty_provisional = bool(horizons_meta["20"]["provisional"])
    shown_20 = table["verde"]["20"]
    all_source = recon_all if twenty_provisional else real_all
    todos = all_source["20"]
    todos_sentence = None
    if todos.get("n") and todos.get("avg") is not None and todos.get("spy_avg") is not None:
        todos_sentence = (
            f"Si se cuenta cada día en verde y no solo el primero de la racha, son {todos['n']} señales, "
            f"con un retorno medio de {_fmt_pct(todos['avg'])} en 20 ruedas contra {_fmt_pct(todos['spy_avg'])} de SPY."
        )
        if twenty_provisional:
            todos_sentence = "Provisorio (reconstruido). " + todos_sentence
    recent: list[dict[str, Any]] = []
    for sig in reversed(real_verde):
        series = real_closes.get(sig["symbol"]) or []
        outcome = _round_outcome(signal_outcome(series, real_spy, int(sig["index"]), 20))
        recent.append(
            {
                "date": sig["date"],
                "symbol": sig["symbol"],
                "desk_score": sig.get("desk_score"),
                "rank": sig.get("rank"),
                **outcome,
            }
        )
        if len(recent) >= RECENT_LIMIT:
            break
    by_symbol: dict[str, dict[str, Any]] = {}
    for sig in real_verde:
        pack = by_symbol.setdefault(sig["symbol"], {"count": 0, "signals": []})
        pack["count"] += 1
    for sig in reversed(real_verde):
        pack = by_symbol[sig["symbol"]]
        if len(pack["signals"]) >= FICHA_LIMIT:
            continue
        series = real_closes.get(sig["symbol"]) or []
        outcome = _round_outcome(signal_outcome(series, real_spy, int(sig["index"]), 20))
        pack["signals"].append({"date": sig["date"], **outcome})
    last_i = len(real_dates) - 1
    closed_today: list[dict[str, Any]] = []
    if last_i >= 20:
        for sig in real_verde:
            if int(sig["index"]) + 20 != last_i:
                continue
            series = real_closes.get(sig["symbol"]) or []
            outcome = _round_outcome(signal_outcome(series, real_spy, int(sig["index"]), 20))
            if outcome.get("status") != "cerrada":
                continue
            closed_today.append({"date": sig["date"], "symbol": sig["symbol"], **outcome})
    real_snaps = _sorted_snaps(real_hist)
    latest = real_snaps[-1] if real_snaps else None
    span = real_dates or (_recon_dates if not purged else [])
    return {
        "real_days": len(real_book),
        "reconstructed_days": 0 if purged else len(recon_book),
        "provisional": any_provisional,
        "purge_real_days": PROVISIONAL_PURGE_REAL_DAYS,
        "provisional_min_closed": PROVISIONAL_MIN_CLOSED_SIGNALS,
        "from": span[0] if span else None,
        "to": span[-1] if span else None,
        "latest": (
            {"date": latest.get("date"), "after_close": bool(latest.get("after_close"))}
            if latest
            else None
        ),
        "horizons": list(HORIZONS),
        "horizons_meta": horizons_meta,
        "dedup": DEDUP_RULE,
        "disclaimer": DISCLAIMER,
        "earnings_note": EARNINGS_NOTE if any_provisional else "",
        "sentence": panel_sentence(shown_20, provisional=twenty_provisional),
        "todos_los_dias_sentence": todos_sentence,
        "table": table,
        "verde_20": shown_20,
        "recent": recent,
        "by_symbol": by_symbol,
        "closed_today": closed_today,
        "equity": equity_curve(real_hist, meta_by),
    }


def _note(loaded: LoadResult, history: dict, *, did_backfill: bool, elapsed: float, saved: bool) -> str:
    real_days = real_snapshot_count(history)
    recon = history.get("reconstructed") if isinstance(history.get("reconstructed"), dict) else {}
    if not saved:
        if loaded.block_deploy:
            return (
                "Historial del semáforo: no se reescribió porque no se pudo leer el anterior. "
                "El deploy se frena para no borrar el archivo publicado."
            )
        return "Historial del semáforo: sin fotos para guardar."
    base = {"publicado": "base publicada", "local": "base local", "nuevo": "arranque"}.get(
        loaded.source, loaded.source
    )
    text = f"Historial del semáforo ({base}): {real_days} ruedas reales"
    purged = bool((history.get("backfill") or {}).get("purged")) if isinstance(history.get("backfill"), dict) else False
    if purged:
        text += ". Reconstrucción provisoria borrada."
    elif recon:
        text += f" y {len(recon)} reconstruidas, aparte, hasta las {PROVISIONAL_PURGE_REAL_DAYS} ruedas reales."
    else:
        text += "."
    if did_backfill:
        text += f" Reconstrucción en {elapsed:.1f}s; queda guardada aparte y no se rehace en cada corrida."
    elif needs_backfill(history):
        text += " La reconstrucción no quedó cerrada; se reintenta en la próxima corrida."
    elif not purged:
        text += " Reconstrucción reutilizada."
    return text


def publish(
    *,
    rows: list[dict],
    meta_by: dict[str, dict],
    all_bars: dict[str, list[dict]],
    now: datetime,
    history_path: Path = HISTORY_PATH,
    flag_path: Path = FLAG_PATH,
    fetch: Callable[[], tuple[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Actualiza el archivo y arma el bloque para datos.json. No lanza hacia el build."""
    loaded = load_previous(history_path, fetch=fetch)
    if not loaded.write:
        save_history(history_path, empty_history(), loaded, flag_path)
        return None, _note(loaded, empty_history(), did_backfill=False, elapsed=0.0, saved=False)
    history = loaded.history or empty_history()
    maybe_purge_reconstructed(history)
    did_backfill = False
    elapsed = 0.0
    if needs_backfill(history) and real_snapshot_count(history) < PROVISIONAL_PURGE_REAL_DAYS:
        try:
            t0 = time.perf_counter()
            snaps = backfill_snapshots(meta_by, all_bars)
            elapsed = time.perf_counter() - t0
            apply_backfill(history, snaps)
            did_backfill = bool(snaps)
            print(f"  historial backfill: {len(snaps)} ruedas en {elapsed:.1f}s")
        except Exception as e:
            print(f"  historial backfill falló (soft): {type(e).__name__}")
            history["backfill"] = {"done": False, "error": type(e).__name__}
    session = session_date_from_rows(rows)
    if session:
        live = snapshot_from_rows(
            rows,
            session,
            after_close=taken_after_close(session, now),
            reconstruido=False,
        )
        upsert_snapshot(history, live)
    maybe_purge_reconstructed(history)
    history["updated_at"] = _stamp(now)
    saved = save_history(history_path, history, loaded, flag_path)
    if not saved:
        blocked = LoadResult(None, "vacio", False, history_path.is_file())
        return None, _note(blocked if history_path.is_file() else loaded, history, did_backfill=did_backfill, elapsed=elapsed, saved=False)
    try:
        report = build_report(history, meta_by)
    except Exception as e:
        print(f"  historial informe falló (soft): {type(e).__name__}")
        return None, _note(loaded, history, did_backfill=did_backfill, elapsed=elapsed, saved=True) + " El informe no entró en esta publicación."
    return report, _note(loaded, history, did_backfill=did_backfill, elapsed=elapsed, saved=True)
