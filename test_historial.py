#!/usr/bin/env python3
"""Historial del semáforo: fotos, dedup, retornos, reconstrucción y persistencia."""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import build
import historial
import signals as s


def _rows(pairs: list[tuple[str, str, float]], *, score: float = 70.0) -> list[dict]:
    out = []
    for i, (sym, verdict, close) in enumerate(pairs, 1):
        out.append(
            {
                "symbol": sym,
                "verdict": verdict,
                "close": close,
                "desk_score": score,
                "rank": i,
            }
        )
    return out


def _snap(day: str, pairs: list[tuple[str, str, float]], *, after_close: bool = True, reconstruido: bool = False) -> dict:
    snap = historial.make_snapshot(day, _rows(pairs), after_close=after_close, reconstruido=reconstruido)
    assert snap is not None
    return snap


def _history(snaps: list[dict]) -> dict:
    history = historial.empty_history()
    for snap in snaps:
        historial.upsert_snapshot(history, snap)
    return history


class UpsertTests(unittest.TestCase):
    def test_one_snapshot_per_date_and_later_build_wins(self) -> None:
        history = historial.empty_history()
        historial.upsert_snapshot(
            history,
            _snap("2026-01-02", [("AAA", "verde", 10.0)], after_close=False),
        )
        historial.upsert_snapshot(
            history,
            _snap("2026-01-02", [("AAA", "ambar", 11.5)], after_close=True),
        )
        historial.upsert_snapshot(
            history,
            _snap("2026-01-05", [("AAA", "rojo", 9.0)], reconstruido=True),
        )
        self.assertEqual(sorted(history["snapshots"]), ["2026-01-02", "2026-01-05"])
        day = history["snapshots"]["2026-01-02"]
        self.assertEqual(day["rows"][0]["close"], 11.5)
        self.assertEqual(day["rows"][0]["verdict"], "ambar")
        self.assertTrue(day["after_close"])
        self.assertFalse(day["reconstruido"])
        self.assertEqual(day["earnings_check"], "publicado")
        other = history["snapshots"]["2026-01-05"]
        self.assertFalse(other["reconstruido"])
        self.assertEqual(other["earnings_check"], "publicado")
        self.assertEqual(other["rows"][0]["close"], 9.0)
        self.assertNotIn("2026-01-05", history.get("reconstructed") or {})

    def test_after_close_follows_new_york_session(self) -> None:
        session = "2026-09-30"
        ny = ZoneInfo("America/New_York")
        before = datetime(2026, 9, 30, 15, 59, tzinfo=ny)
        at_close = datetime(2026, 9, 30, 16, 0, tzinfo=ny)
        saturday = datetime(2026, 10, 3, 15, 0, tzinfo=ny)
        self.assertFalse(historial.taken_after_close(session, before))
        self.assertTrue(historial.taken_after_close(session, at_close))
        self.assertTrue(historial.taken_after_close(session, saturday))


class DedupTests(unittest.TestCase):
    def test_new_signal_only_when_color_turns_on(self) -> None:
        history = _history(
            [
                _snap("2026-03-02", [("AAA", "verde", 1), ("BBB", "verde", 1)]),
                _snap("2026-03-03", [("AAA", "verde", 1), ("BBB", "rojo", 1)]),
                _snap("2026-03-04", [("AAA", "verde", 1), ("BBB", "verde", 1)]),
            ]
        )
        primary = [(s["symbol"], s["date"]) for s in historial.iter_signals(history, "verde", dedup=True)]
        self.assertEqual(primary, [("AAA", "2026-03-02"), ("BBB", "2026-03-02"), ("BBB", "2026-03-04")])
        every_day = historial.iter_signals(history, "verde", dedup=False)
        self.assertEqual(len(every_day), 5)
        ambar = historial.iter_signals(history, "ambar", dedup=True)
        self.assertEqual(ambar, [])


class ForwardReturnTests(unittest.TestCase):
    def _seven(self) -> dict:
        aaa = [100, 110, 120, 130, 140, 150, 160]
        bbb = [100, 90, 80, 70, 60, 50, 40]
        spy = [100, 101, 102, 103, 104, 105, 106]
        days = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12"]
        snaps = []
        for i, day in enumerate(days):
            color = "verde" if i == 0 else "rojo"
            snaps.append(_snap(day, [("AAA", color, aaa[i]), ("BBB", color, bbb[i]), ("SPY", "rojo", spy[i])]))
        return _history(snaps)

    def test_closed_horizon_pending_window_and_aggregates(self) -> None:
        report = historial.build_report(self._seven(), {"AAA": {"kind": "us"}, "BBB": {"kind": "us"}, "SPY": {"kind": "etf"}})
        five = report["table"]["verde"]["5"]
        self.assertEqual(five["n"], 2)
        self.assertEqual(five["avg"], 0.0)
        self.assertEqual(five["median"], 0.0)
        self.assertEqual(five["spy_avg"], 5.0)
        self.assertEqual(five["excess"], -5.0)
        self.assertEqual(five["hit_pct"], 50.0)
        self.assertEqual(five["beat_pct"], 50.0)
        self.assertEqual(five["best"], 50.0)
        self.assertEqual(five["worst"], -50.0)
        self.assertEqual(five["universe_avg"], 0.0)
        self.assertEqual(five["excess_universe"], 0.0)
        self.assertEqual(five["beat_universe_pct"], 50.0)
        self.assertEqual(report["table"]["verde"]["10"]["n"], 0)
        self.assertEqual(report["table"]["verde"]["20"]["n"], 0)
        self.assertEqual(report["table"]["universo"]["5"]["n"], 4)
        by_sym = {row["symbol"]: row for row in report["recent"]}
        self.assertEqual(by_sym["AAA"]["status"], "en curso")
        self.assertEqual(by_sym["AAA"]["sessions"], 6)
        self.assertEqual(by_sym["AAA"]["return_pct"], 60.0)
        self.assertEqual(by_sym["BBB"]["return_pct"], -60.0)
        self.assertEqual(by_sym["AAA"]["spy_return_pct"], 6.0)
        self.assertIn("Todavía no hay señales sin alertas de riesgo", report["sentence"])
        self.assertIn("equiponderado", report["universe_benchmark"])
        self.assertIn("SPY", report["universe_benchmark"])

    def test_closed_twenty_uses_that_window_not_the_last_bar(self) -> None:
        snaps = []
        for i in range(22):
            day = f"2026-02-{i + 1:02d}"
            color = "verde" if i == 0 else "rojo"
            snaps.append(
                _snap(
                    day,
                    [
                        ("AAA", color, 100 + i),
                        ("SPY", "rojo", 200 + i),
                    ],
                )
            )
        report = historial.build_report(_history(snaps), {"AAA": {"kind": "us"}, "SPY": {"kind": "etf"}})
        twenty = report["table"]["verde"]["20"]
        self.assertEqual(twenty["n"], 1)
        self.assertEqual(twenty["avg"], 20.0)
        self.assertEqual(twenty["spy_avg"], 10.0)
        self.assertEqual(twenty["excess"], 10.0)
        self.assertEqual(twenty["universe_avg"], 20.0)
        self.assertEqual(twenty["excess_universe"], 0.0)
        recent = report["recent"][0]
        self.assertEqual(recent["status"], "cerrada")
        self.assertEqual(recent["sessions"], 20)
        self.assertEqual(recent["return_pct"], 20.0)
        self.assertNotEqual(recent["return_pct"], 21.0)
        self.assertIn("En las últimas 1 señales", report["sentence"])
        self.assertIn("SPY", report["sentence"])
        self.assertEqual(report["closed_today"], [])

        closing = []
        for i in range(22):
            day = f"2026-04-{i + 1:02d}"
            color = "verde" if i == 1 else "rojo"
            closing.append(_snap(day, [("AAA", color, 100 + i), ("SPY", "rojo", 200 + i)]))
        closed_report = historial.build_report(_history(closing), {"AAA": {"kind": "us"}, "SPY": {"kind": "etf"}})
        self.assertEqual(len(closed_report["closed_today"]), 1)
        self.assertEqual(closed_report["closed_today"][0]["symbol"], "AAA")
        sentence = historial.resumen_sentence(closed_report)
        self.assertIsNotNone(sentence)
        assert sentence is not None
        self.assertIn("Cerró la ventana de 20 ruedas", sentence)
        self.assertIn("AAA", sentence)
        self.assertIsNone(historial.resumen_sentence(report))


class BackfillTests(unittest.TestCase):
    def _market(self) -> tuple[dict, dict, str]:
        start = date(2025, 1, 2)

        def bars(px0: float, spike_from: int | None = None) -> list[dict]:
            out: list[dict] = []
            day = start
            px = px0
            while len(out) < 220:
                if day.weekday() < 5:
                    px *= 1.0015
                    close = px * (5.0 if spike_from is not None and len(out) >= spike_from else 1.0)
                    close = round(close, 4)
                    out.append(
                        {
                            "t": day.isoformat() + "T00:00:00Z",
                            "o": close,
                            "h": round(close * 1.01, 4),
                            "l": round(close * 0.99, 4),
                            "c": close,
                            "v": 1_000_000 + len(out),
                        }
                    )
                day += timedelta(days=1)
            return out

        meta = {
            "SPY": {"symbol": "SPY", "name": "SPY", "kind": "etf", "sector": "Benchmark"},
            "AAA": {"symbol": "AAA", "name": "Aaa", "kind": "us", "sector": "Technology"},
            "BBB": {"symbol": "BBB", "name": "Bbb", "kind": "us", "sector": "Financials"},
        }
        series = {
            "SPY": bars(400),
            "AAA": bars(100, spike_from=206),
            "BBB": bars(80),
        }
        session = build.bar_session_date(series["SPY"][205])
        return meta, series, session

    def test_backfill_does_not_look_ahead(self) -> None:
        meta, full, session = self._market()
        past = {sym: build.bars_through(bars, session) for sym, bars in full.items()}
        past_rows = historial.evaluate_session(meta, past, session)
        future_rows = historial.evaluate_session(meta, full, session)
        self.assertTrue(past_rows)
        self.assertEqual(
            [(r["symbol"], r["entry"]["verdict"], r["desk_score"], r["rank"], r["close"]) for r in past_rows],
            [(r["symbol"], r["entry"]["verdict"], r["desk_score"], r["rank"], r["close"]) for r in future_rows],
        )
        leaked = {sym: [dict(bar) for bar in bars] for sym, bars in past.items()}
        leaked["AAA"][-1] = dict(leaked["AAA"][-1], c=999, o=999, h=1010, l=980)
        moved = historial.evaluate_session(meta, leaked, session)
        past_aaa = next(r["close"] for r in past_rows if r["symbol"] == "AAA")
        moved_aaa = next(r["close"] for r in moved if r["symbol"] == "AAA")
        self.assertNotEqual(past_aaa, moved_aaa)
        self.assertGreater(full["AAA"][-1]["c"], past_aaa * 2)
        snaps = {s["date"]: s for s in historial.backfill_snapshots(meta, full)}
        self.assertIn(session, snaps)
        self.assertNotIn(build.bar_session_date(full["SPY"][0]), snaps)
        snap = snaps[session]
        self.assertTrue(snap["reconstruido"])
        self.assertTrue(snap["after_close"])
        self.assertEqual(snap["earnings_check"], "omitido")
        from_past = historial.snapshot_from_rows(past_rows, session, after_close=True, reconstruido=True)
        assert from_past is not None
        self.assertEqual(
            [(r["symbol"], r["verdict"], r["desk_score"], r["rank"], r["close"]) for r in snap["rows"]],
            [(r["symbol"], r["verdict"], r["desk_score"], r["rank"], r["close"]) for r in from_past["rows"]],
        )

    def test_reconstructed_earnings_check_passes_and_is_labeled(self) -> None:
        meta, full, session = self._market()
        past = {sym: build.bars_through(bars, session) for sym, bars in full.items()}
        rows = historial.evaluate_session(meta, past, session)
        earn = next(c for c in rows[0]["entry"]["checks"] if c["id"] == "earnings")
        self.assertTrue(earn["ok"])
        self.assertTrue(earn["reconstructed"])
        self.assertIn("se toma como aprobado", earn["reason"])
        direct = s.entry_verdict(
            {
                "symbol": "LLY",
                "kind": "us",
                "sector": "Health Care",
                "desk_score": 80,
                "above_ema200": True,
                "ema200": 10,
                "ema200_slope_up": True,
                "dist_ema200_pct": 1,
                "dist_sma50_pct": 1,
                "rsi14": 50,
                "rs_score": 60,
                "rs_weekly": [50, 52, 54, 56, 58, 60],
                "flags": [],
                "patterns": [{"id": "pullback_sma50"}],
            },
            sector_index={"Health Care": {"rank": 1, "n": 1, "half": 1, "trend": "up", "label": "Salud", "top_half": True}},
            earnings=[{"symbol": "LLY", "date": "2026-10-02"}],
            today=date(2026, 9, 30),
            earnings_known=True,
            earnings_backfill=True,
        )
        check = next(c for c in direct["checks"] if c["id"] == "earnings")
        self.assertTrue(check["ok"])
        self.assertEqual(direct["verdict"], "verde")
        blocked = s.entry_verdict(
            {
                "symbol": "LLY",
                "kind": "us",
                "sector": "Health Care",
                "desk_score": 80,
                "above_ema200": True,
                "ema200": 10,
                "ema200_slope_up": True,
                "dist_ema200_pct": 1,
                "dist_sma50_pct": 1,
                "rsi14": 50,
                "rs_score": 60,
                "rs_weekly": [50, 52, 54, 56, 58, 60],
                "flags": [],
                "patterns": [{"id": "pullback_sma50"}],
            },
            sector_index={"Health Care": {"rank": 1, "n": 1, "half": 1, "trend": "up", "label": "Salud", "top_half": True}},
            earnings=[{"symbol": "LLY", "date": "2026-10-02"}],
            today=date(2026, 9, 30),
            earnings_known=True,
            earnings_through=date(2026, 10, 8),
            earnings_backfill=False,
        )
        self.assertEqual(blocked["verdict"], "ambar")


class PersistenceTests(unittest.TestCase):
    def test_failed_load_does_not_overwrite_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "historial_semaforo.json"
            flag = Path(tmp) / ".historial_fetch_failed"
            path.write_text("{roto", encoding="utf-8")
            before = path.read_text(encoding="utf-8")
            public, note = historial.publish(
                rows=[{"symbol": "AAA", "asof": "2026-09-30", "close": 10, "entry": {"verdict": "verde"}}],
                meta_by={},
                all_bars={},
                now=datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc),
                history_path=path,
                flag_path=flag,
                fetch=lambda: ("failed", None),
            )
            self.assertIsNone(public)
            self.assertEqual(path.read_text(encoding="utf-8"), before)
            self.assertTrue(flag.is_file())
            self.assertIn("no se reescribió", note)

    def test_failed_fetch_falls_back_to_local_and_keeps_old_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "historial_semaforo.json"
            flag = Path(tmp) / ".historial_fetch_failed"
            history = _history(
                [
                    _snap("2026-05-01", [("AAA", "verde", 10), ("SPY", "rojo", 100)]),
                    _snap("2026-05-04", [("AAA", "rojo", 11), ("SPY", "rojo", 101)]),
                ]
            )
            history["backfill"] = {
                "done": True,
                "from": "2026-05-01",
                "to": "2026-05-04",
                "sessions": 2,
                "rules_version": historial.signals.SEMAFORO_RULES_VERSION,
            }
            loaded = historial.LoadResult(history, "nuevo", True, False)
            self.assertTrue(historial.save_history(path, history, loaded, flag))
            calls: list[int] = []

            def _boom(*_a, **_k):
                calls.append(1)
                raise AssertionError("no hay que reconstruir de nuevo")

            original = historial.backfill_snapshots
            historial.backfill_snapshots = _boom  # type: ignore[method-assign]
            try:
                public, note = historial.publish(
                    rows=[
                        {
                            "symbol": "AAA",
                            "asof": "2026-05-05T00:00:00Z",
                            "close": 12,
                            "desk_score": 66,
                            "rank": 3,
                            "entry": {"verdict": "verde"},
                        },
                        {
                            "symbol": "SPY",
                            "asof": "2026-05-05T00:00:00Z",
                            "close": 102,
                            "desk_score": 50,
                            "rank": 40,
                            "entry": {"verdict": "rojo"},
                        },
                    ],
                    meta_by={"AAA": {"kind": "us"}, "SPY": {"kind": "etf"}},
                    all_bars={},
                    now=datetime(2026, 5, 6, 18, 0, tzinfo=timezone.utc),
                    history_path=path,
                    flag_path=flag,
                    fetch=lambda: ("failed", None),
                )
            finally:
                historial.backfill_snapshots = original
            self.assertEqual(calls, [])
            self.assertIsNotNone(public)
            saved = historial.normalize(historial.json.loads(path.read_text(encoding="utf-8")))
            assert saved is not None
            self.assertEqual(sorted(saved["snapshots"]), ["2026-05-01", "2026-05-04", "2026-05-05"])
            self.assertEqual(saved["snapshots"]["2026-05-01"]["rows"][0]["close"], 10)
            self.assertFalse(saved["snapshots"]["2026-05-05"]["reconstruido"])
            self.assertTrue(saved["snapshots"]["2026-05-05"]["after_close"])
            self.assertFalse(flag.exists())
            self.assertIn("base local", note)

    def test_merge_backfill_stays_out_of_real_history(self) -> None:
        history = _history([_snap("2026-06-01", [("AAA", "verde", 5)])])
        recon = _snap("2026-06-01", [("AAA", "rojo", 99)], reconstruido=True)
        other = _snap("2026-05-28", [("AAA", "ambar", 4)], reconstruido=True)
        added = historial.apply_backfill(history, [recon, other])
        self.assertEqual(added, 1)
        self.assertEqual(list(history["snapshots"]), ["2026-06-01"])
        self.assertEqual(history["snapshots"]["2026-06-01"]["rows"][0]["close"], 5)
        self.assertFalse(history["snapshots"]["2026-06-01"]["reconstruido"])
        self.assertNotIn("2026-06-01", history["reconstructed"])
        self.assertTrue(history["reconstructed"]["2026-05-28"]["reconstruido"])
        self.assertEqual(history["reconstructed"]["2026-05-28"]["rows"][0]["close"], 4)
        self.assertTrue(history["backfill"]["done"])

    def test_normalize_splits_legacy_mixed_snapshots(self) -> None:
        raw = {
            "version": 1,
            "snapshots": [
                _snap("2026-07-01", [("AAA", "verde", 1)]),
                _snap("2026-07-02", [("BBB", "verde", 2)], reconstruido=True),
            ],
        }
        loaded = historial.normalize(raw)
        assert loaded is not None
        self.assertEqual(list(loaded["snapshots"]), ["2026-07-01"])
        self.assertEqual(list(loaded["reconstructed"]), ["2026-07-02"])
        self.assertFalse(loaded["snapshots"]["2026-07-01"]["reconstruido"])
        self.assertTrue(loaded["reconstructed"]["2026-07-02"]["reconstruido"])


def _days(n: int, start: str) -> list[str]:
    cursor = date.fromisoformat(start)
    out: list[str] = []
    while len(out) < n:
        out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


class ProvisionalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertEqual(historial.PROVISIONAL_MIN_CLOSED_SIGNALS, 10)
        self.assertEqual(historial.PROVISIONAL_PURGE_REAL_DAYS, 60)

    def _reconstructed(self) -> list[dict]:
        snaps = []
        for i, day in enumerate(_days(21, "2024-01-01")):
            color = "verde" if i == 0 else "rojo"
            snaps.append(_snap(day, [("ZZZ", color, 100 + i), ("SPY", "rojo", 100)], reconstruido=True))
        return snaps

    def _real(self, names: int, sessions: int = 6) -> list[dict]:
        snaps = []
        tickers = [f"T{i:02d}" for i in range(names)]
        for i, day in enumerate(_days(sessions, "2025-06-01")):
            pairs = [("SPY", "rojo", 100.0)]
            for ticker in tickers:
                color = "verde" if i == 0 else "rojo"
                pairs.append((ticker, color, 100.0 if i == 0 else 90.0))
            snaps.append(_snap(day, pairs))
        return snaps

    def _load(self, names: int) -> dict:
        history = historial.empty_history()
        for snap in self._real(names):
            historial.upsert_snapshot(history, snap)
        historial.apply_backfill(history, self._reconstructed())
        return history

    def test_below_ten_closed_signals_shows_only_reconstructed_metrics(self) -> None:
        report = historial.build_report(self._load(9), {})
        meta = report["horizons_meta"]["5"]
        self.assertTrue(meta["provisional"])
        self.assertEqual(meta["real_closed"], 9)
        self.assertEqual(meta["label"], "Provisorio (reconstruido)")
        self.assertIn("9 señales reales sin alertas", meta["note"])
        self.assertIn("10", meta["note"])
        self.assertEqual(report["table"]["verde"]["5"]["n"], 1)
        self.assertEqual(report["table"]["verde"]["5"]["avg"], 5.0)
        symbols = [row["symbol"] for row in report["recent"]]
        self.assertNotIn("ZZZ", symbols)
        self.assertNotIn("ZZZ", report["by_symbol"])
        self.assertTrue(any(sym.startswith("T") for sym in symbols))

    def test_ten_closed_signals_switch_that_horizon_without_mixing(self) -> None:
        report = historial.build_report(self._load(10), {})
        five = report["horizons_meta"]["5"]
        self.assertFalse(five["provisional"])
        self.assertEqual(five["real_closed"], historial.PROVISIONAL_MIN_CLOSED_SIGNALS)
        self.assertEqual(five["label"], "")
        self.assertEqual(report["table"]["verde"]["5"]["n"], 10)
        self.assertEqual(report["table"]["verde"]["5"]["avg"], -10.0)
        twenty = report["horizons_meta"]["20"]
        self.assertTrue(twenty["provisional"])
        self.assertEqual(twenty["real_closed"], 0)
        self.assertEqual(report["table"]["verde"]["20"]["avg"], 20.0)
        self.assertTrue(report["sentence"].startswith("Provisorio (reconstruido)."))
        self.assertNotIn("ZZZ", report["by_symbol"])

    def test_reconstructed_window_does_not_borrow_real_closes(self) -> None:
        history = historial.empty_history()
        for i, day in enumerate(_days(3, "2024-02-01")):
            color = "verde" if i == 0 else "rojo"
            historial.apply_backfill(
                history,
                [_snap(day, [("AAA", color, 100), ("SPY", "rojo", 100)], reconstruido=True)],
            )
        for i, day in enumerate(_days(6, "2025-08-01")):
            color = "verde" if i == 0 else "rojo"
            close = 100 if i == 0 else 200
            historial.upsert_snapshot(history, _snap(day, [("AAA", color, close), ("SPY", "rojo", 100)]))
        report = historial.build_report(history, {"AAA": {"kind": "us"}, "SPY": {"kind": "etf"}})
        self.assertTrue(report["horizons_meta"]["5"]["provisional"])
        self.assertEqual(report["horizons_meta"]["5"]["real_closed"], 1)
        self.assertEqual(report["table"]["verde"]["5"]["n"], 0)
        self.assertIn("AAA", [row["symbol"] for row in report["recent"]])

    def test_sixty_real_days_purge_reconstructed_storage_and_ui(self) -> None:
        history = historial.empty_history()
        limit = historial.PROVISIONAL_PURGE_REAL_DAYS
        for day in _days(limit - 1, "2026-01-01"):
            historial.upsert_snapshot(history, _snap(day, [("AAA", "rojo", 1), ("SPY", "rojo", 1)]))
        historial.apply_backfill(
            history,
            [_snap("2025-06-01", [("ZZZ", "verde", 10), ("SPY", "rojo", 10)], reconstruido=True)],
        )
        self.assertFalse(historial.maybe_purge_reconstructed(history))
        self.assertIn("2025-06-01", history["reconstructed"])
        historial.upsert_snapshot(history, _snap("2026-04-15", [("AAA", "rojo", 1), ("SPY", "rojo", 1)]))
        self.assertEqual(historial.real_snapshot_count(history), limit)
        hidden = historial.build_report(history, {})
        self.assertEqual(hidden["reconstructed_days"], 0)
        self.assertFalse(hidden["provisional"])
        self.assertTrue(all(not hidden["horizons_meta"][key]["provisional"] for key in ("5", "10", "20")))
        self.assertTrue(historial.maybe_purge_reconstructed(history))
        self.assertEqual(history["reconstructed"], {})
        self.assertTrue(history["backfill"]["purged"])
        self.assertTrue(history["backfill"]["done"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "historial_semaforo.json"
            flag = Path(tmp) / "flag"
            loaded = historial.LoadResult(history, "nuevo", True, False)
            self.assertTrue(historial.save_history(path, history, loaded, flag))
            raw = historial.json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("reconstructed", raw)
        self.assertEqual(len(raw["snapshots"]), limit)
        report = historial.build_report(history, {})
        self.assertEqual(report["reconstructed_days"], 0)
        self.assertEqual(report["earnings_note"], "")
        self.assertNotIn("ZZZ", report["by_symbol"])


class DefinitionSplitTests(unittest.TestCase):
    def test_missing_rules_version_loads_as_the_old_entry_light(self) -> None:
        loaded = historial.normalize(
            {
                "version": 1,
                "snapshots": [
                    {
                        "date": "2026-01-02",
                        "after_close": True,
                        "rows": [{"symbol": "AAA", "verdict": "verde", "close": 10}],
                    }
                ],
            }
        )
        assert loaded is not None
        self.assertEqual(loaded["snapshots"]["2026-01-02"]["rules_version"], 1)

    def test_old_and_new_definitions_are_not_averaged_together(self) -> None:
        old = historial.make_snapshot(
            "2026-01-02",
            _rows([("OLD", "verde", 100), ("SPY", "rojo", 100)]),
            after_close=True,
            reconstruido=False,
            rules_version=1,
        )
        new = _snap("2026-01-05", [("NEW", "verde", 20), ("SPY", "rojo", 101)])
        history = historial.empty_history()
        historial.upsert_snapshot(history, old)
        historial.upsert_snapshot(history, new)
        report = historial.build_report(
            history,
            {"OLD": {"kind": "us"}, "NEW": {"kind": "us"}, "SPY": {"kind": "etf"}},
        )
        self.assertEqual(report["rules_version"], s.SEMAFORO_RULES_VERSION)
        self.assertEqual([row["symbol"] for row in report["recent"]], ["NEW"])
        self.assertNotIn("OLD", report["by_symbol"])
        legacy = report["legacy"]
        self.assertIsNotNone(legacy)
        assert legacy is not None
        self.assertEqual(legacy["rules_version"], 1)
        self.assertIn("OLD", legacy["by_symbol"])
        self.assertNotIn("NEW", legacy["by_symbol"])
        self.assertIn("No se promedian", report["definition_note"])
        self.assertIn("alerta de riesgo", report["sentence"])


if __name__ == "__main__":
    unittest.main()
