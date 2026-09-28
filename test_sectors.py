#!/usr/bin/env python3
"""Vista por sectores: agregados del ranking, sin API keys."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import build as b


def row(
    symbol: str,
    kind: str,
    sector: str | None,
    desk: float | None = 50.0,
    rs: float | None = 50.0,
    above: bool = False,
    rank: int | None = 20,
    chg: float | None = 0.0,
    weekly: list | None = None,
    name: str | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "name": name or symbol,
        "kind": kind,
        "sector": sector,
        "desk_score": desk,
        "rs_score": rs,
        "above_ema200": above,
        "rank": rank,
        "change_pct": chg,
        "rs_weekly": weekly,
        "pillars": {"tendencia": 40, "fuerza_rs": 40, "contraccion": 40, "setup": 40},
    }


def weekdays(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def make_bars(closes: list[float], dates: list[date]) -> list[dict]:
    bars = []
    for d, c in zip(dates, closes):
        px = float(c)
        bars.append({"t": d.isoformat() + "T05:00:00Z", "o": px, "h": px * 1.01, "l": px * 0.99, "c": px, "v": 1_000_000})
    return bars


def geometric(n: int, start: float, daily: float) -> list[float]:
    px = float(start)
    out = []
    for _ in range(n):
        px *= daily
        out.append(px)
    return out


class SectorAggregateTests(unittest.TestCase):
    def test_excludes_etfs_benchmark_and_blank_sector(self):
        weekly = [10, 20, 30, 40, 50, 60]
        rows = [
            row("AAA", "us", "Technology", desk=80, rs=70, above=True, rank=1, chg=1.5, weekly=weekly),
            row("XLK", "etf", "Technology", desk=99, rs=99, above=True, rank=2, chg=4, weekly=weekly),
            row("SPY", "etf", "Benchmark", desk=60, rank=3, weekly=weekly),
            row("QQQ", "ETF", "Benchmark", desk=61, rank=4, weekly=weekly),
            row("ORPH", "us", None, desk=90, rank=5),
            row("BLANK", "us", "   ", desk=90, rank=6),
            row("BENCH", "us", "Benchmark", desk=90, rank=7),
        ]
        got = b.compute_sector_view(rows)
        self.assertEqual([r["sector"] for r in got["rows"]], ["Technology"])
        tech = got["rows"][0]
        self.assertEqual(tech["count"], 1)
        self.assertEqual(tech["label"], "Tecnología")
        self.assertEqual(tech["best"]["symbol"], "AAA")
        self.assertEqual(tech["avg_desk_score"], 80.0)
        self.assertEqual(got["included"], 1)
        excluded = got["excluded"]["symbols"]
        for sym in ("XLK", "SPY", "QQQ", "ORPH", "BLANK", "BENCH"):
            self.assertIn(sym, excluded)
        self.assertIn("canastas", got["excluded"]["summary"])
        self.assertNotIn("recomendación de compra", got["caption"])
        self.assertIn("no una recomendación", got["caption"])

    def test_averages_top10_best_and_low_sample(self):
        rows = [
            row("AAA", "us", "Energy", desk=80, rs=70, above=True, rank=1, chg=1.0),
            row("BBB", "us", "Energy", desk=60, rs=50, above=False, rank=11, chg=None),
            row("CCC", "us", "Energy", desk=70, rs=None, above=True, rank=10, chg=3.0),
            row("DDD", "us", "Utilities", desk=40, rs=20, above=False, rank=30, chg=-1.0),
            row("EEE", "us", "Utilities", desk=40, rs=30, above=True, rank=8, chg=1.0),
            row("FFF", "cedear_proxy", "Materials", desk=55, rs=55, above=True, rank=4, chg=0.5),
            row("GGG", "us", "Materials", desk=45, rs=45, above=False, rank=12, chg=0.5),
            row("HHH", "us", "Materials", desk=50, rs=50, above=True, rank=9, chg=None),
        ]
        got = b.compute_sector_view(rows)
        by = {r["sector"]: r for r in got["rows"]}
        # Energy 70.0, Materials 50.0, Utilities 40.0
        self.assertEqual([r["sector"] for r in got["rows"]], ["Energy", "Materials", "Utilities"])
        energy = by["Energy"]
        self.assertEqual(energy["count"], 3)
        self.assertEqual(energy["avg_desk_score"], 70.0)
        self.assertEqual(energy["avg_rs_score"], 60.0)  # None no entra
        self.assertEqual(energy["above_ema200"], 2)
        self.assertEqual(energy["pct_above_ema200"], 66.7)
        self.assertEqual(energy["top10_count"], 2)  # ranks 1 y 10; el ETF no está
        self.assertEqual(energy["best"]["symbol"], "AAA")
        self.assertEqual(energy["avg_change_pct"], 2.0)  # 1.0 y 3.0; None afuera
        self.assertFalse(energy["low_sample"])
        self.assertTrue(by["Utilities"]["low_sample"])
        self.assertEqual(by["Utilities"]["label"], "Servicios")
        self.assertEqual(by["Utilities"]["top10_count"], 1)
        self.assertFalse(by["Materials"]["low_sample"])
        self.assertEqual(by["Materials"]["pct_above_ema200"], 66.7)

    def test_best_ticker_tie_breaks_by_symbol(self):
        rows = [
            row("ZZZ", "us", "Financials", desk=60, rank=15),
            row("AAA", "us", "Financials", desk=60, rank=16),
        ]
        best = b.compute_sector_view(rows)["rows"][0]["best"]
        self.assertEqual(best["symbol"], "AAA")
        self.assertEqual(best["desk_score"], 60.0)

    def test_sort_tie_uses_sector_name(self):
        rows = [
            row("A", "us", "Financials", desk=50),
            row("B", "us", "Energy", desk=50),
        ]
        self.assertEqual(
            [r["sector"] for r in b.compute_sector_view(rows)["rows"]],
            ["Energy", "Financials"],
        )

    def test_rs_trend_now_versus_four_weeks_ago(self):
        # índice -1 = ahora, -5 = hace 4 semanas
        up = [10, 20, 30, 40, 50, 80]
        down_peer = [90, 40, 30, 20, 10, 60]
        flat_a = [50, 50, 50, 50, 50, 50.4]
        flat_b = [50, 50, 50, 50, 50, 50.2]
        missing = [None, None, None, None, None, 99]
        short = [1, 2, 3]
        rows = [
            row("UP1", "us", "Technology", weekly=up, rs=80),
            row("UP2", "us", "Technology", weekly=down_peer, rs=60),
            row("GAP", "us", "Technology", weekly=missing, rs=99),
            row("SHORT", "us", "Technology", weekly=short, rs=10),
            row("FL1", "us", "Health Care", weekly=flat_a, rs=50.4),
            row("FL2", "us", "Health Care", weekly=flat_b, rs=50.2),
            row("DN", "us", "Energy", weekly=[80, 70, 60, 50, 40, 30], rs=30),
        ]
        by = {r["sector"]: r for r in b.compute_sector_view(rows)["rows"]}
        tech = by["Technology"]
        # Sólo UP1 (80 vs 20) y UP2 (60 vs 40). GAP y SHORT no entran.
        self.assertEqual(tech["rs_now"], 70.0)
        self.assertEqual(tech["rs_weeks_ago"], 30.0)
        self.assertEqual(tech["rs_delta"], 40.0)
        self.assertEqual(tech["rs_trend"], "up")
        self.assertEqual(tech["avg_rs_score"], 62.2)  # (80+60+99+10)/4 = 62.25 → 62.2
        self.assertEqual(by["Health Care"]["rs_trend"], "flat")
        self.assertEqual(by["Health Care"]["rs_delta"], 0.3)
        self.assertEqual(by["Energy"]["rs_trend"], "down")
        self.assertEqual(by["Energy"]["rs_delta"], -40.0)
        self.assertEqual(by["Energy"]["rs_weeks_ago"], 70.0)

    def test_unknown_sector_keeps_its_name_and_empty_input(self):
        got = b.compute_sector_view([row("X", "us", "Crypto Mining", desk=10)])
        self.assertEqual(got["rows"][0]["label"], "Crypto Mining")
        self.assertTrue(got["rows"][0]["low_sample"])
        self.assertIsNone(got["rows"][0]["rs_trend"])
        empty = b.compute_sector_view([])
        self.assertEqual(empty["rows"], [])
        self.assertEqual(empty["included"], 0)
        self.assertEqual(b.compute_sector_view(None)["rows"], [])

    def test_does_not_mutate_ranking_rows(self):
        src = row("AAA", "us", " Technology ", desk=70, weekly=[1, 2, 3, 4, 5, 6])
        snapshot = dict(src)
        got = b.compute_sector_view([src])
        self.assertEqual(src, snapshot)
        self.assertEqual(got["rows"][0]["sector"], "Technology")

    def test_pipeline_rows_drop_sector_etfs(self):
        n = 80
        dates = weekdays(n)
        bars = {"SPY": make_bars(geometric(n, 100, 1.0004), dates)}
        meta = {
            "SPY": {"symbol": "SPY", "name": "SPY", "kind": "etf", "sector": "Benchmark"},
            "XLK": {"symbol": "XLK", "name": "XLK", "kind": "etf", "sector": "Technology"},
        }
        bars["XLK"] = make_bars(geometric(n, 80, 1.001), dates)
        for i, sector in enumerate(("Technology", "Technology", "Energy", "Energy", "Energy")):
            sym = f"S{i}"
            meta[sym] = {"symbol": sym, "name": sym, "kind": "us", "sector": sector}
            bars[sym] = make_bars(geometric(n, 40 + i * 5, 1.0003 + i * 0.0002), dates)
        spy = [float(x["c"]) for x in bars["SPY"]]
        rows = []
        for sym, series in bars.items():
            built = b.compute_symbol(meta[sym], series, spy, {})
            if built:
                rows.append(built)
        rows = b.apply_cross_section_scores(rows)
        b.attach_rs_weekly(rows, b.compute_rs_weekly(bars, weeks=8))
        got = b.compute_sector_view(rows)
        sectors = {r["sector"] for r in got["rows"]}
        self.assertEqual(sectors, {"Technology", "Energy"})
        self.assertEqual(got["included"], 5)
        self.assertEqual(got["excluded"]["symbols"], ["SPY", "XLK"])
        by = {r["sector"]: r for r in got["rows"]}
        self.assertEqual(by["Technology"]["count"], 2)
        self.assertTrue(by["Technology"]["low_sample"])
        self.assertEqual(by["Energy"]["count"], 3)
        self.assertFalse(by["Energy"]["low_sample"])
        for item in got["rows"]:
            self.assertIsNotNone(item["avg_desk_score"])
            self.assertIsNotNone(item["avg_rs_score"])
            self.assertIn(item["rs_trend"], ("up", "down", "flat", None))
            self.assertIn(item["best"]["symbol"], {r["symbol"] for r in rows})
            self.assertNotIn(item["best"]["symbol"], ("SPY", "XLK"))
        self.assertEqual(got["sorted_by"], "avg_desk_score")
        scores = [r["avg_desk_score"] for r in got["rows"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
