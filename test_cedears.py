"""Tests de actualizar_cedears.py (sin red ni pypdf: el texto es el que saca pypdf)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import actualizar_cedears as A

# Así sale el texto de pypdf para una tabla con el formato del listado de BYMA:
# una celda por línea (Nombre, Código BYMA, Mercado donde cotiza, Ratio).
PDF_TEXT = """Nombre de la Compañía
Código BYMA
Mercado donde Cotiza
Ratio (*)
Apple Inc.
AAPL
NASDAQ
20:1
Ambev S.A.
ABEV3
B3
1:1
Adidas AG
ADS
XETRA
22:1
ARK INNOVATION
ARKK
NYSE Arca
10:1
CrowdStrike Holdings, Inc.
CRWD
NASDAQ GS
79:1
Berkshire Hathaway Inc.
BRKB
NYSE
22:1
Bank Of America Corporation
BA.C
NYSE
4:1
XPENG INC
XPEV
New York
4:1
Pjsc Tatneft
ATAD
LONDON STOCK EXCHANGE
4:1
SERVICENOW INC
NOW
NYSE
172:1
Actualizado 16/09/2026
"""

# Y así, con la tabla en una línea por fila separada por « | » (pdf.js).
PIPE_TEXT = """Apple Inc. | AAPL | NASDAQ | 20:1
ABBV | NYSE | 10:1
AbbVie Inc.
Ambev S.A. | ABEV3 | B3 | 1:1
Palo Alto Networks Inc | PANW | NASDAQ GS | 50:1
"""


class ParseTests(unittest.TestCase):
    def test_only_us_markets_one_cell_per_line(self):
        self.assertEqual(
            A.parse_codes(PDF_TEXT),
            {"AAPL", "ARKK", "CRWD", "BRKB", "BA.C", "XPEV", "NOW"},
        )

    def test_pipe_separated_rows(self):
        self.assertEqual(A.parse_codes(PIPE_TEXT), {"AAPL", "ABBV", "PANW"})

    def test_listing_date(self):
        self.assertEqual(A.listing_date(PDF_TEXT), "2026-09-16")
        self.assertIsNone(A.listing_date("sin fecha"))

    def test_byma_codes_map_to_us_tickers(self):
        self.assertEqual(
            A.us_tickers({"BRKB", "BA.C", "DISN", "AAPL"}),
            {"BRK.B", "BAC", "DIS", "AAPL"},
        )

    def test_pdf_link_in_byma_page(self):
        html = (
            '<a href="https://cdn.prod.website-files.com/6697a441a50c6b926e1972e0/'
            '6ab2a2889b5ecd166f88f930_2026-09-16-BYMA-CEDEARs.pdf" class="btn">'
            "Ver listado de CEDEARs</a>"
        )
        self.assertTrue(A.find_pdf_url(html).endswith("_2026-09-16-BYMA-CEDEARs.pdf"))
        self.assertIsNone(A.find_pdf_url("<a href='/otra.pdf'>x</a>"))

    def test_codes_file_keeps_us_markets_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "codes.txt"
            p.write_text("AAPL:NASDAQ,ABEV3:B3,ADS:XETRA,BRKB:NYSE,XLK:NYSE\n", encoding="utf-8")
            self.assertEqual(A.codes_from_file(p), {"AAPL", "BRKB", "XLK"})


class ApplyTests(unittest.TestCase):
    def universe(self):
        return {
            "cedear_source": "viejo",
            "tickers": [
                {"symbol": "AAPL", "cedear": True},
                {"symbol": "CRWD", "cedear": False},
                {"symbol": "HPE", "cedear": True},
                {"symbol": "BRK.B", "cedear": False},
            ],
        }

    def test_flags_follow_the_listing(self):
        u = self.universe()
        added, removed = A.apply_flags(u, {"AAPL", "CRWD", "BRK.B"}, "nuevo")
        self.assertEqual(added, ["BRK.B", "CRWD"])
        self.assertEqual(removed, ["HPE"])
        self.assertEqual({r["symbol"]: r["cedear"] for r in u["tickers"]},
                         {"AAPL": True, "CRWD": True, "HPE": False, "BRK.B": True})
        self.assertEqual(u["cedear_source"], "nuevo")

    def test_short_listing_aborts_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            uni = Path(tmp) / "universe.json"
            uni.write_text(json.dumps(self.universe()), encoding="utf-8")
            codes = Path(tmp) / "codes.txt"
            codes.write_text("AAPL:NASDAQ,CRWD:NASDAQ", encoding="utf-8")
            original = A.UNIVERSE
            A.UNIVERSE = uni
            try:
                self.assertEqual(A.main(["--codes", str(codes)]), 1)
            finally:
                A.UNIVERSE = original
            self.assertEqual(json.loads(uni.read_text(encoding="utf-8")), self.universe())


class UniverseFlagTests(unittest.TestCase):
    # No fija tickers puntuales: el workflow mensual corre estos tests después de
    # actualizar la lista, y BYMA suma y da de baja CEDEARs.
    def test_universe_flags_come_from_a_byma_listing(self):
        data = json.loads(A.UNIVERSE.read_text(encoding="utf-8"))
        self.assertIn("BYMA", data["cedear_source"])
        self.assertRegex(data["cedear_source"], r"actualizado \d{4}-\d{2}-\d{2}")
        n = sum(1 for r in data["tickers"] if r.get("cedear"))
        self.assertGreaterEqual(n, 150)


if __name__ == "__main__":
    unittest.main()
