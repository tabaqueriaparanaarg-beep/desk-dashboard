#!/usr/bin/env python3
"""Atribución del exceso del Top 10 vs SPY. Matemática pura, sin API keys."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import build as b


def stock(symbol: str, sector: str, kind: str = "us", desk: float = 80.0) -> dict:
    return {
        "symbol": symbol,
        "name": symbol,
        "kind": kind,
        "sector": sector,
        "desk_score": desk,
    }


def top_row(rank: int, symbol: str, ret: float, desk: float = 80.0) -> dict:
    return {"rank": rank, "symbol": symbol, "desk_score": desk, "return_pct": ret, "spark": [1, 2]}


def block(rows: list[dict], avg: float | None, spy: float | None, window: int = 10) -> dict:
    return {
        "window_sessions": window,
        "asof": "2026-09-25T04:00:00Z",
        "avg_return_pct": avg,
        "spy_return_pct": spy,
        "rows": rows,
    }


def weekdays(n: int, start: date = date(2026, 9, 1)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars_for_return(ret_pct: float, n: int = 11) -> list[dict]:
    """11 cierres cuyo retorno de 10 ruedas es `ret_pct`."""
    start = 100.0
    end = start * (1.0 + ret_pct / 100.0)
    closes = [start] * (n - 1) + [end]
    bars = []
    for d, c in zip(weekdays(n), closes):
        px = float(c)
        bars.append({"t": d.isoformat() + "T05:00:00Z", "o": px, "h": px, "l": px, "c": px, "v": 1})
    return bars


def cents(values: list[float]) -> int:
    return int(round(sum(values) * 100.0))


class AttributionMathTests(unittest.TestCase):
    def test_ticker_contributions_sum_to_published_excess(self):
        ranking = [
            stock("AAA", "Technology"),
            stock("BBB", "Technology"),
            stock("CCC", "Financials"),
        ]
        rows = [top_row(1, "AAA", 10), top_row(2, "BBB", 0), top_row(3, "CCC", -1)]
        got = b.compute_top10_attribution(ranking, block(rows, avg=3, spy=1), {})
        self.assertEqual(got["excess_pct"], 2.0)
        self.assertEqual(got["n"], 3)
        self.assertEqual([t["weight_pct"] for t in got["tickers"]], [33.3, 33.3, 33.3])
        total = sum(t["contribution_pct"] for t in got["tickers"])
        self.assertEqual(cents([total]), cents([got["excess_pct"]]))
        by = {t["symbol"]: t["contribution_pct"] for t in got["tickers"]}
        # (10-1)/3 = 3, (0-1)/3 = -0.333, (-1-1)/3 = -0.666 → centésimas 300, -33, -67 = 200.
        self.assertEqual(by["AAA"], 3.0)
        self.assertEqual(by["BBB"], -0.33)
        self.assertEqual(by["CCC"], -0.67)

    def test_spy_inside_top10_contributes_zero(self):
        ranking = [
            stock("AAA", "Technology"),
            stock("SPY", "Benchmark", kind="etf"),
        ]
        rows = [top_row(1, "SPY", 2), top_row(2, "AAA", 10)]
        got = b.compute_top10_attribution(
            ranking,
            block(rows, avg=6, spy=2),
            {"XLK": bars_for_return(10)},
        )
        by = {t["symbol"]: t for t in got["tickers"]}
        self.assertEqual(by["SPY"]["contribution_pct"], 0.0)
        self.assertEqual(by["AAA"]["contribution_pct"], 4.0)
        self.assertEqual(cents([t["contribution_pct"] for t in got["tickers"]]), cents([got["excess_pct"]]))
        index = next(s for s in got["sectors"] if s["proxy_kind"] == "indice")
        self.assertEqual(index["allocation_pct"], 0.0)
        self.assertEqual(index["label"], "Índice")

    def test_brinson_allocation_and_residual_selection(self):
        # Universo: 2 Tecnología + 3 Finanzas. Top: las dos de Tecnología.
        # XLK +4, XLF 0, SPY +2. Exceso +6.
        # A_tech = (1-0.4)*(4-2) = 1.2; A_fin = (0-0.6)*(0-2) = 1.2; sector 2.4; selección 3.6.
        ranking = [
            stock("T1", "Technology"),
            stock("T2", "Technology"),
            stock("F1", "Financials"),
            stock("F2", "Financials"),
            stock("F3", "Financials"),
            stock("XLK", "Technology", kind="etf"),
            stock("SPY", "Benchmark", kind="etf"),
        ]
        rows = [top_row(1, "T1", 10), top_row(2, "T2", 6)]
        got = b.compute_top10_attribution(
            ranking,
            block(rows, avg=8, spy=2),
            {"XLK": bars_for_return(4), "XLF": bars_for_return(0)},
        )
        self.assertEqual(got["excess_pct"], 6.0)
        self.assertEqual(got["allocation_pct"], 2.4)
        self.assertEqual(got["selection_pct"], 3.6)
        self.assertAlmostEqual(got["allocation_pct"] + got["selection_pct"], got["excess_pct"], places=2)
        sectors = {s["sector"]: s for s in got["sectors"]}
        self.assertEqual(sectors["Technology"]["proxy"], "XLK")
        self.assertEqual(sectors["Technology"]["proxy_kind"], "etf")
        self.assertEqual(sectors["Technology"]["weight_benchmark_pct"], 40.0)
        self.assertEqual(sectors["Technology"]["weight_top10_pct"], 100.0)
        self.assertEqual(sectors["Technology"]["n_benchmark"], 2)
        allocs = [s["allocation_pct"] for s in got["sectors"] if s["allocation_pct"] is not None]
        self.assertEqual(cents(allocs), cents([got["allocation_pct"]]))
        self.assertEqual(got["headline"], "El exceso vino sobre todo de selección.")
        self.assertIn("universo equiponderado", got["que_mide"])
        self.assertIn("no es una señal de compra", got["que_mide"].lower())

    def test_headline_cargado_en_tecnologia(self):
        ranking = [
            stock("T1", "Technology"),
            stock("T2", "Technology"),
            stock("F1", "Financials"),
            stock("F2", "Financials"),
            stock("F3", "Financials"),
        ]
        rows = [top_row(1, "T1", 8), top_row(2, "T2", 8)]
        got = b.compute_top10_attribution(
            ranking,
            block(rows, avg=8, spy=2),
            {"XLK": bars_for_return(8), "XLF": bars_for_return(2)},
        )
        # A_tech = 0.6*(8-2) = 3.6; A_fin = 0; selección = 6-3.6 = 2.4.
        self.assertEqual(got["allocation_pct"], 3.6)
        self.assertEqual(got["selection_pct"], 2.4)
        self.assertEqual(got["headline"], "El exceso vino sobre todo de estar cargado en Tecnología.")

    def test_headline_liviano_en_energia(self):
        # 2 Tecnología y 8 Energía. El Top 10 es solo Tecnología.
        ranking = [stock("TA", "Technology"), stock("TB", "Technology")]
        ranking += [stock(f"E{i}", "Energy") for i in range(8)]
        rows = [top_row(1, "TA", 14), top_row(2, "TB", 14)]
        got = b.compute_top10_attribution(
            ranking,
            block(rows, avg=14, spy=2),
            {"XLK": bars_for_return(4), "XLE": bars_for_return(-8)},
        )
        # A_energy = (0-0.8)*(-8-2) = 8; A_tech = (1-0.2)*(4-2) = 1.6; sector 9.6.
        # Exceso 12, selección 12-9.6 = 2.4. El sector manda y el peso en Energía es 0.
        self.assertEqual(got["excess_pct"], 12.0)
        self.assertEqual(got["allocation_pct"], 9.6)
        self.assertEqual(got["selection_pct"], 2.4)
        self.assertEqual(got["headline"], "El exceso vino sobre todo de estar liviano en Energía.")

    def test_headline_diferencia_en_contra_por_seleccion(self):
        ranking = [stock("AAA", "Health Care"), stock("BBB", "Health Care")]
        rows = [top_row(1, "AAA", 0)]
        got = b.compute_top10_attribution(
            ranking,
            block(rows, avg=0, spy=2),
            {"XLV": bars_for_return(0)},
        )
        self.assertEqual(got["excess_pct"], -2.0)
        self.assertEqual(got["allocation_pct"], 0.0)
        self.assertEqual(got["headline"], "La diferencia en contra vino sobre todo de selección.")

    def test_headline_diferencia_en_contra_cargado(self):
        ranking = [stock("T1", "Technology"), stock("T2", "Technology")]
        ranking += [stock(f"F{i}", "Financials") for i in range(8)]
        rows = [top_row(1, "T1", -4), top_row(2, "T2", -4)]
        got = b.compute_top10_attribution(
            ranking,
            block(rows, avg=-4, spy=0),
            {"XLK": bars_for_return(-10), "XLF": bars_for_return(0)},
        )
        # w_b tech 0.2. A_tech = 0.8*(-10-0) = -8. Selección = -4-(-8) = 4.
        self.assertEqual(got["allocation_pct"], -8.0)
        self.assertEqual(got["selection_pct"], 4.0)
        self.assertEqual(
            got["headline"],
            "La diferencia en contra vino sobre todo de estar cargado en Tecnología.",
        )

    def test_headline_when_sector_and_selection_offset(self):
        ranking = [stock("TA", "Technology"), stock("TB", "Technology")]
        ranking += [stock(f"E{i}", "Energy") for i in range(8)]
        rows = [top_row(1, "TA", 4), top_row(2, "TB", 4)]
        got = b.compute_top10_attribution(
            ranking,
            block(rows, avg=4, spy=2),
            {"XLK": bars_for_return(4), "XLE": bars_for_return(-8)},
        )
        self.assertEqual(got["allocation_pct"], 9.6)
        self.assertEqual(got["selection_pct"], -7.6)
        self.assertEqual(
            got["headline"],
            "El exceso es chico: estar liviano en Energía sumó, y la selección lo compensó.",
        )

    def test_headline_tie_and_flat(self):
        ranking = [
            stock("T1", "Technology"),
            stock("T2", "Technology"),
            stock("F1", "Financials"),
            stock("F2", "Financials"),
        ]
        rows = [top_row(1, "T1", 4), top_row(2, "T2", 4)]
        got = b.compute_top10_attribution(
            ranking,
            block(rows, avg=4, spy=2),
            {"XLK": bars_for_return(4), "XLF": bars_for_return(2)},
        )
        self.assertEqual(got["allocation_pct"], 1.0)
        self.assertEqual(got["selection_pct"], 1.0)
        self.assertEqual(got["headline"], "El exceso se reparte entre el efecto sector y la selección.")

        flat = b.compute_top10_attribution(
            ranking,
            block([top_row(1, "T1", 2.05)], avg=2.05, spy=2.0),
            {"XLK": bars_for_return(2)},
        )
        self.assertEqual(flat["headline"], "En estas ruedas el Top 10 quedó casi empatado con el SPY.")

    def test_etf_proxy_beats_universe_average(self):
        ranking = [stock("E1", "Energy"), stock("E2", "Energy"), stock("XLE", "Energy", kind="etf")]
        rows = [top_row(1, "E1", 10)]
        got = b.compute_top10_attribution(
            ranking,
            block(rows, avg=10, spy=0),
            {
                "XLE": bars_for_return(-8),
                "E1": bars_for_return(10),
                "E2": bars_for_return(10),
            },
        )
        energy = next(s for s in got["sectors"] if s["sector"] == "Energy")
        self.assertEqual(energy["proxy"], "XLE")
        self.assertEqual(energy["proxy_kind"], "etf")
        self.assertEqual(energy["sector_return_pct"], -8.0)
        # El ETF del universo no entra en el peso de referencia.
        self.assertEqual(energy["n_benchmark"], 2)
        self.assertEqual(energy["weight_benchmark_pct"], 100.0)

    def test_universe_mean_when_sector_etf_missing(self):
        ranking = [
            stock("G1", "Communication"),
            stock("G2", "Communication"),
            stock("G3", "Communication"),
        ]
        rows = [top_row(1, "G1", -10)]
        got = b.compute_top10_attribution(
            ranking,
            block(rows, avg=-10, spy=0),
            {"G2": bars_for_return(-6), "G3": bars_for_return(-8)},
        )
        comm = next(s for s in got["sectors"] if s["sector"] == "Communication")
        self.assertEqual(comm["proxy_kind"], "universo")
        self.assertIsNone(comm["proxy"])
        self.assertEqual(comm["proxy_n"], 3)
        # G1 usa el retorno publicado del Top 10 (-10); G2 -6; G3 -8. Media -8.
        self.assertEqual(comm["sector_return_pct"], -8.0)
        self.assertFalse(got["partial"])

    def test_partial_when_sector_return_missing(self):
        # El nombre del Top 10 es un ETF que no está en el mapa (no hay XLB)
        # y la única acción del sector no tiene barras: no hay retorno de sector.
        ranking = [
            stock("XLB", "Materials", kind="etf"),
            stock("BBB", "Materials"),
        ]
        rows = [top_row(1, "XLB", 5)]
        got = b.compute_top10_attribution(ranking, block(rows, avg=5, spy=1), {})
        self.assertTrue(got["partial"])
        self.assertIn("Materiales", got["partial_note"])
        self.assertEqual(got["allocation_pct"] + got["selection_pct"], got["excess_pct"])
        self.assertEqual(got["excess_pct"], 4.0)

    def test_empty_and_missing_spy_do_not_crash(self):
        empty = b.compute_top10_attribution([], None, None)
        self.assertEqual(empty["tickers"], [])
        self.assertIsNone(empty["excess_pct"])
        self.assertIn("Sin retorno", empty["headline"])

        ranking = [stock("AAA", "Technology", desk=70)]
        missing = b.compute_top10_attribution(
            ranking,
            block([top_row(1, "AAA", 3, desk=70)], avg=3, spy=None),
            {},
        )
        self.assertIsNone(missing["excess_pct"])
        self.assertEqual(missing["tickers"][0]["contribution_pct"], None)
        self.assertEqual(ranking[0]["desk_score"], 70)

    def test_does_not_mutate_desk_score(self):
        ranking = [stock("AAA", "Technology", desk=86.9), stock("BBB", "Financials", desk=10)]
        before = [dict(r) for r in ranking]
        b.compute_top10_attribution(
            ranking,
            block([top_row(1, "AAA", 1)], avg=1, spy=0),
            {"XLK": bars_for_return(1)},
        )
        self.assertEqual(ranking, before)
        self.assertIn("0.30*Tendencia", b.DESK_SCORE_FORMULA)
        self.assertIn("no hay pesos del SPY", b.TOP10_ATTRIBUTION_FORMULA)
        self.assertIn("efecto_selección = exceso − efecto_sector", b.TOP10_ATTRIBUTION_FORMULA)
        self.assertEqual(b.SECTOR_ETF["Technology"], "XLK")
        self.assertNotIn("Communication", b.SECTOR_ETF)

    def test_penny_adjustment_lands_on_largest_contribution(self):
        ranking = [stock("A", "Technology"), stock("B", "Financials"), stock("C", "Energy")]
        rows = [top_row(1, "A", 1), top_row(2, "B", 1), top_row(3, "C", 1)]
        got = b.compute_top10_attribution(ranking, block(rows, avg=1, spy=0), {})
        contribs = [t["contribution_pct"] for t in got["tickers"]]
        self.assertEqual(contribs, [0.34, 0.33, 0.33])
        self.assertEqual(cents(contribs), cents([got["excess_pct"]]))


if __name__ == "__main__":
    unittest.main()
