"""
╔══════════════════════════════════════════════════════════════════════════╗
║  YOUR FORMULA — fully configurable from the dashboard form (no code).       ║
╠══════════════════════════════════════════════════════════════════════════╣
║  Every choice below is set from the "Your formula" form in the web UI (or   ║
║  the .env file). A non-coder never touches this file.                        ║
║                                                                            ║
║  The rules, in plain English:                                              ║
║    • Watch a FAST trend line and a SLOW trend line (EMA or SMA).           ║
║    • BUY when the fast line crosses above the slow line.                   ║
║    • SELL when the fast line crosses below the slow line.                  ║
║    • Optional momentum filter (RSI): skip buys when already overbought and ║
║      skip sells when already oversold.                                     ║
║    • Place a safety stop (either volatility-based or a fixed %), and a      ║
║      profit target a chosen multiple of that distance away.                ║
║                                                                            ║
║  Position sizing / risk limits / order routing are handled by the engine.  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

from typing import List, Optional

from ..config import env_bool, env_float, env_int, env_str
from ..core.indicators import atr, crossover, crossunder, ema, rsi, sma
from ..core.strategy import Strategy
from ..core.types import Candle, Position, Side, Signal


class MyFormula(Strategy):
    name = "My Formula"

    def __init__(
        self,
        fast_period: Optional[int] = None,
        slow_period: Optional[int] = None,
        rsi_period: Optional[int] = None,
        rsi_lower: Optional[float] = None,
        rsi_upper: Optional[float] = None,
        atr_period: Optional[int] = None,
        atr_mult: Optional[float] = None,
        risk_reward: Optional[float] = None,
        ma_type: Optional[str] = None,
        use_rsi: Optional[bool] = None,
        stop_mode: Optional[str] = None,
        stop_pct: Optional[float] = None,
    ) -> None:
        # Numbers — default to the .env value, overridable directly (optimizer uses this).
        self.fast_period = fast_period if fast_period is not None else env_int("FAST_EMA", 12)
        self.slow_period = slow_period if slow_period is not None else env_int("SLOW_EMA", 26)
        self.rsi_period = rsi_period if rsi_period is not None else env_int("RSI_PERIOD", 14)
        self.rsi_lower = rsi_lower if rsi_lower is not None else env_float("RSI_LOWER", 30.0)
        self.rsi_upper = rsi_upper if rsi_upper is not None else env_float("RSI_UPPER", 70.0)
        self.atr_period = atr_period if atr_period is not None else env_int("ATR_PERIOD", 14)
        self.atr_mult = atr_mult if atr_mult is not None else env_float("ATR_MULT", 2.0)
        self.risk_reward = risk_reward if risk_reward is not None else env_float("RISK_REWARD", 1.5)

        # Choices — the form's dropdowns/toggles.
        self.ma_type = (ma_type or env_str("MA_TYPE", "ema")).lower()
        self.use_rsi = use_rsi if use_rsi is not None else env_bool("USE_RSI", True)
        self.stop_mode = (stop_mode or env_str("STOP_MODE", "atr")).lower()
        self.stop_pct = stop_pct if stop_pct is not None else env_float("STOP_PCT", 1.0)

        # Precomputed indicator arrays (filled by prepare()).
        self._fast = self._slow = self._rsi = self._atr = None

    def prepare(self, candles: List[Candle]) -> None:
        """Compute indicators once over the whole series (fast: O(n), not O(n²))."""
        closes = self.closes(candles)
        ma = sma if self.ma_type == "sma" else ema
        self._fast = ma(closes, self.fast_period)
        self._slow = ma(closes, self.slow_period)
        self._rsi = rsi(closes, self.rsi_period) if self.use_rsi else None
        self._atr = atr(self.highs(candles), self.lows(candles), closes, self.atr_period)

    def _stop_distance(self, price: float, i: int) -> Optional[float]:
        if self.stop_mode == "percent":
            return price * (self.stop_pct / 100.0)
        return self._atr[i]  # volatility-based (ATR)

    def on_candle(
        self,
        candle: Candle,
        history: List[Candle],
        position: Optional[Position],
    ) -> Optional[Signal]:
        if position is not None:
            return None

        need = max(self.slow_period, self.rsi_period, self.atr_period) + 2
        if len(history) < need:
            return None

        if self._fast is None:  # safety fallback if prepare() wasn't called
            self.prepare(history)

        i = len(history) - 1
        price = candle.close

        stop_dist = self._stop_distance(price, i)
        if stop_dist is None or stop_dist <= 0:
            return None

        rsi_now = self._rsi[i] if self.use_rsi else None
        if self.use_rsi and rsi_now is None:
            return None

        going_up = crossover(self._fast, self._slow, i)
        going_down = crossunder(self._fast, self._slow, i)

        # BUY: fast crosses above slow, and (if enabled) not already overbought.
        if going_up and (not self.use_rsi or rsi_now < self.rsi_upper):
            sl = price - stop_dist
            tp = price + self.risk_reward * stop_dist
            reason = "trend up" + (f" + RSI {rsi_now:.0f}" if self.use_rsi else "")
            return Signal(Side.BUY, stop_loss=sl, take_profit=tp, reason=reason)

        # SELL: fast crosses below slow, and (if enabled) not already oversold.
        if going_down and (not self.use_rsi or rsi_now > self.rsi_lower):
            sl = price + stop_dist
            tp = price - self.risk_reward * stop_dist
            reason = "trend down" + (f" + RSI {rsi_now:.0f}" if self.use_rsi else "")
            return Signal(Side.SELL, stop_loss=sl, take_profit=tp, reason=reason)

        return None
