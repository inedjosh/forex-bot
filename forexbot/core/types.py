"""Core data types shared across the whole bot.

These are deliberately broker-agnostic. A candle from OANDA, MT5, a CSV file, or the
synthetic generator all become the same `Candle` object, so your strategy never has to
care where the data came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    """Direction of a trade."""

    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        """+1 for BUY, -1 for SELL — handy for P&L math."""
        return 1 if self is Side.BUY else -1


@dataclass(frozen=True)
class Candle:
    """One OHLC bar."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Signal:
    """What a strategy emits when it wants to open a trade.

    `stop_loss` and `take_profit` are absolute prices. The engine enforces both, so
    every trade always has a defined risk — the strategy can't "forget" a stop.
    """

    side: Side
    stop_loss: float
    take_profit: Optional[float] = None
    # Optional free-form tag for debugging / logging why the trade fired.
    reason: str = ""


@dataclass
class Order:
    """An instruction to open a position, after sizing has been applied."""

    side: Side
    units: float
    stop_loss: float
    take_profit: Optional[float]
    reason: str = ""


@dataclass
class Position:
    """An open position being tracked by the engine."""

    side: Side
    units: float
    entry_price: float
    entry_time: datetime
    stop_loss: float
    take_profit: Optional[float]
    reason: str = ""

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.entry_price) * self.side.sign * self.units


@dataclass
class Trade:
    """A completed round-trip trade (opened and closed)."""

    side: Side
    units: float
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    exit_reason: str  # "stop_loss", "take_profit", "signal", "end_of_data"
    reason: str = ""

    @property
    def won(self) -> bool:
        return self.pnl > 0
