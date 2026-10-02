#!/usr/bin/env python3
"""Definiciones de la matriz de confluencia. No tocan el Desk Score. Sin red."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import build
import signals as s


def weekdays(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bar(d: date, c: float, h: float | None = None, l: float | None = None, v: float = 1_000_000) -> dict:
    px = float(c)
    return {
        "t": d.isoformat() + "T05:00:00Z",
        "o": px,
        "h": px if h is None else float(h),
        "l": px if l is None else float(l),
        "c": px,
        "v": v,
    }


class SignalDefinitionTests(unittest.TestCase):
    def test_rsi_matches_the_build_helper(self):
        closes = [100 + (i % 7) - 3 + i * 0.05 for i in range(50)]
        self.assertEqual(s.rsi_wilder(closes, 14), build.rsi(closes, 14))

    def test_cross_lookback_is_the_last_bars_only(self):
        fast = [0.0] * 8
        slow = [1.0] * 8
        # Cruce en el índice 4 (hace 3 velas si el último es 7: índices 5, 6 y 7 son las últimas 3).
        fast[4] = 2.0
        fast[5] = 2.0
        fast[6] = 2.0
        fast[7] = 2.0
        self.assertFalse(s.crossed_above(fast, slow, s.MACD_CROSS_LOOKBACK))
        fast = [0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 2.0, 2.0]
        slow = [1.0] * 8
        self.assertTrue(s.crossed_above(fast, slow, s.MACD_CROSS_LOOKBACK))
        self.assertTrue(s.crossed_level([40, 40, 55], 50, s.RSI_MID_LOOKBACK))
        self.assertFalse(s.crossed_level([40, 55, 60, 61, 62], 50, s.RSI_MID_LOOKBACK))
        self.assertTrue(s.crossed_level([20, 25, 28, 29, 35], 30, s.RSI_OVERSOLD_LOOKBACK))

    def test_documented_thresholds(self):
        self.assertEqual(s.MACD_FAST, 12)
        self.assertEqual(s.MACD_SLOW, 26)
        self.assertEqual(s.MACD_SIGNAL, 9)
        self.assertEqual(s.MACD_CROSS_LOOKBACK, 3)
        self.assertEqual(s.RSI_PERIOD, 14)
        self.assertEqual(s.RSI_OVERSOLD, 30.0)
        self.assertEqual(s.RSI_MID, 50.0)
        self.assertEqual(s.REBOTE_NEAR_PCT, 1.5)
        self.assertEqual(s.CONTRACTION_MIN, 70.0)
        self.assertIn("SMA50", s.CONFLUENCE_DEFINITION)
        self.assertIn("no es una compra", s.CONFLUENCE_DEFINITION.lower())
        self.assertIn("EMA200 semanal", s.CONFLUENCE_LIMITATION)

    def test_bounce_needs_a_tag_from_above_and_is_not_a_fresh_cross(self):
        dates = weekdays(230)
        # Plano en 100 (la EMA200 se sienta ahí) y después un tramo arriba.
        bars = [bar(d, 100, h=101, l=99) for d in dates]
        for i in range(25):
            bars[-1 - i] = bar(dates[-1 - i], 110, h=111, l=109)
        closes = [b["c"] for b in bars]
        lows = [b["l"] for b in bars]
        ema200 = s.ema(closes, 200)
        self.assertGreater(closes[-1], ema200[-1])
        self.assertFalse(s.rebote_ema200(closes, lows, ema200))
        bars[-2]["l"] = ema200[-2] * 1.01
        lows[-2] = bars[-2]["l"]
        self.assertTrue(s.rebote_ema200(closes, lows, ema200))

        # El fixture de cruce fresco del escáner no es un rebote.
        below = [bar(d, 80, h=81, l=79) for d in dates]
        for i in range(20):
            below[-1 - i] = bar(dates[-1 - i], 40, h=41, l=39)
        below[-1] = bar(dates[-1], 120, h=121, l=119)
        parsed_c = [b["c"] for b in below]
        parsed_l = [b["l"] for b in below]
        self.assertFalse(s.rebote_ema200(parsed_c, parsed_l, s.ema(parsed_c, 200)))
        flags = s.evaluate_signals(below)["signals"]
        self.assertTrue(flags["cruce_ema200"])
        self.assertFalse(flags["rebote_ema200"])

    def test_pattern_signals_reuse_the_scanner(self):
        dates = weekdays(80)
        bars = [bar(d, 100, h=100, l=99, v=1_000_000) for d in dates]
        bars[-1] = bar(dates[-1], 101, h=102, l=100, v=500_000)
        flags = s.evaluate_signals(bars, contraction=10)["signals"]
        self.assertTrue(flags["pivote"])
        self.assertIn("breakout_52w", [p["id"] for p in s.detect_patterns(bars)])

        quiet = [bar(d, 100, h=100, l=99, v=1_000_000) for d in dates]
        quiet[-1] = bar(dates[-1], 98.5, h=99, l=98, v=500_000)
        self.assertFalse(s.evaluate_signals(quiet, contraction=10)["signals"]["pivote"])

        base_bars = [bar(d, 50 + i * 0.4, h=50 + i * 0.4, l=50 + i * 0.4) for i, d in enumerate(dates)]
        for i in range(20):
            base_bars[-1 - i] = bar(dates[-1 - i], 100.0, h=101.0, l=99.5, v=800_000)
        self.assertTrue(s.evaluate_signals(base_bars, contraction=10)["signals"]["vcp"])

    def test_contraction_pillar_turns_vcp_on_without_a_base(self):
        dates = weekdays(80)
        wide = [bar(d, 100, h=100, l=100) for d in dates]
        for i, swing in enumerate((70, 110, 75, 115, 60, 120)):
            wide[-1 - i] = bar(dates[-1 - i], swing, h=swing + 2, l=swing - 2)
        self.assertNotIn("base", [p["id"] for p in s.detect_patterns(wide)])
        off = s.evaluate_signals(wide, contraction=69.9)["signals"]
        on = s.evaluate_signals(wide, contraction=70)["signals"]
        self.assertFalse(off["vcp"])
        self.assertTrue(on["vcp"])

    def test_above_both_averages_and_not_when_below(self):
        dates = weekdays(230)
        px = 80.0
        bars = []
        for d in dates:
            px *= 1.0015
            bars.append(bar(d, px, h=px * 1.01, l=px * 0.99))
        self.assertTrue(s.evaluate_signals(bars)["signals"]["sobre_medias"])

        flat = [bar(d, 100, h=101, l=99) for d in dates]
        self.assertFalse(s.evaluate_signals(flat)["signals"]["sobre_medias"])

    def test_macd_cross_is_a_fresh_up_cross(self):
        dates = weekdays(90)
        px = 100.0
        closes = []
        for i, _d in enumerate(dates):
            if i < 60:
                px *= 1.002
            elif i < 88:
                px *= 0.97
            else:
                px *= 1.08
            closes.append(px)
        line, sig = s.macd_lines(closes)
        self.assertTrue(s.crossed_above(line, sig, s.MACD_CROSS_LOOKBACK))
        bars = [bar(d, c) for d, c in zip(dates, closes)]
        self.assertTrue(s.evaluate_signals(bars, contraction=0)["signals"]["macd"])

    def test_rsi_leaving_oversold_is_a_cross_not_a_level(self):
        dates = weekdays(44)
        closes = [100.0]
        for _ in range(40):
            closes.append(closes[-1] * 0.97)
        for _ in range(3):
            closes.append(closes[-1] * 1.15)
        rsi = s.rsi_wilder(closes)
        self.assertTrue(s.crossed_level(rsi, s.RSI_OVERSOLD, s.RSI_OVERSOLD_LOOKBACK))
        bars = [bar(d, c) for d, c in zip(dates, closes)]
        self.assertTrue(s.evaluate_signals(bars, contraction=0)["signals"]["rsi"])

    def test_flat_rsi_does_not_count_as_a_cross(self):
        dates = weekdays(40)
        bars = [bar(d, 50, h=50, l=50) for d in dates]
        flags = s.evaluate_signals(bars, contraction=0)["signals"]
        self.assertFalse(flags["rsi"])

    def test_weekly_pivot_needs_a_high_and_volume(self):
        weekly = [
            {"t": f"2024-01-{5 + i:02d}", "h": 10.0, "l": 9.0, "c": 10.0, "v": 100.0}
            for i in range(16)
        ]
        weekly.append({"t": "2024-06-07", "h": 12.5, "l": 11.0, "c": 12.0, "v": 500.0})
        self.assertTrue(s.weekly_pivot(weekly))
        quiet = [dict(b) for b in weekly]
        quiet[-1]["v"] = 50
        self.assertFalse(s.weekly_pivot(quiet))
        # Un lunes a viernes de la misma semana ISO se aplasta en una sola vela.
        monday = date(2024, 1, 1)
        days = weekdays(5, monday)
        self.assertEqual(len(s.to_weekly_bars([bar(d, 10, h=11, l=9, v=10) for d in days])), 1)

    def test_weekly_contraction_is_a_tight_upper_range(self):
        tight = [{"h": 102.0, "l": 98.0, "c": 101.5} for _ in range(6)]
        self.assertTrue(s.weekly_contraction(tight))
        wide = [{"h": 130.0, "l": 70.0, "c": 80.0} for _ in range(6)]
        self.assertFalse(s.weekly_contraction(wide))

    def test_matrix_sorts_by_confluence_and_does_not_touch_the_score(self):
        dates = weekdays(80)
        hot = [bar(d, 100, h=100, l=99, v=1_000_000) for d in dates]
        hot[-1] = bar(dates[-1], 101, h=102, l=100, v=500_000)
        cold = [bar(d, 50, h=70, l=40, v=100) for d in dates]
        rows = [
            {"symbol": "COLD", "name": "Frío", "desk_score": 90, "pillars": {"contraccion": 10}, "patterns": []},
            {"symbol": "HOT", "name": "Caliente", "desk_score": 40, "pillars": {"contraccion": 80}, "patterns": s.detect_patterns(hot)},
        ]
        before = [r["desk_score"] for r in rows]
        block = s.build_confluence(rows, {"HOT": hot, "COLD": cold})
        self.assertEqual([r["desk_score"] for r in rows], before)
        self.assertEqual(build.desk_score(80, 70, 60), build.desk_score(80, 70, 60))
        self.assertEqual(block["rows"][0]["symbol"], "HOT")
        self.assertGreater(block["rows"][0]["count"], block["rows"][1]["count"])
        ids = [item["id"] for item in block["lists"]]
        self.assertIn("pivote", ids)
        self.assertIn("vcp", ids)


if __name__ == "__main__":
    unittest.main()
