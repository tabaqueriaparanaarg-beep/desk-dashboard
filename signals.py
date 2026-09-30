#!/usr/bin/env python3
"""Cálculos nuevos de Angus: patrones, insiders, fundamentos, semáforo, analistas y resumen.

No tocan el Desk Score. No llaman a la red. Los umbrales viven acá, con nombre.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Escáner de patrones
# ---------------------------------------------------------------------------
# Máximo de 52 semanas: cierre >= máximo de las sesiones previas (hasta 252,
# mínimo 60). Si no lo supera pero queda a <= 2% y el volumen de hoy supera
# la media de las 50 sesiones anteriores, también cuenta.
PATTERN_52W_SESSIONS = 252
PATTERN_52W_MIN_SESSIONS = 60
PATTERN_BREAKOUT_NEAR_PCT = 2.0
PATTERN_BREAKOUT_VOL_SESSIONS = 50

# Pullback a la SMA50 en tendencia: cierre sobre la EMA200, en las últimas 5
# sesiones el mínimo entró en la banda de ±2% de la SMA50 de esa sesión, y el
# cierre de hoy volvió a quedar por encima de la SMA50.
PATTERN_PULLBACK_LOOKBACK = 5
PATTERN_PULLBACK_NEAR_PCT = 2.0

# Base lateral: en una ventana de 15, 20 o 30 sesiones (~3 a 6 semanas) el
# rango (máximo − mínimo) / cierre es <= 6%, el cierre se movió <= 2% desde
# el inicio de esa ventana (si no, es tendencia, no lateral), el cierre está
# a <= 3% del máximo de la ventana y a <= 8% del máximo de 52 semanas.
PATTERN_BASE_WINDOWS = (15, 20, 30)
PATTERN_BASE_MAX_RANGE_PCT = 6.0
PATTERN_BASE_MAX_DRIFT_PCT = 2.0
PATTERN_BASE_NEAR_WINDOW_HIGH_PCT = 3.0
PATTERN_BASE_NEAR_52W_PCT = 8.0

# Cruce fresco de la EMA200: el último cruce (arriba o abajo) cayó dentro de
# las últimas 5 sesiones.
PATTERN_EMA_CROSS_SESSIONS = 5
PATTERN_EMA_PERIOD = 200
PATTERN_SMA_PERIOD = 50

PATTERN_ORDER: list[tuple[str, str]] = [
    ("breakout_52w", "Máximo 52s"),
    ("pullback_sma50", "Pullback SMA50"),
    ("base", "Base lateral"),
    ("ema200_cross_up", "Cruce EMA200 ↑"),
    ("ema200_cross_down", "Cruce EMA200 ↓"),
]
PATTERN_LABELS = dict(PATTERN_ORDER)

# ---------------------------------------------------------------------------
# Insiders (mercado abierto) y fundamentos
# ---------------------------------------------------------------------------
INSIDER_WINDOW_DAYS = 90
# Códigos SEC de mercado abierto. El resto (premios A, ejercicios M, etc.)
# se cuenta aparte y no entra en el neto.
INSIDER_OPEN_MARKET = {"P": "buy", "S": "sell"}
INSIDER_NOTABLE_MIN_BUYERS = 2
INSIDER_NOTABLE_MIN_NET_USD = 100_000.0
# Un solo insider, pero con un monto grande, también marca el badge.
INSIDER_NOTABLE_SOLO_USD = 500_000.0
INSIDER_TX_LIMIT = 5

# Mediana del sector: hace falta este mínimo de nombres con el dato (ETF afuera).
SECTOR_MEDIAN_MIN = 3
# Semáforo. Para «más alto es mejor» (márgenes, crecimiento): verde >= 1,05×
# la mediana, rojo <= 0,90×. Para P/E («más bajo es mejor»): verde <= 0,90×,
# rojo >= 1,15×. En el medio, ámbar. P/E negativo no se compara.
CUE_HIGHER_GREEN = 1.05
CUE_HIGHER_RED = 0.90
CUE_LOWER_GREEN = 0.90
CUE_LOWER_RED = 1.15

FUNDAMENTAL_SPECS: list[tuple[str, list[str]]] = [
    ("revenue_growth_yoy", ["revenueGrowthTTMYoy", "revenueGrowthQuarterlyYoy", "revenueGrowth3Y"]),
    ("eps_growth_yoy", ["epsGrowthTTMYoy", "epsGrowthQuarterlyYoy", "epsGrowth3Y"]),
    ("gross_margin", ["grossMarginTTM", "grossMarginAnnual"]),
    ("operating_margin", ["operatingMarginTTM", "operatingMarginAnnual"]),
    ("net_margin", ["netProfitMarginTTM", "netProfitMarginAnnual"]),
    ("debt_equity", ["totalDebt/totalEquityQuarterly", "totalDebt/totalEquityAnnual"]),
    ("current_ratio", ["currentRatioQuarterly", "currentRatioAnnual"]),
    ("pe_ttm", ["peTTM", "peBasicExclExtraTTM", "peNormalizedAnnual"]),
    ("roe", ["roeTTM", "roeRfy", "roe5Y"]),
    ("pb", ["pbQuarterly", "pbAnnual"]),
    ("ps_ttm", ["psTTM", "psAnnual"]),
    ("dividend_yield", ["dividendYieldIndicatedAnnual", "currentDividendYieldTTM"]),
]

# Se comparan contra la mediana del sector. direction: higher = más es mejor.
COMPARE_SPECS: list[tuple[str, str]] = [
    ("pe_ttm", "lower"),
    ("gross_margin", "higher"),
    ("operating_margin", "higher"),
    ("net_margin", "higher"),
    ("revenue_growth_yoy", "higher"),
    ("eps_growth_yoy", "higher"),
]

# ---------------------------------------------------------------------------
# Semáforo de riesgo. Informativo: no entra en el Desk Score ni reordena.
# ---------------------------------------------------------------------------
# No es una señal de compra. Verde = sin alertas de riesgo. Rojo si falla la
# tendencia o hay un cruce bajista reciente de la EMA200. Resultados cerca
# deja el semáforo en ámbar. No se mira estiramiento, Desk Score, patrón,
# sector ni flags: un estudio de feb-2022 a sep-2026 no les encontró el signo
# esperado, y las reglas de «muy estirado» no se invierten.
# Versión 1 era el semáforo de entrada (esas reglas de más). Las fotos viejas
# llevan rules_version 1 y no se mezclan con esta.
SEMAFORO_RULES_VERSION = 2
SEMAFORO_RULES_LABEL = "alerta de riesgo"
ENTRY_EARNINGS_DAYS = 7
ENTRY_BEARISH_PATTERN = "ema200_cross_down"
ENTRY_DISCLAIMER = "Alerta de riesgo automática. El verde no es una señal de compra."
ENTRY_LABELS = {
    "verde": "Verde: sin alertas de riesgo",
    "ambar": "Ámbar: resultados cerca",
    "rojo": "Rojo: alerta de riesgo",
}

# Recomendaciones de analistas (Finnhub /stock/recommendation). Mensual.
# Se guardan el período vigente y hasta 4 anteriores. No entran en el score.
ANALYST_HISTORY_LIMIT = 5
ANALYST_TREND_DAYS = 90
ANALYST_TREND_TOLERANCE_DAYS = 45
ANALYST_NOTE = "Los analistas suelen ser optimistas y reaccionan tarde. Es contexto, no señal."

# Movimiento de puestos que el resumen considera digno de mención.
RANK_MOVE_MIN = 3
# Variación de RS sectorial (puntos) que el resumen menciona.
SECTOR_RS_NOTABLE = 3.0
RESUMEN_NAME_CAP = 4


def ema(values: list[float], period: int) -> list[float | None]:
    """Misma EMA que build.ema (semilla = SMA de las primeras `period`)."""
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


def _f(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def _round(value: float | None, n: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), n)


def _fmt_es(value: float, digits: int = 1) -> str:
    neg = value < 0
    raw = f"{abs(value):,.{digits}f}"
    raw = raw.replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if neg else "") + raw


def _es_join(items: list[str]) -> str:
    clean = [x for x in items if x]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} y {clean[1]}"
    return ", ".join(clean[:-1]) + " y " + clean[-1]


def _cap_names(items: list[str], cap: int = RESUMEN_NAME_CAP) -> str:
    if len(items) <= cap:
        return _es_join(items)
    head = items[:cap]
    extra = len(items) - cap
    # Comas en la lista y un solo «y» antes del resto, para no decir «A y B y 2 más».
    return ", ".join(head) + f" y {extra} más"


# ---------------------------------------------------------------------------
# Patrones
# ---------------------------------------------------------------------------

def _ohlcv(bars: list[dict]) -> tuple[list[float], list[float], list[float], list[float]] | None:
    if not bars:
        return None
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    vols: list[float] = []
    for bar in bars:
        c = _f(bar.get("c"))
        if c is None:
            return None
        h = _f(bar.get("h"))
        l = _f(bar.get("l"))
        v = _f(bar.get("v"))
        closes.append(c)
        highs.append(c if h is None else h)
        lows.append(c if l is None else l)
        vols.append(0.0 if v is None else v)
    return closes, highs, lows, vols


def _detect_breakout(
    highs: list[float], closes: list[float], vols: list[float]
) -> dict[str, str] | None:
    n = len(closes)
    if n < PATTERN_52W_MIN_SESSIONS + 1:
        return None
    window = min(PATTERN_52W_SESSIONS, n)
    prior = highs[-window:-1]
    if len(prior) < PATTERN_52W_MIN_SESSIONS:
        return None
    prior_high = max(prior)
    close = closes[-1]
    if prior_high <= 0 or close <= 0:
        return None
    if close >= prior_high:
        return {
            "id": "breakout_52w",
            "label": PATTERN_LABELS["breakout_52w"],
            "detail": "Cierre en máximo de 52 semanas",
        }
    gap_pct = (prior_high - close) / prior_high * 100.0
    if gap_pct > PATTERN_BREAKOUT_NEAR_PCT:
        return None
    vol_n = PATTERN_BREAKOUT_VOL_SESSIONS
    hist = [v for v in vols[-vol_n - 1 : -1] if v > 0]
    if len(hist) < 20:
        return None
    avg = sum(hist) / len(hist)
    if avg <= 0 or vols[-1] <= avg:
        return None
    return {
        "id": "breakout_52w",
        "label": PATTERN_LABELS["breakout_52w"],
        "detail": (
            f"A {_fmt_es(gap_pct, 1)}% del máximo de 52 semanas, "
            "con volumen sobre la media de 50 días"
        ),
    }


def _detect_pullback(
    lows: list[float],
    closes: list[float],
    sma50: list[float | None],
    ema200: list[float | None],
) -> dict[str, str] | None:
    n = len(closes)
    if n < PATTERN_SMA_PERIOD + 1:
        return None
    if ema200[-1] is None or sma50[-1] is None:
        return None
    if closes[-1] <= ema200[-1] or closes[-1] <= sma50[-1]:
        return None
    start = max(0, n - PATTERN_PULLBACK_LOOKBACK)
    touched = False
    for i in range(start, n):
        sma_i = sma50[i]
        if sma_i is None or sma_i <= 0:
            continue
        dist = abs(lows[i] / sma_i - 1.0) * 100.0
        if dist <= PATTERN_PULLBACK_NEAR_PCT:
            touched = True
            break
    if not touched:
        return None
    return {
        "id": "pullback_sma50",
        "label": PATTERN_LABELS["pullback_sma50"],
        "detail": "Sobre la EMA200, tocó la SMA50 y cerró de nuevo arriba",
    }


def _detect_base(
    highs: list[float], lows: list[float], closes: list[float]
) -> dict[str, str] | None:
    n = len(closes)
    if n < min(PATTERN_BASE_WINDOWS):
        return None
    look = min(PATTERN_52W_SESSIONS, n)
    high_52 = max(highs[-look:])
    close = closes[-1]
    if high_52 <= 0 or close <= 0:
        return None
    dist_52 = (high_52 - close) / high_52 * 100.0
    if dist_52 > PATTERN_BASE_NEAR_52W_PCT:
        return None
    best: tuple[float, int] | None = None
    for win in PATTERN_BASE_WINDOWS:
        if n < win:
            continue
        wh = max(highs[-win:])
        wl = min(lows[-win:])
        first = closes[-win]
        if wh <= 0 or first <= 0:
            continue
        range_pct = (wh - wl) / close * 100.0
        drift_pct = abs(close / first - 1.0) * 100.0
        near_high = (wh - close) / wh * 100.0
        if range_pct > PATTERN_BASE_MAX_RANGE_PCT:
            continue
        if drift_pct > PATTERN_BASE_MAX_DRIFT_PCT:
            continue
        if near_high > PATTERN_BASE_NEAR_WINDOW_HIGH_PCT:
            continue
        if best is None or range_pct < best[0]:
            best = (range_pct, win)
    if best is None:
        return None
    range_pct, win = best
    weeks = max(1, round(win / 5))
    return {
        "id": "base",
        "label": PATTERN_LABELS["base"],
        "detail": (
            f"Rango de {_fmt_es(range_pct, 1)}% en {win} sesiones "
            f"(~{weeks} semanas), cerca de máximos"
        ),
    }


def _detect_cross(
    closes: list[float], ema200: list[float | None]
) -> dict[str, str] | None:
    n = len(closes)
    if ema200[-1] is None or n < 2:
        return None
    start = max(1, n - PATTERN_EMA_CROSS_SESSIONS)
    side: str | None = None
    for i in range(start, n):
        prev_e = ema200[i - 1]
        cur_e = ema200[i]
        if prev_e is None or cur_e is None:
            continue
        prev_c = closes[i - 1]
        cur_c = closes[i]
        if prev_c <= prev_e and cur_c > cur_e:
            side = "up"
        elif prev_c >= prev_e and cur_c < cur_e:
            side = "down"
    if side == "up":
        return {
            "id": "ema200_cross_up",
            "label": PATTERN_LABELS["ema200_cross_up"],
            "detail": "Cruce alcista de la EMA200 en las últimas 5 sesiones",
        }
    if side == "down":
        return {
            "id": "ema200_cross_down",
            "label": PATTERN_LABELS["ema200_cross_down"],
            "detail": "Cruce bajista de la EMA200 en las últimas 5 sesiones",
        }
    return None


def detect_patterns(bars: list[dict] | None) -> list[dict[str, str]]:
    """Patrones sobre barras diarias ascendentes (t, o, h, l, c, v)."""
    parsed = _ohlcv(list(bars or []))
    if parsed is None:
        return []
    closes, highs, lows, vols = parsed
    sma50 = sma(closes, PATTERN_SMA_PERIOD)
    ema200 = ema(closes, PATTERN_EMA_PERIOD)
    found: list[dict[str, str]] = []
    for hit in (
        _detect_breakout(highs, closes, vols),
        _detect_pullback(lows, closes, sma50, ema200),
        _detect_base(highs, lows, closes),
        _detect_cross(closes, ema200),
    ):
        if hit:
            found.append(hit)
    return found


def pattern_groups(rows: list[dict] | None) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for pid, label in PATTERN_ORDER:
        hits: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            for pat in row.get("patterns") or []:
                if not isinstance(pat, dict) or pat.get("id") != pid:
                    continue
                hits.append(
                    {
                        "symbol": row.get("symbol"),
                        "name": row.get("name"),
                        "desk_score": row.get("desk_score"),
                        "rank": row.get("rank"),
                        "detail": pat.get("detail"),
                    }
                )
        hits.sort(
            key=lambda h: (
                -(h["desk_score"] if isinstance(h["desk_score"], (int, float)) else -1),
                str(h.get("symbol") or ""),
            )
        )
        groups.append({"id": pid, "label": label, "count": len(hits), "rows": hits})
    return groups


# ---------------------------------------------------------------------------
# Insiders
# ---------------------------------------------------------------------------

def _norm_name(name: Any) -> str:
    text = " ".join(str(name or "").upper().split())
    return text or "SIN NOMBRE"


def _tx_date(row: dict) -> date | None:
    raw = row.get("transactionDate") or row.get("filingDate") or row.get("date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _tx_role(row: dict) -> str | None:
    for key in ("position", "title", "role", "relationship"):
        val = row.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return None


def _is_notable(net_shares: float, buyers: int, net_value: float | None) -> bool:
    if net_shares <= 0 or buyers < 1:
        return False
    if net_value is None:
        return False
    if buyers >= INSIDER_NOTABLE_MIN_BUYERS and net_value >= INSIDER_NOTABLE_MIN_NET_USD:
        return True
    if net_value >= INSIDER_NOTABLE_SOLO_USD:
        return True
    return False


def aggregate_insiders(
    raw_rows: list[dict] | None,
    *,
    today: date,
    window_days: int = INSIDER_WINDOW_DAYS,
    close: float | None = None,
    fetched_on: date | None = None,
) -> dict[str, Any]:
    """Resume compras y ventas de mercado abierto en la ventana.

    P = compra, S = venta. Cualquier otro código (premios, ejercicios,
    regalos) queda en `excluded_count` y no mueve el neto.
    """
    start = today - timedelta(days=window_days)
    close_px = _f(close)
    buy_shares = 0.0
    sell_shares = 0.0
    buy_value = 0.0
    sell_value = 0.0
    value_approx = False
    priced = False
    buyers: set[str] = set()
    sellers: set[str] = set()
    excluded = 0
    open_rows: list[dict[str, Any]] = []
    latest: date | None = None

    for row in raw_rows or []:
        if not isinstance(row, dict):
            continue
        when = _tx_date(row)
        if when is None or when < start or when > today:
            continue
        code = str(row.get("transactionCode") or row.get("code") or "").strip().upper()
        side = INSIDER_OPEN_MARKET.get(code)
        change = _f(row.get("change"))
        if side is None:
            if change not in (None, 0.0):
                excluded += 1
            continue
        if change is None or change == 0.0:
            continue
        shares = abs(change)
        price = _f(row.get("transactionPrice"))
        if price is not None and price <= 0:
            price = None
        used_close = False
        if price is None and close_px is not None and close_px > 0:
            price = close_px
            used_close = True
            value_approx = True
        value = shares * price if price is not None else None
        if value is not None:
            priced = True
        name = _norm_name(row.get("name"))
        if side == "buy":
            buy_shares += shares
            buyers.add(name)
            if value is not None:
                buy_value += value
        else:
            sell_shares += shares
            sellers.add(name)
            if value is not None:
                sell_value += value
        if latest is None or when > latest:
            latest = when
        open_rows.append(
            {
                "name": name,
                "role": _tx_role(row),
                "side": side,
                "shares": _round(shares, 0),
                "price": _round(price, 2) if price is not None else None,
                "value_usd": _round(value, 0) if value is not None else None,
                "date": when.isoformat(),
                "code": code,
                "price_approx": used_close,
            }
        )

    open_rows.sort(key=lambda r: (r["date"], r["name"]), reverse=True)
    net_shares = buy_shares - sell_shares
    net_value = None
    if priced:
        net_value = buy_value - sell_value
    summary = {
        "source": "finnhub",
        "endpoint": "/stock/insider-transactions",
        "fetched_on": (fetched_on or today).isoformat(),
        "window_days": window_days,
        "window_start": start.isoformat(),
        "window_end": today.isoformat(),
        "net_shares": _round(net_shares, 0),
        "buy_shares": _round(buy_shares, 0),
        "sell_shares": _round(sell_shares, 0),
        "buy_value_usd": _round(buy_value, 0) if priced else None,
        "sell_value_usd": _round(sell_value, 0) if priced else None,
        "net_value_usd": _round(net_value, 0) if net_value is not None else None,
        "value_approx": bool(value_approx and priced),
        "buyers": len(buyers),
        "sellers": len(sellers),
        "latest_date": latest.isoformat() if latest else None,
        "open_market_count": len(open_rows),
        "excluded_count": excluded,
        "notable": _is_notable(net_shares, len(buyers), net_value),
        "transactions": open_rows[:INSIDER_TX_LIMIT],
    }
    return summary


def insider_panel(rows: list[dict] | None, limit: int = 8) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ins = row.get("insiders")
        if not isinstance(ins, dict):
            continue
        net = _f(ins.get("net_shares"))
        if net is None or net <= 0:
            continue
        hits.append(
            {
                "symbol": row.get("symbol"),
                "name": row.get("name"),
                "desk_score": row.get("desk_score"),
                "rank": row.get("rank"),
                "net_shares": ins.get("net_shares"),
                "net_value_usd": ins.get("net_value_usd"),
                "value_approx": bool(ins.get("value_approx")),
                "buyers": ins.get("buyers"),
                "sellers": ins.get("sellers"),
                "latest_date": ins.get("latest_date"),
                "notable": bool(ins.get("notable")),
            }
        )
    hits.sort(
        key=lambda h: (
            h.get("net_value_usd") is None,
            -(_f(h.get("net_value_usd")) or 0.0),
            -(_f(h.get("net_shares")) or 0.0),
            str(h.get("symbol") or ""),
        )
    )
    return {
        "window_days": INSIDER_WINDOW_DAYS,
        "caption": (
            "Compras netas de insiders en el mercado abierto (códigos P y S), "
            f"últimos {INSIDER_WINDOW_DAYS} días. Premios y ejercicios de opciones no cuentan. "
            "Sin tenedores 13F."
        ),
        "rows": hits[:limit],
    }


# ---------------------------------------------------------------------------
# Fundamentos y mediana del sector
# ---------------------------------------------------------------------------

def _metric_dict(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("metric")
    if isinstance(inner, dict):
        return inner
    return payload


def parse_fundamentals(payload: dict | None, *, fetched_on: date) -> dict[str, Any]:
    metric = _metric_dict(payload)
    metrics: dict[str, float | None] = {}
    for key, aliases in FUNDAMENTAL_SPECS:
        found = None
        for alias in aliases:
            if alias not in metric:
                continue
            num = _f(metric.get(alias))
            if num is None:
                continue
            found = _round(num, 2)
            break
        metrics[key] = found
    return {
        "source": "finnhub",
        "endpoint": "/stock/metric",
        "fetched_on": fetched_on.isoformat(),
        "metrics": metrics,
        "vs_sector": {},
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ys = sorted(values)
    n = len(ys)
    mid = n // 2
    if n % 2:
        return ys[mid]
    return (ys[mid - 1] + ys[mid]) / 2.0


def metric_cue(direction: str, value: float | None, median: float | None) -> str | None:
    """green / amber / red, o None si no corresponde comparar."""
    if value is None or median is None:
        return None
    if direction == "lower":
        if value <= 0 or median <= 0:
            return None
        ratio = value / median
        if ratio <= CUE_LOWER_GREEN:
            return "green"
        if ratio >= CUE_LOWER_RED:
            return "red"
        return "amber"
    # higher es mejor. Con mediana positiva, razón. Si no, se mira la diferencia
    # para no invertir el sentido cuando los dos números son negativos.
    if median > 0 and value > 0:
        ratio = value / median
        if ratio >= CUE_HIGHER_GREEN:
            return "green"
        if ratio <= CUE_HIGHER_RED:
            return "red"
        return "amber"
    band = max(abs(median) * 0.05, 0.5)
    if value >= median + band:
        return "green"
    if value <= median - band:
        return "red"
    return "amber"


def _is_etf(row: dict) -> bool:
    return str(row.get("kind") or "").strip().lower() == "etf"


def _sector_of(row: dict) -> str:
    return str(row.get("sector") or "").strip()


def attach_sector_medians(rows: list[dict] | None) -> None:
    """Completa fundamentals.vs_sector. No modifica el Desk Score."""
    usable = [
        r
        for r in (rows or [])
        if isinstance(r, dict) and not _is_etf(r) and _sector_of(r) and _sector_of(r) != "Benchmark"
    ]
    by_sector: dict[str, list[dict]] = {}
    for row in usable:
        by_sector.setdefault(_sector_of(row), []).append(row)

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        fund = row.get("fundamentals")
        if not isinstance(fund, dict):
            continue
        metrics = fund.get("metrics") if isinstance(fund.get("metrics"), dict) else {}
        vs: dict[str, Any] = {}
        peers = by_sector.get(_sector_of(row), []) if not _is_etf(row) else []
        for key, direction in COMPARE_SPECS:
            vals: list[float] = []
            for peer in peers:
                peer_m = (peer.get("fundamentals") or {}).get("metrics") or {}
                num = _f(peer_m.get(key))
                if num is not None:
                    vals.append(num)
            med = _median(vals) if len(vals) >= SECTOR_MEDIAN_MIN else None
            value = _f(metrics.get(key))
            vs[key] = {
                "value": _round(value, 2) if value is not None else None,
                "median": _round(med, 2) if med is not None else None,
                "n": len(vals),
                "direction": direction,
                "cue": metric_cue(direction, value, med),
            }
        fund["vs_sector"] = vs


# ---------------------------------------------------------------------------
# Semáforo de riesgo
# ---------------------------------------------------------------------------

def _pattern_ids(row: dict) -> list[str]:
    ids: list[str] = []
    for pat in row.get("patterns") or []:
        if isinstance(pat, dict) and pat.get("id"):
            ids.append(str(pat["id"]))
        elif isinstance(pat, str):
            ids.append(pat)
    return ids


def _check(cid: str, label: str, ok: bool, reason: str, *, critical: bool = True, hard: bool = False) -> dict[str, Any]:
    return {
        "id": cid,
        "label": label,
        "ok": bool(ok),
        "critical": critical,
        "hard": hard,
        "reason": reason,
    }


def _check_trend(row: dict) -> dict[str, Any]:
    if row.get("ema200") is None and not row.get("above_ema200"):
        return _check("trend", "Tendencia", False, "Sin EMA200", hard=True)
    if not row.get("above_ema200"):
        return _check("trend", "Tendencia", False, "Precio bajo la EMA200", hard=True)
    if row.get("ema200_slope_up") is False:
        return _check("trend", "Tendencia", False, "EMA200 con pendiente en baja", hard=True)
    if row.get("ema200_slope_up") is None:
        return _check("trend", "Tendencia", False, "Sin pendiente de la EMA200", hard=True)
    return _check("trend", "Tendencia", True, "Precio sobre la EMA200 y pendiente en alza", hard=True)


def _parse_iso_date(value: Any) -> date | None:
    text = str(value or "")[:10]
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _check_earnings(
    row: dict,
    earnings: list[dict] | None,
    today: date,
    *,
    earnings_known: bool,
    earnings_through: date | None,
    earnings_backfill: bool = False,
) -> dict[str, Any]:
    if earnings_backfill:
        # El calendario de resultados no se puede reconstruir hacia atrás.
        # El chequeo se toma como aprobado y queda marcado para no mezclarlo
        # con una lectura que sí vio el calendario.
        check = _check(
            "earnings",
            "Resultados",
            True,
            "Reconstruido: no hay calendario de resultados de ese día; se toma como aprobado",
        )
        check["reconstructed"] = True
        return check
    sym = str(row.get("symbol") or "").upper()
    horizon = today + timedelta(days=ENTRY_EARNINGS_DAYS)
    upcoming: list[date] = []
    for earn in earnings or []:
        if not isinstance(earn, dict):
            continue
        if str(earn.get("symbol") or "").upper() != sym:
            continue
        when = _parse_iso_date(earn.get("date"))
        if when is None:
            continue
        if today <= when <= horizon:
            upcoming.append(when)
    if upcoming:
        when = min(upcoming)
        return _check("earnings", "Resultados", False, f"Presenta resultados el {when.strftime('%d/%m')}")
    limited = (not earnings_known) or earnings_through is None or earnings_through < horizon
    if not earnings_known or earnings_through is None:
        return _check(
            "earnings",
            "Resultados",
            True,
            "Sin resultados publicados; la cobertura de earnings es limitada",
        )
    if limited:
        return _check(
            "earnings",
            "Resultados",
            True,
            f"Sin resultados hasta el {earnings_through.strftime('%d/%m')}; el calendario no cubre los {ENTRY_EARNINGS_DAYS} días",
        )
    return _check("earnings", "Resultados", True, f"Sin resultados en los próximos {ENTRY_EARNINGS_DAYS} días")


def _check_bearish(row: dict) -> dict[str, Any]:
    if ENTRY_BEARISH_PATTERN in _pattern_ids(row):
        return _check(
            "bearish_cross",
            "Cruce EMA200",
            False,
            "Cruce bajista de la EMA200 en las últimas sesiones",
            hard=True,
        )
    return _check(
        "bearish_cross",
        "Cruce EMA200",
        True,
        "Sin cruce bajista reciente de la EMA200",
        hard=True,
    )


def entry_verdict(
    row: dict,
    *,
    sector_index: dict[str, dict[str, Any]] | None = None,
    earnings: list[dict] | None = None,
    today: date,
    earnings_known: bool = False,
    earnings_through: date | None = None,
    earnings_backfill: bool = False,
    rs_weeks: int | None = None,
    rs_band: float | None = None,
) -> dict[str, Any]:
    """Alerta de riesgo: verde / ámbar / rojo. No lee ni escribe el Desk Score.

    `sector_index`, `rs_weeks` y `rs_band` se aceptan para no romper llamadas
    viejas. Ya no cambian el color.
    """
    del sector_index, rs_weeks, rs_band
    checks = [
        _check_trend(row),
        _check_bearish(row),
        _check_earnings(
            row,
            earnings,
            today,
            earnings_known=earnings_known,
            earnings_through=earnings_through,
            earnings_backfill=earnings_backfill,
        ),
    ]
    hard_fail = any(c["hard"] and not c["ok"] for c in checks)
    critical_ok = all(c["ok"] for c in checks if c["critical"])
    if hard_fail:
        verdict = "rojo"
    elif critical_ok:
        verdict = "verde"
    else:
        verdict = "ambar"
    return {
        "verdict": verdict,
        "label": ENTRY_LABELS[verdict],
        "disclaimer": ENTRY_DISCLAIMER,
        "rules_version": SEMAFORO_RULES_VERSION,
        "checks": checks,
    }


def attach_entry_lights(
    rows: list[dict] | None,
    sectors: dict | None,
    earnings: list[dict] | None,
    *,
    today: date,
    earnings_known: bool = False,
    earnings_through: date | None = None,
    earnings_backfill: bool = False,
) -> None:
    """Escribe row['entry']. No toca desk_score, rank ni el orden de la lista."""
    del sectors
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        row["entry"] = entry_verdict(
            row,
            earnings=earnings,
            today=today,
            earnings_known=earnings_known,
            earnings_through=earnings_through,
            earnings_backfill=earnings_backfill,
        )


# ---------------------------------------------------------------------------
# Opinión de los analistas
# ---------------------------------------------------------------------------

def _count(value: Any) -> int:
    num = _f(value)
    if num is None or num < 0:
        return 0
    return int(round(num))


def _period_block(row: dict) -> dict[str, Any] | None:
    period = str(row.get("period") or "")[:10]
    if _parse_iso_date(period) is None:
        return None
    strong_buy = _count(row.get("strongBuy"))
    buy = _count(row.get("buy"))
    hold = _count(row.get("hold"))
    sell = _count(row.get("sell"))
    strong_sell = _count(row.get("strongSell"))
    total = strong_buy + buy + hold + sell + strong_sell
    buy_count = strong_buy + buy
    buy_pct = round(buy_count / total * 100.0, 1) if total else None
    return {
        "period": period,
        "strong_buy": strong_buy,
        "buy": buy,
        "hold": hold,
        "sell": sell,
        "strong_sell": strong_sell,
        "total": total,
        "buy_count": buy_count,
        "buy_pct": buy_pct,
    }


def _analyst_trend(periods: list[dict[str, Any]]) -> dict[str, Any]:
    empty = {
        "direction": None,
        "label": "Sin historia de hace 3 meses para comparar",
        "period": None,
        "buy_count": None,
    }
    if len(periods) < 2 or not periods[0].get("period"):
        return empty
    latest = _parse_iso_date(periods[0]["period"])
    if latest is None:
        return empty
    target = latest - timedelta(days=ANALYST_TREND_DAYS)
    best: dict[str, Any] | None = None
    best_gap: int | None = None
    for item in periods[1:]:
        when = _parse_iso_date(item.get("period"))
        if when is None:
            continue
        gap = abs((when - target).days)
        if gap > ANALYST_TREND_TOLERANCE_DAYS:
            continue
        if best is None or best_gap is None or gap < best_gap:
            best = item
            best_gap = gap
    if best is None:
        return empty
    now_buys = int(periods[0].get("buy_count") or 0)
    old_buys = int(best.get("buy_count") or 0)
    if now_buys > old_buys:
        direction = "up"
        label = f"Más compras que hace 3 meses ({now_buys} contra {old_buys})"
    elif now_buys < old_buys:
        direction = "down"
        label = f"Menos compras que hace 3 meses ({now_buys} contra {old_buys})"
    else:
        direction = "flat"
        label = "Igual cantidad de compras que hace 3 meses"
    return {
        "direction": direction,
        "label": label,
        "period": best.get("period"),
        "buy_count": old_buys,
    }


def parse_recommendations(
    payload: Any,
    *,
    fetched_on: date,
    price_target: dict | None = None,
) -> dict[str, Any]:
    """Último mes y hasta 4 anteriores. % compra = (strongBuy + buy) / total."""
    if isinstance(payload, dict):
        raw = payload.get("data") if isinstance(payload.get("data"), list) else []
    elif isinstance(payload, list):
        raw = payload
    else:
        raw = []
    periods: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        block = _period_block(row)
        if block is None or block["period"] in seen:
            continue
        seen.add(block["period"])
        periods.append(block)
    periods.sort(key=lambda p: p["period"], reverse=True)
    periods = periods[:ANALYST_HISTORY_LIMIT]
    trend = _analyst_trend(periods) if periods else {
        "direction": None,
        "label": "Sin recomendaciones en el último período",
        "period": None,
        "buy_count": None,
    }
    latest = periods[0] if periods else None
    target = price_target if isinstance(price_target, dict) else None
    return {
        "source": "finnhub",
        "endpoint": "/stock/recommendation",
        "fetched_on": fetched_on.isoformat(),
        "latest": latest,
        "history": periods,
        "buy_pct": latest.get("buy_pct") if latest else None,
        "total": latest.get("total") if latest else None,
        "trend": trend["direction"],
        "trend_label": trend["label"],
        "compare_period": trend["period"],
        "compare_buy_count": trend["buy_count"],
        "price_target": target,
        "note": ANALYST_NOTE,
    }


def parse_price_target(payload: Any) -> dict[str, Any] | None:
    """Solo números positivos que vinieron en la respuesta. Nunca inventa un target."""
    if not isinstance(payload, dict) or payload.get("error"):
        return None

    def _px(key: str) -> float | None:
        num = _f(payload.get(key))
        if num is None or num <= 0:
            return None
        return round(num, 2)

    high = _px("targetHigh")
    low = _px("targetLow")
    mean = _px("targetMean")
    median = _px("targetMedian")
    if high is None and low is None and mean is None and median is None:
        return None
    updated = str(payload.get("lastUpdated") or "")[:10]
    if _parse_iso_date(updated) is None:
        updated = ""
    return {
        "high": high,
        "low": low,
        "mean": mean,
        "median": median,
        "last_updated": updated or None,
    }


# ---------------------------------------------------------------------------
# Resumen diario
# ---------------------------------------------------------------------------

def _rank_of(row: dict) -> int | None:
    try:
        rank = int(row.get("rank"))
    except (TypeError, ValueError):
        return None
    return rank


def snapshot_from_payload(payload: dict | None) -> dict[str, Any]:
    """Foto chica para comparar dos publicaciones. No incluye series de precios."""
    data = payload or {}
    rows = [r for r in (data.get("ranking") or []) if isinstance(r, dict)]
    ranks: dict[str, int] = {}
    above: dict[str, bool] = {}
    patterns: dict[str, list[str]] = {}
    patterns_known = False
    insiders: list[dict[str, Any]] = []
    spy_change = None
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        rank = _rank_of(row)
        if rank is not None:
            ranks[sym] = rank
        if "above_ema200" in row:
            above[sym] = bool(row.get("above_ema200"))
        if sym == "SPY":
            spy_change = _f(row.get("change_pct"))
        if "patterns" in row:
            patterns_known = True
            ids: list[str] = []
            for pat in row.get("patterns") or []:
                if isinstance(pat, dict) and pat.get("id"):
                    ids.append(str(pat["id"]))
                elif isinstance(pat, str):
                    ids.append(pat)
            patterns[sym] = ids
        ins = row.get("insiders")
        if isinstance(ins, dict):
            net = _f(ins.get("net_shares"))
            if net is not None and net > 0:
                insiders.append(
                    {
                        "symbol": sym,
                        "net_shares": net,
                        "net_value_usd": _f(ins.get("net_value_usd")),
                        "buyers": int(ins.get("buyers") or 0),
                        "notable": bool(ins.get("notable")),
                    }
                )
    top10 = [sym for sym, rank in sorted(ranks.items(), key=lambda kv: (kv[1], kv[0])) if rank <= 10]
    regime = data.get("regime") or data.get("regime_stub") or {}
    sectors_out: list[dict[str, Any]] = []
    for sec in ((data.get("sectors") or {}).get("rows") or []):
        if not isinstance(sec, dict):
            continue
        sectors_out.append(
            {
                "label": sec.get("label") or sec.get("sector") or "",
                "avg_desk_score": _f(sec.get("avg_desk_score")),
                "rs_delta": _f(sec.get("rs_delta")),
            }
        )
    rank_by_sym = ranks
    entry_known = False
    greens: list[tuple[int, str]] = []
    for row in rows:
        if "entry" not in row:
            continue
        entry_known = True
        ent = row.get("entry")
        if not isinstance(ent, dict) or ent.get("verdict") != "verde":
            continue
        if str(row.get("kind") or "").strip().lower() == "etf":
            continue
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        rank = rank_by_sym.get(sym)
        greens.append((rank if rank is not None else 10**9, sym))
    greens.sort()
    earnings_out: list[dict[str, Any]] = []
    for earn in data.get("earnings") or []:
        if not isinstance(earn, dict):
            continue
        sym = str(earn.get("symbol") or "").upper()
        if not sym:
            continue
        earnings_out.append(
            {
                "symbol": sym,
                "date": earn.get("date"),
                "rank": rank_by_sym.get(sym),
            }
        )
    return {
        "generated_at": data.get("generated_at"),
        "regime_label": (regime or {}).get("label") or "sin dato",
        "spy_change_pct": spy_change,
        "top10": top10,
        "ranks": ranks,
        "above_ema200": above,
        "sectors": sectors_out,
        "earnings": earnings_out,
        "patterns": patterns,
        "patterns_known": patterns_known,
        "insiders": insiders,
        "entry_known": entry_known,
        "entry_green": [sym for _rank, sym in greens],
    }


def _fmt_pct_signed(value: float | None) -> str | None:
    if value is None:
        return None
    body = _fmt_es(abs(value), 2)
    if value > 0:
        return "+" + body + "%"
    if value < 0:
        return "−" + body + "%"
    return body + "%"


def _fmt_usd_short(value: float | None) -> str | None:
    if value is None:
        return None
    sign = "−" if value < 0 else ""
    n = abs(value)
    if n >= 1_000_000:
        return f"{sign}USD {_fmt_es(n / 1_000_000, 1)} millones"
    if n >= 1_000:
        return f"{sign}USD {_fmt_es(n / 1_000, 0)} mil"
    return f"{sign}USD {_fmt_es(n, 0)}"


def _fmt_art(iso: str | None) -> str | None:
    if not iso:
        return None
    text = str(iso).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.strftime("%d/%m/%Y %H:%M ART")


def _sentence_regime(snap: dict) -> str:
    label = snap.get("regime_label") or "sin dato"
    spy = _fmt_pct_signed(_f(snap.get("spy_change_pct")))
    if spy:
        return f"El régimen del universo está {label} y SPY cerró el día {spy}."
    return f"El régimen del universo está {label}."


def _sentence_top10(today: dict, prev: dict) -> str:
    now = list(today.get("top10") or [])
    old = list(prev.get("top10") or [])
    entered = [s for s in now if s not in old]
    left = [s for s in old if s not in now]
    if entered and left:
        return f"Entraron al Top 10 {_cap_names(entered)}, y salieron {_cap_names(left)}."
    if entered:
        return f"Entraron al Top 10 {_cap_names(entered)}."
    if left:
        return f"Salieron del Top 10 {_cap_names(left)}."
    return "El Top 10 mantuvo los mismos nombres."


def _sentences_sectors(snap: dict) -> list[str]:
    scored = [s for s in (snap.get("sectors") or []) if _f(s.get("avg_desk_score")) is not None]
    if not scored:
        return []
    best = max(scored, key=lambda s: (_f(s["avg_desk_score"]) or 0, str(s.get("label"))))
    worst = min(scored, key=lambda s: (_f(s["avg_desk_score"]) or 0, str(s.get("label"))))
    best_txt = f"{best.get('label')} (Desk {_fmt_es(_f(best['avg_desk_score']) or 0, 1)})"
    if best.get("label") == worst.get("label"):
        out = [f"El sector más fuerte del universo es {best_txt}."]
    else:
        worst_txt = f"{worst.get('label')} (Desk {_fmt_es(_f(worst['avg_desk_score']) or 0, 1)})"
        out = [f"El sector más fuerte es {best_txt} y el más débil es {worst_txt}."]
    notable = None
    notable_abs = 0.0
    for sec in scored:
        delta = _f(sec.get("rs_delta"))
        if delta is None or abs(delta) < SECTOR_RS_NOTABLE:
            continue
        if abs(delta) > notable_abs:
            notable = sec
            notable_abs = abs(delta)
    if notable is not None:
        delta = _f(notable.get("rs_delta")) or 0.0
        direction = "subió" if delta > 0 else "bajó"
        out.append(
            f"En fuerza relativa, {notable.get('label')} {direction} "
            f"{_fmt_es(abs(delta), 1)} puntos contra hace 4 semanas."
        )
    return out


def _sentence_ranks(today: dict, prev: dict) -> str:
    climbs: list[tuple[int, str]] = []
    drops: list[tuple[int, str]] = []
    prev_ranks = prev.get("ranks") or {}
    for sym, rank in (today.get("ranks") or {}).items():
        old = prev_ranks.get(sym)
        if old is None:
            continue
        delta = int(old) - int(rank)
        if delta >= RANK_MOVE_MIN:
            climbs.append((delta, sym))
        elif delta <= -RANK_MOVE_MIN:
            drops.append((-delta, sym))
    climbs.sort(key=lambda x: (-x[0], x[1]))
    drops.sort(key=lambda x: (-x[0], x[1]))
    if not climbs and not drops:
        return f"Ningún nombre se movió {RANK_MOVE_MIN} puestos o más en el ranking."
    bits: list[str] = []
    if climbs:
        parts = [f"{sym} subió {n} puestos" for n, sym in climbs[:3]]
        bits.append(_es_join(parts))
    if drops:
        parts = [f"{sym} bajó {n} puestos" for n, sym in drops[:3]]
        bits.append(_es_join(parts))
    return "En el ranking, " + ", y ".join(bits) + "."


def _fmt_day(iso: Any) -> str:
    text = str(iso or "")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[8:10] + "/" + text[5:7]
    return text


def _sentence_earnings(snap: dict) -> str:
    rows = list(snap.get("earnings") or [])
    if not rows:
        return "Esta semana no hay resultados de nombres del universo."
    rows.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("symbol") or "")))
    bits: list[str] = []
    top20: list[str] = []
    for earn in rows[:5]:
        sym = str(earn.get("symbol") or "")
        rank = earn.get("rank")
        when = _fmt_day(earn.get("date"))
        extra = f" el {when}" if when else ""
        if isinstance(rank, int):
            flag = ""
            if rank <= 20:
                flag = ", en el Top 20"
                top20.append(sym)
            bits.append(f"{sym}{extra} (puesto {rank}{flag})")
        else:
            bits.append(f"{sym}{extra}" if extra else sym)
    more = ""
    if len(rows) > 5:
        more = f", y {len(rows) - 5} más"
    return "Esta semana presentan resultados " + _es_join(bits) + more + "."


def _sentence_ema(today: dict, prev: dict) -> str:
    lost: list[str] = []
    regained: list[str] = []
    prev_above = prev.get("above_ema200") or {}
    for sym, now in (today.get("above_ema200") or {}).items():
        if sym not in prev_above:
            continue
        old = bool(prev_above.get(sym))
        if old and not now:
            lost.append(sym)
        elif now and not old:
            regained.append(sym)
    lost.sort()
    regained.sort()
    if not lost and not regained:
        return "Nadie perdió ni recuperó la EMA200."
    if lost and regained:
        return (
            f"Perdieron la EMA200 {_cap_names(lost)}, "
            f"y la recuperaron {_cap_names(regained)}."
        )
    if lost:
        return f"Perdieron la EMA200 {_cap_names(lost)}."
    return f"Recuperaron la EMA200 {_cap_names(regained)}."


def _pattern_pairs(snap: dict) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for sym, ids in (snap.get("patterns") or {}).items():
        for pid in ids or []:
            pairs.add((str(sym), str(pid)))
    return pairs


def _sentence_patterns(today: dict, prev: dict | None) -> str:
    counts: dict[str, list[str]] = {pid: [] for pid, _ in PATTERN_ORDER}
    if prev is not None and prev.get("patterns_known"):
        fresh = _pattern_pairs(today) - _pattern_pairs(prev)
        if not fresh:
            return "El escáner no sumó patrones nuevos."
        for sym, pid in sorted(fresh):
            if pid in counts:
                counts[pid].append(sym)
        nice = {
            "breakout_52w": "máximo de 52 semanas",
            "pullback_sma50": "pullback a la SMA50",
            "base": "base lateral",
            "ema200_cross_up": "cruce alcista de la EMA200",
            "ema200_cross_down": "cruce bajista de la EMA200",
        }
        bits: list[str] = []
        for pid, _label in PATTERN_ORDER:
            names = counts[pid]
            if not names:
                continue
            bits.append(f"{nice[pid]} en {_cap_names(names)}")
        return "En el escáner aparecieron " + _es_join(bits) + "."
    for sym, ids in (today.get("patterns") or {}).items():
        for pid in ids or []:
            if pid in counts:
                counts[pid].append(str(sym))
    total = sum(len(v) for v in counts.values())
    if total == 0:
        return "Hoy el escáner no marca ningún patrón."
    bits = []
    nice = {
        "breakout_52w": "máximos de 52 semanas",
        "pullback_sma50": "pullbacks a la SMA50",
        "base": "bases laterales",
        "ema200_cross_up": "cruces alcistas de la EMA200",
        "ema200_cross_down": "cruces bajistas de la EMA200",
    }
    for pid, _label in PATTERN_ORDER:
        n = len(counts[pid])
        if n:
            bits.append(f"{n} {nice[pid]}")
    return "Hoy el escáner marca " + _es_join(bits) + "."


def _sentence_entry(snap: dict) -> str | None:
    if not snap.get("entry_known"):
        return None
    greens = [str(s) for s in (snap.get("entry_green") or []) if s]
    n = len(greens)
    if n == 0:
        return "Hoy no hay acciones sin alertas de riesgo."
    noun = "acción" if n == 1 else "acciones"
    return f"Hoy hay {n} {noun} sin alertas de riesgo: {_cap_names(greens)}."


def _sentence_insiders(snap: dict) -> str:
    rows = list(snap.get("insiders") or [])
    rows = [r for r in rows if (_f(r.get("net_shares")) or 0) > 0]
    if not rows:
        return "No hay compras netas de insiders en los datos de esta corrida."
    rows.sort(
        key=lambda r: (
            0 if r.get("notable") else 1,
            -(_f(r.get("net_value_usd")) or 0.0),
            -(_f(r.get("net_shares")) or 0.0),
            str(r.get("symbol") or ""),
        )
    )
    top = rows[:2]
    bits = []
    for row in top:
        money = _fmt_usd_short(_f(row.get("net_value_usd")))
        buyers = int(row.get("buyers") or 0)
        who = f"{buyers} insiders comprando" if buyers != 1 else "1 insider comprando"
        if money:
            bits.append(f"{row.get('symbol')} ({money}, {who})")
        else:
            bits.append(f"{row.get('symbol')} ({who})")
    return "En compras de insiders de los últimos 90 días se destaca " + _es_join(bits) + "."


def compose_resumen(today: dict, previous: dict | None) -> dict[str, Any]:
    """Texto corto en español de Argentina, solo con hechos de las dos fotos."""
    sentences: list[str] = [_sentence_regime(today)]
    green = _sentence_entry(today)
    if green:
        sentences.append(green)
    if previous is not None:
        sentences.append(_sentence_top10(today, previous))
    sentences.extend(_sentences_sectors(today))
    if previous is not None:
        sentences.append(_sentence_ranks(today, previous))
    sentences.append(_sentence_earnings(today))
    if previous is not None:
        sentences.append(_sentence_ema(today, previous))
    sentences.append(_sentence_patterns(today, previous))
    sentences.append(_sentence_insiders(today))
    if previous is None:
        sentences.append(
            "No hay una publicación anterior para comparar el Top 10, los puestos ni la EMA200."
        )
    n_ranks = len(today.get("ranks") or {})
    if n_ranks and len([s for s in sentences if s and s.strip()]) < 6:
        above_n = sum(1 for v in (today.get("above_ema200") or {}).values() if v)
        sentences.append(
            f"El ranking de hoy tiene {n_ranks} nombres, {above_n} sobre la EMA200."
        )
    # Tope blando: el armado de arriba ya apunta a 6–10 oraciones.
    sentences = [s.strip() for s in sentences if s and s.strip()]
    if len(sentences) > 10:
        tail = " ".join(sentences[9:])
        sentences = sentences[:9] + [tail]
    text = " ".join(sentences)
    when = _fmt_art(today.get("generated_at"))
    headline = f"Angus — resumen del {when}" if when else "Angus — resumen"
    return {
        "generated_at": today.get("generated_at"),
        "headline": headline,
        "text": text,
        "sentences": sentences,
        "compared_to": (previous or {}).get("generated_at") if previous else None,
    }
