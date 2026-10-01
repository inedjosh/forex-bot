#!/usr/bin/env python3
"""Download historical candles from your MT5 broker into a CSV for backtesting.

Backtesting on your *broker's own* prices/spreads is more accurate than free third-party
data. Requires MT5 + `pip install MetaTrader5` on Windows (or a Windows VPS) with the
terminal logged in, and MT5_* credentials in .env.

Examples:
    python scripts/fetch_mt5_data.py --instrument EURUSD --granularity H1 --count 5000
    python scripts/fetch_mt5_data.py --instrument GBPUSD --granularity M15 --count 20000
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forexbot.config import env_str


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch MT5 historical candles to CSV.")
    p.add_argument("--instrument", default=env_str("INSTRUMENT", "EURUSD"))
    p.add_argument("--granularity", default=env_str("GRANULARITY", "H1"))
    p.add_argument("--count", type=int, default=5000)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    login = env_str("MT5_LOGIN", "")
    password = env_str("MT5_PASSWORD", "")
    server = env_str("MT5_SERVER", "")
    if not (login and password and server):
        sys.exit("MT5_LOGIN / MT5_PASSWORD / MT5_SERVER not set in .env.")

    try:
        from forexbot.brokers import Mt5Broker
    except Exception as exc:  # pragma: no cover
        sys.exit(f"Could not load MT5 adapter: {exc}")

    broker = Mt5Broker(login=int(login), password=password, server=server)
    candles = broker.get_candles(args.instrument, args.granularity, args.count)
    broker.shutdown()

    if not candles:
        sys.exit("No candles returned. Check the symbol name and that MT5 is logged in.")

    out_path = args.out or f"data/{args.instrument}_{args.granularity}.csv"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.time.isoformat(), f"{c.open:.6f}", f"{c.high:.6f}",
                        f"{c.low:.6f}", f"{c.close:.6f}", f"{c.volume:.0f}"])

    print(f"Wrote {len(candles)} candles to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
