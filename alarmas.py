#!/usr/bin/env python3
"""Alarmas: cuando los fondos empiezan a desarmar posiciones.

Tres alarmas con ETF de factores, que es lo que miran los sistemas de riesgo:

- momentum: MTUM (las que más subieron) pierde más de 2 puntos contra USMV
  (baja volatilidad) en 5 ruedas. Los sistemas de riesgo empiezan a reducir
  momentum. El Índice Angus es una cartera de momentum: le toca de lleno.
- crecimiento: IWF (crecimiento) pierde más de 3 puntos contra IWD (valor) en
  10 ruedas. La plata sale de lo caro hacia lo barato.
- credito: HYG (bonos high yield) pierde más de 1 punto contra IEF (Tesoro
  7–10 años) en 20 ruedas. El crédito se tensa.

Avisan turbulencia, no la dirección. Medido con datos SIP de Alpaca, 2016 a
nov-2026 (backtest_rotacion.py y la medición de factores de nov-2026):
- momentum (105 episodios): en las 20 ruedas siguientes el momentum no siguió
  cayendo en promedio, pero su volatilidad fue 25 % contra 17 % y la chance de
  otra caída de 3 puntos contra USMV, 20 % contra 12 %. El 8/10/2026 se prendió
  dos días después del pico, con el S&P 500 todavía arriba.
- crecimiento (62 episodios): volatilidad 23 % contra 17 %; otra caída de 3
  puntos, 23 % contra 15 %.
- crédito: caída del S&P 500 de 5 % o más en 13 semanas, 39 % contra 26 %,
  pero con más suba en promedio.
"""
from __future__ import annotations

from typing import Any

EXTRA_SYMBOLS = ["MTUM", "USMV", "IWF", "IWD", "HYG", "IEF"]
SERIES_SESSIONS = 60  # ruedas de la mini curva

ALARMS: list[dict[str, Any]] = [
    {
        "key": "momentum",
        "title": "El momentum se desarma",
        "pair": ("MTUM", "USMV"),
        "pair_label": "Momentum (MTUM) contra baja volatilidad (USMV)",
        "lookback": 5,
        "threshold": -2.0,
        "on_text": "Las acciones que más venían subiendo pierden contra las tranquilas: los sistemas de "
                   "riesgo de los fondos están reduciendo momentum.",
        "off_text": "Las acciones que más venían subiendo no están perdiendo contra las tranquilas.",
        "history": "Desde 2016 se prendió 105 veces. Después, el momentum no siguió cayendo en promedio, "
                   "pero se movió mucho más: volatilidad de 25 % contra 17 %, y 20 % de chance de otra caída "
                   "fuerte contra 12 %. El 8/10/2026 se prendió dos días después del pico, con el S&P 500 "
                   "todavía arriba.",
        "index_note": "El Índice Angus es una cartera de momentum: con esta alarma prendida suelen venir "
                      "semanas movidas para el índice, en los dos sentidos.",
    },
    {
        "key": "crecimiento",
        "title": "De crecimiento a valor",
        "pair": ("IWF", "IWD"),
        "pair_label": "Crecimiento (IWF) contra valor (IWD)",
        "lookback": 10,
        "threshold": -3.0,
        "on_text": "La plata sale de las empresas caras que crecen rápido hacia las baratas.",
        "off_text": "No hay una salida fuerte de crecimiento hacia valor.",
        "history": "Desde 2016 se prendió 62 veces. Después, crecimiento no siguió perdiendo en promedio, "
                   "pero hubo más movimiento: volatilidad de 23 % contra 17 %, y 23 % de chance de otra caída "
                   "fuerte contra 15 %.",
        "index_note": "",
    },
    {
        "key": "credito",
        "title": "Crédito tenso",
        "pair": ("HYG", "IEF"),
        "pair_label": "Bonos de empresas riesgosas (HYG) contra Tesoro (IEF)",
        "lookback": 20,
        "threshold": -1.0,
        "on_text": "Los bonos de empresas riesgosas pierden contra los del Tesoro: los acreedores se cubren.",
        "off_text": "Los bonos de empresas riesgosas no pierden contra los del Tesoro: el crédito está tranquilo.",
        "history": "Desde 2016, con esta alarma prendida fue más común una caída del S&P 500 de 5 % o más en "
                   "los 3 meses siguientes (39 % de las veces contra 26 %), pero el S&P 500 subió más en "
                   "promedio: anticipa movimientos fuertes, no la dirección.",
        "index_note": "",
    },
]

CAPTION = (
    "Los fondos grandes miden su cartera por factores (momentum, crecimiento, valor, baja volatilidad) y "
    "tienen reglas que los obligan a reducir cuando algo pierde varios días seguidos. Estas alarmas miran "
    "los mismos ETF que ellos. Avisan que se vienen semanas movidas, no si el mercado va a subir o bajar. "
    "Datos de Alpaca al último cierre. Esto no es una recomendación de inversión."
)


def _closes(bars: list[dict] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for b in bars or []:
        d = str(b.get("t") or "")[:10]
        c = b.get("c")
        if len(d) == 10 and c is not None:
            out[d] = float(c)
    return out


def _rel(x: dict[str, float], y: dict[str, float], a: str, b: str) -> float | None:
    if a in x and b in x and a in y and b in y and x[a] and y[a]:
        return (x[b] / x[a] - y[b] / y[a]) * 100.0
    return None


def evaluate(spec: dict[str, Any], x: dict[str, float], y: dict[str, float]) -> dict[str, Any] | None:
    """Estado de una alarma: valor de hoy, prendida o no, desde cuándo y su curva."""
    days = sorted(set(x) & set(y))
    look = spec["lookback"]
    if len(days) <= look:
        return None
    values: list[tuple[str, float]] = []
    for i in range(look, len(days)):
        v = _rel(x, y, days[i - look], days[i])
        if v is not None:
            values.append((days[i], v))
    if not values:
        return None
    thr = spec["threshold"]
    today_d, today_v = values[-1]
    on = today_v < thr
    # Desde cuándo está en este estado (racha actual) y la última vez que estuvo prendida.
    since = today_d
    for d, v in reversed(values):
        if (v < thr) != on:
            break
        since = d
    last_on = None
    if not on:
        for d, v in reversed(values):
            if v < thr:
                last_on = d
                break
    series = [{"date": d, "value": round(v, 2)} for d, v in values[-SERIES_SESSIONS:]]
    return {
        "key": spec["key"],
        "title": spec["title"],
        "pair_label": spec["pair_label"],
        "symbols": list(spec["pair"]),
        "lookback": look,
        "threshold": thr,
        "value": round(today_v, 2),
        "on": on,
        "since": since,
        "last_on": last_on,
        "text": spec["on_text"] if on else spec["off_text"],
        "history": spec["history"],
        "index_note": spec["index_note"] if on else "",
        "series": series,
        "asof": today_d,
    }


def compute_alarms(bars_by_symbol: dict[str, list[dict]]) -> dict[str, Any]:
    """Bloque para datos.json. Sin datos para una alarma, esa alarma no aparece."""
    closes = {s: _closes(b) for s, b in bars_by_symbol.items()}
    alarms = []
    for spec in ALARMS:
        a, b = spec["pair"]
        if closes.get(a) and closes.get(b):
            res = evaluate(spec, closes[a], closes[b])
            if res:
                alarms.append(res)
    if not alarms:
        return {}
    on = [a["title"] for a in alarms if a["on"]]
    return {
        "asof": max(a["asof"] for a in alarms),
        "alarms": alarms,
        "on_count": len(on),
        "summary": (
            "Prendidas: " + ", ".join(t.lower() for t in on) + "." if on
            else "Ninguna alarma prendida."
        ),
        "caption": CAPTION,
    }
