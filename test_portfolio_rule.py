#!/usr/bin/env python3
"""Regla de la cartera mensual: banda de permanencia (Top 10 / puesto 20) y tope de 3 por sector.

No usa API keys. Rankings y barras sintéticas.
"""
from __future__ import annotations

import unittest

import build as b
from test_walkforward import universe


def ranking(n: int, sectors: dict[str, str] | None = None, cedear: set[str] | None = None) -> list[dict]:
    """Filas ya ordenadas: T01 es el mejor. Score descendente."""
    rows = []
    for i in range(1, n + 1):
        sym = f"T{i:02d}"
        row = {"symbol": sym, "kind": "us", "desk_score": 100 - i, "desk_score_cons": 100 - i,
               "sector": (sectors or {}).get(sym, f"S{i:02d}")}
        if cedear is not None:
            row["cedear"] = sym in cedear
        rows.append(row)
    return rows


class PortfolioPickTests(unittest.TestCase):
    def test_without_previous_it_is_the_top10(self):
        self.assertEqual(b.portfolio_pick(ranking(30), None, "todas"), [f"T{i:02d}" for i in range(1, 11)])

    def test_names_inside_the_band_stay(self):
        prev = ["T15", "T20", "T21", "T01"]
        got = b.portfolio_pick(ranking(30), prev, "todas")
        self.assertIn("T15", got)
        self.assertIn("T20", got)          # el puesto 20 todavía está adentro
        self.assertNotIn("T21", got)       # el 21 sale
        self.assertEqual(len(got), 10)
        self.assertEqual(got[:3], ["T01", "T15", "T20"])  # primero los que se quedan, por puesto
        self.assertEqual(got[3:], ["T02", "T03", "T04", "T05", "T06", "T07", "T08"])

    def test_a_name_missing_from_the_ranking_leaves(self):
        got = b.portfolio_pick(ranking(30), ["T99", "T02"], "todas")
        self.assertNotIn("T99", got)
        self.assertIn("T02", got)

    def test_sector_cap_skips_the_fourth_of_a_sector(self):
        tech = {f"T{i:02d}": "Tech" for i in range(1, 6)}
        got = b.portfolio_pick(ranking(30, tech), None, "todas")
        self.assertEqual([s for s in got if tech.get(s)], ["T01", "T02", "T03"])
        self.assertEqual(len(got), 10)
        self.assertIn("T12", got)

    def test_kept_names_take_their_sector_slot_first(self):
        # T12 se queda (está dentro de la banda) y ocupa un lugar de Tech antes que T03.
        tech = {f"T{i:02d}": "Tech" for i in (1, 2, 3, 12)}
        got = b.portfolio_pick(ranking(30, tech), ["T12"], "todas")
        self.assertEqual(sorted(s for s in got if s in tech), ["T01", "T02", "T12"])
        self.assertNotIn("T03", got)

    def test_names_without_sector_are_not_capped(self):
        rows = ranking(30)
        for r in rows[:6]:
            r["sector"] = None
        got = b.portfolio_pick(rows, None, "todas")
        self.assertEqual(got, [f"T{i:02d}" for i in range(1, 11)])

    def test_band_counts_places_inside_the_cedear_list(self):
        cedear = {f"T{i:02d}" for i in range(1, 31, 2)}  # impares
        # T29 es el puesto 15 entre los CEDEAR (y el 29 en el total): se queda.
        got = b.portfolio_pick(ranking(40, cedear=cedear), ["T29"], "cedear")
        self.assertIn("T29", got)
        self.assertTrue(all(s in cedear for s in got))

    def test_etfs_never_enter(self):
        rows = ranking(30)
        rows[0]["kind"] = "etf"
        self.assertNotIn("T01", b.portfolio_pick(rows, ["T01"], "todas"))


class PlanWithRuleTests(unittest.TestCase):
    def setUp(self):
        self.meta, self.bars, self.dates = universe(14, 320)

    def test_fixed_holdings_override_the_variant(self):
        plain = b.compute_monthly_plan(self.meta, self.bars)
        real = ["S00", "S01", "S02"]
        plan = b.compute_monthly_plan(
            self.meta, self.bars,
            fixed={"cedear": {"since": plain["since"], "holdings": real, "prev_holdings": ["S03"]}},
        )
        self.assertEqual(plan["holdings"]["cedear"], real)
        self.assertEqual(plan["prev_holdings"]["cedear"], ["S03"])
        self.assertEqual(plan["holdings"]["todas"], plain["holdings"]["todas"])

    def test_fixed_from_another_month_is_ignored(self):
        plain = b.compute_monthly_plan(self.meta, self.bars)
        plan = b.compute_monthly_plan(
            self.meta, self.bars, fixed={"cedear": {"since": "1999-12-31", "holdings": ["S00"]}},
        )
        self.assertEqual(plan["holdings"]["cedear"], plain["holdings"]["cedear"])

    def test_today_applies_the_rule_from_the_current_book(self):
        rows = b.rank_universe_asof(self.meta, self.bars, self.dates[-1].isoformat(), require_exact_session=True)
        plan = b.compute_monthly_plan(self.meta, self.bars, today_rows=rows)
        for v, held in plan["holdings"].items():
            self.assertEqual(plan["today"][v], b.portfolio_pick(rows, held, v))
        self.assertEqual(plan["portfolio_rule"], b.PORTFOLIO_RULE)


if __name__ == "__main__":
    unittest.main()
