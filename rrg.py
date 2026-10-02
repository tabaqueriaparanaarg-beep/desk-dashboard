#!/usr/bin/env python3
"""Gráfico de rotación relativa (RRG) estilo JdK, contra SPY.

Usa sólo cierres semanales de las barras que Angus ya bajó (Alpaca).
No toca el Desk Score, el semáforo ni el historial.

Fórmula (Julius de Kempenaer, suavizado doble, centro en 100)
----------------------------------------------------------------
Semana = última sesión de cada semana ISO (la misma idea que el RS semanal).
Si un ticker no tiene cierre esa semana, ese punto queda vacío.

    RS_t = cierre_ticker_t / cierre_SPY_t

Con N = 10 semanas (largo clásico de JdK):

    SMA1_t = media simple de RS en N semanas
    SMA2_t = media simple de SMA1 en N semanas
    RS-Ratio_t = 100 × SMA1_t / SMA2_t

    RS-Momentum_t = 100 × RS-Ratio_t / media simple de RS-Ratio en N semanas

Hace falta historia previa: el primer RS-Ratio sale en la semana 2N−1
(índice 18 con N=10) y el primer RS-Momentum en la semana 3N−2 (índice 27).
Esas medias se calculan sobre TODA la historia disponible y recién después
se publican las últimas semanas, para que el recorte no coma el suavizado.

Cuadrantes (el eje es 100; >= 100 cae del lado de arriba / de adelante,
así el centro exacto queda en Liderando):

    Liderando      RS-Ratio >= 100 y RS-Momentum >= 100   (arriba a la derecha)
    Debilitándose  RS-Ratio >= 100 y RS-Momentum <  100   (abajo a la derecha)
    Rezagado       RS-Ratio <  100 y RS-Momentum <  100   (abajo a la izquierda)
    Mejorando      RS-Ratio <  100 y RS-Momentum >= 100   (arriba a la izquierda)

SPY no se grafica: es el benchmark, su RS sería 1.
"""
from __future__ import annotations

from datetime import date
from typing import Any

JDK_PERIOD = 10
TAIL_WEEKS = 12
PLOT_WEEKS = 18
CENTER = 100.0

QUADRANT_LABELS = {
    "liderando": "Liderando",
    "debilitandose": "Debilitándose",
    "rezagado": "Rezagado",
    "mejorando": "Mejorando",
}

# Nombres cortos para las notas. El universo no trae XLC; queda por si se agrega.
ETF_DISPLAY = {
    "XLK": "Tecnología",
    "XLF": "Finanzas",
    "XLE": "Energía",
    "XLV": "Salud",
    "XLI": "Industria",
    "XLP": "Consumo básico",
    "XLY": "Consumo discrecional",
    "XLC": "Comunicaciones",
    "XLB": "Materiales",
    "XLU": "Servicios",
    "XLRE": "Inmuebles",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "DIA": "Dow Jones",
    "SPY": "S&P 500",
}

SECTOR_ETFS = {
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY",
    "XLC", "XLB", "XLU", "XLRE",
}

DEFINITION = (
    "Rotación relativa estilo JdK contra SPY, con cierres semanales (última sesión "
    f"de cada semana ISO). RS = cierre / cierre de SPY. Con N={JDK_PERIOD}: "
    "RS-Ratio = 100 × SMA(RS, N) / SMA(SMA(RS, N), N). "
    "RS-Momentum = 100 × RS-Ratio / SMA(RS-Ratio, N). "
    "El centro es 100. Liderando: ratio y momentum ≥ 100. Debilitándose: ratio ≥ 100 "
    "y momentum < 100. Rezagado: los dos < 100. Mejorando: ratio < 100 y momentum ≥ 100. "
    f"La estela muestra hasta {TAIL_WEEKS} semanas. No es una recomendación."
)


def _bar_day(bar: dict) -> str | None:
    raw = str(bar.get("t") or "")[:10]
    if len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
        return None
    try:
        date.fromisoformat(raw)
    except ValueError:
        return None
    return raw


def _close(bar: dict) -> float | None:
    try:
        value = float(bar.get("c"))
    except (TypeError, ValueError):
        return None
    if value != value or value <= 0:  # NaN
        return None
    return value


def weekly_last_closes(bars: list[dict] | None) -> list[tuple[str, float]]:
    """(fecha, cierre) de la última sesión de cada semana ISO, en orden."""
    last: dict[tuple[int, int], tuple[str, float]] = {}
    order: list[tuple[int, int]] = []
    for bar in bars or []:
        day = _bar_day(bar)
        close = _close(bar)
        if day is None or close is None:
            continue
        y, m, d = int(day[0:4]), int(day[5:7]), int(day[8:10])
        iso = date(y, m, d).isocalendar()
        key = (int(iso[0]), int(iso[1]))
        if key not in last:
            order.append(key)
        last[key] = (day, close)
    return [last[k] for k in order]


def _sma_at(values: list[float | None], index: int, period: int) -> float | None:
    """Media de `period` valores consecutivos que terminan en `index`. Vacío si falta uno."""
    if period < 1 or index - period + 1 < 0:
        return None
    window = values[index - period + 1 : index + 1]
    if any(v is None for v in window):
        return None
    return sum(v for v in window if v is not None) / period


def rs_ratio_and_momentum(
    rs: list[float | None], period: int = JDK_PERIOD
) -> tuple[list[float | None], list[float | None]]:
    """RS-Ratio y RS-Momentum alineados a `rs`. None hasta completar el suavizado doble.

    Ver el docstring del módulo para la fórmula exacta.
    """
    n = len(rs)
    sma1 = [_sma_at(rs, i, period) for i in range(n)]
    sma2 = [_sma_at(sma1, i, period) for i in range(n)]
    ratio: list[float | None] = []
    for i in range(n):
        if sma1[i] is None or sma2[i] is None or sma2[i] == 0:
            ratio.append(None)
        else:
            ratio.append(CENTER * sma1[i] / sma2[i])
    sma_ratio = [_sma_at(ratio, i, period) for i in range(n)]
    momentum: list[float | None] = []
    for i in range(n):
        if ratio[i] is None or sma_ratio[i] is None or sma_ratio[i] == 0:
            momentum.append(None)
        else:
            momentum.append(CENTER * ratio[i] / sma_ratio[i])
    return ratio, momentum


def quadrant(ratio: float, momentum: float) -> str:
    """Cuadrante JdK. El centro (100, 100) cae en Liderando (>= en los dos ejes)."""
    ahead = ratio >= CENTER
    up = momentum >= CENTER
    if ahead and up:
        return "liderando"
    if ahead and not up:
        return "debilitandose"
    if not ahead and not up:
        return "rezagado"
    return "mejorando"


def _weeks_phrase(n: int) -> str:
    n = max(1, int(n))
    if n == 1:
        return "1 semana"
    return f"{n} semanas"


def quadrant_change_note(
    *,
    display: str,
    symbol: str,
    prev: dict,
    curr: dict,
    weeks_ahead: int,
) -> str | None:
    """Una oración en español llano si el cuadrante cambió. Nada si sigue igual.

    No es un consejo: describe si quedó adelante o detrás del SPY.
    """
    prev_q = str(prev.get("quadrant") or "")
    curr_q = str(curr.get("quadrant") or "")
    if not prev_q or not curr_q or prev_q == curr_q:
        return None
    label = f"{display} ({symbol})" if display and display != symbol else symbol
    prev_ratio = float(prev["ratio"])
    curr_ratio = float(curr["ratio"])
    if prev_ratio >= CENTER and curr_ratio < CENTER:
        return (
            f"{label} perdió el liderazgo: volvió a quedar detrás del SPY "
            f"tras {_weeks_phrase(weeks_ahead)} adelante."
        )
    if prev_q == "liderando" and curr_q == "debilitandose":
        return (
            f"{label} se está debilitando: sigue adelante del SPY, "
            "pero el momento ya no acompaña."
        )
    if prev_q == "debilitandose" and curr_q == "liderando":
        return (
            f"{label} recuperó el momento: sigue adelante del SPY "
            "y el ritmo volvió a subir."
        )
    if prev_q == "rezagado" and curr_q == "mejorando":
        return f"{label} está mejorando: sigue detrás del SPY, con el momento a favor."
    if prev_q == "mejorando" and curr_q == "liderando":
        return f"{label} pasó a liderar: quedó adelante del SPY con el momento a favor."
    if prev_q == "mejorando" and curr_q == "rezagado":
        return (
            f"{label} volvió a quedar rezagado: el momento se apagó y sigue detrás del SPY."
        )
    if prev_q == "debilitandose" and curr_q == "rezagado":
        return f"{label} quedó rezagado: pasó a quedar detrás del SPY."
    if prev_q == "rezagado" and curr_q == "debilitandose":
        return (
            f"{label} pasó de rezagado a debilitándose: quedó adelante del SPY, "
            "con el momento en contra."
        )
    prev_label = QUADRANT_LABELS.get(prev_q, prev_q)
    curr_label = QUADRANT_LABELS.get(curr_q, curr_q)
    return f"{label} cambió de {prev_label} a {curr_label} respecto del SPY."


def _round2(value: float) -> float:
    return round(float(value), 2)


def _group_of(symbol: str, meta: dict) -> str:
    kind = str(meta.get("kind") or "").strip().lower()
    sector = str(meta.get("sector") or "").strip()
    if symbol in SECTOR_ETFS or (kind == "etf" and sector and sector != "Benchmark"):
        return "sector"
    if kind == "etf":
        return "benchmark"
    return "stock"


def _display_of(symbol: str, meta: dict) -> str:
    if symbol in ETF_DISPLAY:
        return ETF_DISPLAY[symbol]
    name = str(meta.get("name") or "").strip()
    return name or symbol


def _weeks_ahead(points: list[dict | None], index: int) -> int:
    """Semanas consecutivas con RS-Ratio >= 100 que terminan en `index`."""
    n = 0
    i = index
    while i >= 0:
        point = points[i]
        if not point or float(point["ratio"]) < CENTER:
            break
        n += 1
        i -= 1
    return n


def build_rrg(
    bars_by_symbol: dict[str, list[dict]] | None,
    meta_by: dict[str, dict] | None = None,
    *,
    period: int = JDK_PERIOD,
    plot_weeks: int = PLOT_WEEKS,
    tail_weeks: int = TAIL_WEEKS,
) -> dict[str, Any]:
    """Arma el bloque `rrg` de datos.json. SPY es el eje y no entra en la serie."""
    meta_by = meta_by or {}
    bars_by_symbol = bars_by_symbol or {}
    spy_weeks = weekly_last_closes(bars_by_symbol.get("SPY"))
    empty = {
        "benchmark": "SPY",
        "center": CENTER,
        "period": period,
        "tail": tail_weeks,
        "definition": DEFINITION,
        "quadrants": dict(QUADRANT_LABELS),
        "dates": [],
        "series": [],
        "notes": ["Sin historia semanal suficiente para armar el gráfico."],
        "notes_by_date": [],
    }
    if len(spy_weeks) < period * 2:
        return empty

    spy_dates = [d for d, _c in spy_weeks]
    spy_close = {d: c for d, c in spy_weeks}
    # RS completo (con None en huecos) para no cortar el suavizado al publicar.
    ratio_by: dict[str, list[float | None]] = {}
    mom_by: dict[str, list[float | None]] = {}
    for symbol, bars in bars_by_symbol.items():
        if symbol == "SPY":
            continue
        closes = {d: c for d, c in weekly_last_closes(bars)}
        rs: list[float | None] = []
        for day in spy_dates:
            px = closes.get(day)
            bench = spy_close.get(day)
            if px is None or bench is None or bench == 0:
                rs.append(None)
            else:
                rs.append(px / bench)
        ratio, momentum = rs_ratio_and_momentum(rs, period)
        ratio_by[symbol] = ratio
        mom_by[symbol] = momentum

    # Recorte: últimas `plot_weeks` donde al menos un símbolo ya tiene momentum.
    last_ready = -1
    for i in range(len(spy_dates)):
        if any(mom_by[s][i] is not None for s in mom_by):
            last_ready = i
    if last_ready < 0:
        return empty
    start = max(0, last_ready - plot_weeks + 1)
    # Incluir sólo fechas hasta la última con algún punto (no colas vacías).
    dates = spy_dates[start : last_ready + 1]

    series: list[dict[str, Any]] = []
    notes: list[tuple[int, str]] = []
    for symbol in sorted(ratio_by):
        meta = meta_by.get(symbol) or {}
        points: list[dict | None] = []
        for offset, day in enumerate(dates):
            i = start + offset
            ratio = ratio_by[symbol][i]
            momentum = mom_by[symbol][i]
            if ratio is None or momentum is None:
                points.append(None)
                continue
            q = quadrant(ratio, momentum)
            points.append(
                {
                    "date": day,
                    "ratio": _round2(ratio),
                    "momentum": _round2(momentum),
                    "quadrant": q,
                }
            )
        if not any(points):
            continue
        group = _group_of(symbol, meta)
        display = _display_of(symbol, meta)
        item = {
            "symbol": symbol,
            "name": str(meta.get("name") or symbol),
            "display": display,
            "kind": str(meta.get("kind") or ""),
            "sector": str(meta.get("sector") or ""),
            "group": group,
            "points": points,
        }
        series.append(item)

    # Notas por semana, sólo ETFs de sector (la vista por defecto).
    # El último elemento es el que muestra el panel al abrir; al mover el
    # slider la UI usa la semana de ese cuadro.
    notes_by_date: list[list[str]] = [[] for _ in dates]
    for item in series:
        if item["group"] != "sector":
            continue
        pts = item["points"]
        for i in range(1, len(pts)):
            if not pts[i] or not pts[i - 1]:
                continue
            note = quadrant_change_note(
                display=str(item["display"]),
                symbol=str(item["symbol"]),
                prev=pts[i - 1],
                curr=pts[i],
                weeks_ahead=_weeks_ahead(pts, i - 1),
            )
            if note:
                notes_by_date[i].append(note)
    text = list(notes_by_date[-1]) if notes_by_date else []
    if not text:
        text = ["Esta semana ningún ETF de sector cambió de cuadrante respecto del SPY."]
    return {
        "benchmark": "SPY",
        "center": CENTER,
        "period": period,
        "tail": tail_weeks,
        "definition": DEFINITION,
        "quadrants": dict(QUADRANT_LABELS),
        "dates": dates,
        "series": series,
        "notes": text,
        "notes_by_date": notes_by_date,
    }
