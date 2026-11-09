#!/usr/bin/env python3
"""Actualiza la marca `cedear` de universe.json con el listado público de BYMA.

BYMA publica «CEDEARs Negociables en BYMA» como PDF en
https://www.byma.com.ar/productos/productos-financieros/cedears
y el nombre del archivo cambia con cada actualización. Este script busca el link
en esa página, baja el PDF, saca los códigos que cotizan en un mercado de EE.UU.
y marca `cedear: true` en cada ticker del universo que esté en la lista.

Uso:
    pip install pypdf                     # solo para este script; build.py no lo usa
    python3 actualizar_cedears.py         # baja el PDF vigente y actualiza
    python3 actualizar_cedears.py --pdf listado.pdf
    python3 actualizar_cedears.py --codes codigos.txt   # "AAPL:NASDAQ,MSFT:NASDAQ,…"
    python3 actualizar_cedears.py --dry-run             # muestra el cambio sin escribir

Nunca saca la marca de un ticker si el listado parece incompleto: con menos de
MIN_US_CODES códigos de EE.UU. aborta sin tocar el archivo.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UNIVERSE = ROOT / "universe.json"
BYMA_PAGE = "https://www.byma.com.ar/productos/productos-financieros/cedears"
USER_AGENT = "Mozilla/5.0 (desk-dashboard; actualizar_cedears)"
MIN_US_CODES = 200

# Mercados de EE.UU. tal como los escribe BYMA ("NASDAQ GS", "NYSE Arca", "New York"…).
US_MARKET = r"(?:NYSE|NASDAQ|CBOE|New\s+York)"
CODE = r"[A-Z][A-Z0-9]{0,5}(?:\.[A-Z])?"
PAIR_RX = re.compile(r"(?<![A-Za-z0-9.])(" + CODE + r")\s*\|?\s*" + US_MARKET + r"\b")
DATE_RX = re.compile(r"Actualizado\s+(\d{2})/(\d{2})/(\d{4})")
PDF_LINK_RX = re.compile(r"https://[^\"'\s<>]+?BYMA-CEDEARs\.pdf", re.IGNORECASE)

# Código BYMA → ticker en EE.UU., cuando no coinciden.
BYMA_TO_US = {
    "BRKB": "BRK.B",
    "BA.C": "BAC",
    "DISN": "DIS",
    "NOKA": "NOK",
    "TRVV": "TRV",
    "UN": "NU",
    "BNG": "BG",
    "KOFM": "KOF",
    "XROX": "XRX",
}


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def find_pdf_url(html: str) -> str | None:
    """El link al PDF del listado dentro de la página de CEDEARs de BYMA."""
    m = PDF_LINK_RX.search(html)
    return m.group(0) if m else None


def pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("Falta pypdf: pip install pypdf (solo lo usa este script).")
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_codes(text: str) -> set[str]:
    """Códigos BYMA que cotizan en un mercado de EE.UU."""
    return {m.group(1) for m in PAIR_RX.finditer(text)}


def listing_date(text: str) -> str | None:
    m = DATE_RX.search(text)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def codes_from_file(path: Path) -> set[str]:
    """Lista "CODIGO:MERCADO,…" (o un código por línea); solo mercados de EE.UU."""
    raw = path.read_text(encoding="utf-8")
    out = set()
    for item in re.split(r"[,\n]", raw):
        item = item.strip()
        if not item:
            continue
        code, _, market = item.partition(":")
        if not market or re.match(US_MARKET, market, re.IGNORECASE):
            out.add(code.strip())
    return out


def us_tickers(codes: set[str]) -> set[str]:
    return {BYMA_TO_US.get(c, c) for c in codes}


def apply_flags(universe: dict, tickers: set[str], source: str) -> tuple[list[str], list[str]]:
    """Marca cada ticker del universo. Devuelve (los que se suman, los que se pierden)."""
    added, removed = [], []
    for row in universe.get("tickers") or []:
        sym = row.get("symbol")
        new = sym in tickers
        old = bool(row.get("cedear"))
        if new and not old:
            added.append(sym)
        if old and not new:
            removed.append(sym)
        row["cedear"] = new
    universe["cedear_source"] = source
    return sorted(added), sorted(removed)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pdf", type=Path, help="PDF de BYMA ya descargado")
    ap.add_argument("--codes", type=Path, help='lista "CODIGO:MERCADO,…" ya extraída')
    ap.add_argument("--date", help="fecha del listado (AAAA-MM-DD) si no se puede leer del PDF")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    date = args.date
    if args.codes:
        codes = codes_from_file(args.codes)
        origin = f"lista extraída ({args.codes.name})"
    else:
        if args.pdf:
            data = args.pdf.read_bytes()
            origin = args.pdf.name
        else:
            html = http_get(BYMA_PAGE).decode("utf-8", errors="replace")
            url = find_pdf_url(html)
            if not url:
                print("No encontré el link al PDF en la página de BYMA; no cambio nada.")
                return 1
            data = http_get(url)
            origin = url
        text = pdf_text(data)
        codes = parse_codes(text)
        date = date or listing_date(text)

    if len(codes) < MIN_US_CODES:
        print(
            f"Solo leí {len(codes)} códigos de EE.UU. (mínimo {MIN_US_CODES}). "
            "El formato del listado pudo haber cambiado; no cambio nada."
        )
        return 1

    universe = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    source = (
        f"BYMA «CEDEARs Negociables en BYMA» (actualizado {date or 'sin fecha'}), "
        f"{len(codes)} códigos de mercados de EE.UU. El flag es true si el ticker US "
        "(o su equivalente, ej. BRKB → BRK.B) está en ese listado. Se actualiza con "
        "actualizar_cedears.py."
    )
    added, removed = apply_flags(universe, us_tickers(codes), source)
    total = sum(1 for r in universe["tickers"] if r.get("cedear"))
    print(f"Fuente: {origin}")
    print(f"Listado del {date or '?'}: {len(codes)} códigos de EE.UU.")
    print(f"Con CEDEAR en el universo: {total}. Se suman {len(added)}: {', '.join(added) or '—'}.")
    print(f"Se pierden {len(removed)}: {', '.join(removed) or '—'}.")
    if args.dry_run:
        print("--dry-run: no escribí nada.")
        return 0
    UNIVERSE.write_text(json.dumps(universe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Escribí {UNIVERSE.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
