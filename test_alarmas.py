#!/usr/bin/env python3
"""Alarmas de factores: momentum, crecimiento contra valor y crédito.

No usa API keys. Barras sintéticas.
"""
from __future__ import annotations

import unittest

import alarmas as al
from test_walkforward import make_bars, weekdays

N = 90
DATES = weekdays(N)


def series(daily: list[float], start: float = 100.0) -> list[dict]:
    px, out = start, []
    for d in daily:
        px *= d
        out.append(px)
    return make_bars(out, DATES)


def flat() -> list[dict]:
    return series([1.0005] * N)


def with_drop(last_n: int, daily: float) -> list[dict]:
    return series([1.0005] * (N - last_n) + [daily] * last_n)


def universe(**over) -> dict[str, list[dict]]:
    u = {s: flat() for s in al.EXTRA_SYMBOLS}
    u.update(over)
    return u


class AlarmTests(unittest.TestCase):
    def by_key(self, blk):
        return {a["key"]: a for a in blk["alarms"]}

    def test_all_off_in_a_calm_market(self):
        blk = al.compute_alarms(universe())
        self.assertEqual(blk["on_count"], 0)
        self.assertEqual(blk["summary"], "Ninguna alarma prendida.")
        self.assertEqual({a["key"] for a in blk["alarms"]}, {"momentum", "crecimiento", "credito"})

    def test_momentum_unwinding_turns_on_and_says_since_when(self):
        # MTUM cae ~1 % por día las últimas 4 ruedas: pierde más de 2 puntos en 5 ruedas.
        blk = al.compute_alarms(universe(MTUM=with_drop(4, 0.99)))
        mom = self.by_key(blk)["momentum"]
        self.assertTrue(mom["on"])
        self.assertLess(mom["value"], -2.0)
        self.assertIn("reduciendo momentum", mom["text"])
        self.assertIn("Índice Angus", mom["index_note"])
        self.assertLessEqual(mom["since"], DATES[-1].isoformat())
        self.assertGreaterEqual(mom["since"], DATES[-4].isoformat())
        self.assertEqual(blk["summary"], "Prendidas: el momentum se desarma.")

    def test_growth_to_value_uses_ten_sessions(self):
        blk = al.compute_alarms(universe(IWF=with_drop(8, 0.995)))
        g = self.by_key(blk)["crecimiento"]
        self.assertTrue(g["on"])
        self.assertEqual(g["lookback"], 10)
        self.assertEqual(g["index_note"], "")

    def test_credit_stress(self):
        blk = al.compute_alarms(universe(HYG=with_drop(15, 0.999)))
        self.assertTrue(self.by_key(blk)["credito"]["on"])

    def test_off_alarm_reports_last_time_it_was_on(self):
        # Cae y después se recupera: la alarma se apaga y recuerda cuándo estuvo prendida.
        daily = [1.0005] * 60 + [0.99] * 4 + [1.012] * 26
        blk = al.compute_alarms(universe(MTUM=series(daily)))
        mom = self.by_key(blk)["momentum"]
        self.assertFalse(mom["on"])
        self.assertIsNotNone(mom["last_on"])
        self.assertEqual(mom["index_note"], "")

    def test_series_is_capped(self):
        blk = al.compute_alarms(universe())
        self.assertLessEqual(len(blk["alarms"][0]["series"]), al.SERIES_SESSIONS)

    def test_missing_pair_drops_only_that_alarm(self):
        u = universe()
        del u["IWD"]
        keys = {a["key"] for a in al.compute_alarms(u)["alarms"]}
        self.assertEqual(keys, {"momentum", "credito"})

    def test_no_data_no_block(self):
        self.assertEqual(al.compute_alarms({}), {})


if __name__ == "__main__":
    unittest.main()
