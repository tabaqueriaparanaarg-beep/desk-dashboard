#!/usr/bin/env python3
"""Semáforo de entrada y recomendaciones de analistas. Sin red ni claves."""
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

import build
import signals as s


TODAY = date(2026, 9, 30)
# Semana del calendario de Angus: lunes 28/09 → domingo 04/10. No cubre 7 días.
THROUGH = date(2026, 10, 4)


def _sectors():
    # Orden ya rankeado por Desk medio, como lo escribe build.compute_sector_view.
    names = [
        ("Health Care", "Salud", "up"),
        ("Technology", "Tecnología", "up"),
        ("Energy", "Energía", "down"),
        ("Communication", "Comunicación", "up"),
        ("Financials", "Finanzas", "down"),
        ("Industrials", "Industria", "up"),
        ("Materials", "Materiales", "up"),
        ("Consumer Staples", "Consumo básico", "flat"),
        ("Consumer Discretionary", "Consumo discrecional", "up"),
        ("Utilities", "Servicios", "down"),
    ]
    return {
        "rs_trend_weeks": 4,
        "rs_flat_band": 1.0,
        "rows": [{"sector": k, "label": lab, "rs_trend": tr} for k, lab, tr in names],
    }


def _row(**overrides):
    base = {
        "symbol": "LLY",
        "name": "Eli Lilly",
        "kind": "us",
        "sector": "Health Care",
        "desk_score": 84.2,
        "rank": 2,
        "above_ema200": True,
        "ema200": 200.0,
        "ema200_slope_up": True,
        "dist_ema200_pct": 10.6,
        "dist_sma50_pct": 0.6,
        "rsi14": 56.1,
        "rs_score": 70.0,
        "rs_weekly": [40, 45, 50, 55, 60, 70],
        "flags": [],
        "patterns": [{"id": "pullback_sma50", "label": "Pullback SMA50", "detail": ""}],
    }
    base.update(overrides)
    return base


def _verdict(row, earnings=None, *, known=True, through=THROUGH, today=TODAY):
    return s.entry_verdict(
        row,
        earnings=earnings or [],
        today=today,
        earnings_known=known,
        earnings_through=through if known else None,
    )


class EntryVerdictTests(unittest.TestCase):
    def test_all_critical_checks_are_green_and_do_not_touch_the_score(self):
        row = _row()
        score, rank = row["desk_score"], row["rank"]
        out = _verdict(row)
        self.assertEqual(out["verdict"], "verde")
        self.assertEqual(out["label"], "Verde: sin alertas de riesgo")
        self.assertEqual(out["disclaimer"], s.ENTRY_DISCLAIMER)
        self.assertEqual(out["rules_version"], s.SEMAFORO_RULES_VERSION)
        self.assertTrue(all(c["ok"] for c in out["checks"]))
        self.assertEqual(row["desk_score"], score)
        self.assertEqual(row["rank"], rank)
        ids = [c["id"] for c in out["checks"]]
        self.assertEqual(ids, ["trend", "bearish_cross", "earnings"])

    def test_trend_failure_is_red_even_if_the_rest_passes(self):
        out = _verdict(_row(above_ema200=False, ema200_slope_up=True))
        self.assertEqual(out["verdict"], "rojo")
        self.assertEqual(out["label"], "Rojo: alerta de riesgo")
        trend = next(c for c in out["checks"] if c["id"] == "trend")
        self.assertFalse(trend["ok"])
        self.assertTrue(trend["hard"])
        self.assertIn("bajo la EMA200", trend["reason"])

    def test_falling_ema_slope_is_red(self):
        out = _verdict(_row(ema200_slope_up=False))
        self.assertEqual(out["verdict"], "rojo")
        trend = next(c for c in out["checks"] if c["id"] == "trend")
        self.assertIn("pendiente en baja", trend["reason"])

    def test_bearish_cross_forces_red_even_when_the_trend_gate_passes(self):
        out = _verdict(
            _row(patterns=[{"id": "pullback_sma50"}, {"id": "ema200_cross_down"}])
        )
        self.assertEqual(out["verdict"], "rojo")
        bear = next(c for c in out["checks"] if c["id"] == "bearish_cross")
        self.assertFalse(bear["ok"])
        self.assertTrue(bear["hard"])
        self.assertIn("Cruce bajista", bear["reason"])

    def test_score_pattern_and_extension_do_not_change_the_light(self):
        out = _verdict(
            _row(
                desk_score=12.0,
                patterns=[],
                dist_ema200_pct=40.0,
                dist_sma50_pct=30.0,
                rsi14=90.0,
                flags=["atr_elevado", "rsi_sobrecompra"],
                sector="Utilities",
            )
        )
        self.assertEqual(out["verdict"], "verde")
        self.assertEqual(out["label"], "Verde: sin alertas de riesgo")
        ids = [c["id"] for c in out["checks"]]
        self.assertNotIn("extension", ids)
        self.assertNotIn("score", ids)
        self.assertNotIn("sector", ids)
        self.assertNotIn("flags", ids)

    def test_earnings_inside_seven_days_blocks_green_with_the_date(self):
        out = _verdict(
            _row(symbol="NKE"),
            earnings=[{"symbol": "NKE", "date": "2026-10-01", "hour": "AMC"}],
        )
        self.assertEqual(out["verdict"], "ambar")
        self.assertEqual(out["label"], "Ámbar: resultados cerca")
        earn = next(c for c in out["checks"] if c["id"] == "earnings")
        self.assertFalse(earn["ok"])
        self.assertEqual(earn["reason"], "Presenta resultados el 01/10")

    def test_past_earnings_do_not_block_and_limited_coverage_is_stated(self):
        out = _verdict(
            _row(symbol="MU"),
            earnings=[{"symbol": "MU", "date": "2026-09-29"}],
        )
        earn = next(c for c in out["checks"] if c["id"] == "earnings")
        self.assertTrue(earn["ok"])
        self.assertIn("calendario", earn["reason"])
        self.assertIn("04/10", earn["reason"])
        self.assertIn("no cubre", earn["reason"])

    def test_unknown_earnings_calendar_passes_but_says_coverage_is_limited(self):
        out = _verdict(_row(), known=False)
        earn = next(c for c in out["checks"] if c["id"] == "earnings")
        self.assertTrue(earn["ok"])
        self.assertIn("cobertura de earnings es limitada", earn["reason"])

    def test_full_seven_day_coverage_has_a_clean_reason(self):
        out = _verdict(_row(), through=date(2026, 10, 7))
        earn = next(c for c in out["checks"] if c["id"] == "earnings")
        self.assertTrue(earn["ok"])
        self.assertEqual(earn["reason"], "Sin resultados en los próximos 7 días")

    def test_etf_uses_the_same_risk_checks(self):
        out = _verdict(
            _row(symbol="XLF", kind="etf", sector="Financials", rs_score=30, rs_weekly=[80, 70, 60, 50, 40, 20])
        )
        self.assertEqual(out["verdict"], "verde")
        self.assertEqual([c["id"] for c in out["checks"]], ["trend", "bearish_cross", "earnings"])

    def test_attach_keeps_ranking_order(self):
        rows = [
            _row(symbol="ZZ", rank=2, desk_score=70),
            _row(symbol="AA", rank=1, desk_score=90, above_ema200=False),
        ]
        order = [r["symbol"] for r in rows]
        scores = [r["desk_score"] for r in rows]
        s.attach_entry_lights(
            rows,
            _sectors(),
            [],
            today=TODAY,
            earnings_known=True,
            earnings_through=THROUGH,
        )
        self.assertEqual([r["symbol"] for r in rows], order)
        self.assertEqual([r["desk_score"] for r in rows], scores)
        self.assertEqual(rows[0]["entry"]["verdict"], "verde")
        self.assertEqual(rows[1]["entry"]["verdict"], "rojo")


class AnalystTests(unittest.TestCase):
    def test_latest_buy_pct_and_three_month_trend(self):
        raw = [
            {"period": "2026-06-01", "strongBuy": 8, "buy": 10, "hold": 6, "sell": 1, "strongSell": 0},
            {"period": "2026-09-01", "strongBuy": 12, "buy": 16, "hold": 4, "sell": 1, "strongSell": 0},
            {"period": "2026-08-01", "strongBuy": 11, "buy": 14, "hold": 5, "sell": 1, "strongSell": 0},
            {"period": "2026-07-01", "strongBuy": 9, "buy": 12, "hold": 5, "sell": 1, "strongSell": 0},
            {"period": "2026-05-01", "strongBuy": 4, "buy": 4, "hold": 4, "sell": 2, "strongSell": 1},
            {"period": "2026-04-01", "strongBuy": 1, "buy": 1, "hold": 1, "sell": 1, "strongSell": 1},
        ]
        out = s.parse_recommendations(raw, fetched_on=TODAY)
        self.assertEqual(out["latest"]["period"], "2026-09-01")
        self.assertEqual(out["latest"]["buy_count"], 28)
        self.assertEqual(out["latest"]["total"], 33)
        self.assertEqual(out["buy_pct"], round(28 / 33 * 100, 1))
        self.assertEqual(len(out["history"]), 5)
        self.assertNotIn("2026-04-01", [p["period"] for p in out["history"]])
        self.assertEqual(out["trend"], "up")
        self.assertEqual(out["compare_period"], "2026-06-01")
        self.assertIn("Más compras que hace 3 meses (28 contra 18)", out["trend_label"])
        self.assertIsNone(out["price_target"])
        self.assertIn("no señal", out["note"])

    def test_fewer_buys_and_missing_history(self):
        raw = [
            {"period": "2026-09-01", "strongBuy": 2, "buy": 3, "hold": 8, "sell": 2, "strongSell": 1},
            {"period": "2026-08-01", "strongBuy": 9, "buy": 9, "hold": 2, "sell": 0, "strongSell": 0},
        ]
        out = s.parse_recommendations(raw, fetched_on=TODAY)
        self.assertIsNone(out["trend"])
        self.assertIn("Sin historia de hace 3 meses", out["trend_label"])
        down = s.parse_recommendations(
            [
                {"period": "2026-09-01", "strongBuy": 2, "buy": 2, "hold": 1, "sell": 0, "strongSell": 0},
                {"period": "2026-06-01", "strongBuy": 6, "buy": 6, "hold": 1, "sell": 0, "strongSell": 0},
            ],
            fetched_on=TODAY,
        )
        self.assertEqual(down["trend"], "down")
        self.assertIn("Menos compras", down["trend_label"])

    def test_price_target_keeps_only_positive_numbers(self):
        self.assertIsNone(s.parse_price_target(None))
        self.assertIsNone(s.parse_price_target({"error": "You don't have access to this resource."}))
        self.assertIsNone(
            s.parse_price_target(
                {"targetHigh": 0, "targetLow": 0, "targetMean": 0, "targetMedian": None}
            )
        )
        parsed = s.parse_price_target(
            {
                "targetHigh": 220.5,
                "targetLow": 0,
                "targetMean": 198.25,
                "targetMedian": -4,
                "lastUpdated": "2026-09-15",
            }
        )
        self.assertEqual(parsed["mean"], 198.25)
        self.assertEqual(parsed["high"], 220.5)
        self.assertIsNone(parsed["low"])
        self.assertIsNone(parsed["median"])
        self.assertEqual(parsed["last_updated"], "2026-09-15")

    def test_analyst_cache_age_is_seven_days(self):
        today = date(2026, 9, 29)
        prev = {
            "AAA": {"analysts": {"fetched_on": "2026-09-22"}},
            "BBB": {"analysts": {"fetched_on": "2026-09-23"}},
        }
        plan, _budget = build._plan_slow_fetches(["AAA", "BBB"], prev, today)
        self.assertIn(("AAA", "analysts"), plan)
        self.assertNotIn(("BBB", "analysts"), plan)
        self.assertEqual(build.ANALYST_MAX_AGE_DAYS, 7)


class PriceTargetGateTests(unittest.TestCase):
    def test_access_error_skips_the_endpoint_for_the_rest_of_the_run(self):
        calls: list[str] = []

        def fake(path, params, key, pacer):
            calls.append(path)
            if path == "stock/price-target":
                raise build.FinnhubAccessError()
            return []

        pacer = build._FinnhubPacer(0)
        with mock.patch.object(build, "_finnhub_get", side_effect=fake):
            gate = build._PriceTargetGate()
            self.assertIsNone(gate.fetch("AAPL", "k", pacer))
            self.assertIsNone(gate.fetch("MSFT", "k", pacer))
        self.assertEqual(calls, ["stock/price-target"])
        self.assertEqual(gate.state, "off")

    def test_a_working_target_is_kept_and_not_invented(self):
        def fake(path, params, key, pacer):
            return {"targetMean": 150.5, "targetHigh": 0, "targetLow": None, "targetMedian": 140}

        pacer = build._FinnhubPacer(0)
        with mock.patch.object(build, "_finnhub_get", side_effect=fake):
            parsed = build._PriceTargetGate().fetch("AAPL", "k", pacer)
        self.assertEqual(parsed["mean"], 150.5)
        self.assertEqual(parsed["median"], 140)
        self.assertIsNone(parsed["high"])


class EntryResumenTests(unittest.TestCase):
    def test_green_count_sentence_lists_stocks_and_skips_etfs(self):
        payload = {
            "generated_at": "2026-09-30T18:40:00-03:00",
            "regime": {"label": "mixto"},
            "ranking": [
                {"symbol": "SPY", "kind": "etf", "rank": 1, "entry": {"verdict": "verde"}, "change_pct": 0.1},
                {"symbol": "LLY", "kind": "us", "rank": 2, "entry": {"verdict": "verde"}},
                {"symbol": "NKE", "kind": "us", "rank": 8, "entry": {"verdict": "ambar"}},
                {"symbol": "XOM", "kind": "us", "rank": 12, "entry": {"verdict": "verde"}},
                {"symbol": "ITUB", "kind": "cedear_proxy", "rank": 20, "entry": {"verdict": "verde"}},
            ],
            "sectors": {"rows": []},
            "earnings": [],
        }
        snap = s.snapshot_from_payload(payload)
        self.assertTrue(snap["entry_known"])
        self.assertEqual(snap["entry_green"], ["LLY", "XOM", "ITUB"])
        text = s.compose_resumen(snap, None)["text"]
        self.assertIn("Hoy hay 3 acciones sin alertas de riesgo: LLY, XOM y ITUB.", text)
        many = dict(snap)
        many["entry_green"] = ["LLY", "MA", "ABBV", "V", "DIS", "ITUB", "JNJ", "XOM", "CVX"]
        many_text = s.compose_resumen(many, None)["text"]
        self.assertIn("Hoy hay 9 acciones sin alertas de riesgo: LLY, MA, ABBV, V y 5 más.", many_text)
        self.assertNotIn("y V y", many_text)
        self.assertNotIn("SPY", text.split("riesgo")[1][:40])

    def test_old_payload_does_not_invent_a_green_count(self):
        snap = s.snapshot_from_payload(
            {
                "generated_at": "2026-09-25T10:00:00-03:00",
                "regime": {"label": "alcista"},
                "ranking": [{"symbol": "AAPL", "rank": 1, "kind": "us", "above_ema200": True}],
            }
        )
        self.assertFalse(snap["entry_known"])
        text = s.compose_resumen(snap, None)["text"]
        self.assertNotIn("sin alertas de riesgo", text)

    def test_no_greens_is_stated(self):
        snap = s.snapshot_from_payload(
            {
                "generated_at": "2026-09-30T18:40:00-03:00",
                "regime": {"label": "bajista"},
                "ranking": [
                    {"symbol": "BA", "kind": "us", "rank": 4, "entry": {"verdict": "rojo"}},
                ],
            }
        )
        text = s.compose_resumen(snap, None)["text"]
        self.assertIn("Hoy no hay acciones sin alertas de riesgo.", text)


if __name__ == "__main__":
    unittest.main()
