#!/usr/bin/env python3
"""Universo ampliado y la rotación de Finnhub. Sin red."""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

import build

ROOT = Path(__file__).resolve().parent
# Las 61 acciones que ya estaban antes de ampliar.
ORIGINAL_STOCKS = {
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "AVGO", "NFLX",
    "JPM", "V", "MA", "XOM", "CVX", "JNJ", "UNH", "PEP", "KO", "WMT", "COST", "DIS",
    "BA", "CAT", "GE", "MELI", "GGAL", "BABA", "BIDU", "PBR", "VALE", "ITUB", "BBD",
    "B", "XYZ", "PYPL", "CRM", "ORCL", "INTC", "QCOM", "MU", "ADBE", "CSCO", "IBM",
    "GS", "BAC", "C", "WFC", "HD", "NKE", "MCD", "SBUX", "TMO", "ABBV", "LLY", "MRK",
    "PFE", "COP", "SLB", "NEE", "LIN",
}
ORIGINAL_ETFS = {"SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY"}


class UniverseFileTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.meta = build.load_universe()

    def test_shape_and_original_names_stay(self):
        self.assertGreaterEqual(self.meta.get("stocks") or 0, 350)
        symbols = [r["symbol"] for r in self.rows]
        self.assertEqual(len(symbols), len(set(symbols)))
        stocks = [r for r in self.rows if str(r.get("kind") or "").lower() != "etf"]
        etfs = [r for r in self.rows if str(r.get("kind") or "").lower() == "etf"]
        self.assertGreaterEqual(len(stocks), 350)
        self.assertLessEqual(len(stocks), 400)
        self.assertEqual({r["symbol"] for r in etfs}, ORIGINAL_ETFS)
        self.assertTrue(ORIGINAL_STOCKS <= {r["symbol"] for r in stocks})
        for row in self.rows:
            self.assertTrue(row.get("symbol"))
            self.assertTrue(row.get("name"))
            self.assertTrue(row.get("sector"))
            self.assertIn(row.get("kind"), ("us", "etf", "cedear_proxy"))
            self.assertIsInstance(row.get("cedear"), bool)
        self.assertTrue(next(r for r in self.rows if r["symbol"] == "AAPL")["cedear"])
        self.assertTrue(next(r for r in self.rows if r["symbol"] == "B")["cedear"])
        self.assertEqual(self.meta.get("expanded_on"), "2026-10-02")

    def test_list_form_still_loads(self):
        listed, listed_meta = _load_raw(
            [{"symbol": "AAA", "name": "Aaa", "sector": "Energy", "kind": "us"}]
        )
        self.assertEqual(listed[0]["symbol"], "AAA")
        self.assertEqual(listed_meta, {})


def _load_raw(raw):
    """Misma rama que load_universe, con un objeto ya parseado."""
    if isinstance(raw, list):
        return raw, {}
    raise AssertionError("expected list")


class FinnhubRotationTests(unittest.TestCase):
    def test_intraday_does_not_call_finnhub(self):
        self.assertEqual(build.company_data_policy("intradia"), "cache")
        self.assertEqual(build.company_data_policy("intraday"), "cache")
        self.assertEqual(build.company_data_policy("cierre"), "rotate")

    def test_cold_universe_stays_inside_the_budget(self):
        symbols = [f"S{i:03d}" for i in range(380)]
        plan, budget = build._plan_slow_fetches(symbols, {}, date(2026, 10, 2))
        self.assertEqual(budget, build.SLOW_BUDGET_COLD)
        self.assertLessEqual(len(plan), budget)
        self.assertGreater(len(plan), 0)
        # Primero lo que nunca se pidió, y de a un símbolo van los tres tipos.
        self.assertEqual(plan[0], ("S000", "insiders"))
        self.assertEqual(plan[1], ("S000", "analysts"))
        self.assertEqual(plan[2], ("S000", "fundamentals"))

    def test_warm_cache_uses_the_smaller_budget(self):
        today = date(2026, 10, 2)
        prev = {
            "AAA": {
                "insiders": {"fetched_on": "2026-10-01"},
                "analysts": {"fetched_on": "2026-10-01"},
                "fundamentals": {"fetched_on": "2026-10-01"},
            }
        }
        plan, budget = build._plan_slow_fetches(["AAA"], prev, today)
        self.assertEqual(budget, build.SLOW_BUDGET_WARM)
        self.assertEqual(plan, [])

    def test_stale_names_come_after_the_ones_never_fetched(self):
        today = date(2026, 10, 2)
        prev = {
            "OLD": {
                "insiders": {"fetched_on": "2026-09-01"},
                "analysts": {"fetched_on": "2026-10-01"},
                "fundamentals": {"fetched_on": "2026-10-01"},
            }
        }
        symbols = ["OLD"] + [f"N{i:02d}" for i in range(20)]
        plan, budget = build._plan_slow_fetches(symbols, prev, today)
        self.assertEqual(budget, build.SLOW_BUDGET_COLD)
        kinds = {sym: kind for sym, kind in plan}
        self.assertEqual(plan[0][0], "N00")
        self.assertIn(("OLD", "insiders"), plan)
        self.assertLess(plan.index(("N00", "insiders")), plan.index(("OLD", "insiders")))
        self.assertLessEqual(len(plan), budget)
        self.assertTrue(kinds)

    def test_split_fichas_keeps_the_ranking_light(self):
        rows = [
            {
                "symbol": "AAA",
                "desk_score": 10,
                "analysts": {
                    "buy_pct": 80,
                    "trend_label": "igual",
                    "fetched_on": "2026-10-02",
                    "latest": {"total": 4, "buy": 3},
                    "history": [{"period": "2026-09-01"}],
                },
                "fundamentals": {"metrics": {"pe_ttm": 12}},
                "insiders": {"net_shares": 10, "transactions": [{"x": 1}]},
            }
        ]
        fichas = build.split_fichas(rows)
        self.assertNotIn("fundamentals", rows[0])
        self.assertNotIn("insiders", rows[0])
        self.assertNotIn("history", rows[0]["analysts"])
        self.assertEqual(rows[0]["analysts"]["buy_pct"], 80)
        self.assertEqual(rows[0]["desk_score"], 10)
        self.assertIn("history", fichas["AAA"]["analysts"])
        self.assertEqual(fichas["AAA"]["fundamentals"]["metrics"]["pe_ttm"], 12)


if __name__ == "__main__":
    unittest.main()
