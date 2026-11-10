#!/usr/bin/env python3
"""Plan del mes: fechas de revisión y cartera armada en el último fin de mes.

No usa API keys. Las barras son sintéticas.
"""
from __future__ import annotations

import unittest
from datetime import date

import build as b
from test_walkforward import universe


class ReviewDateTests(unittest.TestCase):
    def test_last_weekday_of_the_month(self):
        self.assertEqual(b.last_trading_day_of_month(2026, 11), date(2026, 11, 30))
        self.assertEqual(b.last_trading_day_of_month(2026, 1), date(2026, 1, 30))  # 31 es sábado
        self.assertEqual(b.last_trading_day_of_month(2026, 12), date(2026, 12, 31))

    def test_memorial_day_moves_the_review(self):
        # 2027: el lunes 31 de mayo es Memorial Day, la revisión pasa al viernes 28.
        self.assertEqual(b.last_trading_day_of_month(2027, 5), date(2027, 5, 28))

    def test_good_friday_moves_the_review(self):
        # 2029: Pascua 1/4, Viernes Santo 30/3 (y el 31 es sábado).
        self.assertEqual(b._easter(2029), date(2029, 4, 1))
        self.assertEqual(b.last_trading_day_of_month(2029, 3), date(2029, 3, 29))

    def test_month_end_sessions(self):
        s = ["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-30", "2026-11-02", "2026-11-06"]
        self.assertEqual(b.month_end_sessions(s), ["2026-09-30", "2026-10-30"])
        # La última sesión cuenta si es el último hábil del mes.
        self.assertEqual(b.month_end_sessions(["2026-11-27", "2026-11-30"]), ["2026-11-30"])


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.meta, self.bars, self.dates = universe(14, 320)

    def test_holdings_come_from_the_last_month_end(self):
        plan = b.compute_monthly_plan(self.meta, self.bars)
        sessions = [d.isoformat() for d in self.dates]
        ends = b.month_end_sessions(sessions)
        self.assertEqual(plan["since"], ends[-1])
        self.assertEqual(plan["prev_since"], ends[-2])
        self.assertEqual(set(plan["holdings"]), set(b.TOP10_VARIANTS))
        ranked = b.rank_universe_asof(self.meta, self.bars, ends[-1], require_exact_session=True)
        want = [r["symbol"] for r in b.top10_pick(ranked, "todas")]
        self.assertEqual(plan["holdings"]["todas"], want)
        self.assertNotIn("SPY", plan["holdings"]["todas"])

    def test_no_look_ahead(self):
        # Romper los precios después del fin de mes no cambia la cartera.
        plan = b.compute_monthly_plan(self.meta, self.bars)
        since = plan["since"]
        broken = {
            s: [dict(x, c=x["c"] * (50 if x["t"][:10] > since and s == "S00" else 1)) for x in bars]
            for s, bars in self.bars.items()
        }
        again = b.compute_monthly_plan(self.meta, broken)
        self.assertEqual(plan["holdings"], again["holdings"])

    def test_after_the_month_end_close_the_next_review_is_next_month(self):
        sessions = [d.isoformat() for d in self.dates]
        ends = b.month_end_sessions(sessions)
        cut = sessions.index(ends[-1]) + 1
        bars = {s: x[:cut] for s, x in self.bars.items()}
        plan = b.compute_monthly_plan(self.meta, bars)
        self.assertTrue(plan["review_done"])
        self.assertFalse(plan["review_today"])
        self.assertEqual(plan["since"], ends[-1])
        self.assertGreater(plan["next_review"][:7], ends[-1][:7])

    def test_performance_is_equal_weight_since_the_month_end(self):
        plan = b.compute_monthly_plan(self.meta, self.bars)
        since = plan["since"]
        perf = plan["performance"]["todas"]

        def ret(sym):
            bars = self.bars[sym]
            base = next(x["c"] for x in bars if x["t"][:10] == since)
            return bars[-1]["c"] / base - 1

        held = plan["holdings"]["todas"]
        want = sum(ret(s) for s in held) / len(held) * 100
        self.assertAlmostEqual(perf["portfolio_pct"], want, places=2)
        self.assertAlmostEqual(perf["spy_pct"], ret("SPY") * 100, places=2)

    def test_no_performance_on_the_day_the_book_is_built(self):
        sessions = [d.isoformat() for d in self.dates]
        cut = sessions.index(b.month_end_sessions(sessions)[-1]) + 1
        plan = b.compute_monthly_plan(self.meta, {s: x[:cut] for s, x in self.bars.items()})
        self.assertEqual(plan["performance"], {})

    def test_upcoming_reviews_are_twelve_month_ends(self):
        plan = b.compute_monthly_plan(self.meta, self.bars)
        up = plan["upcoming_reviews"]
        self.assertEqual(len(up), 12)
        self.assertEqual(up[0], plan["next_review"])
        self.assertEqual(len({d[:7] for d in up}), 12)
        self.assertEqual(up, sorted(up))

    def test_live_session_is_not_a_month_end(self):
        sessions = [d.isoformat() for d in self.dates]
        last = sessions[-1]
        plan = b.compute_monthly_plan(self.meta, self.bars, live_session=last)
        self.assertNotEqual(plan["since"], last)
        self.assertEqual(plan["data_date"], last)
        self.assertGreaterEqual(plan["next_review"], last)


if __name__ == "__main__":
    unittest.main()
