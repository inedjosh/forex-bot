#!/usr/bin/env python3
"""Download real historical candles from OANDA into a CSV for backtesting.

Requires an OANDA account (demo is fine) with OANDA_ACCESS_TOKEN set in .env, plus
`pip install oandapyV20`.

Examples:
    python scripts/fetch_data.py --instrument EUR_USD --granularity H1 --count 5000
    python scripts/fetch_data.py --instrument GBP_USD --granularity M15 --count 5000 \
        --out data/GBPUSD_M15.csv

Then backtest on it:
    python scripts/run_backtest.py --csv data/EUR_USD_H1.csv --strategy my_formula
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forexbot.config import env_str


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch OANDA historical candles to CSV.")
    p.add_argument("--instrument", default=env_str("INSTRUMENT", "EUR_USD"))
    p.add_argument("--granularity", default=env_str("GRANULARITY", "H1"))
    p.add_argument("--count", type=int, default=5000, help="number of candles")
    p.add_argument("--out", default=None, help="output CSV path")
    args = p.parse_args()

    token = env_str("OANDA_ACCESS_TOKEN", "")
    if not token:
        sys.exit("OANDA_ACCESS_TOKEN not set in .env. Open a free OANDA account first.")

    try:
        from oandapyV20 import API
        from oandapyV20.endpoints import instruments
    except ImportError:
        sys.exit("oandapyV20 not installed. Run:  pip install oandapyV20")

    api = API(access_token=token, environment=env_str("OANDA_ENVIRONMENT", "practice"))

    # OANDA caps each request at 5000 candles; page backwards if more are requested.
    out_path = args.out or f"data/{args.instrument}_{args.granularity}.csv"
    remaining = args.count
    all_rows = []
    to_time = None
    while remaining > 0:
        batch = min(5000, remaining)
        params = {"granularity": args.granularity, "count": batch, "price": "M"}
        if to_time:
            params["to"] = to_time
        req = instruments.InstrumentsCandles(instrument=args.instrument, params=params)
        resp = api.request(req)
        candles = [c for c in resp.get("candles", []) if c.get("complete")]
        if not candles:
            break
        for c in candles:
            m = c["mid"]
            all_rows.append([c["time"], m["o"], m["h"], m["l"], m["c"], c.get("volume", 0)])
        to_time = candles[0]["time"]  # page further back
        remaining -= len(candles)
        print(f"fetched {len(all_rows)} candles...")

    # De-dup and sort ascending by time.
    seen = set()
    rows = []
    for r in sorted(all_rows, key=lambda x: x[0]):
        if r[0] in seen:
            continue
        seen.add(r[0])
        rows.append(r)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        w.writerows(rows)

    print(f"\nWrote {len(rows)} candles to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
