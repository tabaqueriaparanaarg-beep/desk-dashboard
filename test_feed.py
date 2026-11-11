#!/usr/bin/env python3
"""Feed de Alpaca: recorte del fin para SIP (plan gratis, 15 min de demora) y respaldo IEX.

No usa API keys ni red: el pedido HTTP se reemplaza.
"""
from __future__ import annotations

import io
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from unittest import mock

import build as b

NOW = datetime(2026, 11, 10, 21, 30, tzinfo=timezone.utc)


class AlpacaEndTests(unittest.TestCase):
    def test_sip_end_in_the_last_15_minutes_is_clamped(self):
        self.assertEqual(b.alpaca_end("2026-11-10T23:59:59Z", "sip", NOW), "2026-11-10T21:14:00Z")

    def test_sip_end_in_the_past_is_untouched(self):
        self.assertEqual(b.alpaca_end("2026-11-09T23:59:59Z", "sip", NOW), "2026-11-09T23:59:59Z")
        self.assertEqual(b.alpaca_end("2026-11-09", "sip", NOW), "2026-11-09")

    def test_date_only_means_the_whole_new_york_day(self):
        # Alpaca responde 403 a end=2026-11-10 hasta que termina ese día en Nueva York.
        self.assertEqual(b.alpaca_end("2026-11-10", "sip", NOW), "2026-11-10T21:14:00Z")
        late = NOW.replace(day=11, hour=0, minute=36)
        self.assertEqual(b.alpaca_end("2026-11-10", "sip", late), "2026-11-11T00:20:00Z")
        after = NOW.replace(day=11, hour=5, minute=30)
        self.assertEqual(b.alpaca_end("2026-11-10", "sip", after), "2026-11-10")

    def test_date_only_in_the_future_is_clamped(self):
        self.assertEqual(b.alpaca_end("2026-11-11", "sip", NOW), "2026-11-10T21:14:00Z")

    def test_iex_is_never_clamped(self):
        self.assertEqual(b.alpaca_end("2026-11-10T23:59:59Z", "iex", NOW), "2026-11-10T23:59:59Z")


def _http_403(url: str) -> urllib.error.HTTPError:
    body = io.BytesIO(b'{"message":"subscription does not permit querying recent SIP data"}')
    return urllib.error.HTTPError(url, 403, "Forbidden", {}, body)


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self._feed = b.ALPACA_FEED
        self.addCleanup(setattr, b, "ALPACA_FEED", self._feed)
        self.feeds: list[str] = []

    def _fake_get(self, deny_sip: bool):
        def get(url, headers=None, timeout=60):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            feed = q["feed"][0]
            self.feeds.append(feed)
            if deny_sip and feed == "sip":
                raise _http_403(url)
            return {"bars": {"SPY": [{"t": "2026-11-10T05:00:00Z", "c": 1.0}]}}
        return get

    def _fetch(self, deny_sip: bool):
        with mock.patch.object(b, "http_get_json", side_effect=self._fake_get(deny_sip)), \
             mock.patch.object(b, "alpaca_headers", return_value={}), \
             mock.patch("builtins.print"):
            return b.fetch_bars_batch(["SPY"], "2026-11-01T00:00:00Z", "2026-11-10T23:59:59Z")

    def test_sip_403_falls_back_to_iex_for_the_rest_of_the_run(self):
        b.ALPACA_FEED = "sip"
        got = self._fetch(deny_sip=True)
        self.assertEqual(got["SPY"][0]["c"], 1.0)
        self.assertEqual(b.ALPACA_FEED, "iex")
        self._fetch(deny_sip=True)
        self.assertEqual(self.feeds, ["sip", "iex", "iex"])

    def test_sip_allowed_stays_on_sip(self):
        b.ALPACA_FEED = "sip"
        self._fetch(deny_sip=False)
        self.assertEqual(b.ALPACA_FEED, "sip")
        self.assertEqual(self.feeds, ["sip"])

    def test_other_errors_are_not_swallowed(self):
        b.ALPACA_FEED = "sip"

        def boom(url, headers=None, timeout=60):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b"{}"))

        with mock.patch.object(b, "http_get_json", side_effect=boom), \
             mock.patch.object(b, "alpaca_headers", return_value={}):
            with self.assertRaises(urllib.error.HTTPError):
                b.fetch_bars_batch(["SPY"], "2026-11-01", "2026-11-10")
        self.assertEqual(b.ALPACA_FEED, "sip")


if __name__ == "__main__":
    unittest.main()
