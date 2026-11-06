#!/usr/bin/env python3
"""Backtest por pilares del Desk Score, en dos universos.

Usa la cache de backtest_largo.py (.cache_backtest_bars.json); no llama a Alpaca.

    python3 backtest_pilares.py

Señales que mide (siempre solo acciones, sin ETFs):
  desk            Desk Score publicado
  tendencia       pilar Tendencia
  fuerza_rs       pilar Fuerza RS (percentil RS + bonus aceleración 1m)
  rs_score        percentil de rendimiento relativo 6m vs SPY, sin bonus
  rs_accel        aceleración 1m (el bonus por sí solo)
  contraccion     pilar Contracción
  desk_sin_contr  Tendencia y Fuerza RS con los mismos pesos relativos, sin Contracción
  mom121          retorno t-252 → t-21
  mom121_ema200   mom121, solo nombres sobre la EMA200

Universos:
  amplio      las 380 acciones de universe.json (+ proxies)
  original61  las 61 acciones que había antes del 02/10/2026 (menos sesgo de
              supervivencia); el percentil de RS se recalcula dentro de esas 61

Escribe backtest_pilares.json y una tabla en pantalla.
"""
from __future__ import annotations

import copy
import json
import statistics as st
import time
from pathlib import Path

import backtest_largo as BL
import build as B

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "backtest_pilares.json"
COST_BPS = 10
SIGNALS = ["desk", "tendencia", "fuerza_rs", "rs_score", "rs_accel", "contraccion",
           "desk_sin_contr", "mom121", "mom121_ema200"]


def original_61() -> set[str]:
    h = json.loads((ROOT / "historial_semaforo.json").read_text())
    first = (h.get("reconstructed") or h["snapshots"])[0]
    return {r["symbol"] for r in first["rows"]}


def signals_from_rows(ranked: list[dict], mom: dict[str, float]) -> dict[str, dict[str, float]]:
    out = {k: {} for k in SIGNALS}
    for r in ranked:
        s, p = r["symbol"], r["pillars"]
        out["desk"][s] = r["desk_score"]
        out["tendencia"][s] = p["tendencia"]
        out["fuerza_rs"][s] = p["fuerza_rs"]
        out["rs_score"][s] = r["rs_score"]
        if r.get("rs_accel") is not None:
            out["rs_accel"][s] = r["rs_accel"]
        out["contraccion"][s] = p["contraccion"]
        out["desk_sin_contr"][s] = (0.30 * p["tendencia"] + 0.35 * p["fuerza_rs"]) / 0.65
        if s in mom:
            out["mom121"][s] = mom[s]
            if r.get("above_ema200"):
                out["mom121_ema200"][s] = mom[s]
    return out


def main():
    universe = BL.load_universe()
    meta_by = {u["symbol"]: u for u in universe}
    meta_by.setdefault("SPY", {"symbol": "SPY", "kind": "etf"})
    stocks_all = {u["symbol"] for u in universe if u.get("kind") in ("us", "cedear_proxy")}
    orig = original_61() & stocks_all
    universes = {"amplio": stocks_all, "original61": orig}
    print(f"Universos: amplio {len(stocks_all)} · original61 {len(orig)}")

    cache = json.loads(BL.CACHE.read_text())
    bars_by = {s: sorted(b, key=lambda x: x["t"]) for s, b in cache["bars"].items() if b}
    for b in bars_by.values():
        for x in b:
            x["t"] = x["t"][:10]
    idx_by = {s: {x["t"]: i for i, x in enumerate(b)} for s, b in bars_by.items()}
    closes = {s: {x["t"]: float(x["c"]) for x in b} for s, b in bars_by.items()}
    spy_bars = bars_by["SPY"]
    spy_dates = [x["t"] for x in spy_bars]
    spy_closes = closes["SPY"]
    weekly = BL.last_weekly(spy_dates[BL.MOM_LONG:])
    monthly = BL.last_monthly(weekly)
    monthly_dates = [d for d in weekly if d in monthly]

    sig = {u: {k: {} for k in SIGNALS} for u in universes}  # u -> señal -> fecha -> {sym: valor}
    t0 = time.time()
    for n, d in enumerate(weekly, 1):
        i = idx_by["SPY"][d]
        spy_win = [float(x["c"]) for x in spy_bars[max(0, i + 1 - BL.WINDOW): i + 1]]
        raw, mom = [], {}
        for sym in stocks_all:
            j = idx_by.get(sym, {}).get(d)
            if j is None:
                continue
            bars = bars_by[sym]
            row = B.compute_symbol(meta_by[sym], bars[max(0, j + 1 - BL.WINDOW): j + 1], spy_win, {})
            if row:
                raw.append(row)
            if j >= BL.MOM_LONG:
                c0, c1 = float(bars[j - BL.MOM_LONG]["c"]), float(bars[j - BL.MOM_SKIP]["c"])
                if c0 > 0:
                    mom[sym] = c1 / c0 - 1
        for uname, members in universes.items():
            rows = [copy.deepcopy(r) for r in raw if r["symbol"] in members]
            ranked = B.apply_cross_section_scores(rows)
            per = signals_from_rows(ranked, {s: v for s, v in mom.items() if s in members})
            for k in SIGNALS:
                sig[uname][k][d] = per[k]
        if n % 20 == 0 or n == len(weekly):
            el = time.time() - t0
            print(f"  {n}/{len(weekly)} ({el:.0f}s)", flush=True)

    result = {"desde_datos": spy_dates[0], "hasta": spy_dates[-1], "costo_bps_por_lado": COST_BPS,
              "universos": {u: len(m) for u, m in universes.items()}, "por_universo": {}}
    for uname in universes:
        strat, quint = [], []
        for k in SIGNALS:
            book = sig[uname][k]

            def pick(d, book=book):
                m = book.get(d) or {}
                return sorted(m, key=lambda s: (-m[s], s))[:BL.TOP_N]

            for label, dates in (("semanal", weekly), ("mensual", monthly_dates)):
                s = BL.run_strategy(f"{k}_{label}", dates, spy_dates, pick, closes, COST_BPS, spy_closes)
                s.pop("curva", None)
                strat.append(s)
            for h in (1, 4):
                quint.append(BL.quintile_test(weekly, book, closes, spy_closes, h, k))
        ew = BL.run_strategy("universo_ew", weekly, spy_dates,
                             lambda d, u=uname: list(sig[u]["desk"].get(d, {})), closes, 0, spy_closes)
        spy = BL.run_strategy("spy", weekly, spy_dates, lambda d: ["SPY"], closes, 0, spy_closes)
        for s in (ew, spy):
            s.pop("curva", None)
            strat.append(s)
        result["por_universo"][uname] = {"estrategias": strat, "quintiles": quint}

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    for uname, block in result["por_universo"].items():
        print(f"\n=== {uname} ({result['universos'][uname]} acciones) ===")
        print(f"{'estrategia':<26}{'CAGR':>7}{'vol':>7}{'Sharpe':>8}{'caídaMax':>10}{'>SPY':>6}")
        for s in block["estrategias"]:
            print(f"{s['nombre']:<26}{s['cagr_pct']:>6}%{s['vol_anual_pct']:>6}%{str(s['sharpe_sin_rf']):>8}"
                  f"{s['caida_max_pct']:>9}%{s['pct_periodos_gana_spy']:>5}%")
        print(f"\n{'señal':<16}{'h':>3}  {'Q1':>7}{'Q2':>7}{'Q3':>7}{'Q4':>7}{'Q5':>7}{'Q5-Q1':>8}{'IC':>8}{'IC>0':>6}")
        for q in block["quintiles"]:
            v = q["exceso_medio_vs_spy_pct_por_quintil"]
            spread = (v["Q5"] - v["Q1"]) if v["Q5"] is not None and v["Q1"] is not None else None
            print(f"{q['senal']:<16}{q['horizonte_semanas']:>3}  " + "".join(
                f"{(x if x is not None else float('nan')):>+7.2f}" for x in v.values())
                + f"{spread:>+8.2f}{str(q['ic_medio']):>8}{str(q['ic_positivo_pct']):>6}")
    print(f"\nListo → {OUT.name}")


if __name__ == "__main__":
    main()
