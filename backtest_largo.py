#!/usr/bin/env python3
"""Backtest largo: Desk Score vs momentum 12-1 vs SPY.

Uso (desde la carpeta del repo, con las mismas keys que build.py):

    export ALPACA_API_KEY=...  ALPACA_SECRET_KEY=...
    python3 backtest_largo.py                 # desde 2019-01-01
    python3 backtest_largo.py --start 2017-01-01 --costo-bps 10

Baja barras diarias de Alpaca (una sola vez; quedan en .cache_backtest_bars.json,
NO commitear) y escribe backtest_resultado.json + un resumen en pantalla.

El Desk Score se calcula con las funciones de build.py (compute_symbol +
apply_cross_section_scores), truncando cada serie en la fecha de rebalanceo y
usando solo las últimas ~300 ruedas, igual que el ranking publicado.

Estrategias (todas Top 10 equiponderado, compra al cierre del rebalanceo):
  desk_semanal        Desk Score, todo el universo (lo que hoy muestra la página)
  desk_semanal_acc    Desk Score, solo acciones (sin ETFs ni proxies)
  desk_mensual        Desk Score, rebalanceo mensual
  mom121_mensual      Momentum 12-1 (ret. t-252 → t-21), solo acciones, mensual
  mom121_semanal      Momentum 12-1, solo acciones, semanal
  universo_ew         Todas las acciones equiponderadas, semanal
  spy                 SPY comprar y mantener

Sesgo a tener en cuenta: el universo es el de HOY (universe.json), así que hay
sesgo de supervivencia. Afecta a todas las estrategias; la comparación entre
ellas sigue siendo útil, los números absolutos salen inflados.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
import sys
import time
import urllib.error
import urllib.parse
from datetime import date
from pathlib import Path

import os
import ssl
import urllib.request

import build as B

ROOT = Path(__file__).resolve().parent

# El score tiene que salir de build.py; sin estas dos funciones no hay backtest.
_SCORE_FUNCS = ("compute_symbol", "apply_cross_section_scores")
_missing = [f for f in _SCORE_FUNCS if not hasattr(B, f)]
if _missing:
    sys.exit(
        "ERROR: el build.py de esta carpeta no tiene " + ", ".join(_missing) + ". "
        "Es una versión distinta a la de GitHub; actualizá build.py antes de correr el backtest."
    )


def _env_first(*names, default=""):
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return default


# Lo que no es el score: si build.py no lo trae, se usa una copia local.
ALPACA_DATA = getattr(B, "ALPACA_DATA", None) or _env_first(
    "ALPACA_DATA_URL", "ALPACA_DATA_BASE_URL", default="https://data.alpaca.markets").rstrip("/")
ALPACA_FEED = getattr(B, "ALPACA_FEED", None) or _env_first("ALPACA_FEED", default="iex")
BATCH_SIZE = getattr(B, "BATCH_SIZE", 15)
SLEEP_BETWEEN_BATCHES = getattr(B, "SLEEP_BETWEEN_BATCHES", 0.35)


def alpaca_headers():
    if hasattr(B, "alpaca_headers"):
        return B.alpaca_headers()
    key = _env_first("ALPACA_API_KEY", "APCA_API_KEY_ID")
    secret = _env_first("ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY")
    if not key or not secret:
        sys.exit("ERROR: faltan ALPACA_API_KEY / ALPACA_SECRET_KEY en el entorno.")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}


def http_get_json(url, headers):
    if hasattr(B, "http_get_json"):
        return B.http_get_json(url, headers=headers)
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(min(2 ** attempt * 1.5, 30))
                continue
            raise
        except Exception:
            if attempt == 4:
                raise
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError("Alpaca no respondió")


def load_universe():
    """Lee universe.json directo (lista vieja o {tickers: [...]})."""
    raw = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    tickers = raw if isinstance(raw, list) else raw.get("tickers")
    if not isinstance(tickers, list):
        sys.exit("ERROR: universe.json no tiene una lista de tickers.")
    return [t if isinstance(t, dict) else {"symbol": t} for t in tickers]
CACHE = ROOT / ".cache_backtest_bars.json"
OUT = ROOT / "backtest_resultado.json"
WINDOW = 300          # ruedas que ve el Desk Score en cada fecha (como el live)
MOM_LONG, MOM_SKIP = 252, 21
TOP_N = 10


# --------------------------------------------------------------------------- datos
def fetch_all(symbols: list[str], start: str, end: str) -> dict[str, list[dict]]:
    """Barras diarias ajustadas por splits y dividendos (adjustment=all)."""
    headers = alpaca_headers()
    out: dict[str, list[dict]] = {s: [] for s in symbols}
    batches = [symbols[i : i + BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]
    for n, batch in enumerate(batches, 1):
        params = urllib.parse.urlencode({
            "symbols": ",".join(batch), "timeframe": "1Day", "start": start, "end": end,
            "adjustment": "all", "feed": ALPACA_FEED, "limit": 10000, "sort": "asc",
        })
        url = f"{ALPACA_DATA}/v2/stocks/bars?{params}"
        token = None
        while True:
            u = url if not token else f"{url}&page_token={urllib.parse.quote(token)}"
            data = http_get_json(u, headers)
            for sym, bars in (data.get("bars") or {}).items():
                out.setdefault(sym, []).extend(
                    {k: b[k] for k in ("t", "o", "h", "l", "c", "v") if k in b} for b in bars
                )
            token = data.get("next_page_token")
            if not token:
                break
            time.sleep(0.15)
        print(f"  barras: lote {n}/{len(batches)}", end="\r", flush=True)
        time.sleep(SLEEP_BETWEEN_BATCHES)
    print()
    return out


def load_bars(symbols: list[str], start: str, end: str, refresh: bool) -> dict[str, list[dict]]:
    if CACHE.exists() and not refresh:
        cached = json.loads(CACHE.read_text())
        if cached.get("start") == start and set(symbols) <= set(cached["bars"]):
            print(f"Usando cache {CACHE.name} ({cached['end']})")
            return cached["bars"]
    print(f"Bajando {len(symbols)} símbolos de Alpaca ({ALPACA_FEED}) desde {start}…")
    bars = fetch_all(symbols, start, end)
    CACHE.write_text(json.dumps({"start": start, "end": end, "bars": bars}))
    return bars


# --------------------------------------------------------------------------- señales
def last_weekly(dates: list[str]) -> list[str]:
    wk: dict[tuple, str] = {}
    for d in dates:
        wk[date.fromisoformat(d).isocalendar()[:2]] = d
    return [wk[k] for k in sorted(wk)]


def last_monthly(dates: list[str]) -> set[str]:
    m: dict[str, str] = {}
    for d in dates:
        m[d[:7]] = d
    return set(m.values())


def signals_asof(meta_by, bars_by, idx_by, session: str, spy_window: list[float]):
    """Desk Score (ranking completo) y momentum 12-1 en `session`."""
    rows, mom = [], {}
    for sym, bars in bars_by.items():
        i = idx_by[sym].get(session)
        if i is None:  # sin barra ese día → afuera (como require_exact_session)
            continue
        win = bars[max(0, i + 1 - WINDOW) : i + 1]
        row = B.compute_symbol(meta_by.get(sym) or {"symbol": sym}, win, spy_window, {})
        if row:
            rows.append(row)
        if i >= MOM_LONG:
            c0, c1 = float(bars[i - MOM_LONG]["c"]), float(bars[i - MOM_SKIP]["c"])
            if c0 > 0:
                mom[sym] = c1 / c0 - 1
    ranked = B.apply_cross_section_scores(rows)
    return [(r["symbol"], r["desk_score"]) for r in ranked], mom


# --------------------------------------------------------------------------- métricas
def ret_between(closes, syms, d0, d1):
    rs = [closes[s][d1] / closes[s][d0] - 1 for s in syms
          if d0 in closes.get(s, {}) and d1 in closes.get(s, {}) and closes[s][d0] > 0]
    return st.mean(rs) if rs else 0.0


def max_dd(eq):
    peak, dd = eq[0], 0.0
    for x in eq:
        peak = max(peak, x)
        dd = min(dd, x / peak - 1)
    return dd


def run_strategy(name, rebal_dates, all_dates, pick, closes, cost_bps, spy_closes):
    """pick(date) -> lista de símbolos. Se mantiene hasta el próximo rebalanceo."""
    eq, curve, held, turnovers, periods = 1.0, [], [], [], []
    reb = [d for d in rebal_dates]
    for d0, d1 in zip(reb, reb[1:]):
        new = pick(d0)
        if not new:
            continue
        changed = len(set(held) - set(new)) if held else len(new)
        turn = changed / max(len(new), 1)
        turnovers.append(turn)
        cost = turn * 2 * cost_bps / 10000 if held else cost_bps / 10000
        r = ret_between(closes, new, d0, d1) - cost
        s = spy_closes[d1] / spy_closes[d0] - 1
        eq *= 1 + r
        curve.append((d1, eq))
        periods.append((d1, r, s))
        held = new
    return summarize(name, curve, periods, turnovers)


def summarize(name, curve, periods, turnovers):
    if not curve:
        return {"nombre": name, "error": "sin datos"}
    d0, d1 = periods[0][0], curve[-1][0]
    years = (date.fromisoformat(d1) - date.fromisoformat(d0)).days / 365.25 or 1
    rets = [p[1] for p in periods]
    per_year = len(rets) / years
    total = curve[-1][1] - 1
    vol = st.pstdev(rets) * math.sqrt(per_year) if len(rets) > 1 else 0
    cagr = (1 + total) ** (1 / years) - 1
    by_year: dict[str, float] = {}
    for d, r, _ in periods:
        by_year[d[:4]] = (1 + by_year.get(d[:4], 0)) * (1 + r) - 1
    return {
        "nombre": name,
        "desde": periods[0][0], "hasta": d1, "periodos": len(rets),
        "total_pct": round(100 * total, 1),
        "cagr_pct": round(100 * cagr, 1),
        "vol_anual_pct": round(100 * vol, 1),
        "sharpe_sin_rf": round(cagr / vol, 2) if vol else None,
        "caida_max_pct": round(100 * max_dd([1] + [e for _, e in curve]), 1),
        "pct_periodos_gana_spy": round(100 * sum(r > s for _, r, s in periods) / len(periods), 0),
        "rotacion_media": round(st.mean(turnovers), 2) if turnovers else None,
        "por_anio_pct": {y: round(100 * v, 1) for y, v in sorted(by_year.items())},
        "curva": [(d, round(e, 4)) for d, e in curve],
    }


def spearman(xs, ys):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for k, i in enumerate(o):
            r[i] = k
        return r
    if len(xs) < 5:
        return None
    rx, ry = rank(xs), rank(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def quintile_test(weekly, sig_by_date, closes, spy_closes, horizon_weeks, label):
    """Exceso medio vs SPY por quintil de señal, a `horizon_weeks` semanas. Q5 = señal más alta."""
    q = {k: [] for k in range(5)}
    ics = []
    for i, d0 in enumerate(weekly[:-horizon_weeks]):
        d1 = weekly[i + horizon_weeks]
        sig = sig_by_date.get(d0) or {}
        s_ret = spy_closes[d1] / spy_closes[d0] - 1
        pts = [(v, closes[s][d1] / closes[s][d0] - 1 - s_ret) for s, v in sig.items()
               if d0 in closes.get(s, {}) and d1 in closes.get(s, {})]
        if len(pts) < 20:
            continue
        pts.sort(key=lambda p: p[0])
        n = len(pts)
        buckets = {k: [] for k in range(5)}
        for j, (_, ex) in enumerate(pts):
            buckets[min(4, j * 5 // n)].append(ex)
        for k in range(5):
            q[k].append(st.mean(buckets[k]))
        ic = spearman([p[0] for p in pts], [p[1] for p in pts])
        if ic is not None:
            ics.append(ic)
    return {
        "senal": label, "horizonte_semanas": horizon_weeks, "fechas": len(ics),
        "exceso_medio_vs_spy_pct_por_quintil": {f"Q{k+1}": round(100 * st.mean(v), 2) if v else None
                                                for k, v in q.items()},
        "ic_medio": round(st.mean(ics), 3) if ics else None,
        "ic_positivo_pct": round(100 * sum(x > 0 for x in ics) / len(ics), 0) if ics else None,
    }


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--costo-bps", type=float, default=10, help="costo por lado, en puntos básicos")
    ap.add_argument("--refresh", action="store_true", help="ignorar la cache y volver a bajar")
    args = ap.parse_args()

    universe = load_universe()
    meta_by = {u["symbol"]: u for u in universe}
    if "SPY" not in meta_by:
        meta_by["SPY"] = {"symbol": "SPY", "kind": "etf"}
    stocks = {u["symbol"] for u in universe if u.get("kind", "us") == "us" and u["symbol"] != "SPY"}

    bars_by = load_bars(sorted(meta_by), args.start, args.end, args.refresh)
    bars_by = {s: sorted(b, key=lambda x: x["t"]) for s, b in bars_by.items() if b}
    for b in bars_by.values():
        for x in b:
            x["t"] = x["t"][:10]
    if "SPY" not in bars_by:
        sys.exit("No vinieron barras de SPY.")
    idx_by = {s: {x["t"]: i for i, x in enumerate(b)} for s, b in bars_by.items()}
    closes = {s: {x["t"]: float(x["c"]) for x in b} for s, b in bars_by.items()}
    spy_bars = bars_by["SPY"]
    spy_dates = [x["t"] for x in spy_bars]
    spy_closes = closes["SPY"]
    print(f"SPY: {spy_dates[0]} → {spy_dates[-1]} ({len(spy_dates)} ruedas). "
          f"Símbolos con datos: {len(bars_by)}/{len(meta_by)}")

    eligible = spy_dates[MOM_LONG:]  # momentum y EMA200 definidos
    weekly = last_weekly(eligible)
    monthly = last_monthly(weekly)
    print(f"Calculando señales en {len(weekly)} cierres semanales (tarda unos minutos)…")

    desk_rank, desk_sig, mom_sig = {}, {}, {}
    t0 = time.time()
    for n, d in enumerate(weekly, 1):
        i = idx_by["SPY"][d]
        spy_win = [float(x["c"]) for x in spy_bars[max(0, i + 1 - WINDOW) : i + 1]]
        ranked, mom = signals_asof(meta_by, bars_by, idx_by, d, spy_win)
        desk_rank[d] = ranked
        desk_sig[d] = {s: v for s, v in ranked if s in stocks}
        mom_sig[d] = {s: v for s, v in mom.items() if s in stocks}
        if n % 10 == 0 or n == len(weekly):
            el = time.time() - t0
            print(f"  {n}/{len(weekly)}  ({el:.0f}s, faltan ~{el / n * (len(weekly) - n):.0f}s)",
                  end="\r", flush=True)
    print()

    def top_desk(d, only_stocks=False):
        return [s for s, _ in desk_rank.get(d, []) if not only_stocks or s in stocks][:TOP_N]

    def top_mom(d):
        m = mom_sig.get(d) or {}
        return sorted(m, key=lambda s: -m[s])[:TOP_N]

    monthly_dates = [d for d in weekly if d in monthly]
    c = args.costo_bps
    strategies = [
        run_strategy("desk_semanal", weekly, spy_dates, top_desk, closes, c, spy_closes),
        run_strategy("desk_semanal_acc", weekly, spy_dates, lambda d: top_desk(d, True), closes, c, spy_closes),
        run_strategy("desk_mensual", monthly_dates, spy_dates, top_desk, closes, c, spy_closes),
        run_strategy("mom121_mensual", monthly_dates, spy_dates, top_mom, closes, c, spy_closes),
        run_strategy("mom121_semanal", weekly, spy_dates, top_mom, closes, c, spy_closes),
        run_strategy("universo_ew", weekly, spy_dates,
                     lambda d: [s for s in desk_sig.get(d, {})], closes, 0, spy_closes),
        run_strategy("spy", weekly, spy_dates, lambda d: ["SPY"], closes, 0, spy_closes),
    ]
    quintiles = [
        quintile_test(weekly, desk_sig, closes, spy_closes, 1, "desk_score"),
        quintile_test(weekly, desk_sig, closes, spy_closes, 4, "desk_score"),
        quintile_test(weekly, mom_sig, closes, spy_closes, 1, "mom121"),
        quintile_test(weekly, mom_sig, closes, spy_closes, 4, "mom121"),
    ]

    result = {
        "generado": date.today().isoformat(),
        "parametros": {"start": args.start, "end": args.end, "costo_bps_por_lado": c,
                       "feed": ALPACA_FEED, "top_n": TOP_N, "ventana_desk": WINDOW,
                       "universo": len(meta_by), "con_datos": len(bars_by)},
        "sesgo": "Universo actual (sesgo de supervivencia). Comparar estrategias entre sí.",
        "estrategias": strategies,
        "quintiles": quintiles,
        "ultimo_top10": {"fecha": weekly[-1], "desk": top_desk(weekly[-1]), "mom121": top_mom(weekly[-1])},
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))

    print(f"\n{'estrategia':<18}{'total':>9}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}{'caídaMax':>10}{'>SPY':>7}{'rot':>6}")
    for s in strategies:
        if "error" in s:
            print(f"{s['nombre']:<18} {s['error']}")
            continue
        print(f"{s['nombre']:<18}{s['total_pct']:>8}%{s['cagr_pct']:>7}%{s['vol_anual_pct']:>6}%"
              f"{str(s['sharpe_sin_rf']):>8}{s['caida_max_pct']:>9}%{s['pct_periodos_gana_spy']:>6}%"
              f"{str(s['rotacion_media']):>6}")
    print("\nExceso medio vs SPY por quintil (Q5 = señal más alta):")
    for q in quintiles:
        qs = "  ".join(f"{k}:{v:+.2f}%" for k, v in q["exceso_medio_vs_spy_pct_por_quintil"].items() if v is not None)
        print(f"  {q['senal']:<11}{q['horizonte_semanas']}sem  {qs}   IC {q['ic_medio']}")
    print(f"\nListo → {OUT.name}. Pasame ese archivo.")


if __name__ == "__main__":
    main()
