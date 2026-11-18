#!/usr/bin/env python3
"""Hacia dónde va la plata: sectores contra el SPY y las cuatro lecturas.

No usa API keys. Barras sintéticas.
"""
from __future__ import annotations

import unittest

import rotacion as rot
from test_walkforward import geometric, make_bars, weekdays

N = 120
DATES = weekdays(N)


def bars(daily: float, start: float = 100.0) -> list[dict]:
    return make_bars(geometric(N, start, daily), DATES)


def universe(spy=1.001, overrides: dict[str, float] | None = None) -> dict[str, list[dict]]:
    out = {"SPY": bars(spy), "RSP": bars(spy), "HYG": bars(1.0002), "IEF": bars(1.0002)}
    for sym, _ in rot.SECTOR_ETFS:
        out[sym] = bars(spy)
    for sym, daily in (overrides or {}).items():
        out[sym] = bars(daily)
    return out


def ret4w(daily: float) -> float:
    return (daily ** rot.LOOKBACK - 1) * 100


class SectorTests(unittest.TestCase):
    def test_sectors_sorted_by_excess_over_spy(self):
        blk = rot.compute_rotation(universe(overrides={"XLP": 1.004, "XLK": 0.997}))
        names = [s["symbol"] for s in blk["sectors"]]
        self.assertEqual(names[0], "XLP")
        self.assertEqual(names[-1], "XLK")
        self.assertEqual(len(names), 11)
        xlp = blk["sectors"][0]
        self.assertAlmostEqual(xlp["rel_4w"], ret4w(1.004) - ret4w(1.001), places=1)
        self.assertEqual(blk["window_start"], DATES[-1 - rot.LOOKBACK].isoformat())

    def test_headline_names_where_the_money_went(self):
        blk = rot.compute_rotation(universe(spy=0.999, overrides={"XLP": 1.004, "XLV": 1.003, "XLK": 0.995}))
        self.assertEqual(
            blk["headline"],
            "En las últimas 4 semanas la plata fue de tecnología a consumo básico y salud con el S&P 500 en baja.",
        )

    def test_flat_market_says_no_clear_rotation(self):
        blk = rot.compute_rotation(universe())
        self.assertIn("no hay una rotación clara", blk["headline"])

    def test_missing_sector_is_left_out(self):
        u = universe()
        del u["XLRE"]
        blk = rot.compute_rotation(u)
        self.assertEqual(len(blk["sectors"]), 10)

    def test_no_spy_no_block(self):
        u = universe()
        del u["SPY"]
        self.assertEqual(rot.compute_rotation(u), {})

    def test_spark_has_one_point_per_week(self):
        blk = rot.compute_rotation(universe())
        self.assertEqual(len(blk["sectors"][0]["spark"]), rot.SPARK_WEEKS)


class ReadingTests(unittest.TestCase):
    def readings(self, **kw):
        return {r["key"]: r for r in rot.compute_rotation(universe(**kw))["readings"]}

    def test_health_beating_tech_while_spy_rises_is_the_warning(self):
        r = self.readings(overrides={"XLV": 1.004})
        self.assertTrue(r["salud"]["on"])
        self.assertTrue(r["salud"]["highlight"])
        self.assertIn("cubriendo", r["salud"]["text"])

    def test_health_beating_tech_while_spy_falls_is_rotation_in_progress(self):
        r = self.readings(spy=0.998, overrides={"XLV": 1.002})
        self.assertFalse(r["salud"]["on"])
        self.assertTrue(r["salud"]["highlight"])
        self.assertIn("en curso", r["salud"]["text"])

    def test_breadth_narrow_rally(self):
        r = self.readings(overrides={"RSP": 1.0})
        self.assertTrue(r["amplitud"]["on"])
        self.assertIn("pocas empresas", r["amplitud"]["text"])

    def test_credit_stress(self):
        r = self.readings(overrides={"HYG": 0.999})
        self.assertTrue(r["credito"]["on"])
        self.assertIn("se tensa", r["credito"]["text"])
        calm = self.readings()
        self.assertFalse(calm["credito"]["on"])

    def test_values_are_point_differences(self):
        r = self.readings(overrides={"XLP": 1.003})
        self.assertAlmostEqual(r["consumo"]["value"], ret4w(1.003) - ret4w(1.001), places=1)


if __name__ == "__main__":
    unittest.main()
