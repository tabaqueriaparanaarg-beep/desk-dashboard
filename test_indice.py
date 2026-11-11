#!/usr/bin/env python3
"""Índice Angus: registro hacia adelante, meses congelados y persistencia segura.

No usa API keys ni red. Las barras son sintéticas.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import build as b
import indice as ix
from test_walkforward import universe


def _sessions(bars):
    return b.session_dates_from_bars(bars["SPY"])


def _cut(bars, upto):
    return {s: [x for x in v if x["t"][:10] <= upto] for s, v in bars.items()}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.meta, self.bars, _ = universe(14, 320)
        self.sessions = _sessions(self.bars)
        self.ends = b.month_end_sessions(self.sessions)

    def test_starts_at_the_last_month_end_with_that_days_top10(self):
        led = ix.update_ledger(None, self.meta, self.bars)
        self.assertEqual(led["inception"], self.ends[-1])
        self.assertEqual(len(led["periods"]), 1)
        ranked = b.rank_universe_asof(self.meta, self.bars, self.ends[-1], require_exact_session=True)
        self.assertEqual(led["periods"][0]["holdings"], [r["symbol"] for r in b.top10_pick(ranked, "cedear")])
        self.assertEqual(led["points"][0], {"date": self.ends[-1], "index": 100.0, "spy": 100.0})
        self.assertEqual(led["points"][-1]["date"], self.sessions[-1])

    def test_level_is_equal_weight_since_the_start(self):
        led = ix.update_ledger(None, self.meta, self.bars)
        p = led["periods"][-1]
        closes = {s: ix._closes(v) for s, v in self.bars.items()}
        last = self.sessions[-1]
        rets = [closes[s][last] / closes[s][p["start"]] - 1 for s in p["holdings"]]
        self.assertAlmostEqual(led["points"][-1]["index"], 100 * (1 + sum(rets) / len(rets)), places=3)
        spy = closes["SPY"][last] / closes["SPY"][p["start"]] * 100
        self.assertAlmostEqual(led["points"][-1]["spy"], spy, places=3)

    def test_later_runs_close_the_month_and_open_the_next(self):
        first_end = self.ends[-2]
        early = ix.update_ledger(None, self.meta, _cut(self.bars, first_end))
        self.assertEqual(early["inception"], first_end)
        later = ix.update_ledger(copy.deepcopy(early), self.meta, self.bars)
        self.assertEqual(later["inception"], first_end)
        self.assertEqual([p["start"] for p in later["periods"]], [first_end, self.ends[-1]])
        closed, current = later["periods"]
        self.assertEqual(closed["end"], self.ends[-1])
        self.assertEqual(current["level_start"], closed["level_end"])
        self.assertEqual(current["spy_start"], closed["spy_end"])
        self.assertNotIn("last_rets", closed)
        on_end = next(p for p in later["points"] if p["date"] == self.ends[-1])
        self.assertEqual(on_end["index"], closed["level_end"])
        dates = [p["date"] for p in later["points"]]
        self.assertEqual(dates, sorted(set(dates)))

    def test_closed_months_are_never_recomputed(self):
        led = ix.update_ledger(None, self.meta, _cut(self.bars, self.ends[-2]))
        led = ix.update_ledger(led, self.meta, self.bars)
        frozen = [p for p in led["points"] if p["date"] <= self.ends[-1]]
        # Si el proveedor reescribe precios viejos, los meses cerrados no cambian.
        rewritten = {
            s: [dict(x, c=x["c"] * 3) if x["t"][:10] <= self.ends[-1] else x for x in v]
            for s, v in self.bars.items()
        }
        again = ix.update_ledger(copy.deepcopy(led), self.meta, rewritten)
        self.assertEqual([p for p in again["points"] if p["date"] <= self.ends[-1]], frozen)
        self.assertEqual(again["periods"][0], led["periods"][0])

    def test_a_split_inside_the_open_month_is_not_a_drop(self):
        led = ix.update_ledger(None, self.meta, self.bars)
        sym = led["periods"][-1]["holdings"][0]
        # Serie ajustada por un split 2:1: toda la historia a la mitad.
        adjusted = dict(self.bars)
        adjusted[sym] = [dict(x, c=x["c"] / 2) for x in self.bars[sym]]
        again = ix.update_ledger(copy.deepcopy(led), self.meta, adjusted)
        self.assertEqual(again["points"], led["points"])

    def test_a_name_without_data_keeps_its_last_return(self):
        led = ix.update_ledger(None, self.meta, self.bars)
        sym = led["periods"][-1]["holdings"][0]
        kept = led["periods"][-1]["last_rets"][sym]
        gone = {s: v for s, v in self.bars.items() if s != sym}
        again = ix.update_ledger(copy.deepcopy(led), self.meta, gone)
        self.assertEqual(again["periods"][-1]["last_rets"][sym], kept)
        self.assertAlmostEqual(again["points"][-1]["index"], led["points"][-1]["index"], places=3)

    def test_live_session_is_left_out(self):
        last = self.sessions[-1]
        led = ix.update_ledger(None, self.meta, self.bars, live_session=last)
        self.assertEqual(led["points"][-1]["date"], self.sessions[-2])

    def test_rerun_on_the_same_data_is_idempotent(self):
        led = ix.update_ledger(None, self.meta, self.bars)
        again = ix.update_ledger(copy.deepcopy(led), self.meta, self.bars)
        self.assertEqual(again, led)


class PublicBlockTests(unittest.TestCase):
    def ledger(self):
        return {
            "version": 1, "name": "Índice Angus", "variant": "cedear", "base": 100.0,
            "inception": "2026-09-30",
            "periods": [
                {"start": "2026-09-30", "end": "2026-10-30", "rules": ix.RULES,
                 "holdings": ["A", "B", "C"], "level_start": 100.0, "spy_start": 100.0,
                 "level_end": 110.0, "spy_end": 102.0},
                {"start": "2026-10-30", "end": None, "rules": ix.RULES,
                 "holdings": ["A", "C", "D"], "level_start": 110.0, "spy_start": 102.0,
                 "last_rets": {"A": 0.05, "C": -0.02, "D": 0.10}},
            ],
            "points": [
                {"date": "2026-09-30", "index": 100.0, "spy": 100.0},
                {"date": "2026-10-15", "index": 90.0, "spy": 101.0},
                {"date": "2026-10-30", "index": 110.0, "spy": 102.0},
                {"date": "2026-11-10", "index": 121.0, "spy": 104.04},
            ],
        }

    def test_totals_month_and_drawdown(self):
        blk = ix.public_block(self.ledger(), {"A": {"name": "Alfa", "sector": "Tech"}})
        self.assertEqual(blk["level"], 121.0)
        self.assertEqual(blk["return_pct"], 21.0)
        self.assertEqual(blk["spy_return_pct"], 4.04)
        self.assertEqual(blk["excess_pct"], 16.96)
        self.assertEqual(blk["max_drawdown_pct"], -10.0)
        self.assertEqual(blk["months"], 1)
        self.assertEqual(blk["period_return_pct"], 10.0)
        self.assertEqual(blk["period_spy_return_pct"], 2.0)
        self.assertIn("30/09/2026", blk["explainer"])

    def test_holdings_sorted_by_return_with_names(self):
        blk = ix.public_block(self.ledger(), {"A": {"name": "Alfa", "sector": "Tech"}})
        self.assertEqual([h["symbol"] for h in blk["holdings"]], ["D", "A", "C"])
        self.assertEqual(blk["holdings"][1]["name"], "Alfa")
        self.assertEqual(blk["holdings"][0]["return_pct"], 10.0)

    def test_changes_list_ins_and_outs(self):
        blk = ix.public_block(self.ledger())
        self.assertEqual(blk["changes"], [{"date": "2026-10-30", "in": ["D"], "out": ["B"]}])

    def test_empty_ledger_has_no_block(self):
        self.assertIsNone(ix.public_block(ix.empty_ledger()))
        self.assertIsNone(ix.public_block(None))


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.meta, self.bars, _ = universe(14, 320)
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "indice_angus.json"
        self.flag = self.tmp / ".indice_fetch_failed"

    def run_publish(self, fetch, write=True):
        return ix.publish(
            meta_by=self.meta, all_bars=self.bars, write=write,
            path=self.path, flag_path=self.flag, fetch=fetch,
        )

    def test_first_run_creates_the_file(self):
        block, note = self.run_publish(lambda: ("missing", None))
        self.assertTrue(self.path.is_file())
        self.assertFalse(self.flag.exists())
        saved = json.loads(self.path.read_text(encoding="utf-8"))["points"][-1]["index"]
        self.assertAlmostEqual(block["level"], saved, places=1)
        self.assertIn("guardado", note)

    def test_failed_download_without_copy_blocks_the_deploy(self):
        block, _ = self.run_publish(lambda: ("failed", None))
        self.assertIsNone(block)
        self.assertFalse(self.path.exists())
        self.assertTrue(self.flag.exists())

    def test_failed_download_uses_the_local_copy(self):
        self.run_publish(lambda: ("missing", None))
        before = json.loads(self.path.read_text(encoding="utf-8"))
        block, note = self.run_publish(lambda: ("failed", None))
        self.assertIsNotNone(block)
        self.assertEqual(block["inception"], before["inception"])
        self.assertIn("local", note)

    def test_published_copy_wins_over_local(self):
        self.run_publish(lambda: ("missing", None))
        published = json.loads(self.path.read_text(encoding="utf-8"))
        published["inception"] = "2000-01-31"
        block, _ = self.run_publish(lambda: ("ok", published))
        self.assertEqual(block["inception"], "2000-01-31")

    def test_live_runs_never_write(self):
        block, note = self.run_publish(lambda: ("missing", None), write=False)
        self.assertIsNotNone(block)
        self.assertFalse(self.path.exists())
        self.assertIn("en vivo", note)

    def test_live_run_without_any_copy_shows_nothing(self):
        block, _ = self.run_publish(lambda: ("failed", None), write=False)
        self.assertIsNone(block)
        self.assertFalse(self.flag.exists())


if __name__ == "__main__":
    unittest.main()
