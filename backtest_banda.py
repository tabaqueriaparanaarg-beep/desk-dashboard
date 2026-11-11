#!/usr/bin/env python3
"""Backtest de la banda de permanencia y el tope por sector del Top 10 mensual.

Uso (keys de Alpaca en el entorno; la primera vez baja barras a la cache):

    python3 backtest_banda.py                  # desde 2016 (SIP)
    python3 backtest_banda.py --refresh        # volver a bajar

Reglas que compara (rebalanceo el último día hábil de cada mes, partes iguales):
  banda N   un nombre entra si está en el Top 10 y sale solo si cae debajo del
            puesto N. Los huecos se llenan con los mejores que no están.
            N = 10 es el Top 10 de siempre.
  tope 3    como mucho 3 nombres del mismo sector (se saltean los siguientes).

Universos: «cedear» (acciones con CEDEAR), «todas» (todas las acciones) y
«original61» (las 61 de antes del 02/10/2026, percentiles dentro de esas 61).
Los tres tienen sesgo de supervivencia (universo de hoy): sirve para comparar
reglas entre sí, no para el número absoluto.

Escribe backtest_banda.json (no se commitea) y una tabla en pantalla.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import statistics as st
import time
from datetime import date
from pathlib import Path

import backtest_largo as BL
import backtest_pilares as BP
import build as B

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "backtest_banda.json"
TOP_N = 10
BANDS = (10, 15, 20, 25)
CAPS = (None, 3)
COSTS_BPS = (10, 50)


def month_ends(dates: list[str]) -> list[str]:
    """Último día con datos de cada mes (el día de la revisión)."""
    out = []
    for i, d in enumerate(dates):
        if i + 1 == len(dates) or dates[i + 1][:7] != d[:7]:
            out.append(d)
    return out[:-1] if dates and out and out[-1] == dates[-1] else out


def pick_with_rules(ordered: list[str], held: list[str], band: int, cap: int | None,
                    sector_of: dict[str, str]) -> list[str]:
    """Cartera nueva: se quedan los de `held` que siguen dentro de `band`; el resto, por orden."""
    rank = {s: i + 1 for i, s in enumerate(ordered)}
    keep = [s for s in held if rank.get(s, 10**9) <= band]
    keep.sort(key=lambda s: rank[s])
    out: list[str] = []
    per_sector: dict[str, int] = {}

    def fits(s: str) -> bool:
        if cap is None:
            return True
        sec = sector_of.get(s) or "?"
        return per_sector.get(sec, 0) < cap

    def add(s: str) -> None:
        out.append(s)
        sec = sector_of.get(s) or "?"
        per_sector[sec] = per_sector.get(sec, 0) + 1

    for s in keep:
        if len(out) < TOP_N and fits(s):
            add(s)
    for s in ordered:
        if len(out) >= TOP_N:
            break
        if s not in out and fits(s):
            add(s)
    return out


def run_book(dates, ordered_by_date, band, cap, sector_of, closes, spy_closes, cost_bps):
    eq, curve, periods, outs, held = 1.0, [], [], [], []
    tenure: dict[str, int] = {}
    finished: list[int] = []
    for d0, d1 in zip(dates, dates[1:]):
        ordered = ordered_by_date.get(d0) or []
        if not ordered:
            continue
        new = pick_with_rules(ordered, held, band, cap, sector_of)
        gone = [s for s in held if s not in new]
        for s in gone:
            finished.append(tenure.pop(s, 0))
        for s in new:
            tenure[s] = tenure.get(s, 0) + 1
        turn = (len(gone) / TOP_N) if held else 1.0
        if held:
            outs.append(len(gone))
        r = BL.ret_between(closes, new, d0, d1) - turn * (2 if held else 1) * cost_bps / 10000
        s = spy_closes[d1] / spy_closes[d0] - 1
        eq *= 1 + r
        curve.append((d1, eq))
        periods.append((d1, r, s))
        held = new
    res = BL.summarize("", curve, periods, [o / TOP_N for o in outs])
    res.pop("curva", None)
    res["salen_por_mes"] = round(st.mean(outs), 2) if outs else None
    res["meses_promedio_adentro"] = round(st.mean(finished), 1) if finished else None
    half = len(periods) // 2
    for label, chunk in (("primera_mitad", periods[:half]), ("segunda_mitad", periods[half:])):
        if chunk:
            g = math.prod(1 + p[1] for p in chunk)
            yrs = len(chunk) / 12
            res[label] = {"desde": chunk[0][0], "hasta": chunk[-1][0],
                          "cagr_pct": round(100 * (g ** (1 / yrs) - 1), 1)}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    universe = BL.load_universe()
    meta_by = {u["symbol"]: u for u in universe}
    meta_by.setdefault("SPY", {"symbol": "SPY", "kind": "etf"})
    stocks = {u["symbol"] for u in universe
              if str(u.get("kind") or "us").lower() != "etf" and u["symbol"] != "SPY"}
    cedear = {s for s in stocks if meta_by[s].get("cedear")}
    try:
        orig = BP.original_61() & stocks
    except Exception:
        orig = set()
    universes = {"cedear": stocks, "todas": stocks}
    if orig:
        universes["original61"] = orig
    sector_of = {s: (meta_by[s].get("sector") or "?") for s in stocks}

    bars_by = BL.load_bars(sorted(meta_by), args.start, args.end, args.refresh)
    bars_by = {s: sorted(b, key=lambda x: x["t"]) for s, b in bars_by.items() if b}
    for b in bars_by.values():
        for x in b:
            x["t"] = x["t"][:10]
    idx_by = {s: {x["t"]: i for i, x in enumerate(b)} for s, b in bars_by.items()}
    closes = {s: {x["t"]: float(x["c"]) for x in b} for s, b in bars_by.items()}
    spy_bars = bars_by["SPY"]
    spy_dates = [x["t"] for x in spy_bars]
    spy_closes = closes["SPY"]
    dates = month_ends(spy_dates[BL.MOM_LONG:])
    dates.append(spy_dates[-1])  # el último cierre solo valúa el mes en curso
    print(f"SPY {spy_dates[0]} → {spy_dates[-1]}; {len(dates) - 1} revisiones mensuales; "
          f"universos: cedear {len(cedear)}, todas {len(stocks)}, original61 {len(orig)}")

    ordered: dict[str, dict[str, list[str]]] = {u: {} for u in universes}
    t0 = time.time()
    for n, d in enumerate(dates[:-1], 1):
        i = idx_by["SPY"][d]
        spy_win = [float(x["c"]) for x in spy_bars[max(0, i + 1 - BL.WINDOW): i + 1]]
        raw = []
        for sym in stocks:
            j = idx_by.get(sym, {}).get(d)
            if j is None:
                continue
            row = B.compute_symbol(meta_by[sym], bars_by[sym][max(0, j + 1 - BL.WINDOW): j + 1], spy_win, {})
            if row:
                raw.append(row)
        # El percentil es sobre todo el universo, como en la página.
        ranked_all = B.apply_cross_section_scores([copy.deepcopy(r) for r in raw])
        all_order = [r["symbol"] for r in ranked_all]
        ordered["todas"][d] = all_order
        ordered["cedear"][d] = [s for s in all_order if s in cedear]
        if orig:
            r61 = B.apply_cross_section_scores([copy.deepcopy(r) for r in raw if r["symbol"] in orig])
            ordered["original61"][d] = [r["symbol"] for r in r61]
        if n % 12 == 0 or n == len(dates) - 1:
            print(f"  {n}/{len(dates) - 1} ({time.time() - t0:.0f}s)", flush=True)

    result = {"generado": date.today().isoformat(), "desde_datos": spy_dates[0], "hasta": spy_dates[-1],
              "feed": BL.ALPACA_FEED, "revisiones": len(dates) - 1,
              "sesgo": "Universo de hoy (supervivencia). Comparar reglas entre sí.", "resultados": {}}
    spy = BL.run_strategy("spy", dates, spy_dates, lambda d: ["SPY"], closes, 0, spy_closes)
    spy.pop("curva", None)
    result["spy"] = spy
    for u in universes:
        for cost in COSTS_BPS:
            for cap in CAPS:
                for band in BANDS:
                    key = f"{u}|{cost}bps|tope{cap or '-'}|banda{band}"
                    result["resultados"][key] = run_book(
                        dates, ordered[u], band, cap, sector_of, closes, spy_closes, cost)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))

    print(f"\nSPY: CAGR {spy['cagr_pct']}%  vol {spy['vol_anual_pct']}%  caída {spy['caida_max_pct']}%")
    hdr = f"{'regla':<22}{'CAGR':>7}{'vol':>7}{'Sharpe':>7}{'caída':>8}{'>SPY':>6}{'salen/mes':>10}{'meses':>7}{'1ª½':>7}{'2ª½':>7}"
    for u in universes:
        for cost in COSTS_BPS:
            print(f"\n=== {u} · costo {cost} bps por lado ===\n{hdr}")
            for cap in CAPS:
                for band in BANDS:
                    r = result["resultados"][f"{u}|{cost}bps|tope{cap or '-'}|banda{band}"]
                    name = f"banda {band}" + (f" · tope {cap}" if cap else "")
                    print(f"{name:<22}{r['cagr_pct']:>6}%{r['vol_anual_pct']:>6}%{str(r['sharpe_sin_rf']):>7}"
                          f"{r['caida_max_pct']:>7}%{r['pct_periodos_gana_spy']:>5}%{str(r['salen_por_mes']):>10}"
                          f"{str(r['meses_promedio_adentro']):>7}"
                          f"{r['primera_mitad']['cagr_pct']:>6}%{r['segunda_mitad']['cagr_pct']:>6}%")
    print(f"\nListo → {OUT.name}")


if __name__ == "__main__":
    main()
