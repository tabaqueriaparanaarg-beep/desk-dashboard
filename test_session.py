#!/usr/bin/env python3
"""Modo de corrida: intradía, cierre y salteo con el mercado cerrado."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import build
import historial
import market_session as ms


NY = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent


class ModeTests(unittest.TestCase):
    def test_close_cron_always_runs_the_close(self) -> None:
        for open_flag in (True, False, None):
            self.assertEqual(ms.detect_mode("schedule", ms.CLOSE_CRON, open_flag), "cierre")

    def test_intraday_cron_runs_only_when_the_clock_is_open(self) -> None:
        for cron in ms.INTRADAY_CRONS:
            self.assertEqual(ms.detect_mode("schedule", cron, True), "intradia")

    def test_intraday_cron_skips_when_the_market_is_closed(self) -> None:
        # Feriado, o el extremo de la ventana que en esta estación no es rueda.
        for cron in ms.INTRADAY_CRONS:
            self.assertEqual(ms.detect_mode("schedule", cron, False), "skip")

    def test_intraday_cron_skips_when_the_clock_cannot_be_read(self) -> None:
        self.assertEqual(ms.detect_mode("schedule", "30 13 * * 1-5", None), "skip")
        self.assertEqual(ms.detect_mode("schedule", "0 21 * * 1-5", None), "skip")

    def test_push_follows_the_clock(self) -> None:
        self.assertEqual(ms.detect_mode("push", None, True), "intradia")
        self.assertEqual(ms.detect_mode("workflow_dispatch", "", False), "cierre")

    def test_push_without_clock_uses_new_york_hours(self) -> None:
        during = datetime(2026, 10, 1, 11, 11, tzinfo=NY)
        after = datetime(2026, 10, 1, 16, 5, tzinfo=NY)
        self.assertEqual(ms.detect_mode("push", None, None, now=during), "intradia")
        self.assertEqual(ms.detect_mode("push", None, None, now=after), "cierre")

    def test_unknown_schedule_is_skipped(self) -> None:
        self.assertEqual(ms.detect_mode("schedule", "0 12 * * 1-5", True), "skip")

    def test_only_the_close_records_persistent_state(self) -> None:
        self.assertTrue(ms.records_persistent_state("cierre"))
        self.assertFalse(ms.records_persistent_state("intradia"))
        self.assertFalse(ms.records_persistent_state("skip"))


class CalendarTests(unittest.TestCase):
    def test_half_hour_crons_cover_summer_and_winter(self) -> None:
        # EDT = UTC-4 (offset 4). EST = UTC-5 (offset 5). De 9:30 a 16:00 ET.
        for offset, label in ((4, "verano"), (5, "invierno")):
            for minutes in ms.nyse_half_hours():
                hour, minute = ms.nyse_slot_utc(minutes, offset)
                self.assertTrue(
                    ms.cron_covers_utc(hour, minute),
                    f"{label} {minutes // 60:02d}:{minutes % 60:02d} ET → {hour:02d}:{minute:02d} UTC",
                )
        self.assertFalse(ms.cron_covers_utc(21, 30))
        self.assertFalse(ms.cron_covers_utc(13, 0))

    def test_banners(self) -> None:
        self.assertEqual(ms.session_banner("intradia", "2026-10-01"), ms.LIVE_BANNER)
        self.assertEqual(ms.session_banner("cierre", "2026-10-01"), "Cierre del 01/10")
        self.assertEqual(ms.session_banner("cierre", "2026-09-30"), "Cierre del 30/09")

    def test_open_session_date_is_only_today_in_new_york(self) -> None:
        during = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(ms.open_session_date("2026-10-01", during), "2026-10-01")
        self.assertIsNone(ms.open_session_date("2026-09-30", during))

    def test_regular_hours_in_both_seasons(self) -> None:
        self.assertTrue(ms.ny_session_open(datetime(2026, 7, 15, 9, 30, tzinfo=NY)))
        self.assertFalse(ms.ny_session_open(datetime(2026, 7, 15, 9, 29, tzinfo=NY)))
        self.assertFalse(ms.ny_session_open(datetime(2026, 7, 15, 16, 0, tzinfo=NY)))
        self.assertTrue(ms.ny_session_open(datetime(2026, 1, 15, 9, 30, tzinfo=NY)))
        self.assertFalse(ms.ny_session_open(datetime(2026, 1, 15, 16, 0, tzinfo=NY)))
        self.assertFalse(ms.ny_session_open(datetime(2026, 10, 3, 12, 0, tzinfo=NY)))
        summer_open = datetime(2026, 7, 15, 9, 30, tzinfo=NY).astimezone(timezone.utc)
        winter_open = datetime(2026, 1, 15, 9, 30, tzinfo=NY).astimezone(timezone.utc)
        self.assertEqual((summer_open.hour, summer_open.minute), (13, 30))
        self.assertEqual((winter_open.hour, winter_open.minute), (14, 30))


class ClockTests(unittest.TestCase):
    def test_clock_reads_v2_clock_without_putting_the_key_in_the_url(self) -> None:
        seen: list[str] = []

        def fake(url: str, headers: dict, timeout: int = 20) -> dict:
            seen.append(url)
            self.assertEqual(headers["APCA-API-KEY-ID"], "k")
            self.assertNotIn("k=", url)
            self.assertNotIn("APCA", url)
            return {"is_open": True}

        with patch.dict(os.environ, {"ALPACA_TRADING_URL": "", "ALPACA_BASE_URL": "", "APCA_API_BASE_URL": ""}):
            clock = ms.fetch_clock(
                get=fake,
                headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
            )
        self.assertTrue(clock["is_open"])
        self.assertEqual(seen, ["https://api.alpaca.markets/v2/clock"])

    def test_clock_falls_back_to_paper_on_401(self) -> None:
        seen: list[str] = []

        def fake(url: str, headers: dict, timeout: int = 20) -> dict:
            seen.append(url)
            if "paper-api" not in url:
                raise urllib.error.HTTPError(url, 401, "no", Message(), io.BytesIO(b""))
            return {"is_open": False}

        with patch.dict(os.environ, {"ALPACA_TRADING_URL": "", "ALPACA_BASE_URL": "", "APCA_API_BASE_URL": ""}):
            clock = ms.fetch_clock(
                get=fake,
                headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
            )
        self.assertFalse(ms.clock_is_open(clock))
        self.assertEqual(len(seen), 2)
        self.assertTrue(seen[1].startswith("https://paper-api.alpaca.markets/v2/clock"))

    def test_missing_keys_do_not_call_the_network(self) -> None:
        def fake(*_a, **_k):
            raise AssertionError("no hay que llamar")

        with patch.dict(os.environ, {"ALPACA_API_KEY": "", "ALPACA_SECRET_KEY": "", "APCA_API_KEY_ID": "", "APCA_API_SECRET_KEY": ""}):
            self.assertIsNone(ms.fetch_clock(get=fake, headers=None))


class BuildModeTests(unittest.TestCase):
    def test_workflow_mode_skips_the_clock(self) -> None:
        with patch.dict(os.environ, {"ANGUS_SESSION": "intradia"}):
            with patch("market_session.fetch_clock", side_effect=AssertionError("no clock")):
                self.assertEqual(build.resolve_session_mode(), "intradia")

    def test_finalize_does_not_keep_a_close_before_the_bell(self) -> None:
        during = datetime(2026, 10, 1, 11, 11, tzinfo=NY)
        after = datetime(2026, 10, 1, 16, 0, tzinfo=NY)
        self.assertEqual(build.finalize_session_mode("cierre", "2026-10-01", during), "intradia")
        self.assertEqual(build.finalize_session_mode("cierre", "2026-10-01", after), "cierre")
        self.assertEqual(build.finalize_session_mode("intradia", "2026-10-01", after), "intradia")
        # Feriado: la última barra es de ayer y ya está cerrada.
        holiday = datetime(2026, 11, 26, 12, 0, tzinfo=NY)
        self.assertEqual(build.finalize_session_mode("cierre", "2026-11-25", holiday), "cierre")

    def test_live_session_is_not_reused_as_a_walkforward_point(self) -> None:
        previous = {
            "top10_walkforward": {
                "window_end": "2026-09-30",
                "curve": [{"date": "2026-09-30", "portfolio": 100, "spy": 100}],
            }
        }
        self.assertIsNotNone(build.previous_walkforward_reusable(previous, "2026-10-01"))
        tainted = {
            "top10_walkforward": {
                "window_end": "2026-10-01",
                "curve": [{"date": "2026-10-01", "portfolio": 101, "spy": 100}],
            }
        }
        self.assertIsNone(build.previous_walkforward_reusable(tainted, "2026-10-01"))
        bars = {
            "SPY": [
                {"t": "2026-09-30T00:00:00Z", "c": 1},
                {"t": "2026-10-01T14:00:00Z", "c": 2},
            ]
        }
        trimmed = build.bars_without_session(bars, "2026-10-01")
        self.assertEqual(build.session_dates_from_bars(trimmed["SPY"]), ["2026-09-30"])

    def test_cached_earnings_do_not_need_the_network(self) -> None:
        previous = {
            "generated_at": "2026-10-01T11:11:41-03:00",
            "earnings": [
                {"symbol": "AAPL", "date": "2026-10-02"},
                {"symbol": "NOPE", "date": "2026-10-02"},
            ],
        }
        rows, notes, meta = build.cached_earnings(previous, {"AAPL"}, datetime(2026, 10, 1).date())
        self.assertEqual([r["symbol"] for r in rows], ["AAPL"])
        self.assertTrue(meta["cached"])
        self.assertTrue(meta["known"])
        self.assertTrue(any("caché" in n for n in notes))

    def test_resumen_marks_the_live_run_as_provisional(self) -> None:
        resumen = build.mark_resumen_provisional(
            {"headline": "Angus — resumen del 01/10", "sentences": ["El régimen está mixto."], "text": ""}
        )
        self.assertTrue(resumen["provisional"])
        self.assertIn("provisorio", resumen["headline"].lower())
        self.assertTrue(resumen["text"].startswith("Provisorio:"))
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "resumen.txt"
            with patch.object(build, "RESUMEN_PATH", target):
                build.write_resumen_file(resumen)
            body = target.read_text(encoding="utf-8")
        self.assertTrue(body.startswith("PROVISORIO"))


class HistoryLiveTests(unittest.TestCase):
    def test_readonly_does_not_touch_the_file_or_keep_the_partial_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "historial_semaforo.json"
            flag = Path(tmp) / ".historial_fetch_failed"
            history = historial.empty_history()
            historial.upsert_snapshot(
                history,
                historial.make_snapshot(
                    "2026-09-30",
                    [{"symbol": "AAA", "verdict": "verde", "close": 10, "desk_score": 70, "rank": 1}],
                    after_close=True,
                    reconstruido=False,
                ),
            )
            historial.upsert_snapshot(
                history,
                historial.make_snapshot(
                    "2026-10-01",
                    [{"symbol": "AAA", "verdict": "verde", "close": 11, "desk_score": 71, "rank": 1}],
                    after_close=False,
                    reconstruido=False,
                ),
            )
            loaded = historial.LoadResult(history, "local", True, False)
            self.assertTrue(historial.save_history(path, history, loaded, flag))
            before = path.read_bytes()
            report, note = historial.publish_readonly(
                meta_by={"AAA": {"kind": "us"}},
                history_path=path,
                fetch=lambda: ("failed", None),
            )
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(flag.exists())
            self.assertIn("no se escribe", note)
            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual(report["real_days"], 1)
            self.assertEqual(report["latest"]["date"], "2026-09-30")
            self.assertNotEqual(report["to"], "2026-10-01")

    def test_repo_history_has_no_open_session(self) -> None:
        data = json.loads((ROOT / "historial_semaforo.json").read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc)
        dates = []
        for snap in data.get("snapshots") or []:
            self.assertTrue(snap.get("after_close"), snap.get("date"))
            # Una foto commiteada tiene que ser de una rueda que Nueva York ya cerró.
            self.assertTrue(historial.taken_after_close(str(snap.get("date")), now), snap.get("date"))
            dates.append(snap.get("date"))
        self.assertIn("2026-09-30", dates)


class WorkflowTests(unittest.TestCase):
    def test_workflow_has_the_crons_the_clock_and_concurrency(self) -> None:
        text = (ROOT / ".github/workflows/update-and-deploy.yml").read_text(encoding="utf-8")
        self.assertIn(f'cron: "{ms.CLOSE_CRON}"', text)
        for cron in ms.INTRADAY_CRONS:
            self.assertIn(f'cron: "{cron}"', text)
        self.assertIn("concurrency:", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("market_session.py --github-output", text)
        self.assertIn("ANGUS_SESSION:", text)
        self.assertIn("steps.market.outputs.mode == 'cierre'", text)
        self.assertIn("steps.market.outputs.mode != 'skip'", text)
        js = (ROOT / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        sw = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertIn(ms.LIVE_BANNER, js)
        self.assertIn('id="session-banner"', html)
        self.assertIn('VERSION = "dd-v34"', sw)
        self.assertIn("app.js?v=34", html)
        self.assertIn("styles.css?v=34", html)
        self.assertIn("app.js?v=34", sw)
        self.assertIn("styles.css?v=34", sw)


if __name__ == "__main__":
    unittest.main()
