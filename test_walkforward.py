#!/usr/bin/env python3
"""Walk-forward del Top 10 vs SPY: sin look-ahead y con la matemática del rebalanceo.

No usa API keys. Las barras son sintéticas.
"""
from __future__ import annotations

import copy
import unittest
from datetime import date, timedelta

import build as b


def weekdays(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def make_bars(closes: list[float], dates: list[date], volume: float = 1_000_000) -> list[dict]:
    bars = []
    for d, c in zip(dates, closes):
        px = float(c)
        bars.append(
            {
                "t": d.isoformat() + "T05:00:00Z",
                "o": px,
                "h": px * 1.004,
                "l": px * 0.996,
                "c": px,
                "v": volume,
            }
        )
    return bars


def geometric(n: int, start: float, daily: float) -> list[float]:
    px = float(start)
    out = []
    for _ in range(n):
        px *= daily
        out.append(px)
    return out


def universe(n_names: int, sessions: int, drifts: list[float] | None = None):
    dates = weekdays(sessions)
    drifts = drifts or [1.0002 + i * 0.00005 for i in range(n_names)]
    bars_by = {"SPY": make_bars(geometric(sessions, 100, 1.0003), dates)}
    meta = {"SPY": {"symbol": "SPY", "name": "SPY", "kind": "etf"}}
    for i in range(n_names):
        sym = f"S{i:02d}"
        meta[sym] = {"symbol": sym, "name": sym, "kind": "us"}
        bars_by[sym] = make_bars(geometric(sessions, 40 + i, drifts[i]), dates)
    return meta, bars_by, dates


class ScheduleMathTests(unittest.TestCase):
    def test_equal_weight_rebalance_compounds_from_the_entry_book(self):
        dates = ["2026-01-02", "2026-01-09", "2026-01-16"]
        # El libro del 2/1 gana la primera semana. El del 9/1 gana la segunda.
        # El 16/1 solo marca el valor: no hay un tercer retorno.
        holdings = {
            "2026-01-02": ["AAA", "BBB"],
            "2026-01-09": ["AAA", "CCC"],
            "2026-01-16": ["ZZZ"],
        }
        closes = {
            "AAA": {"2026-01-02": 100.0, "2026-01-09": 110.0, "2026-01-16": 121.0},
            "BBB": {"2026-01-02": 50.0, "2026-01-09": 40.0, "2026-01-16": 40.0},
            "CCC": {"2026-01-02": 10.0, "2026-01-09": 10.0, "2026-01-16": 12.0},
            "ZZZ": {"2026-01-02": 1.0, "2026-01-09": 1.0, "2026-01-16": 5.0},
            "SPY": {"2026-01-02": 400.0, "2026-01-09": 404.0, "2026-01-16": 396.0},
        }
        got = b.walkforward_from_schedule(
            dates, holdings, closes, warmup_sessions=200, target_weeks=26, recent=6
        )
        # Semana 1: AAA +10%, BBB −20% → −5%. No es el libro AAA+CCC (+5%).
        self.assertAlmostEqual(got["periods"][0]["portfolio_return"], -5.0)
        self.assertEqual(got["periods"][0]["symbols"], ["AAA", "BBB"])
        self.assertIsNone(got["periods"][0]["names_changed"])
        # Semana 2: AAA +10%, CCC +20% → +15%. ZZZ no participa.
        self.assertAlmostEqual(got["periods"][1]["portfolio_return"], 15.0)
        self.assertEqual(got["periods"][1]["names_changed"], 1)  # salió BBB
        self.assertEqual(got["weeks"], 2)
        self.assertAlmostEqual(got["total_return_pct"], 9.25)
        self.assertAlmostEqual(got["spy_total_return_pct"], -1.0)
        self.assertAlmostEqual(got["excess_return_pct"], 10.25)
        self.assertEqual(got["weeks_beat_spy"], 1)
        self.assertAlmostEqual(got["weeks_beat_spy_pct"], 50.0)
        self.assertAlmostEqual(got["max_drawdown_pct"], -5.0)
        self.assertAlmostEqual(got["spy_max_drawdown_pct"], round((99 / 101 - 1) * 100, 2))
        self.assertAlmostEqual(got["avg_names_changed"], 1.0)
        self.assertEqual([p["portfolio"] for p in got["curve"]], [100, 95, 109.25])
        self.assertEqual([p["spy"] for p in got["curve"]], [100, 101, 99])
        self.assertEqual([s["date"] for s in got["signals"]], ["2026-01-02", "2026-01-09"])
        self.assertNotIn("ZZZ", got["signals"][0]["symbols"] + got["signals"][1]["symbols"])

        pub = b.walkforward_public(got)
        self.assertNotIn("signals", pub)
        self.assertNotIn("periods", pub)
        self.assertEqual(pub["recent"][-1]["date"], "2026-01-16")
        self.assertEqual(pub["recent"][-1]["names_changed"], 1)
        self.assertEqual(pub["base"], 100)

    def test_tie_with_spy_does_not_count_as_a_win(self):
        dates = ["2026-01-02", "2026-01-09"]
        holdings = {"2026-01-02": ["AAA"]}
        closes = {
            "AAA": {"2026-01-02": 10.0, "2026-01-09": 11.0},
            "SPY": {"2026-01-02": 10.0, "2026-01-09": 11.0},
        }
        got = b.walkforward_from_schedule(dates, holdings, closes, recent=6)
        self.assertEqual(got["weeks"], 1)
        self.assertEqual(got["weeks_beat_spy"], 0)
        self.assertIsNone(got["avg_names_changed"])
        self.assertAlmostEqual(got["excess_return_pct"], 0.0)
        self.assertAlmostEqual(got["max_drawdown_pct"], 0.0)

    def test_missing_exit_close_drops_the_name_and_renormalizes(self):
        closes = {
            "AAA": {"d0": 10.0, "d1": 12.0},  # +20%
            "BBB": {"d0": 10.0, "d1": 8.0},  # −20%
            "CCC": {"d0": 10.0},  # sin cierre de salida
        }
        ret = b.equal_weight_return(["AAA", "BBB", "CCC"], closes, "d0", "d1")
        self.assertAlmostEqual(ret, 0.0)  # media de dos, no de tres
        self.assertIsNone(b.equal_weight_return(["CCC"], closes, "d0", "d1"))

        got = b.walkforward_from_schedule(
            ["d0", "d1"],
            {"d0": ["CCC"]},
            {"CCC": {"d0": 10.0}, "SPY": {"d0": 100.0, "d1": 110.0}},
            recent=6,
        )
        # Sin ningún cierre de salida la cartera queda plana y SPY sí se mueve.
        self.assertAlmostEqual(got["periods"][0]["portfolio_return"], 0.0)
        self.assertAlmostEqual(got["periods"][0]["spy_return"], 10.0)
        self.assertEqual(got["weeks_beat_spy"], 0)

    def test_spy_total_is_buy_and_hold_between_the_same_marks(self):
        dates = ["2026-03-06", "2026-03-13", "2026-03-20", "2026-03-27"]
        holdings = {d: ["AAA"] for d in dates}
        spy = {"2026-03-06": 200.0, "2026-03-13": 210.0, "2026-03-20": 205.0, "2026-03-27": 220.0}
        closes = {"AAA": {d: 10.0 for d in dates}, "SPY": spy}
        got = b.walkforward_from_schedule(dates, holdings, closes, recent=2)
        raw = (220.0 / 200.0 - 1.0) * 100.0
        self.assertAlmostEqual(got["spy_total_return_pct"], round(raw, 2))
        self.assertEqual(len(got["recent"]), 2)
        self.assertEqual(got["recent"][0]["date"], "2026-03-20")


class CalendarTests(unittest.TestCase):
    def test_rebalance_is_the_last_session_of_the_iso_week(self):
        # Semana del 5/1/2026 (lunes) completa, y la siguiente corta el jueves 15
        # (sin viernes): el rebalanceo cae el jueves.
        days = []
        d = date(2026, 1, 5)
        while d <= date(2026, 1, 15):
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(days=1)
        marks = b.eligible_weekly_dates([x.isoformat() for x in days], warmup=1, weeks=1)
        self.assertEqual(marks, ["2026-01-09", "2026-01-15"])
        self.assertEqual(date(2026, 1, 15).weekday(), 3)  # jueves

    def test_warmup_drops_weeks_before_ema200_exists(self):
        dates = [d.isoformat() for d in weekdays(40)]
        marks = b.eligible_weekly_dates(dates, warmup=20, weeks=50)
        self.assertGreaterEqual(len(marks), 2)
        for d in marks:
            self.assertGreaterEqual(dates.index(d), 19)

    def test_window_is_capped_at_the_requested_weeks(self):
        dates = [d.isoformat() for d in weekdays(80)]
        marks = b.eligible_weekly_dates(dates, warmup=5, weeks=4)
        self.assertEqual(len(marks), 5)  # 4 semanas medidas + el cierre final
        self.assertEqual(marks[-1], b.weekly_close_dates(dates, weeks=1)[-1])

    def test_ranking_window_drops_bars_before_the_floor(self):
        dates = weekdays(8)
        bars = make_bars([float(i + 1) for i in range(8)], dates)
        floor = dates[3].isoformat()
        sliced = b.ranking_window_bars(bars, floor)
        self.assertEqual([b.bar_session_date(x) for x in sliced], [d.isoformat() for d in dates[3:]])
        self.assertEqual(b.ranking_window_bars(bars, dates[0].isoformat()), bars)
        self.assertEqual(b.ranking_window_bars(bars, "2099-01-01"), [])


class ScoringWalkforwardTests(unittest.TestCase):
    def test_top10_is_the_existing_ranker_truncated_at_that_close(self):
        meta, bars_by, dates = universe(12, 80)
        session = dates[-1].isoformat()
        got = b.top10_symbols_asof(meta, bars_by, session, top_n=10)
        ranked = b.rank_universe_asof(meta, bars_by, session, require_exact_session=True)
        self.assertEqual(got, [r["symbol"] for r in ranked[:10]])

    def test_symbol_without_a_bar_that_day_is_not_bought(self):
        meta, bars_by, dates = universe(12, 80)
        last = dates[-1].isoformat()
        bars_by["S00"] = bars_by["S00"][:-1]
        strict = b.rank_universe_asof(meta, bars_by, last, require_exact_session=True)
        loose = b.rank_universe_asof(meta, bars_by, last, require_exact_session=False)
        self.assertNotIn("S00", [r["symbol"] for r in strict])
        self.assertIn("S00", [r["symbol"] for r in loose])

    def test_default_warmup_needs_two_hundred_spy_sessions(self):
        meta, bars_by, dates = universe(10, 199)
        empty = b.compute_top10_walkforward(meta, bars_by)
        self.assertEqual(empty["weeks"], 0)
        self.assertEqual(empty["curve"], [])
        self.assertIn("simulación", empty["note"].lower())

        meta2, bars2, dates2 = universe(10, 220)
        got = b.compute_top10_walkforward(meta2, bars2, weeks=26)
        self.assertGreaterEqual(got["weeks"], 1)
        spy_dates = [d.isoformat() for d in dates2]
        for sig in got["signals"]:
            self.assertGreaterEqual(spy_dates.index(sig["date"]), b.WALKFORWARD_WARMUP_SESSIONS - 1)
        # El retorno de SPY es comprar y mantener entre el primer y el último cierre.
        closes = b.close_by_session(bars2)["SPY"]
        raw = (closes[got["window_end"]] / closes[got["window_start"]] - 1.0) * 100.0
        self.assertAlmostEqual(got["spy_total_return_pct"], round(raw, 2))
        # Cada semana usa el libro del cierre de entrada, no el del cierre de salida.
        for period in got["periods"]:
            ret = b.equal_weight_return(period["symbols"], b.close_by_session(bars2), period["start"], period["end"])
            self.assertIsNotNone(ret)
            self.assertAlmostEqual(period["portfolio_return"], ret * 100.0)

    def test_future_prices_do_not_change_the_book_already_chosen(self):
        meta, bars_by, dates = universe(14, 100)
        base = b.compute_top10_walkforward(meta, bars_by, warmup_sessions=60, weeks=4)
        self.assertGreaterEqual(base["weeks"], 2)
        cutoff = base["signals"][0]["date"]
        held = base["signals"][0]["symbols"][0]
        self.assertTrue(held)

        alt_bars = copy.deepcopy(bars_by)
        for bar in alt_bars[held]:
            if b.bar_session_date(bar) > cutoff:
                for k in ("o", "h", "l", "c"):
                    bar[k] = float(bar[k]) * 0.5

        alt = b.compute_top10_walkforward(meta, alt_bars, warmup_sessions=60, weeks=4)

        # El libro elegido en el corte no ve los precios posteriores.
        self.assertEqual(base["signals"][0]["symbols"], alt["signals"][0]["symbols"])
        base_rank = b.rank_universe_asof(meta, bars_by, cutoff, require_exact_session=True)
        alt_rank = b.rank_universe_asof(meta, alt_bars, cutoff, require_exact_session=True)
        self.assertEqual(
            [(r["symbol"], r["desk_score"]) for r in base_rank],
            [(r["symbol"], r["desk_score"]) for r in alt_rank],
        )
        # Esos mismos precios sí mueven el resultado de la semana que empieza en el corte,
        # porque el libro ya estaba comprado y el camino posterior es el que se realiza.
        self.assertNotEqual(
            round(base["periods"][0]["portfolio_return"], 4),
            round(alt["periods"][0]["portfolio_return"], 4),
        )
        # Y un cierre posterior al corte cambia el score de ese nombre.
        later = base["signals"][-1]["date"]
        self.assertGreater(later, cutoff)
        later_base = {
            r["symbol"]: r["desk_score"]
            for r in b.rank_universe_asof(meta, bars_by, later, require_exact_session=True)
        }
        later_alt = {
            r["symbol"]: r["desk_score"]
            for r in b.rank_universe_asof(meta, alt_bars, later, require_exact_session=True)
        }
        self.assertNotEqual(later_base[held], later_alt[held])

    def test_every_signal_falls_on_the_last_session_of_its_week(self):
        meta, bars_by, dates = universe(10, 220)
        got = b.compute_top10_walkforward(meta, bars_by, weeks=6)
        sessions = {d.isoformat() for d in dates}
        marks = [got["window_start"], *[p["end"] for p in got["periods"]]]
        for d in marks:
            iso = date.fromisoformat(d).isocalendar()[:2]
            later = [
                s
                for s in sessions
                if s > d and date.fromisoformat(s).isocalendar()[:2] == iso
            ]
            self.assertEqual(later, [])


if __name__ == "__main__":
    unittest.main()
