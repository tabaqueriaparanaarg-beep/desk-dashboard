#!/usr/bin/env python3
"""Hacia dónde va la plata: termómetro de rotación entre sectores.

Muestra, en las últimas 4 semanas (20 ruedas), cómo le fue a cada sector del
S&P 500 (los 11 ETF «Select Sector») contra el SPY, y cuatro lecturas:

- salud y consumo básico contra tecnología (defensivas contra la que lidera),
- amplitud: RSP (todas las empresas al mismo peso) contra SPY,
- crédito: HYG (bonos high yield) contra IEF (Tesoro 7–10 años).

Es un termómetro, no un pronóstico. Medido con backtest_rotacion.py (SIP,
2016–nov-2026, 564 semanas): ninguna lectura anticipa caídas de forma
confiable (el crédito sube la chance de movimientos fuertes, en cualquier
sentido), y el sector que más subió en 4 semanas después le pierde al SPY en
promedio (−0,5% a 4 semanas, −1,0% a 13; le gana el 40% de las veces).

Los ETF que no están en el universo (RSP, HYG, IEF, XLB, XLU, XLRE, XLC) se
bajan aparte y no entran al ranking.
"""
from __future__ import annotations

from typing import Any

LOOKBACK = 20         # ruedas (~4 semanas)
LONG_LOOKBACK = 63    # ruedas (~3 meses), de contexto
SPARK_WEEKS = 13
TREND_MIN_WEEKS = 3   # semanas seguidas mejorando (o empeorando) para marcar «gana/pierde terreno»

SECTOR_ETFS: list[tuple[str, str]] = [
    ("XLK", "Tecnología"),
    ("XLV", "Salud"),
    ("XLF", "Finanzas"),
    ("XLE", "Energía"),
    ("XLY", "Consumo discrecional"),
    ("XLP", "Consumo básico"),
    ("XLI", "Industria"),
    ("XLB", "Materiales"),
    ("XLU", "Servicios públicos"),
    ("XLRE", "Inmuebles"),
    ("XLC", "Comunicaciones"),
]
# Los que el build baja aparte (no están en universe.json).
EXTRA_SYMBOLS = ["RSP", "HYG", "IEF", "XLB", "XLU", "XLRE", "XLC"]

SECTOR_EDGE = 2.0   # puntos de ventaja de la defensiva sobre tecnología
BREADTH_EDGE = 1.0  # puntos que RSP pierde contra SPY
CREDIT_EDGE = 1.0   # puntos que HYG pierde contra IEF

CAPTION = (
    "Cada barra es cuánto le ganó (o perdió) ese sector al S&P 500 en las últimas 4 semanas, "
    "medido con los ETF de cada sector. Sirve para ver hacia dónde se mueve la plata mientras pasa. "
    "No la anticipa: medido de 2016 a 2026, el sector que más subió en 4 semanas después le perdió "
    "al S&P 500 en promedio y le ganó solo 4 de cada 10 veces. "
    "La línea de cada sector es esa misma ventaja, semana a semana, en los últimos 3 meses: si sube, "
    "el sector gana terreno de a poco. «Gana terreno» marca 3 semanas seguidas o más mejorando. Muestra "
    "el movimiento antes de que el número sea grande, pero no asegura que siga: la vieja vista de rotación "
    "(RRG), que medía algo parecido, no anticipó retornos. Datos de Alpaca al último cierre. "
    "Esto no es una recomendación de inversión."
)
READINGS_CAPTION = (
    "Salud y consumo básico contra tecnología: cuando las defensivas le ganan, la plata se está cubriendo. "
    "Amplitud: el S&P 500 con todas las empresas al mismo peso (RSP) contra el normal (SPY); si pierde, "
    "la suba la empujan pocas acciones. Crédito: bonos de empresas riesgosas (HYG) contra bonos del Tesoro "
    "(IEF); si pierden, el crédito se tensa. Medido de 2016 a 2026: con el crédito tenso fue más común "
    "una caída del 5% en los 3 meses siguientes (39% de las veces contra 26%), pero el S&P 500 subió más "
    "en promedio: anticipa movimientos fuertes, no la dirección."
)


def _closes(bars: list[dict] | None) -> list[tuple[str, float]]:
    out = []
    for b in bars or []:
        d = str(b.get("t") or "")[:10]
        c = b.get("c")
        if len(d) == 10 and c is not None:
            out.append((d, float(c)))
    return out


def _ret_pct(series: dict[str, float], a: str, b: str) -> float | None:
    if a in series and b in series and series[a]:
        return (series[b] / series[a] - 1.0) * 100.0
    return None


def _r(x: float | None, n: int = 2) -> float | None:
    return None if x is None else round(x, n)


def _join_es(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def trend(spark: list[float]) -> dict[str, Any]:
    """Racha al final de la curva: semanas seguidas en que la ventaja de 4 semanas contra el SPY
    mejoró (`up`) o empeoró (`down`). Marca la tendencia desde TREND_MIN_WEEKS semanas.

    `change` es cuántos puntos se movió la ventaja en esa racha.
    """
    if len(spark) < 2:
        return {"dir": None, "weeks": 0, "change": None}
    last_dir = None
    weeks = 0
    for i in range(len(spark) - 1, 0, -1):
        step = spark[i] - spark[i - 1]
        d = "up" if step > 0 else "down" if step < 0 else None
        if d is None or (last_dir is not None and d != last_dir):
            break
        last_dir = d
        weeks += 1
    if weeks < TREND_MIN_WEEKS:
        return {"dir": None, "weeks": weeks, "change": None}
    return {"dir": last_dir, "weeks": weeks, "change": round(spark[-1] - spark[-1 - weeks], 2)}


def trend_line(sectors: list[dict]) -> str:
    """Una frase con los que ganan y pierden terreno de a poco, aunque el número de hoy sea chico."""
    gain = [s["name"].lower() for s in sectors if (s.get("trend") or {}).get("dir") == "up"]
    lose = [s["name"].lower() for s in sectors if (s.get("trend") or {}).get("dir") == "down"]
    parts = []
    if gain:
        parts.append(f"Ganan terreno hace {TREND_MIN_WEEKS} semanas o más: {_join_es(gain)}.")
    if lose:
        parts.append(f"Pierden terreno: {_join_es(lose)}.")
    return " ".join(parts) if parts else "Ningún sector viene ganando o perdiendo terreno de forma sostenida."


def headline(sectors: list[dict], spy_ret: float | None) -> str:
    """Una frase: de dónde sale y a dónde va la plata en estas 4 semanas."""
    ok = [s for s in sectors if s.get("rel_4w") is not None]
    if len(ok) < 3:
        return ""
    winners = [s["name"].lower() for s in ok if s["rel_4w"] >= 2.0][:2]
    losers = [s["name"].lower() for s in reversed(ok) if s["rel_4w"] <= -2.0][:2]
    market = ""
    if spy_ret is not None:
        market = " con el S&P 500 en alza" if spy_ret > 0.5 else " con el S&P 500 en baja" if spy_ret < -0.5 else ""
    if winners and losers:
        return f"En las últimas 4 semanas la plata fue de {_join_es(losers)} a {_join_es(winners)}{market}."
    if winners:
        return f"En las últimas 4 semanas lideraron {_join_es(winners)}{market}."
    if losers:
        return f"En las últimas 4 semanas quedaron atrás {_join_es(losers)}{market}."
    return f"En las últimas 4 semanas los sectores se movieron parejo{market}: no hay una rotación clara."


def compute_rotation(bars_by_symbol: dict[str, list[dict]]) -> dict[str, Any]:
    """Bloque para datos.json. Vacío ({}) si no hay SPY o historia suficiente."""
    spy_pairs = _closes(bars_by_symbol.get("SPY"))
    if len(spy_pairs) <= LOOKBACK:
        return {}
    days = [d for d, _ in spy_pairs]
    series = {sym: dict(_closes(bars)) for sym, bars in bars_by_symbol.items()}
    spy = series["SPY"]
    end = days[-1]
    start = days[-1 - LOOKBACK]
    start_long = days[-1 - LONG_LOOKBACK] if len(days) > LONG_LOOKBACK else None
    spy_4w = _ret_pct(spy, start, end)
    spy_13w = _ret_pct(spy, start_long, end) if start_long else None

    # Cierre de cada semana para la mini curva (exceso acumulado de 4 semanas, semana a semana).
    week_ends: list[int] = []
    from datetime import date as _date
    last_key = None
    for i in range(len(days) - 1, -1, -1):
        key = _date.fromisoformat(days[i]).isocalendar()[:2]
        if key != last_key:
            week_ends.append(i)
            last_key = key
        if len(week_ends) >= SPARK_WEEKS:
            break
    week_ends.reverse()

    sectors = []
    for sym, name in SECTOR_ETFS:
        s = series.get(sym) or {}
        r4 = _ret_pct(s, start, end)
        if r4 is None or spy_4w is None:
            continue
        r13 = _ret_pct(s, start_long, end) if start_long else None
        spark = []
        for i in week_ends:
            if i - LOOKBACK < 0:
                continue
            a, b = days[i - LOOKBACK], days[i]
            x, y = _ret_pct(s, a, b), _ret_pct(spy, a, b)
            if x is not None and y is not None:
                spark.append(round(x - y, 2))
        sectors.append({
            "symbol": sym,
            "name": name,
            "ret_4w": _r(r4),
            "rel_4w": _r(r4 - spy_4w),
            "ret_13w": _r(r13),
            "rel_13w": _r(r13 - spy_13w) if r13 is not None and spy_13w is not None else None,
            "spark": spark,
            "trend": trend(spark),
        })
    sectors.sort(key=lambda x: (-(x["rel_4w"] if x["rel_4w"] is not None else -1e9), x["symbol"]))

    def diff(a_sym: str, b_sym: str) -> float | None:
        x = _ret_pct(series.get(a_sym) or {}, start, end)
        y = _ret_pct(series.get(b_sym) or {}, start, end)
        return None if x is None or y is None else x - y

    spy_up = spy_4w is not None and spy_4w > 0
    readings = []

    def reading(key: str, label: str, value: float | None, on: bool, text: str, highlight: bool | None = None) -> None:
        """`on`: la regla medida en el backtest. `highlight`: la página la resalta (aviso o rotación en curso)."""
        readings.append({"key": key, "label": label, "value": _r(value), "on": bool(on), "text": text,
                         "highlight": bool(on if highlight is None else highlight)})

    v = diff("XLV", "XLK")
    if v is not None:
        reading("salud", "Salud contra tecnología", v, spy_up and v > SECTOR_EDGE,
                ("Salud le gana a tecnología" if v > 0 else "Tecnología le gana a salud")
                + (" con el S&P 500 subiendo: alguien se está cubriendo." if spy_up and v > SECTOR_EDGE
                   else " con el S&P 500 bajando: la rotación ya está en curso." if not spy_up and v > SECTOR_EDGE
                   else "."), highlight=v > SECTOR_EDGE)
    v = diff("XLP", "XLK")
    if v is not None:
        reading("consumo", "Consumo básico contra tecnología", v, spy_up and v > SECTOR_EDGE,
                ("Consumo básico le gana a tecnología" if v > 0 else "Tecnología le gana a consumo básico")
                + (" con el S&P 500 subiendo: alguien se está cubriendo." if spy_up and v > SECTOR_EDGE
                   else " con el S&P 500 bajando: la rotación ya está en curso." if not spy_up and v > SECTOR_EDGE
                   else "."), highlight=v > SECTOR_EDGE)
    v = diff("RSP", "SPY")
    if v is not None:
        reading("amplitud", "Amplitud: todas al mismo peso contra el S&P 500", v, spy_up and v < -BREADTH_EDGE,
                "La suba la empujan pocas empresas grandes." if spy_up and v < -BREADTH_EDGE
                else "La plata se reparte entre más empresas." if v > BREADTH_EDGE
                else "Sin diferencias grandes entre las empresas grandes y el resto.")
    v = diff("HYG", "IEF")
    if v is not None:
        reading("credito", "Crédito: bonos riesgosos contra Tesoro", v, v < -CREDIT_EDGE,
                "El crédito se tensa: suelen venir movimientos fuertes." if v < -CREDIT_EDGE
                else "El crédito está tranquilo.")

    return {
        "asof": end,
        "window_start": start,
        "lookback_sessions": LOOKBACK,
        "spy_ret_4w": _r(spy_4w),
        "spy_ret_13w": _r(spy_13w),
        "headline": headline(sectors, spy_4w),
        "trend_line": trend_line(sectors),
        "trend_min_weeks": TREND_MIN_WEEKS,
        "sectors": sectors,
        "readings": readings,
        "caption": CAPTION,
        "readings_caption": READINGS_CAPTION,
    }
