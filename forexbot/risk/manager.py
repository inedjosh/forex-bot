"""Position sizing and risk guards.

This is the safety layer that sits between a strategy's signal and an actual order. It
decides *how big* a trade should be and *whether it's allowed at all*. Keeping this out
of the strategy means you can't accidentally over-leverage in your formula, and the same
rules apply identically in backtest and live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from ..core.types import Order, Signal


@dataclass
class RiskConfig:
    starting_balance: float = 10_000.0
    # Sizing
    units_mode: str = "risk_pct"      # "risk_pct" or "fixed"
    risk_pct: float = 1.0             # risk this % of balance per trade
    fixed_units: float = 1_000.0
    # Guards
    max_open_positions: int = 1
    max_daily_loss_pct: float = 3.0   # halt for the day after losing this % of balance


class RiskManager:
    """Sizes orders and enforces guards. Stateful: tracks balance and daily P&L."""

    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self.balance = config.starting_balance
        self._day: Optional[date] = None
        self._day_start_balance = config.starting_balance

    # ── daily loss tracking ────────────────────────────────────────────────
    def _roll_day(self, today: date) -> None:
        if self._day != today:
            self._day = today
            self._day_start_balance = self.balance

    def trading_halted_for_day(self, today: date) -> bool:
        """True if today's realized loss has breached the max-daily-loss guard."""
        self._roll_day(today)
        if self.config.max_daily_loss_pct <= 0:
            return False
        loss = self._day_start_balance - self.balance
        limit = self._day_start_balance * (self.config.max_daily_loss_pct / 100.0)
        return loss >= limit

    def on_trade_closed(self, pnl: float) -> None:
        """Update balance after a trade closes."""
        self.balance += pnl

    # ── sizing ─────────────────────────────────────────────────────────────
    def size_order(self, signal: Signal, entry_price: float) -> Optional[Order]:
        """Turn a Signal into a sized Order, or None if it can't be sized safely."""
        stop_distance = abs(entry_price - signal.stop_loss)
        if stop_distance <= 0:
            # A zero-distance stop would mean infinite size / no risk definition.
            return None

        if self.config.units_mode == "fixed":
            units = self.config.fixed_units
        else:
            risk_amount = self.balance * (self.config.risk_pct / 100.0)
            # units such that (stop_distance * units) == risk_amount
            units = risk_amount / stop_distance

        if units <= 0:
            return None

        return Order(
            side=signal.side,
            units=units,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            reason=signal.reason,
        )
