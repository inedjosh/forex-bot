"""Pure-Python technical indicators — no external dependencies.

Each function takes a list of floats (usually closing prices) and returns a list of the
same length, with `None` in the leading positions where there isn't enough data yet.
This makes them easy to use inside a strategy without pulling in pandas.
"""

from __future__ import annotations

from typing import List, Optional

Series = List[float]
OptSeries = List[Optional[float]]


def sma(values: Series, period: int) -> OptSeries:
    """Simple moving average."""
    out: OptSeries = [None] * len(values)
    if period <= 0:
        raise ValueError("period must be positive")
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def ema(values: Series, period: int) -> OptSeries:
    """Exponential moving average, seeded with an SMA of the first `period` values."""
    if period <= 0:
        raise ValueError("period must be positive")
    out: OptSeries = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def rsi(values: Series, period: int = 14) -> OptSeries:
    """Relative Strength Index (Wilder's smoothing)."""
    out: OptSeries = [None] * len(values)
    if len(values) <= period:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_from(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi_from(avg_gain, avg_loss)
    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(highs: Series, lows: Series, closes: Series, period: int = 14) -> OptSeries:
    """Average True Range — a volatility measure, useful for sizing stop distances."""
    n = len(closes)
    out: OptSeries = [None] * n
    if n <= period:
        return out
    trs: Series = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    first = sum(trs[1 : period + 1]) / period
    out[period] = first
    prev = first
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


def crossover(fast: OptSeries, slow: OptSeries, i: int) -> bool:
    """True if `fast` crossed *above* `slow` at bar `i`."""
    if i < 1:
        return False
    a0, a1 = fast[i - 1], fast[i]
    b0, b1 = slow[i - 1], slow[i]
    if None in (a0, a1, b0, b1):
        return False
    return a0 <= b0 and a1 > b1


def crossunder(fast: OptSeries, slow: OptSeries, i: int) -> bool:
    """True if `fast` crossed *below* `slow` at bar `i`."""
    if i < 1:
        return False
    a0, a1 = fast[i - 1], fast[i]
    b0, b1 = slow[i - 1], slow[i]
    if None in (a0, a1, b0, b1):
        return False
    return a0 >= b0 and a1 < b1
