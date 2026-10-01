"""Shared free-data downloader (Yahoo Finance). Used by the CLI and the web UI."""

from __future__ import annotations

import csv
import os
from typing import Tuple


def to_yahoo_symbol(pair: str) -> str:
    """EURUSD / EUR_USD / eurusd -> EURUSD=X (Yahoo's FX ticker format)."""
    p = pair.upper().replace("/", "").replace("_", "").replace("=X", "")
    return f"{p}=X"


def download_yahoo(
    pair: str = "EURUSD",
    interval: str = "1h",
    period: str = "2y",
    out_path: str | None = None,
) -> Tuple[str, int]:
    """Download FX candles from Yahoo to a CSV. Returns (path, num_rows).

    Raises ImportError if yfinance is missing, RuntimeError if no data comes back.
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise ImportError("yfinance not installed. Run: pip install yfinance") from exc

    symbol = to_yahoo_symbol(pair)
    df = yf.download(symbol, interval=interval, period=period,
                     auto_adjust=False, progress=False)
    if df is None or df.empty:
        raise RuntimeError("No data returned (Yahoo restricts intraday history — "
                           "try a shorter period or coarser interval).")

    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    out_path = out_path or f"data/{pair.upper()}_{interval}.csv"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    rows = 0
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for ts, row in df.iterrows():
            try:
                o, h, l, c = (float(row["Open"]), float(row["High"]),
                              float(row["Low"]), float(row["Close"]))
            except (KeyError, TypeError, ValueError):
                continue
            if any(v != v for v in (o, h, l, c)):  # NaN
                continue
            vol = float(row.get("Volume", 0) or 0)
            w.writerow([ts.isoformat(), f"{o:.6f}", f"{h:.6f}",
                        f"{l:.6f}", f"{c:.6f}", f"{vol:.0f}"])
            rows += 1

    if rows == 0:
        raise RuntimeError("All rows were empty/NaN — nothing written.")
    return out_path, rows
