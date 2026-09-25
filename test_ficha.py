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
    def test_weights_sum_to_one_and_max_points_are_the_ficha_scale(self):
        self.assertAlmostEqual(sum(b.PILLAR_WEIGHTS.values()), 1.0)
        self.assertEqual(
            b.PILLAR_MAX_POINTS,
            {"tendencia": 25, "fuerza_rs": 30, "contraccion": 30, "setup": 15},
        )
        self.assertEqual(sum(b.PILLAR_MAX_POINTS.values()), 100)

    def test_points_come_from_pillar_scores_before_penalties(self):
        _dates, meta, bars_by = market()
        rows = score_full(meta, bars_by)
        self.assertGreaterEqual(len(rows), 10)
        for r in rows:
            pts = r["pillar_points"]
            pillars = r["pillars"]
            total = 0.0
            for key, mx in b.PILLAR_MAX_POINTS.items():
                self.assertEqual(pts[key]["max"], mx)
                self.assertIsNotNone(pts[key]["points"])
                self.assertGreaterEqual(pts[key]["points"], 0)
                self.assertLessEqual(pts[key]["points"], mx)
                # El 0–100 guardado ya está redondeado a 1 decimal; los puntos usan
                # el score sin redondear, así que la diferencia cabe en el redondeo.
                from_rounded = round(pillars[key] * (mx / 100.0), 1)
                self.assertAlmostEqual(pts[key]["points"], from_rounded, delta=0.15)
                total += pts[key]["points"]
            penalizing = {"extendido_vs_ema200", "posible_distribucion", "atr_elevado"}
            if not penalizing.intersection(r["flags"]):
                self.assertAlmostEqual(total, r["desk_score"], delta=0.4)

    def test_extendido_penalty_lowers_desk_score_not_pillar_points(self):
        n = 240
        dates = weekdays(n)
        spy = geometric(n, 100, 1.0002)
        # Rampa final fuerte: el cierre queda muy por encima de la EMA200.
        px = geometric(n - 25, 50, 1.0003)
        last = px[-1]
        for _ in range(25):
            last *= 1.012
            px.append(last)
        bars_by = {
            "SPY": make_bars(spy, dates),
            "HOT": make_bars(px, dates),
        }
        meta = {
            "SPY": {"symbol": "SPY"},
            "HOT": {"symbol": "HOT", "name": "Hot", "kind": "us"},
        }
        # Un universo de un solo nombre deja el percentil en 50; alcanza para el flag.
        rows = score_full(meta, bars_by)
        hot = next(r for r in rows if r["symbol"] == "HOT")
        self.assertIn("extendido_vs_ema200", hot["flags"])
        self.assertGreater(hot["dist_ema200_pct"], 25)
        pts = sum(hot["pillar_points"][k]["points"] for k in b.PILLAR_MAX_POINTS)
        self.assertLessEqual(hot["desk_score"], round(pts - 5, 1) + 0.4)
        self.assertGreater(pts - hot["desk_score"], 4.0)


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
