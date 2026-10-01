#!/usr/bin/env python3
"""Download real FX candles for backtesting — FREE, no account, no API key.

Uses Yahoo Finance via the `yfinance` package. Works anywhere (no broker, no country
restriction), on Mac/Linux/Windows. Output CSV matches what run_backtest.py expects.

    pip install yfinance

Examples:
    python scripts/fetch_free_data.py --pair EURUSD --interval 1h --period 2y
    python scripts/fetch_free_data.py --pair GBPUSD --interval 1d --period 10y
    python scripts/fetch_free_data.py --pair USDJPY --interval 15m --period 60d --out data/usdjpy.csv

Then backtest:
    python scripts/run_backtest.py --csv data/EURUSD_1h.csv --strategy my_formula

Yahoo interval limits (as of writing):
    1m  -> last 7 days      | 15m/30m/1h -> last ~730 days
    1d/1wk -> many years
"""

from __future__ import annotations

import argparse
import csv
import os
import sys


def to_yahoo_symbol(pair: str) -> str:
    """EURUSD -> EURUSD=X (Yahoo's FX ticker format)."""
    p = pair.upper().replace("/", "").replace("_", "").replace("=X", "")
    return f"{p}=X"


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch free FX candles from Yahoo Finance.")
    p.add_argument("--pair", default="EURUSD", help="e.g. EURUSD, GBPUSD, USDJPY")
    p.add_argument("--interval", default="1h",
                   help="1m,2m,5m,15m,30m,1h,1d,1wk (Yahoo limits apply)")
    p.add_argument("--period", default="2y",
                   help="how far back: 7d,60d,730d,1y,2y,5y,10y,max")
    p.add_argument("--out", default=None, help="output CSV path")
    args = p.parse_args()

    try:
        import yfinance as yf
    except ImportError:
        sys.exit("yfinance not installed. Run:  pip install yfinance")

    symbol = to_yahoo_symbol(args.pair)
    print(f"Downloading {symbol}  interval={args.interval}  period={args.period} ...")
    df = yf.download(
        symbol,
        interval=args.interval,
        period=args.period,
        auto_adjust=False,
        progress=False,
    )
    if df is None or df.empty:
        sys.exit("No data returned. Try a shorter period or a different interval "
                 "(Yahoo restricts intraday history).")

    # yfinance may return MultiIndex columns for a single symbol; flatten them.
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    out_path = args.out or f"data/{args.pair.upper()}_{args.interval}.csv"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    rows = 0
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for ts, row in df.iterrows():
            # Skip any rows with missing OHLC (Yahoo occasionally returns NaNs).
            try:
                o, h, l, c = (float(row["Open"]), float(row["High"]),
                              float(row["Low"]), float(row["Close"]))
            except (KeyError, TypeError, ValueError):
                continue
            if any(v != v for v in (o, h, l, c)):  # NaN check
                continue
            vol = float(row.get("Volume", 0) or 0)
            w.writerow([ts.isoformat(), f"{o:.6f}", f"{h:.6f}",
                        f"{l:.6f}", f"{c:.6f}", f"{vol:.0f}"])
            rows += 1

    if rows == 0:
        sys.exit("All rows were empty/NaN — nothing written.")
    print(f"Wrote {rows} candles to {out_path}")
    print(f"\nBacktest it:\n    python scripts/run_backtest.py --csv {out_path} --strategy my_formula")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
