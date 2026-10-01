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
    # Guards (0 = disabled)
    max_open_positions: int = 1
    max_daily_loss_pct: float = 3.0       # stop for the day after losing this % of balance
    daily_profit_target_pct: float = 0.0  # stop for the day once up this % (lock in gains)
    max_trades_per_day: int = 0           # stop after this many trades in a day
    max_consecutive_losses: int = 0       # stop for the day after this many losses in a row

    @classmethod
    def from_env(cls, starting_balance: Optional[float] = None,
                 risk_pct: Optional[float] = None) -> "RiskConfig":
        """Build a RiskConfig from .env, so all loss limits apply everywhere."""
        from ..config import env_float, env_int
        return cls(
            starting_balance=(starting_balance if starting_balance is not None
                              else env_float("STARTING_BALANCE", 10_000.0)),
            risk_pct=(risk_pct if risk_pct is not None else env_float("RISK_PCT", 1.0)),
            max_daily_loss_pct=env_float("MAX_DAILY_LOSS_PCT", 3.0),
            daily_profit_target_pct=env_float("DAILY_PROFIT_TARGET_PCT", 0.0),
            max_trades_per_day=env_int("MAX_TRADES_PER_DAY", 0),
            max_consecutive_losses=env_int("MAX_CONSECUTIVE_LOSSES", 0),
        )


class RiskManager:
    """Sizes orders and enforces guards. Stateful: tracks balance, daily P&L, streaks."""

    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self.balance = config.starting_balance
        self._day: Optional[date] = None
        self._day_start_balance = config.starting_balance
        self._trades_today = 0
        self._consecutive_losses = 0

    # ── daily tracking ──────────────────────────────────────────────────────
    def _roll_day(self, today: date) -> None:
        if self._day != today:
            self._day = today
            self._day_start_balance = self.balance
            self._trades_today = 0
            self._consecutive_losses = 0

    def halt_reason(self, today: date) -> Optional[str]:
        """Return why trading is paused today, or None if it's allowed."""
        self._roll_day(today)
        c = self.config
        change = self.balance - self._day_start_balance  # +profit / -loss today
        if c.max_daily_loss_pct > 0:
            limit = self._day_start_balance * (c.max_daily_loss_pct / 100.0)
            if -change >= limit:
                return f"daily loss limit hit ({c.max_daily_loss_pct}%)"
        if c.daily_profit_target_pct > 0:
            target = self._day_start_balance * (c.daily_profit_target_pct / 100.0)
            if change >= target:
                return f"daily profit target reached ({c.daily_profit_target_pct}%)"
        if c.max_trades_per_day > 0 and self._trades_today >= c.max_trades_per_day:
            return f"max trades per day reached ({c.max_trades_per_day})"
        if c.max_consecutive_losses > 0 and self._consecutive_losses >= c.max_consecutive_losses:
            return f"{c.max_consecutive_losses} losses in a row, pausing for the day"
        return None

    def trading_halted_for_day(self, today: date) -> bool:
        """True if any daily guard is tripped."""
        return self.halt_reason(today) is not None

    def on_trade_opened(self, today: date) -> None:
        """Count a newly opened trade toward the daily trade cap."""
        self._roll_day(today)
        self._trades_today += 1

    def on_trade_closed(self, pnl: float) -> None:
        """Update balance and the losing-streak counter after a trade closes."""
        self.balance += pnl
        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

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
