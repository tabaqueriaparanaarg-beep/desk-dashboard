#!/usr/bin/env python3
"""Ficha por ticker: puntos de pilar, rango 52s, gate EMA200 y RS semanal (sin API)."""
from __future__ import annotations

import json
import time
import unittest
from datetime import date, timedelta

import build as b


def weekdays(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def make_bars(closes: list[float], dates: list[date], volume: float = 1_000_000) -> list[dict]:
    bars = []
    for d, c in zip(dates, closes):
        px = float(c)
        bars.append(
            {
                "t": d.isoformat() + "T05:00:00Z",
                "o": px,
                "h": px * 1.01,
                "l": px * 0.99,
                "c": px,
                "v": volume,
            }
        )
    return bars


def geometric(n: int, start: float, daily: float) -> list[float]:
    px = float(start)
    out = []
    for _ in range(n):
        px *= daily
        out.append(px)
    return out


def score_full(meta_by: dict, bars_by: dict) -> list[dict]:
    spy = [float(x["c"]) for x in bars_by["SPY"]]
    rows = []
    for sym, bars in bars_by.items():
        row = b.compute_symbol(meta_by[sym], bars, spy, {})
        if row:
            rows.append(row)
    return b.apply_cross_section_scores(rows)


def market(n: int = 240, names: int = 14) -> tuple[list[date], dict, dict]:
    dates = weekdays(n)
    bars_by = {"SPY": make_bars(geometric(n, 100, 1.0004), dates)}
    meta = {"SPY": {"symbol": "SPY", "name": "SPY", "kind": "etf"}}
    for i in range(names):
        sym = f"S{i:02d}"
        meta[sym] = {"symbol": sym, "name": sym, "kind": "us", "sector": "Test"}
        bars_by[sym] = make_bars(geometric(n, 40 + i, 1.0002 + i * 0.00008), dates)
    return dates, meta, bars_by


class PillarPointTests(unittest.TestCase):
    def test_momentum_is_the_only_weighted_pillar(self):
        self.assertEqual(b.PILLAR_WEIGHTS, {"momentum": 1.0})
        self.assertEqual(b.PILLAR_MAX_POINTS, {"momentum": 100})
        self.assertEqual(b.SCORE_VERSION, 3)
        for key in b.INFO_PILLARS:
            self.assertNotIn(key, b.PILLAR_WEIGHTS)

    def test_score_is_momentum_percentile_halved_below_ema200(self):
        _dates, meta, bars_by = market()
        rows = score_full(meta, bars_by)
        self.assertGreaterEqual(len(rows), 10)
        for r in rows:
            mom = r["pillars"]["momentum"]
            self.assertIsNotNone(mom)
            self.assertEqual(r["pillar_points"]["momentum"]["points"], mom)
            self.assertEqual(r["pillar_points"]["momentum"]["max"], 100)
            factor = 1.0 if r["above_ema200"] else b.BELOW_EMA200_FACTOR
            self.assertAlmostEqual(r["desk_score"], mom * factor, delta=0.15)
            # Los pilares viejos siguen ahí, como información.
            for key in b.INFO_PILLARS:
                self.assertIsNotNone(r["pillars"][key])

    def test_below_ema200_halves_the_score(self):
        self.assertEqual(b.desk_score(80, True), 80)
        self.assertEqual(b.desk_score(80, False), 40)
        self.assertEqual(b.desk_score(None, True), 0)

    def test_flags_no_longer_subtract_points(self):
        n = 300
        dates = weekdays(n)
        spy = geometric(n, 100, 1.0002)
        # Rampa fuerte de 60 ruedas que termina un mes antes: momentum alto y
        # cierre muy por encima de la EMA200 (flag extendido).
        px = geometric(n - 60, 50, 1.0003)
        last = px[-1]
        for i in range(60):
            last *= 1.012 if i < 39 else 1.004
            px.append(last)
        cold = geometric(n, 50, 1.0001)
        bars_by = {"SPY": make_bars(spy, dates), "HOT": make_bars(px, dates), "COLD": make_bars(cold, dates)}
        meta = {
            "SPY": {"symbol": "SPY"},
            "HOT": {"symbol": "HOT", "name": "Hot", "kind": "us"},
            "COLD": {"symbol": "COLD", "name": "Cold", "kind": "us"},
        }
        rows = score_full(meta, bars_by)
        hot = next(r for r in rows if r["symbol"] == "HOT")
        self.assertIn("extendido_vs_ema200", hot["flags"])
        self.assertEqual(hot["mom_horizon"], "12-1")
        self.assertEqual(hot["desk_score"], hot["pillars"]["momentum"])
        self.assertEqual(rows[0]["symbol"], "HOT")


class MomentumTests(unittest.TestCase):
    def test_last_month_does_not_count(self):
        base = geometric(300, 50, 1.001)
        spiked = base[:-21] + [c * 1.5 for c in base[-21:]]
        a, ha = b.momentum_12_1(base)
        c, hc = b.momentum_12_1(spiked)
        self.assertEqual((ha, hc), ("12-1", "12-1"))
        self.assertAlmostEqual(a, c)
        self.assertAlmostEqual(a, base[-22] / base[-253] - 1)

    def test_short_history_falls_back_then_gives_up(self):
        mid = geometric(200, 50, 1.001)
        val, horizon = b.momentum_12_1(mid)
        self.assertEqual(horizon, "6-1")
        self.assertAlmostEqual(val, mid[-22] / mid[-127] - 1)
        self.assertEqual(b.momentum_12_1(geometric(120, 50, 1.001)), (None, None))

    def test_short_history_is_flagged_and_scores_zero(self):
        n = 300
        dates = weekdays(n)
        bars_by = {
            "SPY": make_bars(geometric(n, 100, 1.0003), dates),
            "OLD": make_bars(geometric(n, 50, 1.0005), dates),
            "MID": make_bars(geometric(200, 50, 1.0005), dates[-200:]),
            "NEW": make_bars(geometric(100, 50, 1.002), dates[-100:]),
        }
        meta = {s: {"symbol": s, "kind": "us"} for s in bars_by}
        rows = {r["symbol"]: r for r in score_full(meta, bars_by)}
        self.assertIn("momentum_6m", rows["MID"]["flags"])
        self.assertIn("sin_historia_momentum", rows["NEW"]["flags"])
        self.assertEqual(rows["NEW"]["desk_score"], 0)
        self.assertNotIn("momentum_6m", rows["OLD"]["flags"])


class SeriesFieldTests(unittest.TestCase):
    def test_daily_change_matches_last_two_closes(self):
        n = 220
        dates = weekdays(n)
        daily = 1.0025
        closes = geometric(n, 80, daily)
        bars = make_bars(closes, dates)
        spy = make_bars(geometric(n, 100, 1.0003), dates)
        row = b.compute_symbol({"symbol": "AAA", "name": "Aaa"}, bars, [c["c"] for c in spy], {})
        self.assertIsNotNone(row)
        expected = (closes[-1] / closes[-2] - 1.0) * 100.0
        self.assertAlmostEqual(row["change_pct"], round(expected, 2), places=2)

    def test_range_ignores_spike_older_than_252_sessions(self):
        highs = [10.0] * 300
        lows = [8.0] * 300
        highs[0] = 999.0  # fuera de la ventana (índices 48..299)
        highs[-1] = 20.0
        lows[-10] = 7.5
        got = b.range_52w(highs, lows, close=15.0)
        self.assertEqual(got["sessions"], 252)
        self.assertEqual(got["high"], 20.0)
        self.assertEqual(got["low"], 7.5)
        # (15 − 7.5) / (20 − 7.5) × 100 = 60
        self.assertEqual(got["position_pct"], 60.0)

    def test_flat_range_position_is_100(self):
        got = b.range_52w([5.0, 5.0], [5.0, 5.0], close=5.0)
        self.assertEqual(got["position_pct"], 100.0)
        self.assertEqual(got["sessions"], 2)

    def test_rising_trend_gate_and_falling_trend_gate(self):
        n = 230
        dates = weekdays(n)
        up = make_bars(geometric(n, 50, 1.0015), dates)
        down = make_bars(geometric(n, 200, 0.9985), dates)
        spy = [c["c"] for c in make_bars(geometric(n, 100, 1.0002), dates)]
        up_row = b.compute_symbol({"symbol": "UP"}, up, spy, {})
        down_row = b.compute_symbol({"symbol": "DN"}, down, spy, {})
        self.assertTrue(up_row["above_ema200"])
        self.assertTrue(up_row["ema200_slope_up"])
        self.assertGreater(up_row["ema200_slope_pct"], 0)
        self.assertEqual(up_row["trend_gate"], "Precio > EMA200 con pendiente +")
        self.assertFalse(down_row["above_ema200"])
        self.assertFalse(down_row["ema200_slope_up"])
        self.assertLess(down_row["ema200_slope_pct"], 0)
        self.assertEqual(down_row["trend_gate"], "Precio < EMA200 con pendiente -")
        up_row["range_52w"]["position_pct"]
        self.assertGreater(up_row["range_52w"]["position_pct"], 90)
        self.assertLess(down_row["range_52w"]["position_pct"], 15)

    def test_trend_gate_label_table(self):
        self.assertEqual(b.trend_gate_label("above", True), "Precio > EMA200 con pendiente +")
        self.assertEqual(b.trend_gate_label("above", False), "Precio > EMA200 con pendiente -")
        self.assertEqual(b.trend_gate_label("below", True), "Precio < EMA200 con pendiente +")
        self.assertEqual(b.trend_gate_label("equal", None), "Precio = EMA200")
        self.assertEqual(b.trend_gate_label(None, True), "Sin EMA200")

    def test_short_history_has_no_ema_gate(self):
        n = 80
        dates = weekdays(n)
        bars = make_bars(geometric(n, 40, 1.001), dates)
        spy = [c["c"] for c in make_bars(geometric(n, 100, 1.0002), dates)]
        row = b.compute_symbol({"symbol": "SH"}, bars, spy, {})
        self.assertIsNone(row["ema200"])
        self.assertIsNone(row["ema200_slope_up"])
        self.assertEqual(row["trend_gate"], "Sin EMA200")
        self.assertEqual(row["range_52w"]["sessions"], n)


class WeeklyRsTests(unittest.TestCase):
    def test_weekly_close_dates_keep_the_last_session_of_each_iso_week(self):
        dates = [
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
            "2026-06-04",
            "2026-06-05",
            "2026-06-08",
            "2026-06-09",
            "2026-06-10",
        ]
        self.assertEqual(b.weekly_close_dates(dates, weeks=16), ["2026-06-05", "2026-06-10"])
        self.assertEqual(b.weekly_close_dates(dates, weeks=1), ["2026-06-10"])
        self.assertEqual(b.weekly_close_dates(dates, weeks=0), [])

    def test_last_weekly_point_matches_published_rs_before_overwrite(self):
        dates, meta, bars_by = market(n=240, names=12)
        rows = score_full(meta, bars_by)
        block = b.compute_rs_weekly(bars_by, weeks=16)
        self.assertGreaterEqual(len(block["dates"]), 12)
        self.assertLessEqual(len(block["dates"]), 16)
        self.assertEqual(block["dates"], sorted(block["dates"]))
        self.assertEqual(block["dates"][-1], dates[-1].isoformat())
        by_row = {r["symbol"]: r for r in rows}
        for sym, seq in block["by_symbol"].items():
            self.assertEqual(len(seq), len(block["dates"]))
            self.assertIsNotNone(seq[-1], msg=sym)
            self.assertAlmostEqual(seq[-1], by_row[sym]["rs_score"], places=1)
        b.attach_rs_weekly(rows, block)
        for r in rows:
            self.assertEqual(len(r["rs_weekly"]), len(block["dates"]))
            self.assertEqual(r["rs_weekly"][-1], r["rs_score"])
        public = b.rs_weekly_public(block)
        self.assertNotIn("by_symbol", public)
        self.assertIn("percentil", public["definition"])
        blob = json.dumps({"dates": public["dates"], "rows": {r["symbol"]: r["rs_weekly"] for r in rows}})
        self.assertLess(len(blob), 20_000)

    def test_stale_symbol_last_point_is_the_published_score(self):
        _dates, meta, bars_by = market(n=240, names=8)
        bars_by["S00"] = bars_by["S00"][:-12]
        rows = score_full(meta, bars_by)
        block = b.compute_rs_weekly(bars_by, weeks=16)
        # Sin barra en el último cierre semanal, el recálculo deja el hueco.
        self.assertIsNone(block["by_symbol"]["S00"][-1])
        self.assertTrue(any(v is not None for v in block["by_symbol"]["S00"][:-1]))
        b.attach_rs_weekly(rows, block)
        s00 = next(r for r in rows if r["symbol"] == "S00")
        self.assertEqual(s00["rs_weekly"][-1], s00["rs_score"])

    def test_weekly_replay_stays_small_on_a_full_universe(self):
        n = 250
        dates = weekdays(n)
        bars_by = {"SPY": make_bars(geometric(n, 100, 1.0003), dates)}
        for i in range(72):
            sym = f"T{i:02d}"
            bars_by[sym] = make_bars(geometric(n, 20 + (i % 17), 1.0001 + (i % 11) * 0.00005), dates)
        t0 = time.perf_counter()
        block = b.compute_rs_weekly(bars_by, 16)
        elapsed = time.perf_counter() - t0
        self.assertEqual(len(block["dates"]), 16)
        self.assertEqual(len(block["by_symbol"]), 73)
        self.assertLess(elapsed, 3.0, msg=f"RS semanal tardó {elapsed:.2f}s")
        raw = json.dumps(block["by_symbol"])
        self.assertLess(len(raw), 40_000)


if __name__ == "__main__":
    unittest.main()
