#!/usr/bin/env python3
"""Matemática del RRG (JdK) y las notas de cambio de cuadrante. Sin red."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import rrg


def weekdays(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars_from_closes(closes: list[float], start: date = date(2024, 1, 2)) -> list[dict]:
    days = weekdays(len(closes), start)
    out = []
    for d, c in zip(days, closes):
        px = float(c)
        out.append({"t": d.isoformat() + "T05:00:00Z", "o": px, "h": px, "l": px, "c": px, "v": 1_000_000})
    return out


class RrgMathTests(unittest.TestCase):
    def test_constant_rs_sits_on_the_center(self):
        rs = [1.0] * 40
        ratio, momentum = rrg.rs_ratio_and_momentum(rs, 10)
        # SMA1 en la semana 9, SMA2 en la 18, momentum en la 27.
        self.assertIsNone(ratio[17])
        self.assertEqual(ratio[18], 100.0)
        self.assertIsNone(momentum[26])
        self.assertEqual(momentum[27], 100.0)
        self.assertEqual(rrg.quadrant(100.0, 100.0), "liderando")

    def test_quadrant_boundaries_use_the_center(self):
        self.assertEqual(rrg.quadrant(100.0, 100.0), "liderando")
        self.assertEqual(rrg.quadrant(100.0, 99.99), "debilitandose")
        self.assertEqual(rrg.quadrant(99.99, 100.0), "mejorando")
        self.assertEqual(rrg.quadrant(99.0, 99.0), "rezagado")
        self.assertEqual(rrg.quadrant(110.0, 110.0), "liderando")

    def test_rising_rs_leads_and_falling_rs_lags(self):
        # Una suba que se acelera deja el ratio y el momentum arriba de 100.
        # Una pendiente lineal ya madura puede caer apenas debajo de 100 en el
        # momentum (el ritmo deja de aumentar): eso es Debilitándose, no Liderando.
        rising = [1.0]
        for _ in range(50):
            rising.append(rising[-1] * 1.01)
        for _ in range(15):
            rising.append(rising[-1] * 1.08)
        ratio, momentum = rrg.rs_ratio_and_momentum(rising, 10)
        self.assertGreater(ratio[-1], 100)
        self.assertGreater(momentum[-1], 100)
        self.assertEqual(rrg.quadrant(ratio[-1], momentum[-1]), "liderando")

        falling = [2.0 - i * 0.01 for i in range(60)]
        ratio_f, mom_f = rrg.rs_ratio_and_momentum(falling, 10)
        self.assertLess(ratio_f[-1], 100)
        self.assertLess(mom_f[-1], 100)
        self.assertEqual(rrg.quadrant(ratio_f[-1], mom_f[-1]), "rezagado")

    def test_a_turn_up_while_still_behind_is_improving(self):
        # Baja largo y después un rebote corto: el momentum cruza 100 antes que el ratio.
        rs = [2.2 - i * 0.02 for i in range(45)]
        rs += [rs[-1] * (1.04 ** (i + 1)) for i in range(6)]
        ratio, momentum = rrg.rs_ratio_and_momentum(rs, 10)
        quads = [
            rrg.quadrant(r, m)
            for r, m in zip(ratio, momentum)
            if r is not None and m is not None
        ]
        self.assertIn("mejorando", quads)
        self.assertIn("rezagado", quads)

    def test_gap_in_rs_does_not_invent_a_point(self):
        rs = [1.0] * 40
        rs[30] = None
        ratio, momentum = rrg.rs_ratio_and_momentum(rs, 10)
        self.assertIsNone(ratio[30])
        self.assertIsNone(momentum[30])
        # La ventana de 10 que toca el hueco también queda vacía.
        self.assertIsNone(ratio[35])
        self.assertIsNotNone(ratio[18])


class RrgNoteTests(unittest.TestCase):
    def test_leadership_lost_after_one_week_matches_the_plain_sentence(self):
        note = rrg.quadrant_change_note(
            display="Comunicaciones",
            symbol="XLC",
            prev={"ratio": 101.0, "momentum": 102.0, "quadrant": "liderando"},
            curr={"ratio": 99.0, "momentum": 98.0, "quadrant": "rezagado"},
            weeks_ahead=1,
        )
        self.assertEqual(
            note,
            "Comunicaciones (XLC) perdió el liderazgo: volvió a quedar detrás del SPY "
            "tras 1 semana adelante.",
        )

    def test_several_weeks_ahead_uses_the_plural(self):
        note = rrg.quadrant_change_note(
            display="Tecnología",
            symbol="XLK",
            prev={"ratio": 104.0, "momentum": 101.0, "quadrant": "liderando"},
            curr={"ratio": 99.2, "momentum": 103.0, "quadrant": "mejorando"},
            weeks_ahead=3,
        )
        self.assertIn("tras 3 semanas adelante", note)
        self.assertIn("perdió el liderazgo", note)
        self.assertNotIn("compra", note.lower())

    def test_weakening_stays_ahead_of_spy(self):
        note = rrg.quadrant_change_note(
            display="Energía",
            symbol="XLE",
            prev={"ratio": 103.0, "momentum": 101.0, "quadrant": "liderando"},
            curr={"ratio": 102.0, "momentum": 99.0, "quadrant": "debilitandose"},
            weeks_ahead=4,
        )
        self.assertIn("adelante del SPY", note)
        self.assertIn("debilit", note)
        self.assertNotIn("detrás del SPY", note)

    def test_same_quadrant_has_no_note(self):
        note = rrg.quadrant_change_note(
            display="Salud",
            symbol="XLV",
            prev={"ratio": 101.0, "momentum": 101.0, "quadrant": "liderando"},
            curr={"ratio": 102.0, "momentum": 101.5, "quadrant": "liderando"},
            weeks_ahead=2,
        )
        self.assertIsNone(note)


class RrgBuildTests(unittest.TestCase):
    def test_spy_is_the_benchmark_and_sectors_are_grouped(self):
        n = 220
        spy = [100.0 * (1.001 ** i) for i in range(n)]
        xlk = [100.0 * (1.003 ** i) for i in range(n)]
        aapl = [50.0 * (1.0005 ** i) for i in range(n)]
        bars = {
            "SPY": bars_from_closes(spy),
            "XLK": bars_from_closes(xlk),
            "AAPL": bars_from_closes(aapl),
        }
        meta = {
            "SPY": {"name": "SPDR S&P 500 ETF", "kind": "etf", "sector": "Benchmark"},
            "XLK": {"name": "Technology Select Sector", "kind": "etf", "sector": "Technology"},
            "AAPL": {"name": "Apple", "kind": "us", "sector": "Technology"},
        }
        block = rrg.build_rrg(bars, meta)
        symbols = [s["symbol"] for s in block["series"]]
        self.assertNotIn("SPY", symbols)
        self.assertIn("XLK", symbols)
        self.assertIn("AAPL", symbols)
        xlk_row = next(s for s in block["series"] if s["symbol"] == "XLK")
        self.assertEqual(xlk_row["group"], "sector")
        self.assertEqual(xlk_row["display"], "Tecnología")
        aapl_row = next(s for s in block["series"] if s["symbol"] == "AAPL")
        self.assertEqual(aapl_row["group"], "stock")
        self.assertGreaterEqual(len(block["dates"]), 2)
        self.assertLessEqual(len(block["dates"]), rrg.PLOT_WEEKS)
        last = next(p for p in reversed(xlk_row["points"]) if p)
        self.assertIn(last["quadrant"], rrg.QUADRANT_LABELS)
        self.assertGreater(last["ratio"], 100)
        self.assertIn("SPY", block["definition"])
        self.assertIn("100", block["definition"])
        self.assertEqual(block["tail"], rrg.TAIL_WEEKS)
        self.assertEqual(block["center"], 100)

    def test_leadership_loss_is_counted_from_the_trail(self):
        points = [
            {"date": "2026-01-02", "ratio": 99.0, "momentum": 99.0, "quadrant": "rezagado"},
            {"date": "2026-01-09", "ratio": 101.5, "momentum": 102.0, "quadrant": "liderando"},
            {"date": "2026-01-16", "ratio": 98.0, "momentum": 97.0, "quadrant": "rezagado"},
        ]
        self.assertEqual(rrg._weeks_ahead(points, 1), 1)
        note = rrg.quadrant_change_note(
            display="Comunicaciones",
            symbol="XLC",
            prev=points[1],
            curr=points[2],
            weeks_ahead=rrg._weeks_ahead(points, 1),
        )
        self.assertIn("tras 1 semana adelante", note)

    def test_without_enough_history_the_chart_stays_empty(self):
        short = bars_from_closes([100.0 + i for i in range(15)])
        block = rrg.build_rrg({"SPY": short, "XLK": short}, {"XLK": {"kind": "etf", "sector": "Technology"}})
        self.assertEqual(block["series"], [])
        self.assertTrue(block["notes"])
        self.assertIn("historia", block["notes"][0].lower())

    def test_no_etf_change_uses_the_quiet_sentence(self):
        n = 220
        flat = [100.0] * n
        # Misma pendiente: el ratio se queda en 100 y no cambia de cuadrante.
        bars = {
            "SPY": bars_from_closes(flat),
            "XLK": bars_from_closes(flat),
        }
        meta = {"XLK": {"name": "Technology Select Sector", "kind": "etf", "sector": "Technology"}}
        block = rrg.build_rrg(bars, meta)
        self.assertEqual(
            block["notes"],
            ["Esta semana ningún ETF de sector cambió de cuadrante respecto del SPY."],
        )
        self.assertTrue(block["notes_by_date"])
        self.assertTrue(all(not week for week in block["notes_by_date"]))


if __name__ == "__main__":
    unittest.main()
