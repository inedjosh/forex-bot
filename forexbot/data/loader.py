"""Data sources for backtesting.

Two ways to get candles without a broker account:
  - `load_csv`        : read an OHLC CSV you already have.
  - `synthetic_candles`: generate a deterministic random-walk price series, so the bot
                          runs end-to-end with zero setup.
"""

from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta
from typing import List

from ..core.types import Candle


def load_csv(
    path: str,
    time_col: str = "time",
    time_format: str | None = None,
) -> List[Candle]:
    """Load candles from a CSV with columns: time, open, high, low, close[, volume].

    `time` may be an ISO-8601 string (default) or match `time_format` (strptime).
    """
    candles: List[Candle] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_time = row[time_col]
            if time_format:
                ts = datetime.strptime(raw_time, time_format)
            else:
                ts = datetime.fromisoformat(raw_time)
            candles.append(
                Candle(
                    time=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0) or 0),
                )
            )
    candles.sort(key=lambda c: c.time)
    return candles


def synthetic_candles(
    n: int = 2000,
    start_price: float = 1.1000,
    seed: int = 42,
    volatility: float = 0.0008,
    drift: float = 0.0,
    start_time: datetime | None = None,
    step: timedelta = timedelta(hours=1),
) -> List[Candle]:
    """Generate a deterministic pseudo-random OHLC series (no numpy needed).

    Uses a simple linear-congruential generator so results are reproducible across
    machines and Python versions given the same seed.
    """
    if start_time is None:
        start_time = datetime(2020, 1, 1)

    # Minimal LCG -> uniform floats in [0, 1).
    state = seed & 0xFFFFFFFF

    def rand() -> float:
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return state / 0x7FFFFFFF

    def gauss() -> float:
        # Box-Muller from two uniforms.
        u1 = max(rand(), 1e-12)
        u2 = rand()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

    candles: List[Candle] = []
    price = start_price
    t = start_time
    for _ in range(n):
        ret = drift + volatility * gauss()
        open_ = price
        close = max(0.0001, open_ * (1.0 + ret))
        # Intrabar wiggle for high/low.
        span = abs(close - open_) + volatility * open_ * (0.5 + rand())
        high = max(open_, close) + span * rand()
        low = min(open_, close) - span * rand()
        candles.append(
            Candle(time=t, open=open_, high=high, low=low, close=close, volume=1000.0)
        )
        price = close
        t = t + step
    return candles
