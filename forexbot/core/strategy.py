"""The Strategy base class — the contract every trading formula implements.

This is intentionally tiny. A strategy's only job is to look at market data and decide
*whether to enter and where to place its stop/target*. Everything else — position
sizing, risk limits, order execution, tracking open trades, computing P&L — is handled
by the engine and the risk manager. That separation is what keeps your formula clean and
lets the same strategy run identically in backtest, demo, and live.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from .types import Candle, Position, Signal


class Strategy(ABC):
    """Subclass this to implement a trading formula.

    The engine calls `on_candle` once per bar, passing the just-closed candle and the
    full history up to and including it. Return a `Signal` to open a trade, or `None` to
    do nothing.
    """

    #: Human-readable name, shown in reports. Override in subclasses.
    name: str = "unnamed"

    def on_start(self) -> None:
        """Optional hook called once before the first candle."""

    def prepare(self, candles: List[Candle]) -> None:
        """Optional hook to precompute indicators over the whole series at once.

        The backtest engine calls this once with all candles before replaying them, and
        the live loop calls it each cycle with the current window. Because an indicator
        value at bar *i* depends only on data up to *i*, a strategy can safely precompute
        the full arrays here and then do an O(1) lookup per bar in `on_candle` — turning
        an O(n²) backtest into O(n). Indexing by `len(history) - 1` in `on_candle` stays
        aligned with these arrays and preserves the no-look-ahead guarantee.

        Default: no-op (strategies may compute inside `on_candle` instead).
        """

    @abstractmethod
    def on_candle(
        self,
        candle: Candle,
        history: List[Candle],
        position: Optional[Position],
    ) -> Optional[Signal]:
        """Decide what to do on this bar.

        Args:
            candle: The candle that just closed.
            history: All candles up to and including `candle` (oldest first).
            position: The currently open position, or None if flat.

        Return:
            A `Signal` to open a trade (only meaningful when `position is None`),
            or `None` to hold.
        """
        raise NotImplementedError

    # Convenience: strategies often want just the closing prices.
    @staticmethod
    def closes(history: List[Candle]) -> List[float]:
        return [c.close for c in history]

    @staticmethod
    def highs(history: List[Candle]) -> List[float]:
        return [c.high for c in history]

    @staticmethod
    def lows(history: List[Candle]) -> List[float]:
        return [c.low for c in history]
