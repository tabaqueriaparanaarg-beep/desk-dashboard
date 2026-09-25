#!/usr/bin/env python3
"""Racha «Entró» del Top 10: membresía sintética y barras mock (sin API keys)."""
from __future__ import annotations

import time
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


def score_full(meta_by: dict, bars_by: dict) -> list[dict]:
    spy = [float(x["c"]) for x in bars_by["SPY"]]
    rows = []
    for sym, bars in bars_by.items():
        row = b.compute_symbol(meta_by[sym], bars, spy, {})
        if row:
            rows.append(row)
    return b.apply_cross_section_scores(rows)


class MembershipTests(unittest.TestCase):
    def test_label_current_streak_and_singular(self):
        membership = [
            ("2026-09-10", ["AAA", "BBB"]),
            ("2026-09-11", ["BBB", "CCC"]),
            ("2026-09-12", ["CCC", "BBB"]),
            ("2026-09-15", ["CCC", "DDD"]),
        ]
        got = b.streaks_from_membership(membership)
        self.assertEqual(list(got), ["CCC", "DDD"])
        self.assertEqual(got["CCC"]["label"], "11/09 · 3 ruedas")
        self.assertFalse(got["CCC"]["censored"])
        self.assertEqual(got["CCC"]["date"], "2026-09-11")
        self.assertEqual(got["CCC"]["sessions"], 3)
        self.assertEqual(got["DDD"]["label"], "15/09 · 1 rueda")
        self.assertEqual(got["DDD"]["sessions"], 1)
        self.assertNotIn("BBB", got)
        self.assertNotIn("AAA", got)

    def test_reentry_counts_only_the_latest_streak(self):
        membership = [
            ("2026-09-01", ["AAA", "BBB"]),
            ("2026-09-02", ["BBB", "CCC"]),
            ("2026-09-03", ["AAA", "BBB"]),
            ("2026-09-04", ["AAA", "CCC"]),
        ]
        got = b.streaks_from_membership(membership)
        self.assertEqual(got["AAA"]["date"], "2026-09-03")
        self.assertEqual(got["AAA"]["sessions"], 2)
        self.assertEqual(got["AAA"]["label"], "03/09 · 2 ruedas")

    def test_full_window_is_censored(self):
        days = [f"2026-09-{d:02d}" for d in range(1, 6)]
        membership = [(d, ["KEEP", "OTHER"]) for d in days]
        got = b.streaks_from_membership(membership)
        self.assertTrue(got["KEEP"]["censored"])
        self.assertIsNone(got["KEEP"]["date"])
        self.assertEqual(got["KEEP"]["earliest_seen"], "2026-09-01")
        self.assertEqual(got["KEEP"]["sessions"], 5)
        self.assertEqual(got["KEEP"]["label"], "antes del 01/09 · >5 ruedas")

    def test_empty(self):
        self.assertEqual(b.streaks_from_membership([]), {})


class BarWindowTests(unittest.TestCase):
    def test_bars_through_truncates_on_session_date(self):
        dates = weekdays(5)
        bars = make_bars([10, 11, 12, 13, 14], dates)
        self.assertEqual(len(b.bars_through(bars, dates[2].isoformat())), 3)
        self.assertEqual(b.bars_through(bars, dates[-1].isoformat()), bars)
        self.assertEqual(b.bars_through(bars, "2020-01-01"), [])
        self.assertEqual(b.session_dates_from_bars(bars), [d.isoformat() for d in dates])

    def test_last_session_matches_full_series_ranking(self):
        n = 220
        dates = weekdays(n)
        bars_by = {"SPY": make_bars(geometric(n, 100, 1.0004), dates)}
        meta = {"SPY": {"symbol": "SPY", "name": "SPY", "kind": "etf"}}
        for i in range(12):
            sym = f"S{i:02d}"
            meta[sym] = {"symbol": sym, "name": sym, "kind": "us"}
            bars_by[sym] = make_bars(geometric(n, 50 + i, 1.0002 + i * 0.00015), dates)
        full = score_full(meta, bars_by)
        asof = b.rank_universe_asof(meta, bars_by, dates[-1].isoformat())
        self.assertEqual([r["symbol"] for r in asof], [r["symbol"] for r in full])
        for a, f in zip(asof, full):
            self.assertEqual(a["desk_score"], f["desk_score"])
            self.assertEqual(a["rs_score"], f["rs_score"])


class SyntheticMarketTests(unittest.TestCase):
    def _market(self, n: int = 240):
        dates = weekdays(n)
        bars_by = {"SPY": make_bars(geometric(n, 100, 1.00035), dates)}
        meta = {"SPY": {"symbol": "SPY", "name": "SPY", "kind": "etf"}}
        for i in range(14):
            sym = f"S{i:02d}"
            meta[sym] = {"symbol": sym, "name": sym, "kind": "us"}
            bars_by[sym] = make_bars(geometric(n, 40 + i, 1.00015 + i * 0.00012), dates)
        return dates, meta, bars_by

    def test_stable_leaders_are_censored(self):
        dates, meta, bars_by = self._market()
        rows = score_full(meta, bars_by)
        lookback = 15
        entry = b.compute_top10_entry(meta, bars_by, lookback, today_rows=rows)
        self.assertEqual(entry["sessions_evaluated"], lookback)
        self.assertEqual(entry["window_end"], dates[-1].isoformat())
        self.assertEqual(entry["window_start"], dates[-lookback].isoformat())
        top = [r["symbol"] for r in rows[:10]]
        self.assertEqual(list(entry["by_symbol"]), top)
        for sym in top:
            info = entry["by_symbol"][sym]
            self.assertTrue(info["censored"], msg=f"{sym} {info}")
            self.assertIn(">15 ruedas", info["label"])
            self.assertTrue(info["label"].startswith("antes del "))
        # El 11º no está en la racha publicada.
        self.assertNotIn(rows[10]["symbol"], entry["by_symbol"])
        # Recomputar el último día sin anclar today_rows da el mismo Top 10.
        recomputed = b.rank_universe_asof(meta, bars_by, dates[-1].isoformat())
        self.assertEqual([r["symbol"] for r in recomputed[:10]], top)

    def test_late_entrant_streak_is_shorter_than_the_window(self):
        dates, meta, bars_by = self._market()
        n = len(dates)
        # S00 es el más débil. Una suba moderada al final lo mete al Top 10
        # sin disparar el penalty de extensión (dist EMA200 se queda < 25).
        base = geometric(n, 40, 1.00015)
        ramp_at = n - 18
        late = list(base)
        for i in range(ramp_at, n):
            late[i] = late[i - 1] * 1.006
        bars_by["S00"] = make_bars(late, dates)
        # S13 (líder) se desarma en las últimas ruedas y sale del Top 10.
        leader = geometric(n, 40 + 13, 1.00015 + 13 * 0.00012)
        for i in range(n - 6, n):
            leader[i] = leader[i - 1] * 0.94
        bars_by["S13"] = make_bars(leader, dates)

        rows = score_full(meta, bars_by)
        top = [r["symbol"] for r in rows[:10]]
        self.assertIn("S00", top, msg=f"S00 no entró al Top 10: {top}")
        self.assertNotIn("S13", top, msg=f"S13 sigue en el Top 10: {top}")

        lookback = 20
        entry = b.compute_top10_entry(meta, bars_by, lookback, today_rows=rows)
        info = entry["by_symbol"]["S00"]
        self.assertFalse(info["censored"])
        self.assertGreaterEqual(info["sessions"], 1)
        self.assertLess(info["sessions"], lookback)
        self.assertRegex(info["label"], r"^\d{2}/\d{2} · \d+ ruedas?$")

        # La membresía recomputada día por día coincide con la racha.
        membership = []
        for d in dates[-lookback:]:
            ranked = b.rank_universe_asof(meta, bars_by, d.isoformat())
            membership.append((d.isoformat(), [r["symbol"] for r in ranked[:10]]))
        # El ancla de hoy es el ranking publicado; tiene que coincidir con el recálculo.
        self.assertEqual(membership[-1][1], top)
        walked = b.streaks_from_membership(membership)
        self.assertEqual(walked["S00"], info)

        # Alguien que estaba y salió no lleva `entro` en el ranking publicado.
        b.attach_entro(rows, {"rows": [{"symbol": s} for s in top]}, entry["by_symbol"])
        by_sym = {r["symbol"]: r.get("entro") for r in rows}
        self.assertIsNone(by_sym["S13"])
        self.assertEqual(by_sym["S00"]["label"], info["label"])

    def test_published_top10_anchors_the_last_session(self):
        dates, meta, bars_by = self._market(n=200)
        rows = score_full(meta, bars_by)
        outsider = rows[12]["symbol"]
        published = [dict(r) for r in rows]
        # Forzar un nombre que el modelo no tiene en el Top 10 como si la UI lo mostrara.
        published[9] = dict(published[9], symbol=outsider, desk_score=99)
        entry = b.compute_top10_entry(meta, bars_by, 10, today_rows=published)
        self.assertIn(outsider, entry["by_symbol"])
        self.assertEqual(entry["by_symbol"][outsider]["sessions"], 1)
        self.assertFalse(entry["by_symbol"][outsider]["censored"])
        self.assertEqual(entry["by_symbol"][outsider]["date"], dates[-1].isoformat())

    def test_copy_entro_from_ranking(self):
        ranking = [
            {"symbol": "AAA", "entro": {"label": "12/09 · 9 ruedas"}},
            {"symbol": "BBB", "entro": None},
        ]
        top10 = {"rows": [{"symbol": "AAA"}, {"symbol": "BBB"}, {"symbol": "CCC"}]}
        b.copy_entro_from_ranking(ranking, top10)
        self.assertEqual(top10["rows"][0]["entro"]["label"], "12/09 · 9 ruedas")
        self.assertIsNone(top10["rows"][1]["entro"])
        self.assertIsNone(top10["rows"][2]["entro"])

    def test_replay_stays_fast_on_a_full_universe(self):
        n = 250
        dates = weekdays(n)
        bars_by = {"SPY": make_bars(geometric(n, 100, 1.0003), dates)}
        meta = {"SPY": {"symbol": "SPY"}}
        for i in range(72):
            sym = f"T{i:02d}"
            meta[sym] = {"symbol": sym}
            bars_by[sym] = make_bars(geometric(n, 20 + (i % 17), 1.0001 + (i % 11) * 0.00005), dates)
        rows = score_full(meta, bars_by)
        t0 = time.perf_counter()
        entry = b.compute_top10_entry(meta, bars_by, 30, today_rows=rows)
        elapsed = time.perf_counter() - t0
        self.assertEqual(entry["sessions_evaluated"], 30)
        self.assertEqual(len(entry["by_symbol"]), 10)
        self.assertLess(elapsed, 12.0, msg=f"replay tardó {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
