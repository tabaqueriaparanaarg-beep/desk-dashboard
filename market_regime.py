"""Régimen de mercado: puntaje 0–100 sobre 125 pts crudos.

No entra en el Desk Score, el semáforo ni el ranking. SPY/QQQ se leen de las
barras que el build ya bajó. VIXY, si hace falta, es solo sentimiento.
"""
from __future__ import annotations

import csv
import io
import ssl
import urllib.request
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

# Misma semilla que build.ema / build.sma (el test lo traba).
# Pendiente: valor de hoy contra el de hace 5 sesiones (índice -6), igual que el pilar de tendencia.
SLOPE_LAG = 5
HL_WINDOW = 252
HL_MIN_PRIOR = 60
BREADTH_SESSIONS = 42

INDEX_EACH = 8.0
INDEX_MAX = 40.0  # 5 condiciones × 8
BREADTH_PART = 10.0
BREADTH_MAX = 30.0
VIX_MAX = 15.0
VIX_CALM_MAX = 20.0
POINTS_MAX = 125.0

CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"

DISCLAIMER = "Guía automática de exposición, no es un consejo de inversión."

# [lo, hi) salvo el último tramo, que incluye 100. El borde cae en el tramo de arriba
# (25 es «25–50», no «0–25») para que el número del medidor y el color coincidan.
EXPOSURE_BANDS: tuple[tuple[int, int, str, str, str], ...] = (
    (0, 25, "red", "0–25%", "mínima, liquidez"),
    (25, 50, "orange", "25–50%", "posiciones chicas, stops cortos"),
    (50, 75, "yellow", "50–75%", "exposición normal"),
    (75, 101, "green", "75–100%", "exposición plena"),
)

FORMULA = (
    "Puntaje 0–100 = puntos obtenidos / puntos disponibles × 100, redondeado al entero "
    "(half up). Máximo teórico 125. El número del medidor y el color usan ese entero. "
    "Índices SPY/QQQ (80 = 40 × 2). Cada condición suma 8, por índice: "
    "cierre > EMA200; cierre > SMA50; EMA200 hoy > EMA200 de hace 5 sesiones; "
    "SMA50 hoy > SMA50 de hace 5 sesiones; SMA50 > EMA200. "
    "Si falta la serie de un índice, sus 40 pts salen del denominador. "
    "Una condición que no se puede evaluar (sin media) suma 0 y sigue dentro de los 40. "
    "Amplitud (30): 10 × (nombres con cierre > EMA200 / nombres scored) + "
    "10 × (nombres con cierre > SMA50 / nombres scored) + "
    "10 × (nuevos máximos de 52 semanas / (máximos + mínimos)) si ese día hubo al menos un extremo; "
    "5 pts neutros si no hubo ni máximos ni mínimos. "
    f"Nuevo máximo: high de la sesión ancla (última de SPY) > máximo de las hasta {HL_WINDOW} sesiones previas "
    f"(mínimo {HL_MIN_PRIOR} previas). Nuevo mínimo: low < mínimo de esa ventana. "
    "Un símbolo cuya última barra no es la sesión ancla, o sin historia suficiente, no entra en el conteo. "
    "Sentimiento (15). Fuente primaria: CSV público de CBOE "
    f"({CBOE_VIX_URL}), último cierre, sin clave. "
    f"5 pts si el cierre ≤ {VIX_CALM_MAX:.0f}; 5 si el cierre < media de 20 ruedas; 5 si el cierre < media de 50. "
    "Si falta una media, esos puntos salen del denominador. "
    "Fallback: VIXY de Alpaca (no se agrega al universo, al ranking ni a los KPIs). "
    "Sin umbral absoluto, porque el precio de VIXY no es el índice: 8 pts si el cierre < media de 20 "
    "y 7 si el cierre < media de 50. "
    "Si no hay CBOE ni VIXY, el componente queda afuera y el pie dice "
    "«calculado sobre X pts disponibles de 125». "
    "Exposición: [0, 25) rojo, 0–25% · mínima, liquidez; "
    "[25, 50) naranja, 25–50% · posiciones chicas, stops cortos; "
    "[50, 75) amarillo, 50–75% · exposición normal; "
    "[75, 100] verde, 75–100% · exposición plena. "
    f"Serie: % de activos scored con cierre > EMA200 en cada una de las últimas {BREADTH_SESSIONS} "
    "sesiones del calendario de SPY (o del universo si no hay SPY), con las barras ya descargadas. "
    "Quien no tiene barra ese día no entra en el denominador de esa rueda. "
    "Quien tiene barra pero todavía no tiene EMA200 cuenta como no está arriba."
)


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period or period < 1:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    acc = sum(values[:period])
    out[period - 1] = acc / period
    for i in range(period, len(values)):
        acc += values[i] - values[i - period]
        out[i] = acc / period
    return out


def round_half_up(value: float, digits: int = 0) -> float:
    quant = Decimal("1") if digits == 0 else Decimal("0.1") ** digits
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def format_points(value: float) -> str:
    rounded = round_half_up(float(value), 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.1f}"


def bar_day(bar: dict) -> str:
    return str(bar.get("t") or "")[:10]


def _closes(bars: list[dict]) -> list[float]:
    return [float(b["c"]) for b in bars]


def score_index(bars: list[dict] | None) -> dict[str, Any]:
    """40 pts máx. Serie ausente → el bloque no está disponible."""
    if not bars:
        return {
            "available": False,
            "points": 0.0,
            "points_exact": 0.0,
            "max_points": INDEX_MAX,
            "checks": [],
        }
    closes = _closes(bars)
    ema_s = ema(closes, 200)
    sma_s = sma(closes, 50)
    close = closes[-1]
    ema_v = ema_s[-1]
    sma_v = sma_s[-1]
    lag = SLOPE_LAG + 1
    ema_prev = ema_s[-lag] if len(ema_s) >= lag else None
    sma_prev = sma_s[-lag] if len(sma_s) >= lag else None
    flags = [
        ("close_above_ema200", ema_v is not None and close > ema_v),
        ("close_above_sma50", sma_v is not None and close > sma_v),
        ("ema200_slope_up", ema_v is not None and ema_prev is not None and ema_v > ema_prev),
        ("sma50_slope_up", sma_v is not None and sma_prev is not None and sma_v > sma_prev),
        ("sma50_above_ema200", sma_v is not None and ema_v is not None and sma_v > ema_v),
    ]
    checks = [{"id": name, "ok": bool(ok), "points": INDEX_EACH if ok else 0.0} for name, ok in flags]
    exact = float(sum(c["points"] for c in checks))
    return {
        "available": True,
        "points": round_half_up(exact, 1),
        "points_exact": exact,
        "max_points": INDEX_MAX,
        "checks": checks,
    }


def _prior_window(values: list[float]) -> list[float] | None:
    if len(values) < HL_MIN_PRIOR + 1:
        return None
    prior_n = min(HL_WINDOW, len(values) - 1)
    if prior_n < HL_MIN_PRIOR:
        return None
    return values[-(prior_n + 1) : -1]


def session_extremes(bars: list[dict] | None, anchor: str | None) -> dict[str, bool]:
    """Máximo/mínimo de 52 semanas en la sesión ancla. No eligible si la última barra es otra sesión."""
    empty = {"eligible": False, "new_high": False, "new_low": False}
    if not bars or not anchor or bar_day(bars[-1]) != anchor:
        return empty
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    prior_h = _prior_window(highs)
    prior_l = _prior_window(lows)
    if prior_h is None or prior_l is None:
        return empty
    return {
        "eligible": True,
        "new_high": highs[-1] > max(prior_h),
        "new_low": lows[-1] < min(prior_l),
    }


def anchor_day(bars_by_symbol: dict[str, list[dict]], symbols: list[str]) -> str | None:
    spy = bars_by_symbol.get("SPY") or []
    if spy and bar_day(spy[-1]):
        return bar_day(spy[-1])
    days = [bar_day(bars_by_symbol[s][-1]) for s in symbols if bars_by_symbol.get(s)]
    days = [d for d in days if d]
    return max(days) if days else None


def count_52w(
    bars_by_symbol: dict[str, list[dict]],
    symbols: list[str],
    anchor: str | None,
) -> dict[str, Any]:
    highs = 0
    lows = 0
    eligible = 0
    for sym in symbols:
        hit = session_extremes(bars_by_symbol.get(sym), anchor)
        if not hit["eligible"]:
            continue
        eligible += 1
        if hit["new_high"]:
            highs += 1
        if hit["new_low"]:
            lows += 1
    return {"highs": highs, "lows": lows, "eligible": eligible, "asof": anchor}


def score_breadth(n: int, above_ema: int, above_sma: int, highs: int, lows: int) -> dict[str, Any]:
    if n <= 0:
        return {
            "available": False,
            "points": 0.0,
            "points_exact": 0.0,
            "max_points": BREADTH_MAX,
            "parts": {},
        }
    ema_pts = BREADTH_PART * (above_ema / n)
    sma_pts = BREADTH_PART * (above_sma / n)
    if highs + lows > 0:
        hl_pts = BREADTH_PART * (highs / (highs + lows))
        hl_mode = "balance"
    else:
        hl_pts = BREADTH_PART / 2.0
        hl_mode = "neutral"
    exact = ema_pts + sma_pts + hl_pts
    return {
        "available": True,
        "points": round_half_up(exact, 1),
        "points_exact": exact,
        "max_points": BREADTH_MAX,
        "parts": {
            "ema200": ema_pts,
            "sma50": sma_pts,
            "high_low": hl_pts,
            "high_low_mode": hl_mode,
        },
    }


def score_vix(closes: list[float] | None, source: str | None) -> dict[str, Any]:
    """15 pts. source 'cboe' o 'vixy'. Sin serie → componente afuera (max 0 disponible)."""
    base = {
        "available": False,
        "points": None,
        "points_exact": 0.0,
        "max_points": 0.0,
        "component_max": VIX_MAX,
        "source": None,
        "close": None,
        "sma20": None,
        "sma50": None,
        "checks": [],
        "detail": "Sin CBOE ni VIXY",
    }
    if source not in ("cboe", "vixy") or not closes:
        return base
    last = float(closes[-1])
    sma20 = sma(closes, 20)[-1]
    sma50 = sma(closes, 50)[-1]
    weighted: list[tuple[str, float, bool]] = []
    if source == "cboe":
        weighted.append(("nivel", 5.0, last <= VIX_CALM_MAX))
        if sma20 is not None:
            weighted.append(("bajo_sma20", 5.0, last < sma20))
        if sma50 is not None:
            weighted.append(("bajo_sma50", 5.0, last < sma50))
    else:
        if sma20 is not None:
            weighted.append(("bajo_sma20", 8.0, last < sma20))
        if sma50 is not None:
            weighted.append(("bajo_sma50", 7.0, last < sma50))
    if not weighted:
        return base
    exact = float(sum(weight for _name, weight, ok in weighted if ok))
    max_points = float(sum(weight for _name, weight, _ok in weighted))
    checks = [
        {"id": name, "ok": ok, "points": weight if ok else 0.0, "max_points": weight}
        for name, weight, ok in weighted
    ]
    return {
        "available": True,
        "points": round_half_up(exact, 1),
        "points_exact": exact,
        "max_points": max_points,
        "component_max": VIX_MAX,
        "source": source,
        "close": last,
        "sma20": sma20,
        "sma50": sma50,
        "checks": checks,
        "detail": _vix_detail(source, last, sma20, sma50),
    }


def _vix_detail(source: str, close: float, sma20: float | None, sma50: float | None) -> str:
    if source == "cboe":
        head = f"CBOE {close:.1f}"
        if close <= VIX_CALM_MAX:
            head += " · en 20 o menos"
        else:
            head += " · por encima de 20"
    else:
        head = f"VIXY {close:.2f} · no entra al ranking"
    bits: list[str] = []
    if sma20 is not None:
        bits.append("bajo media de 20" if close < sma20 else "sobre media de 20")
    if sma50 is not None:
        bits.append("bajo media de 50" if close < sma50 else "sobre media de 50")
    if bits:
        return head + " · " + " y ".join(bits)
    return head


def exposure_band(score: int) -> dict[str, Any]:
    clipped = max(0, min(100, int(score)))
    for lo, hi, color, pct, note in EXPOSURE_BANDS:
        if lo <= clipped < hi:
            return {
                "id": f"{lo}-{min(hi, 100)}",
                "lo": lo,
                "hi": min(hi, 100),
                "color": color,
                "exposure_pct": pct,
                "exposure_note": note,
                "line": f"{pct} · {note}",
                "disclaimer": DISCLAIMER,
            }
    raise RuntimeError(f"puntaje fuera de rango: {score}")


def format_clock(iso: str | None) -> str | None:
    """Hora ya en la zona del iso (el build guarda ART, UTC−3). 21:45 → 09:45 p. m."""
    if not iso:
        return None
    text = str(iso).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    suffix = "a. m." if dt.hour < 12 else "p. m."
    hour = dt.hour % 12 or 12
    return f"{hour:02d}:{dt.minute:02d} {suffix}"


def footer_text(clock: str | None, available: float, maximum: float = POINTS_MAX) -> str:
    body = f"calculado sobre {format_points(available)} pts disponibles de {format_points(maximum)}"
    if clock:
        return f"{clock} · {body}"
    return body


def finalize_score(earned: float, available: float) -> dict[str, Any]:
    if available <= 0:
        return {
            "score": None,
            "raw_points": round_half_up(earned, 1),
            "raw_points_exact": earned,
            "points_available": 0.0,
            "points_max": POINTS_MAX,
            "band": None,
        }
    ratio = earned / available * 100.0
    score = int(round_half_up(ratio, 0))
    score = max(0, min(100, score))
    return {
        "score": score,
        "raw_points": round_half_up(earned, 1),
        "raw_points_exact": earned,
        "points_available": available,
        "points_max": POINTS_MAX,
        "band": exposure_band(score),
    }


def breadth_ema200_series(
    bars_by_symbol: dict[str, list[dict]],
    symbols: list[str],
    sessions: int = BREADTH_SESSIONS,
) -> list[dict[str, Any]]:
    """% sobre EMA200 por sesión, calendario de SPY, sin pedir barras nuevas."""
    prepared: dict[str, dict[str, tuple[float, float | None]]] = {}
    for sym in symbols:
        bars = bars_by_symbol.get(sym) or []
        if not bars:
            continue
        closes = _closes(bars)
        emas = ema(closes, 200)
        by_day: dict[str, tuple[float, float | None]] = {}
        for bar, close, ema_v in zip(bars, closes, emas):
            day = bar_day(bar)
            if day:
                by_day[day] = (close, ema_v)
        if by_day:
            prepared[sym] = by_day
    spy_days = sorted((prepared.get("SPY") or {}))
    if spy_days:
        calendar = spy_days
    else:
        calendar = sorted({day for series in prepared.values() for day in series})
    if sessions > 0:
        calendar = calendar[-sessions:]
    out: list[dict[str, Any]] = []
    for day in calendar:
        above = 0
        eligible = 0
        for series in prepared.values():
            pair = series.get(day)
            if pair is None:
                continue
            close, ema_v = pair
            eligible += 1
            if ema_v is not None and close > ema_v:
                above += 1
        pct = (above / eligible * 100.0) if eligible else None
        out.append(
            {
                "date": day,
                "pct": round_half_up(pct, 1) if pct is not None else None,
                "above": above,
                "eligible": eligible,
            }
        )
    return out


def _index_component(bars_by_symbol: dict[str, list[dict]]) -> dict[str, Any]:
    symbols: dict[str, Any] = {}
    exact = 0.0
    max_points = 0.0
    missing: list[str] = []
    for sym in ("SPY", "QQQ"):
        part = score_index(bars_by_symbol.get(sym))
        symbols[sym] = part
        if part["available"]:
            exact += part["points_exact"]
            max_points += part["max_points"]
        else:
            missing.append(sym)
    detail = None
    if missing and max_points > 0:
        detail = " y ".join(missing) + " sin serie: esos puntos salen del denominador"
    elif missing:
        detail = "Sin serie de SPY ni de QQQ"
    return {
        "id": "indices",
        "label": "Índices SPY / QQQ",
        "available": max_points > 0,
        "points": round_half_up(exact, 1) if max_points > 0 else None,
        "points_exact": exact,
        "max_points": max_points if max_points > 0 else INDEX_MAX * 2,
        "symbols": symbols,
        "detail": detail,
    }


def _scoped_symbols(rows: list[dict]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def build_market_regime(
    rows: list[dict],
    bars_by_symbol: dict[str, list[dict]] | None,
    *,
    generated_at: str | None = None,
    vix_closes: list[float] | None = None,
    vix_source: str | None = None,
    vix_meta: dict | None = None,
) -> dict[str, Any]:
    """Arma el bloque `market_regime`. No muta las filas ni mete a VIXY en el universo."""
    bars_by_symbol = bars_by_symbol or {}
    symbols = _scoped_symbols(rows)
    scoped_rows = [r for r in rows if isinstance(r, dict) and str(r.get("symbol") or "").upper() in set(symbols)]
    n = len(scoped_rows)
    above_ema = sum(1 for r in scoped_rows if r.get("above_ema200"))
    above_sma = sum(1 for r in scoped_rows if r.get("above_sma50"))

    anchor = anchor_day(bars_by_symbol, symbols)
    extremes = count_52w(bars_by_symbol, symbols, anchor)
    breadth = score_breadth(n, above_ema, above_sma, extremes["highs"], extremes["lows"])
    indices = _index_component(bars_by_symbol)
    sentiment = score_vix(vix_closes, vix_source)

    components = [
        indices,
        {
            "id": "breadth",
            "label": "Amplitud del universo",
            "available": breadth["available"],
            "points": breadth["points"] if breadth["available"] else None,
            "points_exact": breadth["points_exact"],
            "max_points": breadth["max_points"] if breadth["available"] else BREADTH_MAX,
            "parts": breadth["parts"],
            "detail": None,
        },
        {
            "id": "vix",
            "label": "Sentimiento (VIX)",
            "available": sentiment["available"],
            "points": sentiment["points"],
            "points_exact": sentiment["points_exact"],
            "max_points": sentiment["max_points"] if sentiment["available"] else VIX_MAX,
            "source": sentiment["source"],
            "close": sentiment["close"],
            "sma20": sentiment["sma20"],
            "sma50": sentiment["sma50"],
            "checks": sentiment["checks"],
            "detail": sentiment["detail"],
        },
    ]
    earned = 0.0
    available = 0.0
    for comp in components:
        if not comp["available"]:
            continue
        earned += float(comp["points_exact"])
        available += float(comp["max_points"])
    summary = finalize_score(earned, available)
    clock = format_clock(generated_at)
    series = breadth_ema200_series(bars_by_symbol, symbols, BREADTH_SESSIONS)
    vix_public = {
        "source": sentiment["source"],
        "available": sentiment["available"],
        "close": sentiment["close"],
        "sma20": sentiment["sma20"],
        "sma50": sentiment["sma50"],
        "detail": sentiment["detail"],
    }
    if vix_meta:
        vix_public["meta"] = vix_meta
    return {
        "score": summary["score"],
        "raw_points": summary["raw_points"],
        "points_available": summary["points_available"],
        "points_max": POINTS_MAX,
        "band": summary["band"],
        "components": components,
        "highs_lows": extremes,
        "breadth_series": series,
        "sessions": BREADTH_SESSIONS,
        "generated_at": generated_at,
        "asof_label": clock,
        "footer": footer_text(clock, summary["points_available"], POINTS_MAX),
        "vix": vix_public,
        "disclaimer": DISCLAIMER,
    }


def parse_cboe_vix_csv(text: str) -> list[float]:
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV de VIX sin encabezado")
    closes: list[float] = []
    for row in reader:
        norm = {(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}
        raw = norm.get("CLOSE")
        if not raw:
            continue
        closes.append(float(raw))
    if not closes:
        raise ValueError("CSV de VIX sin cierres")
    return closes


def fetch_cboe_vix_closes(url: str = CBOE_VIX_URL, timeout: int = 20) -> list[float]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "angus-dashboard/1.0", "Accept": "text/csv,*/*"},
        method="GET",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    closes = parse_cboe_vix_csv(payload)
    if len(closes) < 20:
        raise ValueError(f"VIX de CBOE demasiado corto ({len(closes)})")
    return closes
