#!/usr/bin/env python3
"""Puntaje de régimen de mercado: tramos, renormalización sin VIX y máximos/mínimos."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import build
import market_regime as mr


def weekdays(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars_from_ohlc(
    rows: list[tuple[float, float, float, float]],
    start: date = date(2024, 1, 2),
) -> list[dict]:
    bars = []
    for d, (o, h, l, c) in zip(weekdays(len(rows), start), rows):
        bars.append(
            {
                "t": d.isoformat() + "T05:00:00Z",
                "o": o,
                "h": h,
                "l": l,
                "c": c,
                "v": 1_000_000,
            }
        )
    return bars


def bars_from_closes(closes: list[float], start: date = date(2024, 1, 2)) -> list[dict]:
    rows = [(c, c * 1.01, c * 0.99, c) for c in closes]
    return bars_from_ohlc(rows, start)


def geometric(n: int, start: float, daily: float) -> list[float]:
    px = float(start)
    out = []
    for _ in range(n):
        px *= daily
        out.append(px)
    return out


def flat_then(n_prior: int, high: float, low: float, close: float = 100.0) -> list[dict]:
    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(n_prior)]
    rows.append((close, high, low, close))
    return bars_from_ohlc(rows)


class IndicatorParityTests(unittest.TestCase):
    def test_ema_and_sma_match_build(self):
        values = [float(i) for i in range(1, 90)]
        self.assertEqual(mr.ema(values, 10), build.ema(values, 10))
        self.assertEqual(mr.sma(values, 12), build.sma(values, 12))
        self.assertEqual(mr.HL_WINDOW, build.RANGE_52W_SESSIONS)
        self.assertEqual(mr.SLOPE_LAG, 5)


class IndexScoreTests(unittest.TestCase):
    def test_uptrend_scores_all_five_checks(self):
        got = mr.score_index(bars_from_closes(geometric(260, 100.0, 1.003)))
        self.assertTrue(got["available"])
        self.assertEqual([c["ok"] for c in got["checks"]], [True, True, True, True, True])
        self.assertEqual(got["points_exact"], 40.0)
        self.assertEqual(got["max_points"], 40.0)

    def test_downtrend_scores_zero(self):
        got = mr.score_index(bars_from_closes(geometric(260, 100.0, 0.997)))
        self.assertEqual([c["ok"] for c in got["checks"]], [False, False, False, False, False])
        self.assertEqual(got["points_exact"], 0.0)
        self.assertEqual(got["max_points"], 40.0)

    def test_missing_series_is_unavailable(self):
        got = mr.score_index(None)
        self.assertFalse(got["available"])
        self.assertEqual(mr.score_index([])["available"], False)


class HighLowTests(unittest.TestCase):
    def test_new_high_and_new_low_and_neither(self):
        high = flat_then(80, high=102.0, low=99.5)
        low = flat_then(80, high=100.5, low=98.0)
        inside = flat_then(80, high=100.5, low=99.5)
        both = flat_then(80, high=110.0, low=90.0)
        short = flat_then(40, high=110.0, low=90.0)
        anchor = high[-1]["t"][:10]
        self.assertEqual(mr.session_extremes(high, anchor), {"eligible": True, "new_high": True, "new_low": False})
        self.assertEqual(mr.session_extremes(low, anchor), {"eligible": True, "new_high": False, "new_low": True})
        self.assertEqual(mr.session_extremes(inside, anchor), {"eligible": True, "new_high": False, "new_low": False})
        self.assertEqual(mr.session_extremes(both, anchor), {"eligible": True, "new_high": True, "new_low": True})
        self.assertFalse(mr.session_extremes(short, anchor)["eligible"])
        # Otra sesión no cuenta como «hoy».
        self.assertFalse(mr.session_extremes(high, "1999-01-01")["eligible"])

    def test_count_ignores_symbols_outside_the_rows(self):
        up = bars_from_closes(geometric(260, 50.0, 1.004))
        # Misma cantidad de ruedas para compartir la sesión ancla. Plano: no es extremo.
        quiet = bars_from_closes([100.0] * 260)
        anchor = up[-1]["t"][:10]
        self.assertEqual(quiet[-1]["t"][:10], anchor)
        # VIXY está en las barras pero no en el universo scored.
        counted = mr.count_52w(
            {"SPY": up, "AAA": quiet, "VIXY": up},
            ["SPY", "AAA"],
            anchor,
        )
        self.assertEqual(counted["highs"], 1)
        self.assertEqual(counted["lows"], 0)
        self.assertEqual(counted["eligible"], 2)


class BreadthScoreTests(unittest.TestCase):
    def test_linear_parts_and_neutral_day(self):
        got = mr.score_breadth(10, above_ema=6, above_sma=4, highs=0, lows=0)
        self.assertTrue(got["available"])
        self.assertAlmostEqual(got["parts"]["ema200"], 6.0)
        self.assertAlmostEqual(got["parts"]["sma50"], 4.0)
        self.assertAlmostEqual(got["parts"]["high_low"], 5.0)
        self.assertEqual(got["parts"]["high_low_mode"], "neutral")
        self.assertAlmostEqual(got["points_exact"], 15.0)

    def test_high_low_balance(self):
        got = mr.score_breadth(10, 0, 0, highs=2, lows=8)
        self.assertAlmostEqual(got["parts"]["high_low"], 2.0)
        self.assertEqual(got["parts"]["high_low_mode"], "balance")
        self.assertAlmostEqual(got["points_exact"], 2.0)

    def test_all_lows_score_zero_on_that_part(self):
        got = mr.score_breadth(5, 0, 0, highs=0, lows=4)
        self.assertAlmostEqual(got["parts"]["high_low"], 0.0)

    def test_empty_universe_unavailable(self):
        self.assertFalse(mr.score_breadth(0, 0, 0, 0, 0)["available"])


class VixScoreTests(unittest.TestCase):
    def test_calm_vix_below_both_averages_is_fifteen(self):
        closes = [25.0] * 60 + [18.0]
        got = mr.score_vix(closes, "cboe")
        self.assertTrue(got["available"])
        self.assertEqual(got["points_exact"], 15.0)
        self.assertEqual(got["max_points"], 15.0)
        self.assertLessEqual(got["close"], 20)
        self.assertLess(got["close"], got["sma20"])
        self.assertLess(got["close"], got["sma50"])
        self.assertIn("CBOE", got["detail"])

    def test_vix_equal_to_twenty_gets_the_level_points(self):
        closes = [10.0] * 60 + [20.0]
        got = mr.score_vix(closes, "cboe")
        by_id = {c["id"]: c for c in got["checks"]}
        self.assertTrue(by_id["nivel"]["ok"])
        self.assertFalse(by_id["bajo_sma20"]["ok"])
        self.assertFalse(by_id["bajo_sma50"]["ok"])
        self.assertEqual(got["points_exact"], 5.0)

    def test_stressed_vix_above_both_averages_is_zero(self):
        closes = [15.0] * 60 + [35.0]
        got = mr.score_vix(closes, "cboe")
        self.assertEqual(got["points_exact"], 0.0)
        self.assertEqual(got["max_points"], 15.0)

    def test_missing_sma50_drops_those_points(self):
        closes = [30.0] * 29 + [22.0]
        got = mr.score_vix(closes, "cboe")
        self.assertIsNone(got["sma50"])
        self.assertIsNotNone(got["sma20"])
        self.assertEqual(got["max_points"], 10.0)
        self.assertEqual(got["points_exact"], 5.0)  # bajo la media de 20; el nivel no, 22 > 20

    def test_vixy_uses_averages_only(self):
        calm = [40.0] * 60 + [20.0]
        hot = [20.0] * 60 + [40.0]
        below = mr.score_vix(calm, "vixy")
        above = mr.score_vix(hot, "vixy")
        self.assertEqual(below["points_exact"], 15.0)
        self.assertEqual(below["max_points"], 15.0)
        self.assertEqual(above["points_exact"], 0.0)
        self.assertNotIn("nivel", {c["id"] for c in below["checks"]})
        self.assertIn("no entra al ranking", below["detail"])
        only20 = mr.score_vix([30.0] * 25 + [10.0], "vixy")
        self.assertEqual(only20["max_points"], 8.0)
        self.assertEqual(only20["points_exact"], 8.0)

    def test_no_source_drops_the_component(self):
        for source, closes in ((None, None), ("cboe", None), ("vixy", []), ("otro", [1.0] * 60)):
            got = mr.score_vix(closes, source)
            self.assertFalse(got["available"])
            self.assertEqual(got["max_points"], 0.0)

    def test_parse_cboe_csv(self):
        text = "DATE,OPEN,HIGH,LOW,CLOSE\n01/02/1990,17.24,18,17,18.22\n01/03/1990,18,19,17,19.5\n"
        self.assertEqual(mr.parse_cboe_vix_csv(text), [18.22, 19.5])
        self.assertEqual(mr.parse_cboe_vix_csv("\ufeff" + text), [18.22, 19.5])
        with self.assertRaises(ValueError):
            mr.parse_cboe_vix_csv("DATE,OPEN\n01/02/1990,1\n")


class BandTests(unittest.TestCase):
    def test_edges(self):
        expect = {
            0: ("red", "0–25% · mínima, liquidez"),
            24: ("red", "0–25% · mínima, liquidez"),
            25: ("orange", "25–50% · posiciones chicas, stops cortos"),
            49: ("orange", "25–50% · posiciones chicas, stops cortos"),
            50: ("yellow", "50–75% · exposición normal"),
            74: ("yellow", "50–75% · exposición normal"),
            75: ("green", "75–100% · exposición plena"),
            100: ("green", "75–100% · exposición plena"),
        }
        for score, (color, line) in expect.items():
            band = mr.exposure_band(score)
            self.assertEqual(band["color"], color, score)
            self.assertEqual(band["line"], line, score)
            self.assertEqual(band["disclaimer"], mr.DISCLAIMER)

    def test_half_up_moves_the_band_with_the_displayed_score(self):
        low = mr.finalize_score(30.624, 125)
        high = mr.finalize_score(30.625, 125)
        self.assertEqual(low["score"], 24)
        self.assertEqual(low["band"]["color"], "red")
        self.assertEqual(high["score"], 25)
        self.assertEqual(high["band"]["color"], "orange")
        top = mr.finalize_score(93.125, 125)  # 74.5 → 75
        self.assertEqual(top["score"], 75)
        self.assertEqual(top["band"]["color"], "green")


class ClockTests(unittest.TestCase):
    def test_art_clock(self):
        self.assertEqual(mr.format_clock("2026-09-25T21:45:00-03:00"), "09:45 p. m.")
        self.assertEqual(mr.format_clock("2026-09-25T00:05:00-03:00"), "12:05 a. m.")
        self.assertEqual(mr.format_clock("2026-09-25T12:00:00-03:00"), "12:00 p. m.")
        self.assertEqual(
            mr.footer_text("09:45 p. m.", 110, 125),
            "09:45 p. m. · calculado sobre 110 pts disponibles de 125",
        )
        self.assertEqual(
            mr.footer_text(None, 125, 125),
            "calculado sobre 125 pts disponibles de 125",
        )


class AssembleTests(unittest.TestCase):
    def _row(self, symbol: str, above_ema: bool, above_sma: bool, desk: float = 50.0) -> dict:
        return {
            "symbol": symbol,
            "above_ema200": above_ema,
            "above_sma50": above_sma,
            "desk_score": desk,
            "rank": 1,
        }

    def test_renormalizes_when_vix_is_missing(self):
        spy = bars_from_closes(geometric(260, 100.0, 1.003))
        row = self._row("SPY", True, True, desk=83.5)
        got = mr.build_market_regime(
            [row],
            {"SPY": spy, "VIXY": spy, "QQQ": spy},
            generated_at="2026-09-25T21:45:00-03:00",
            vix_closes=None,
            vix_source=None,
        )
        # QQQ tiene barras, así que entra. Para «falta el índice» va otro test.
        indices = got["components"][0]
        breadth = got["components"][1]
        vix = got["components"][2]
        self.assertEqual(indices["points_exact"], 80.0)
        self.assertEqual(indices["max_points"], 80.0)
        self.assertEqual(breadth["points_exact"], 30.0)  # 100% / 100% / nuevo máximo
        self.assertFalse(vix["available"])
        self.assertEqual(got["points_available"], 110.0)
        self.assertEqual(got["points_max"], 125.0)
        self.assertEqual(got["score"], 100)
        self.assertEqual(got["band"]["color"], "green")
        self.assertIn("110 pts disponibles de 125", got["footer"])
        self.assertTrue(got["footer"].startswith("09:45 p. m."))
        self.assertEqual(row["desk_score"], 83.5)
        self.assertEqual(row["rank"], 1)
        self.assertTrue(all(point["eligible"] == 1 for point in got["breadth_series"]))
        self.assertEqual(len(got["breadth_series"]), 42)
        self.assertNotIn("VIXY", [point.get("symbol") for point in got["breadth_series"]])

    def test_missing_qqq_leaves_its_forty_points_out(self):
        spy = bars_from_closes(geometric(260, 100.0, 1.003))
        got = mr.build_market_regime(
            [self._row("SPY", True, True)],
            {"SPY": spy},
            vix_closes=[25.0] * 60 + [18.0],
            vix_source="cboe",
        )
        indices = got["components"][0]
        self.assertEqual(indices["max_points"], 40.0)
        self.assertEqual(indices["points_exact"], 40.0)
        self.assertFalse(indices["symbols"]["QQQ"]["available"])
        self.assertIn("QQQ sin serie", indices["detail"])
        # 40 índices + 30 amplitud + 15 VIX = 85, todo cumplido.
        self.assertEqual(got["points_available"], 85.0)
        self.assertEqual(got["raw_points"], 85.0)
        self.assertEqual(got["score"], 100)
        self.assertIn("85 pts disponibles de 125", got["footer"])

    def test_vix_zero_keeps_the_fifteen_in_the_denominator(self):
        spy = bars_from_closes(geometric(260, 100.0, 1.003))
        stressed = [15.0] * 60 + [35.0]
        got = mr.build_market_regime(
            [self._row("SPY", True, True)],
            {"SPY": spy},
            vix_closes=stressed,
            vix_source="cboe",
        )
        self.assertEqual(got["components"][2]["points_exact"], 0.0)
        self.assertEqual(got["components"][2]["max_points"], 15.0)
        self.assertEqual(got["points_available"], 85.0)
        self.assertEqual(got["raw_points"], 70.0)
        self.assertEqual(got["score"], 82)  # 70/85*100 = 82.352 → 82
        self.assertEqual(got["band"]["color"], "green")

    def test_highs_and_lows_of_the_anchor_session(self):
        spy = flat_then(80, high=100.5, low=99.5)
        winner = flat_then(80, high=130.0, low=99.5)
        loser = flat_then(80, high=100.5, low=70.0)
        stale = flat_then(80, high=130.0, low=70.0, close=100.0)
        stale[-1]["t"] = "2020-01-02T05:00:00Z"
        rows = [
            self._row("SPY", False, False),
            self._row("WIN", False, False),
            self._row("LOSE", False, False),
            self._row("OLD", False, False),
        ]
        got = mr.build_market_regime(
            rows,
            {"SPY": spy, "WIN": winner, "LOSE": loser, "OLD": stale, "VIXY": winner},
        )
        hl = got["highs_lows"]
        self.assertEqual(hl["highs"], 1)
        self.assertEqual(hl["lows"], 1)
        self.assertEqual(hl["eligible"], 3)
        breadth = got["components"][1]
        # 0% sobre las medias + 10 * 1/(1+1) = 5
        self.assertAlmostEqual(breadth["points_exact"], 5.0)
        self.assertEqual(breadth["parts"]["high_low_mode"], "balance")

    def test_series_tracks_who_is_above_the_ema(self):
        up = geometric(250, 80.0, 1.002)
        flat = [50.0] * 250
        down = geometric(250, 80.0, 0.998)
        bars = {
            "SPY": bars_from_closes(up),
            "AAA": bars_from_closes(flat),
            "BBB": bars_from_closes(down),
        }
        rows = [
            self._row("SPY", True, True),
            self._row("AAA", False, False),
            self._row("BBB", False, False),
        ]
        series = mr.breadth_ema200_series(bars, ["SPY", "AAA", "BBB"])
        self.assertEqual(len(series), 42)
        self.assertEqual(series[-1]["eligible"], 3)
        self.assertEqual(series[-1]["above"], 1)
        self.assertEqual(series[-1]["pct"], 33.3)
        self.assertLess(series[0]["date"], series[-1]["date"])
        block = mr.build_market_regime(rows, bars)
        self.assertEqual(block["breadth_series"][-1]["pct"], 33.3)
        self.assertEqual(rows[0]["desk_score"], 50.0)


if __name__ == "__main__":
    unittest.main()
