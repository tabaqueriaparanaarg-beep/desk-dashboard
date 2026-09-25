#!/usr/bin/env python3
"""
Baja logos de empresas (Finnhub /stock/profile2) a assets/logos/<TICKER>.<ext>
y parchea datos.json (campo `logo` en ranking / top10 / earnings + mapa `logos`)
sin rebuild completo de Alpaca.

Usage:
  cd /workspace/desk-dashboard
  python3 fetch_logos.py            # sólo faltantes (cache: archivo o null en index.json)
  python3 fetch_logos.py --force    # re-pide todo (incluye nulls cacheados)
  python3 fetch_logos.py --symbols AAPL,MELI --force
  python3 fetch_logos.py --no-patch # no toca datos.json
"""
from __future__ import annotations

import argparse
import json

import build as b


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="ignorar cache (archivos y nulls)")
    ap.add_argument("--symbols", default="", help="lista separada por comas (default: todo universe.json)")
    ap.add_argument("--no-patch", action="store_true", help="no parchear datos.json")
    ap.add_argument("--sleep", type=float, default=b.LOGO_SLEEP, help="segundos entre llamadas Finnhub")
    args = ap.parse_args()

    universe = json.loads(b.UNIVERSE_PATH.read_text())
    all_syms = [b.logo_symbol(u) for u in universe]
    if args.symbols:
        target = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        target = all_syms

    key = b.load_finnhub_key()
    if not key:
        print("AVISO: no hay FINNHUB_API_KEY — sólo se usa la cache local")
    print(f"fetch_logos — {len(target)} símbolos{' (force)' if args.force else ''}")
    _, notes = b.fetch_logos(target, key, force=args.force, sleep_s=args.sleep)
    for n in notes:
        print(n)

    logo_map = b.logo_map_from_cache(all_syms)
    missing = [s for s, v in logo_map.items() if not v]
    print(f"Con logo: {len(all_syms) - len(missing)} / {len(all_syms)}")
    if missing:
        print("Sin logo (fallback): " + ", ".join(missing))

    if args.no_patch or not b.OUT_PATH.is_file():
        return
    data = json.loads(b.OUT_PATH.read_text())
    # incluir símbolos presentes en datos.json aunque no estén en universe.json
    extra = {
        str(r.get("symbol")).upper()
        for key_ in ("ranking", "earnings")
        for r in (data.get(key_) or [])
        if isinstance(r, dict) and r.get("symbol")
    } - set(logo_map)
    if extra:
        logo_map.update(b.logo_map_from_cache(sorted(extra)))
    b.attach_logos(data, logo_map)
    note = f"Logos: {len(all_syms) - len(missing)}/{len(all_syms)} con logo (fetch_logos.py)"
    notes_list = data.setdefault("notes", [])
    notes_list[:] = [n for n in notes_list if not str(n).startswith("Logos:")]
    notes_list.append(note)
    b.OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"Patched {b.OUT_PATH}")


if __name__ == "__main__":
    main()
