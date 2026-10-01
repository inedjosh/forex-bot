"""Broker interface — the seam between your bot and the outside world.

Any live/paper broker (OANDA, MT5, IBKR, ...) implements this. The backtest engine is
effectively a broker too (a simulated one), which is why the same strategy runs
unchanged across backtest, demo, and live.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import List

from ..core.types import Candle, Order


class Broker(ABC):
    @abstractmethod
    def get_candles(self, instrument: str, granularity: str, count: int) -> List[Candle]:
        """Fetch the most recent `count` closed candles."""

    @abstractmethod
    def account_balance(self) -> float:
        """Current account balance in the account's home currency."""

    @abstractmethod
    def place_order(self, instrument: str, order: Order) -> str:
        """Submit a market order with attached stop-loss/take-profit. Returns an id."""

    @abstractmethod
    def has_open_position(self, instrument: str) -> bool:
        """True if there's already an open position for the instrument."""

    def position_info(self, instrument: str):
        """Return a dict describing the open position, or None. Optional for adapters."""
        return None

    def open_positions(self, instrument=None) -> list:
        """Return a list of ALL currently-open positions (dicts). Default: the single one."""
        p = self.position_info(instrument)
        return [p] if p else []

    def drain_closed_trades(self) -> list:
        """Return trades that closed since the last call (and clear them). Optional."""
        return []

    def wait_next(self, poll_seconds: float) -> bool:
        """Block until it's time to check for a new candle.

        Real brokers just sleep and always return True (the loop runs forever).
        The simulated broker overrides this to advance its internal clock and returns
        False when the historical data is exhausted.
        """
        time.sleep(poll_seconds)
        return True
