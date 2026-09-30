#!/usr/bin/env python3
"""Insiders, mediana sectorial, patrones y resumen. Sin red ni claves."""
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


def flat(n: int, px: float, v: float = 1_000_000, wick: float = 0.0) -> list[dict]:
    return [
        bar(d, px, h=px * (1 + wick), l=px * (1 - wick), v=v)
        for d in weekdays(n)
    ]


class InsiderAggregationTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 29)

    def test_open_market_net_ignores_grants_exercises_and_old_trades(self):
        raw = [
            {
                "name": "Perez  Juan",
                "change": 1000,
                "transactionCode": "P",
                "transactionPrice": 10,
                "transactionDate": "2026-09-01",
                "position": "CEO",
            },
            {
                "name": "PEREZ JUAN",
                "change": -200,
                "transactionCode": "S",
                "transactionPrice": 12,
                "transactionDate": "2026-08-15",
            },
            {
                "name": "Gomez Ana",
                "change": 500,
                "transactionCode": "p",
                "transactionPrice": 11,
                "transactionDate": "2026-09-20",
                "title": "CFO",
            },
            {
                "name": "Lopez",
                "change": 9000,
                "transactionCode": "A",
                "transactionPrice": 0,
                "transactionDate": "2026-09-10",
            },
            {
                "name": "Lopez",
                "change": 100,
                "transactionCode": "M",
                "transactionPrice": 5,
                "transactionDate": "2026-09-11",
            },
            {
                "name": "Viejo",
                "change": 5000,
                "transactionCode": "P",
                "transactionPrice": 10,
                "transactionDate": "2026-01-01",
            },
        ]
        out = s.aggregate_insiders(raw, today=self.today, close=10)
        self.assertEqual(out["net_shares"], 1300)
        self.assertEqual(out["buy_shares"], 1500)
        self.assertEqual(out["sell_shares"], 200)
        self.assertEqual(out["buyers"], 2)
        self.assertEqual(out["sellers"], 1)
        self.assertEqual(out["excluded_count"], 2)
        self.assertEqual(out["open_market_count"], 3)
        self.assertEqual(out["net_value_usd"], 13100)
        self.assertFalse(out["value_approx"])
        self.assertEqual(out["latest_date"], "2026-09-20")
        self.assertFalse(out["notable"])
        txs = out["transactions"]
        self.assertEqual([t["date"] for t in txs], ["2026-09-20", "2026-09-01", "2026-08-15"])
        self.assertEqual(txs[0]["role"], "CFO")
        self.assertEqual(txs[0]["side"], "buy")
        self.assertEqual(txs[1]["role"], "CEO")
        self.assertEqual(txs[1]["name"], "PEREZ JUAN")
        self.assertNotIn("A", [t["code"] for t in txs])

    def test_notable_needs_two_buyers_or_a_large_solo_ticket(self):
        def buy(name, shares, price, when="2026-09-10"):
            return {
                "name": name,
                "change": shares,
                "transactionCode": "P",
                "transactionPrice": price,
                "transactionDate": when,
            }

        small = s.aggregate_insiders(
            [buy("A", 100, 10), buy("B", 100, 10)],
            today=self.today,
        )
        self.assertGreater(small["net_shares"], 0)
        self.assertEqual(small["buyers"], 2)
        self.assertFalse(small["notable"])

        two = s.aggregate_insiders(
            [buy("A", 10000, 10), buy("B", 5000, 10)],
            today=self.today,
        )
        self.assertGreaterEqual(two["net_value_usd"], s.INSIDER_NOTABLE_MIN_NET_USD)
        self.assertTrue(two["notable"])

        solo = s.aggregate_insiders([buy("A", 60000, 10)], today=self.today)
        self.assertEqual(solo["buyers"], 1)
        self.assertGreaterEqual(solo["net_value_usd"], s.INSIDER_NOTABLE_SOLO_USD)
        self.assertTrue(solo["notable"])

    def test_missing_price_uses_close_and_marks_approx(self):
        raw = [
            {
                "name": "Sin Precio",
                "change": 100,
                "transactionCode": "P",
                "transactionDate": "2026-09-12",
            }
        ]
        out = s.aggregate_insiders(raw, today=self.today, close=20)
        self.assertTrue(out["value_approx"])
        self.assertEqual(out["net_value_usd"], 2000)
        self.assertEqual(out["transactions"][0]["price"], 20)

    def test_panel_lists_only_net_buyers_by_value(self):
        rows = [
            {"symbol": "AAA", "desk_score": 10, "insiders": {"net_shares": 100, "net_value_usd": 50, "buyers": 1}},
            {"symbol": "BBB", "desk_score": 90, "insiders": {"net_shares": 10, "net_value_usd": 9000, "buyers": 2, "notable": True}},
            {"symbol": "CCC", "desk_score": 80, "insiders": {"net_shares": -5, "net_value_usd": -100, "buyers": 0}},
            {"symbol": "ETF", "kind": "etf"},
        ]
        panel = s.insider_panel(rows)
        self.assertEqual([r["symbol"] for r in panel["rows"]], ["BBB", "AAA"])


class SectorMedianTests(unittest.TestCase):
    def _row(self, symbol, sector, pe, margin, growth, kind="us"):
        return {
            "symbol": symbol,
            "kind": kind,
            "sector": sector,
            "desk_score": 50,
            "fundamentals": {
                "fetched_on": "2026-09-29",
                "metrics": {
                    "pe_ttm": pe,
                    "gross_margin": margin,
                    "operating_margin": margin,
                    "net_margin": margin,
                    "revenue_growth_yoy": growth,
                    "eps_growth_yoy": growth,
                },
            },
        }

    def test_median_and_cues_ignore_etfs_and_other_sectors(self):
        rows = [
            self._row("A", "Technology", 32, 40, 20),
            self._row("B", "Technology", 24, 30, 10),
            self._row("C", "Technology", 16, 20, 5),
            self._row("D", "Technology", None, None, None),
            self._row("XLK", "Technology", 5, 90, 80, kind="etf"),
            self._row("E", "Energy", 8, 50, 40),
            self._row("F", "Energy", 9, 50, 40),
        ]
        before = rows[0]["desk_score"]
        s.attach_sector_medians(rows)
        self.assertEqual(rows[0]["desk_score"], before)
        vs = rows[0]["fundamentals"]["vs_sector"]["pe_ttm"]
        self.assertEqual(vs["n"], 3)
        self.assertEqual(vs["median"], 24)
        self.assertEqual(vs["cue"], "red")
        cheap = rows[2]["fundamentals"]["vs_sector"]["pe_ttm"]
        self.assertEqual(cheap["cue"], "green")
        mid = rows[1]["fundamentals"]["vs_sector"]["pe_ttm"]
        self.assertEqual(mid["cue"], "amber")
        margin = rows[0]["fundamentals"]["vs_sector"]["gross_margin"]
        self.assertEqual(margin["median"], 30)
        self.assertEqual(margin["cue"], "green")
        weak_margin = rows[2]["fundamentals"]["vs_sector"]["gross_margin"]
        self.assertEqual(weak_margin["cue"], "red")
        missing = rows[3]["fundamentals"]["vs_sector"]["pe_ttm"]
        self.assertEqual(missing["median"], 24)
        self.assertIsNone(missing["value"])
        self.assertIsNone(missing["cue"])
        self.assertEqual(missing["n"], 3)
        etf_vs = rows[4]["fundamentals"]["vs_sector"]["pe_ttm"]
        self.assertEqual(etf_vs["n"], 0)
        self.assertIsNone(etf_vs["median"])
        # Energía tiene solo 2 nombres: sin mediana.
        self.assertIsNone(rows[5]["fundamentals"]["vs_sector"]["pe_ttm"]["median"])
        self.assertEqual(rows[5]["fundamentals"]["vs_sector"]["pe_ttm"]["n"], 2)

    def test_even_count_median_and_negative_pe_has_no_cue(self):
        self.assertEqual(s._median([10, 20, 30, 40]), 25)
        self.assertIsNone(s.metric_cue("lower", -5, 20))
        self.assertEqual(s.metric_cue("higher", -2, -10), "green")
        self.assertEqual(s.metric_cue("higher", -20, -10), "red")

    def test_parse_fundamentals_picks_known_keys_and_skips_junk(self):
        parsed = s.parse_fundamentals(
            {
                "metric": {
                    "peTTM": 28.4,
                    "grossMarginTTM": 46.2,
                    "revenueGrowthTTMYoy": 8.1,
                    "epsGrowthTTMYoy": None,
                    "series": {"annual": [1, 2, 3]},
                }
            },
            fetched_on=date(2026, 9, 29),
        )
        self.assertEqual(parsed["metrics"]["pe_ttm"], 28.4)
        self.assertEqual(parsed["metrics"]["gross_margin"], 46.2)
        self.assertEqual(parsed["metrics"]["revenue_growth_yoy"], 8.1)
        self.assertIsNone(parsed["metrics"]["eps_growth_yoy"])
        self.assertNotIn("series", parsed)


class PatternTests(unittest.TestCase):
    def test_thresholds_are_the_documented_ones(self):
        self.assertEqual(s.PATTERN_BREAKOUT_NEAR_PCT, 2.0)
        self.assertEqual(s.PATTERN_PULLBACK_NEAR_PCT, 2.0)
        self.assertEqual(s.PATTERN_PULLBACK_LOOKBACK, 5)
        self.assertEqual(s.PATTERN_EMA_CROSS_SESSIONS, 5)
        self.assertIn(15, s.PATTERN_BASE_WINDOWS)
        self.assertIn(30, s.PATTERN_BASE_WINDOWS)
        self.assertLessEqual(s.PATTERN_BASE_MAX_RANGE_PCT, 8)
        self.assertLessEqual(s.PATTERN_BASE_NEAR_52W_PCT, 10)

    def test_new_52w_high_and_near_high_only_with_volume(self):
        dates = weekdays(80)
        bars = [bar(d, 100, h=100, l=99, v=1_000_000) for d in dates]
        bars[-1] = bar(dates[-1], 101, h=102, l=100, v=500_000)
        ids = [p["id"] for p in s.detect_patterns(bars)]
        self.assertIn("breakout_52w", ids)

        near = [bar(d, 100, h=100, l=99, v=1_000_000) for d in dates]
        near[-1] = bar(dates[-1], 98.5, h=99, l=98, v=2_000_000)
        self.assertIn("breakout_52w", [p["id"] for p in s.detect_patterns(near)])

        quiet = [bar(d, 100, h=100, l=99, v=1_000_000) for d in dates]
        quiet[-1] = bar(dates[-1], 98.5, h=99, l=98, v=500_000)
        self.assertNotIn("breakout_52w", [p["id"] for p in s.detect_patterns(quiet)])

        far = [bar(d, 100, h=100, l=99, v=1_000_000) for d in dates]
        far[-1] = bar(dates[-1], 90, h=91, l=89, v=5_000_000)
        self.assertNotIn("breakout_52w", [p["id"] for p in s.detect_patterns(far)])

    def test_pullback_to_sma50_in_uptrend_only(self):
        dates = weekdays(230)
        px = 80.0
        bars = []
        for d in dates:
            px *= 1.0015
            bars.append(bar(d, px, h=px * 1.005, l=px * 0.995, v=1_000_000))
        closes = [b["c"] for b in bars]
        sma50 = s.sma(closes, 50)
        ema200 = s.ema(closes, 200)
        self.assertGreater(closes[-1], sma50[-1])
        self.assertGreater(closes[-1], ema200[-1])
        self.assertNotIn("pullback_sma50", [p["id"] for p in s.detect_patterns(bars)])

        bars[-3]["l"] = sma50[-3]
        self.assertIn("pullback_sma50", [p["id"] for p in s.detect_patterns(bars)])

        # Debajo de la EMA200 no es pullback en tendencia, aunque toque la SMA50.
        crashed = [dict(b) for b in bars]
        crashed[-1] = dict(crashed[-1])
        crashed[-1]["c"] = ema200[-1] * 0.9
        crashed[-1]["h"] = crashed[-1]["c"]
        crashed[-1]["l"] = sma50[-1]
        self.assertNotIn("pullback_sma50", [p["id"] for p in s.detect_patterns(crashed)])

    def test_tight_base_near_highs_and_rejects_a_wide_range(self):
        dates = weekdays(80)
        bars = [bar(d, 50 + i * 0.4, h=50 + i * 0.4, l=50 + i * 0.4) for i, d in enumerate(dates)]
        # Lateral chico arriba del recorrido.
        for i in range(20):
            px = 100.0
            bars[-1 - i] = bar(dates[-1 - i], px, h=101.0, l=99.5, v=800_000)
        ids = [p["id"] for p in s.detect_patterns(bars)]
        self.assertIn("base", ids)

        wide = [bar(d, 100, h=100, l=100) for d in dates]
        for i, swing in enumerate((70, 110, 75, 115)):
            wide[-1 - i] = bar(dates[-1 - i], swing, h=swing + 2, l=swing - 2)
        self.assertNotIn("base", [p["id"] for p in s.detect_patterns(wide)])

    def test_fresh_ema200_cross_up_and_down_inside_five_sessions(self):
        dates = weekdays(230)
        above = [bar(d, 160, h=161, l=159) for d in dates]
        above[-1] = bar(dates[-1], 40, h=41, l=39)
        down = [p["id"] for p in s.detect_patterns(above)]
        self.assertIn("ema200_cross_down", down)
        self.assertNotIn("ema200_cross_up", down)

        below = [bar(d, 80, h=81, l=79) for d in dates]
        # Un tramo largo abajo y un cierre reciente arriba.
        for i in range(20):
            below[-1 - i] = bar(dates[-1 - i], 40, h=41, l=39)
        below[-1] = bar(dates[-1], 120, h=121, l=119)
        up = [p["id"] for p in s.detect_patterns(below)]
        self.assertIn("ema200_cross_up", up)

        stale = [bar(d, 160, h=161, l=159) for d in dates]
        for i in range(12):
            stale[-1 - i] = bar(dates[-1 - i], 40, h=41, l=39)
        stale_ids = [p["id"] for p in s.detect_patterns(stale)]
        self.assertNotIn("ema200_cross_down", stale_ids)
        self.assertNotIn("ema200_cross_up", stale_ids)


class ResumenTests(unittest.TestCase):
    def _snap(self, **overrides):
        base = {
            "generated_at": "2026-09-29T18:40:00-03:00",
            "regime_label": "mixto",
            "spy_change_pct": 0.42,
            "top10": ["ABBV", "MSFT", "KO", "NVDA", "JPM", "V", "MA", "AAPL", "XOM", "UNH"],
            "ranks": {
                "ABBV": 1,
                "MSFT": 2,
                "KO": 3,
                "NVDA": 4,
                "JPM": 5,
                "V": 6,
                "MA": 7,
                "AAPL": 8,
                "XOM": 9,
                "UNH": 10,
                "MELI": 18,
                "BA": 30,
            },
            "above_ema200": {"NVDA": True, "BA": False, "KO": True, "MELI": True},
            "sectors": [
                {"label": "Tecnología", "avg_desk_score": 72.4, "rs_delta": 1.0},
                {"label": "Energía", "avg_desk_score": 41.2, "rs_delta": 6.5},
            ],
            "earnings": [
                {"symbol": "AAPL", "date": "2026-10-01", "rank": 8},
                {"symbol": "BA", "date": "2026-10-02", "rank": 30},
            ],
            "patterns": {"NVDA": ["breakout_52w"], "JPM": ["ema200_cross_up"]},
            "patterns_known": True,
            "insiders": [
                {
                    "symbol": "AVGO",
                    "net_shares": 20000,
                    "net_value_usd": 2_400_000,
                    "buyers": 3,
                    "notable": True,
                }
            ],
        }
        base.update(overrides)
        return base

    def test_diff_mentions_only_facts_from_the_two_snapshots(self):
        prev = self._snap(
            generated_at="2026-09-26T18:40:00-03:00",
            top10=["ABBV", "MSFT", "KO", "CRM", "JPM", "V", "MA", "AAPL", "XOM", "UNH"],
            ranks={
                "ABBV": 1,
                "MSFT": 2,
                "KO": 3,
                "CRM": 4,
                "JPM": 12,
                "V": 6,
                "MA": 7,
                "AAPL": 8,
                "XOM": 9,
                "UNH": 10,
                "MELI": 11,
                "BA": 22,
                "NVDA": 14,
            },
            above_ema200={"NVDA": False, "BA": True, "KO": True, "MELI": True},
            patterns={"JPM": ["ema200_cross_up"]},
            patterns_known=True,
            insiders=[],
        )
        out = s.compose_resumen(self._snap(), prev)
        text = out["text"]
        self.assertGreaterEqual(len(out["sentences"]), 6)
        self.assertLessEqual(len(out["sentences"]), 10)
        self.assertIn("mixto", text)
        self.assertIn("+0,42%", text)
        self.assertIn("NVDA", text)
        self.assertIn("CRM", text)
        self.assertIn("Tecnología", text)
        self.assertIn("Energía", text)
        self.assertIn("6,5", text)
        self.assertIn("AAPL", text)
        self.assertIn("Top 20", text)
        self.assertIn("BA", text)
        self.assertIn("AVGO", text)
        self.assertIn("USD 2,4 millones", text)
        self.assertIn("máximo de 52 semanas", text)
        self.assertNotIn("cruce alcista", text)  # JPM ya lo tenía: no es nuevo
        self.assertEqual(out["compared_to"], prev["generated_at"])
        self.assertIn("29/09/2026 18:40 ART", out["headline"])
        # No inventa un ticker que no está en los datos.
        self.assertNotIn("TSLA", text)

    def test_without_previous_publication_there_is_no_false_diff(self):
        out = s.compose_resumen(self._snap(), None)
        text = out["text"]
        self.assertIsNone(out["compared_to"])
        self.assertGreaterEqual(len(out["sentences"]), 6)
        self.assertLessEqual(len(out["sentences"]), 10)
        self.assertNotIn("Entraron al Top 10", text)
        self.assertNotIn("Salieron del Top 10", text)
        self.assertNotIn("Perdieron la EMA200", text)
        self.assertNotIn("Recuperaron la EMA200", text)
        self.assertNotIn("aparecieron", text)
        self.assertIn("Hoy el escáner marca", text)
        self.assertIn("No hay una publicación anterior", text)

    def test_snapshot_from_old_payload_has_no_pattern_baseline(self):
        payload = {
            "generated_at": "2026-09-25T10:00:00-03:00",
            "regime": {"label": "alcista"},
            "ranking": [
                {"symbol": "SPY", "rank": 5, "change_pct": -0.2, "above_ema200": True, "kind": "etf"},
                {"symbol": "AAPL", "rank": 1, "above_ema200": True, "kind": "us"},
            ],
            "sectors": {"rows": [{"label": "Tecnología", "avg_desk_score": 60, "rs_delta": 0.2}]},
            "earnings": [],
        }
        snap = s.snapshot_from_payload(payload)
        self.assertFalse(snap["patterns_known"])
        self.assertEqual(snap["top10"], ["AAPL", "SPY"])
        self.assertEqual(snap["spy_change_pct"], -0.2)
        self.assertEqual(snap["regime_label"], "alcista")


class SlowFetchPlanTests(unittest.TestCase):
    def test_cold_budget_fills_missing_symbols_in_pairs(self):
        today = date(2026, 9, 29)
        symbols = [f"S{i:02d}" for i in range(50)]
        plan, budget = build._plan_slow_fetches(symbols, {}, today)
        self.assertEqual(budget, build.SLOW_BUDGET_COLD)
        self.assertEqual(len(plan), build.SLOW_BUDGET_COLD)
        self.assertEqual(plan[0], ("S00", "insiders"))
        self.assertEqual(plan[1], ("S00", "analysts"))
        self.assertEqual(plan[2], ("S00", "fundamentals"))

    def test_warm_budget_refreshes_only_stale_blocks(self):
        today = date(2026, 9, 29)
        prev = {
            "AAA": {
                "insiders": {"fetched_on": "2026-09-20"},
                "analysts": {"fetched_on": "2026-09-28"},
                "fundamentals": {"fetched_on": "2026-09-01"},
            },
            "BBB": {
                "insiders": {"fetched_on": "2026-09-28"},
                "analysts": {"fetched_on": "2026-09-28"},
                "fundamentals": {"fetched_on": "2026-09-28"},
            },
        }
        plan, budget = build._plan_slow_fetches(["AAA", "BBB"], prev, today)
        self.assertEqual(budget, build.SLOW_BUDGET_WARM)
        self.assertEqual(plan, [("AAA", "fundamentals"), ("AAA", "insiders")])

    def test_missing_analysts_go_out_before_stale_blocks(self):
        today = date(2026, 9, 29)
        prev = {
            "AAA": {
                "insiders": {"fetched_on": "2026-09-28"},
                "fundamentals": {"fetched_on": "2026-09-01"},
            },
        }
        plan, budget = build._plan_slow_fetches(["AAA"], prev, today)
        self.assertEqual(budget, build.SLOW_BUDGET_WARM)
        self.assertEqual(plan[0], ("AAA", "analysts"))
        self.assertIn(("AAA", "fundamentals"), plan)
        self.assertNotIn(("AAA", "insiders"), plan)


class ScoreUntouchedTests(unittest.TestCase):
    def test_patterns_and_fundamentals_do_not_change_desk_score(self):
        dates = weekdays(80)
        bars = [bar(d, 100 + i * 0.1) for i, d in enumerate(dates)]
        meta = {"symbol": "AAA", "name": "Aaa", "kind": "us", "sector": "Technology"}
        spy = [bar(d, 100) for d in dates]
        row = build.compute_symbol(meta, bars, [b["c"] for b in spy], {})
        self.assertIsNotNone(row)
        scored = build.apply_cross_section_scores([row])
        score = scored[0]["desk_score"]
        scored[0]["patterns"] = s.detect_patterns(bars)
        scored[0]["fundamentals"] = s.parse_fundamentals(
            {"metric": {"peTTM": 10}}, fetched_on=date(2026, 9, 29)
        )
        s.attach_sector_medians(scored)
        s.attach_entry_lights(
            scored,
            {"rows": [{"sector": "Technology", "label": "Tecnología", "rs_trend": "up"}]},
            [],
            today=date(2026, 9, 29),
            earnings_known=True,
            earnings_through=date(2026, 10, 6),
        )
        scored[0]["analysts"] = s.parse_recommendations(
            [{"period": "2026-09-01", "strongBuy": 1, "buy": 2, "hold": 1, "sell": 0, "strongSell": 0}],
            fetched_on=date(2026, 9, 29),
        )
        self.assertEqual(scored[0]["desk_score"], score)
        self.assertEqual(scored[0]["rank"], 1)


if __name__ == "__main__":
    unittest.main()
