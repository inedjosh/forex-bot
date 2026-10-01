"""
╔══════════════════════════════════════════════════════════════════════════╗
║  CRT — Candle Range Theory (the bot's core strategy)                        ║
╠══════════════════════════════════════════════════════════════════════════╣
║  A liquidity / price-action model (ICT "Power of 3": accumulation ->        ║
║  manipulation -> distribution).                                             ║
║                                                                            ║
║  The 3-phase idea, in plain terms:                                        ║
║    1. RANGE      : a prior candle (or N candles) sets a high and a low.    ║
║    2. MANIPULATION: price pierces BEYOND that range (a liquidity sweep /   ║
║       false break) then CLOSES BACK INSIDE the range — the trap.          ║
║    3. DISTRIBUTION: price expands the other way, toward the opposite side. ║
║                                                                            ║
║  Trades:                                                                   ║
║    • Sweep BELOW the range low, close back inside  -> BUY  (target range hi)║
║    • Sweep ABOVE the range high, close back inside -> SELL (target range lo)║
║    • Stop-loss just beyond the sweep wick (the manipulation extreme).      ║
║                                                                            ║
║  All settings come from the admin form / .env. Best on higher timeframes  ║
║  (Daily or 4H). Position sizing & risk are handled by the engine.          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

from typing import List, Optional

from ..config import env_float, env_int, env_str
from ..core.strategy import Strategy
from ..core.types import Candle, Position, Side, Signal


class CrtStrategy(Strategy):
    name = "CRT (Candle Range Theory)"

    def __init__(
        self,
        range_lookback: Optional[int] = None,
        target_mode: Optional[str] = None,
        risk_reward: Optional[float] = None,
        stop_buffer_pct: Optional[float] = None,
        min_rr: Optional[float] = None,
    ) -> None:
        # How many prior candles form the range (1 = the single previous candle).
        self.range_lookback = range_lookback if range_lookback is not None else env_int("CRT_RANGE_LOOKBACK", 1)
        # "range" = target the opposite side of the range; "rr" = fixed reward:risk.
        self.target_mode = (target_mode or env_str("CRT_TARGET_MODE", "range")).lower()
        self.risk_reward = risk_reward if risk_reward is not None else env_float("CRT_RISK_REWARD", 2.0)
        # Extra cushion beyond the sweep wick for the stop, as a % of price.
        self.stop_buffer_pct = stop_buffer_pct if stop_buffer_pct is not None else env_float("CRT_STOP_BUFFER_PCT", 0.0)
        # Skip setups whose reward:risk (to the range target) is below this.
        self.min_rr = min_rr if min_rr is not None else env_float("CRT_MIN_RR", 1.0)

    def on_candle(
        self,
        candle: Candle,
        history: List[Candle],
        position: Optional[Position],
    ) -> Optional[Signal]:
        if position is not None:
            return None

        n = self.range_lookback
        if len(history) < n + 1:
            return None

        # The range is the prior n candles (excluding the current one).
        prior = history[-(n + 1):-1]
        range_high = max(c.high for c in prior)
        range_low = min(c.low for c in prior)
        if range_high <= range_low:
            return None

        price = candle.close
        buf = self.stop_buffer_pct / 100.0

        # ── BUY: swept below the range low, then reclaimed (closed back inside) ──
        if candle.low < range_low and price > range_low:
            sl = candle.low * (1.0 - buf)
            risk = price - sl
            if risk <= 0:
                return None
            tp = range_high if self.target_mode == "range" else price + self.risk_reward * risk
            if tp <= price or (tp - price) / risk < self.min_rr:
                return None
            return Signal(Side.BUY, stop_loss=sl, take_profit=tp,
                          reason="CRT: swept low, reclaimed")

        # ── SELL: swept above the range high, then reclaimed (closed back inside) ──
        if candle.high > range_high and price < range_high:
            sl = candle.high * (1.0 + buf)
            risk = sl - price
            if risk <= 0:
                return None
            tp = range_low if self.target_mode == "range" else price - self.risk_reward * risk
            if tp >= price or (price - tp) / risk < self.min_rr:
                return None
            return Signal(Side.SELL, stop_loss=sl, take_profit=tp,
                          reason="CRT: swept high, reclaimed")

        return None
