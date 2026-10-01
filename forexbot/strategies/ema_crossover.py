"""Sample placeholder strategy: EMA crossover with an ATR-based stop.

This exists so the bot runs end-to-end out of the box. It is NOT investment advice and
not a good strategy — it's a demonstration of the API. Replace it with your own formula
in `my_formula.py`.

Logic:
  - Compute a fast EMA and a slow EMA of closing prices.
  - Go LONG when the fast EMA crosses above the slow EMA.
  - Go SHORT when the fast EMA crosses below the slow EMA.
  - Stop-loss = `atr_mult` * ATR away from entry; take-profit = `rr` * stop distance.
"""

from __future__ import annotations

from typing import List, Optional

from ..core.indicators import atr, crossover, crossunder, ema
from ..core.strategy import Strategy
from ..core.types import Candle, Position, Side, Signal


class EmaCrossover(Strategy):
    name = "EMA Crossover (sample)"

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        atr_period: int = 14,
        atr_mult: float = 2.0,
        rr: float = 1.5,
    ) -> None:
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.rr = rr
        self._fast_ema = self._slow_ema = self._atr = None

    def prepare(self, candles: List[Candle]) -> None:
        closes = self.closes(candles)
        self._fast_ema = ema(closes, self.fast)
        self._slow_ema = ema(closes, self.slow)
        self._atr = atr(self.highs(candles), self.lows(candles), closes, self.atr_period)

    def on_candle(
        self,
        candle: Candle,
        history: List[Candle],
        position: Optional[Position],
    ) -> Optional[Signal]:
        # Only look for new entries when flat.
        if position is not None:
            return None

        # Need enough bars for the slow EMA and ATR to be defined.
        if len(history) < max(self.slow, self.atr_period) + 2:
            return None

        if self._fast_ema is None:
            self.prepare(history)
        fast_ema, slow_ema, atr_series = self._fast_ema, self._slow_ema, self._atr

        i = len(history) - 1
        stop_dist = atr_series[i]
        if stop_dist is None or stop_dist <= 0:
            return None

        price = candle.close

        if crossover(fast_ema, slow_ema, i):
            sl = price - self.atr_mult * stop_dist
            tp = price + self.rr * (price - sl)
            return Signal(Side.BUY, stop_loss=sl, take_profit=tp, reason="EMA cross up")

        if crossunder(fast_ema, slow_ema, i):
            sl = price + self.atr_mult * stop_dist
            tp = price - self.rr * (sl - price)
            return Signal(Side.SELL, stop_loss=sl, take_profit=tp, reason="EMA cross down")

        return None
