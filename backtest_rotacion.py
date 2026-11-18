#!/usr/bin/env python3
"""¿Las señales de rotación anticipan caídas del SPY? Medición 2016–hoy.

Uso (keys de Alpaca en el entorno; la primera vez baja barras a .cache_rotacion.json):

    python3 backtest_rotacion.py
    python3 backtest_rotacion.py --refresh

Señales, cada cierre semanal, mirando las últimas 4 semanas (20 ruedas):
  salud      XLV le gana a XLK por más de 2 puntos MIENTRAS el SPY sube
  consumo    XLP le gana a XLK por más de 2 puntos mientras el SPY sube
  amplitud   RSP (S&P 500 con todas al mismo peso) pierde contra SPY por más de
             1 punto mientras el SPY sube: la suba la empujan pocas acciones
  credito    HYG (bonos high yield) pierde contra IEF (Tesoro 7–10 años) por más
             de 1 punto: proxy del spread high yield que se ensancha
  alguna     cualquiera de las cuatro
  dos_o_mas  al menos dos a la vez

Para cada señal compara, contra todas las semanas:
  - retorno del SPY a 4, 8 y 13 semanas
  - probabilidad de una caída de 5 % o más (desde ese cierre) dentro de 13 semanas
y revisa si estaba prendida en las 6 semanas antes de cada pico previo a una caída
de 10 % o más. Las semanas se superponen: los conteos de "episodios" agrupan
semanas seguidas con la señal prendida.

Escribe backtest_rotacion.json (no se commitea) y una tabla en pantalla.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from datetime import date
from pathlib import Path

import backtest_largo as BL

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache_rotacion.json"
OUT = ROOT / "backtest_rotacion.json"
SECTORS = ["XLK", "XLV", "XLF", "XLE", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]
SYMBOLS = ["SPY", "RSP", "HYG", "IEF"] + SECTORS
LOOKBACK = 20          # ruedas (~4 semanas)
HORIZONS = (4, 8, 13)  # semanas
DD_HORIZON = 13        # semanas para medir la caída
DD_THRESHOLD = -5.0    # %
BIG_DROP = -10.0       # % desde el pico para contar una caída grande
SECTOR_EDGE = 2.0      # puntos de ventaja de la defensiva sobre XLK
BREADTH_EDGE = 1.0     # puntos que RSP pierde contra SPY
CREDIT_EDGE = 1.0      # puntos que HYG pierde contra IEF
SIGNALS = ["salud", "consumo", "amplitud", "credito", "alguna", "dos_o_mas"]


def load(start: str, end: str, refresh: bool) -> dict[str, dict[str, float]]:
    if CACHE.exists() and not refresh:
        cached = json.loads(CACHE.read_text())
        if cached.get("start") == start and set(SYMBOLS) <= set(cached["bars"]):
            print(f"Usando cache {CACHE.name} ({cached['end']})")
            bars = cached["bars"]
        else:
            bars = None
    else:
        bars = None
    if bars is None:
        print(f"Bajando {', '.join(SYMBOLS)} de Alpaca ({BL.ALPACA_FEED}) desde {start}…")
        bars = BL.fetch_all(SYMBOLS, start, end)
        CACHE.write_text(json.dumps({"start": start, "end": end, "bars": bars}))
    return {s: {x["t"][:10]: float(x["c"]) for x in bars.get(s) or []} for s in SYMBOLS}


def ret(series: dict[str, float], a: str, b: str) -> float | None:
    if a in series and b in series and series[a]:
        return (series[b] / series[a] - 1.0) * 100.0
    return None


def weekly_closes(dates: list[str]) -> list[str]:
    out: dict[tuple, str] = {}
    for d in dates:
        out[date.fromisoformat(d).isocalendar()[:2]] = d
    return [out[k] for k in sorted(out)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    px = load(args.start, args.end, args.refresh)
    spy = px["SPY"]
    days = sorted(spy)
    pos = {d: i for i, d in enumerate(days)}
    weeks = [w for w in weekly_closes(days) if pos[w] >= LOOKBACK]
    print(f"SPY {days[0]} → {days[-1]}; {len(weeks)} cierres semanales")

    rows = []
    for wi, d in enumerate(weeks):
        a = days[pos[d] - LOOKBACK]
        r = {s: ret(px[s], a, d) for s in SYMBOLS}
        if any(v is None for v in (r["SPY"], r["XLK"], r["XLV"], r["XLP"])):
            continue
        spy_up = r["SPY"] > 0
        sig = {
            "salud": spy_up and r["XLV"] - r["XLK"] > SECTOR_EDGE,
            "consumo": spy_up and r["XLP"] - r["XLK"] > SECTOR_EDGE,
            "amplitud": spy_up and r["RSP"] is not None and r["RSP"] - r["SPY"] < -BREADTH_EDGE,
            "credito": r["HYG"] is not None and r["IEF"] is not None and r["HYG"] - r["IEF"] < -CREDIT_EDGE,
        }
        n_on = sum(sig.values())
        sig["alguna"] = n_on >= 1
        sig["dos_o_mas"] = n_on >= 2
        fwd = {}
        for h in HORIZONS:
            j = wi + h
            fwd[h] = ret(spy, d, weeks[j]) if j < len(weeks) else None
        # Peor caída desde este cierre dentro de DD_HORIZON semanas.
        k = wi + DD_HORIZON
        dd = None
        if k < len(weeks):
            window = [spy[x] for x in days[pos[d]: pos[weeks[k]] + 1]]
            dd = (min(window) / spy[d] - 1.0) * 100.0
        rows.append({"date": d, "sig": sig, "fwd": fwd, "dd": dd})

    def stats(sel: list[dict]) -> dict:
        out = {"semanas": len(sel)}
        for h in HORIZONS:
            vals = [x["fwd"][h] for x in sel if x["fwd"][h] is not None]
            out[f"ret_{h}s"] = round(st.mean(vals), 2) if vals else None
            out[f"neg_{h}s_pct"] = round(100 * sum(v < 0 for v in vals) / len(vals), 0) if vals else None
        dds = [x["dd"] for x in sel if x["dd"] is not None]
        out["caida5_13s_pct"] = round(100 * sum(v <= DD_THRESHOLD for v in dds) / len(dds), 0) if dds else None
        return out

    def episodes(name: str) -> int:
        n, prev = 0, False
        for x in rows:
            on = x["sig"][name]
            if on and not prev:
                n += 1
            prev = on
        return n

    base = stats(rows)
    by_signal = {}
    for name in SIGNALS:
        on = [x for x in rows if x["sig"][name]]
        off = [x for x in rows if not x["sig"][name]]
        by_signal[name] = {"prendida": stats(on), "apagada": stats(off), "episodios": episodes(name),
                           "pct_del_tiempo": round(100 * len(on) / len(rows), 0)}

    # Picos antes de caídas de 10 % o más.
    peaks = []
    peak_d, peak_v, in_drop = days[0], spy[days[0]], False
    for d in days:
        v = spy[d]
        if not in_drop and v > peak_v:
            peak_d, peak_v = d, v
        dd = (v / peak_v - 1.0) * 100.0
        if not in_drop and dd <= BIG_DROP:
            in_drop = True
            trough = v
            peaks.append({"pico": peak_d, "spy_pico": round(peak_v, 2)})
        if in_drop:
            trough = min(trough, v)
            peaks[-1]["caida_max_pct"] = round((trough / peak_v - 1.0) * 100.0, 1)
            if v >= peak_v:
                in_drop, peak_d, peak_v = False, d, v
    for p in peaks:
        before = [x for x in rows if x["date"] <= p["pico"]][-6:]
        p["senales_6s_antes"] = {n: sum(x["sig"][n] for x in before) for n in SIGNALS[:4]}

    # ¿El sector que más subió en 4 semanas le sigue ganando al SPY después? (persistencia)
    persist = {h: {"lider": [], "ultimo": [], "top3": []} for h in (4, 13)}
    for wi, d in enumerate(weeks):
        a = days[pos[d] - LOOKBACK]
        past = {s: ret(px[s], a, d) for s in SECTORS}
        past = {s: v for s, v in past.items() if v is not None}
        if len(past) < 8:
            continue
        order = sorted(past, key=lambda s: -past[s])
        for h in (4, 13):
            j = wi + h
            if j >= len(weeks):
                continue
            spy_f = ret(spy, d, weeks[j])
            fut = {s: ret(px[s], d, weeks[j]) for s in past}
            if spy_f is None or any(v is None for v in fut.values()):
                continue
            persist[h]["lider"].append(fut[order[0]] - spy_f)
            persist[h]["ultimo"].append(fut[order[-1]] - spy_f)
            persist[h]["top3"].append(st.mean(fut[s] for s in order[:3]) - spy_f)
    sector_persistence = {
        f"{h}s": {k: {"exceso_vs_spy": round(st.mean(v), 2),
                      "le_gana_al_spy_pct": round(100 * sum(x > 0 for x in v) / len(v), 0), "n": len(v)}
                  for k, v in vals.items() if v}
        for h, vals in persist.items()
    }

    result = {"generado": date.today().isoformat(), "desde": rows[0]["date"], "hasta": rows[-1]["date"],
              "feed": BL.ALPACA_FEED, "parametros": {"lookback_ruedas": LOOKBACK, "ventaja_sector": SECTOR_EDGE,
              "ventaja_amplitud": BREADTH_EDGE, "ventaja_credito": CREDIT_EDGE, "caida": DD_THRESHOLD},
              "todas_las_semanas": base, "senales": by_signal, "caidas_grandes": peaks,
              "persistencia_sectores": sector_persistence}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))

    print(f"\nTodas las semanas: {base}")
    print(f"\n{'señal':<11}{'%tiempo':>8}{'epis.':>6}  {'SPY 4s':>7}{'8s':>7}{'13s':>7}  {'P(caída≥5%,13s)':>16}   (apagada: 13s / P caída)")
    for name, v in by_signal.items():
        on, off = v["prendida"], v["apagada"]
        print(f"{name:<11}{v['pct_del_tiempo']:>7}%{v['episodios']:>6}  {on['ret_4s']:>+6}%{on['ret_8s']:>+6}%{on['ret_13s']:>+6}%"
              f"{on['caida5_13s_pct']:>15}%     ({off['ret_13s']:+}% / {off['caida5_13s_pct']}%)")
    print(f"\nBase: SPY 13s {base['ret_13s']:+}%, P(caída≥5% en 13s) {base['caida5_13s_pct']}%")
    print("\nCaídas de 10 % o más: semanas con cada señal en las 6 antes del pico")
    for p in peaks:
        s = p["senales_6s_antes"]
        print(f"  pico {p['pico']}  caída {p.get('caida_max_pct')}%   salud {s['salud']}/6  consumo {s['consumo']}/6"
              f"  amplitud {s['amplitud']}/6  crédito {s['credito']}/6")
    print("\nSector según cómo le fue en las últimas 4 semanas, después (exceso vs SPY):")
    for h, block in sector_persistence.items():
        print(f"  {h}: " + "  ".join(
            f"{k} {v['exceso_vs_spy']:+}% (le gana {v['le_gana_al_spy_pct']}%)" for k, v in block.items()))
    print(f"\nListo → {OUT.name}")


if __name__ == "__main__":
    main()
