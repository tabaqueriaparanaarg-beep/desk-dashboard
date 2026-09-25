#!/usr/bin/env python3
"""
One-shot: compute top10_return for current datos.json ranking (Top 10 + SPY)
without a full-universe rebuild. Patches datos.json in place.

Usage:
  cd /workspace/desk-dashboard && python3 patch_top10_return.py
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import build as b

ROOT = Path(__file__).resolve().parent
OUT_PATH = ROOT / "datos.json"
LOOKBACK_CALENDAR_DAYS = 45  # enough for 10 sessions + cushion


def main() -> None:
    if not b.APCA_KEY or not b.APCA_SECRET:
        raise SystemExit(
            "Faltan ALPACA_API_KEY / ALPACA_SECRET_KEY (o APCA_API_KEY_ID / APCA_API_SECRET_KEY) en el entorno "
            "(necesarias para fetch Alpaca)."
        )
    if not OUT_PATH.is_file():
        raise SystemExit(f"No existe {OUT_PATH} — corré build.py primero")

    data = json.loads(OUT_PATH.read_text())
    ranking = data.get("ranking") or []
    if not ranking:
        raise SystemExit("datos.json no tiene ranking")

    top = sorted(
        ranking,
        key=lambda r: (-(r.get("desk_score") or 0), r.get("symbol") or ""),
    )[:10]
    symbols = [r["symbol"] for r in top if r.get("symbol")]
    if "SPY" not in symbols:
        symbols.append("SPY")

    end_dt = datetime.now(timezone.utc).date()
    start_dt = end_dt - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    start_s = start_dt.isoformat() + "T00:00:00Z"
    end_s = end_dt.isoformat() + "T23:59:59Z"

    print(f"patch_top10_return — {len(symbols)} símbolos, {start_s[:10]} → {end_s[:10]}")
    print("  " + ", ".join(symbols))

    all_bars: dict[str, list] = {}
    batch_size = b.BATCH_SIZE
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        try:
            got = b.fetch_bars_batch(batch, start_s, end_s)
            for s in batch:
                bars = got.get(s) or []
                all_bars[s] = bars
                print(f"  {'OK' if len(bars) >= 11 else 'LOW'} {s}: {len(bars)} bars")
        except Exception as e:
            print(f"  FAIL batch {batch}: {e}")
            for s in batch:
                try:
                    time.sleep(0.4)
                    got = b.fetch_bars_batch([s], start_s, end_s)
                    bars = got.get(s) or []
                    all_bars[s] = bars
                    print(f"  OK {s} (retry): {len(bars)} bars")
                except Exception as e2:
                    all_bars[s] = []
                    print(f"  FAIL {s}: {e2}")
        time.sleep(b.SLEEP_BETWEEN_BATCHES)

    if len(all_bars.get("SPY") or []) < 11:
        raise SystemExit("SPY sin barras suficientes para la ventana de 10 ruedas")

    top10 = b.compute_top10_return(ranking, all_bars, b.WINDOW_SESSIONS)
    data["top10_return"] = top10
    formulas = data.setdefault("formulas", {})
    formulas["top10_return"] = (
        f"(close[-1]/close[-{b.WINDOW_SESSIONS + 1}] - 1)*100 sobre últimas "
        f"{b.WINDOW_SESSIONS} ruedas; avg = media de los Top 10 con retorno válido; "
        "SPY misma ventana"
    )
    notes = data.setdefault("notes", [])
    note = (
        f"Retorno Top 10 ({b.WINDOW_SESSIONS} ruedas): medio "
        f"{top10.get('avg_return_pct')}% · SPY {top10.get('spy_return_pct')}%"
    )
    # replace prior top10 note if present
    notes[:] = [n for n in notes if not str(n).startswith("Retorno Top 10")]
    notes.append(note)

    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"\nPatched {OUT_PATH}")
    print(
        f"avg={top10.get('avg_return_pct')}% SPY={top10.get('spy_return_pct')}% "
        f"asof={top10.get('asof')} rows={len(top10.get('rows') or [])}"
    )
    for r in top10.get("rows") or []:
        print(
            f"  #{r['rank']} {r['symbol']:6} score={r.get('desk_score')} "
            f"ret={r.get('return_pct')}% spark_n={len(r.get('spark') or [])}"
        )


if __name__ == "__main__":
    main()
