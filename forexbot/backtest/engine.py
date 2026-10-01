"""Historical replay engine.

Feeds candles one at a time to a strategy — exactly as they'll arrive live — manages the
open position, checks stop-loss/take-profit against each new bar, and records completed
trades. Then computes performance statistics.

Important modeling choices (kept realistic but simple):
  - Signals act on the *close* of the bar that produced them, entering at that close.
    (No look-ahead: the strategy only ever sees candles up to and including the current.)
  - Stops/targets are checked against the *next* bars' high/low ranges.
  - If a single bar's range spans both stop and target, we assume the stop hit first
    (conservative / pessimistic).
  - A `spread` (in price units) is deducted on entry to approximate transaction cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..core.strategy import Strategy
from ..core.types import Candle, Position, Side, Trade
from ..risk import RiskConfig, RiskManager


@dataclass
class BacktestResult:
    strategy_name: str
    starting_balance: float
    ending_balance: float
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)

    # ── summary stats ──────────────────────────────────────────────────────
    @property
    def net_pnl(self) -> float:
        return self.ending_balance - self.starting_balance

    @property
    def return_pct(self) -> float:
        if self.starting_balance == 0:
            return 0.0
        return 100.0 * self.net_pnl / self.starting_balance

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> List[Trade]:
        return [t for t in self.trades if t.won]

    @property
    def losses(self) -> List[Trade]:
        return [t for t in self.trades if not t.won]

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return 100.0 * len(self.wins) / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t.pnl for t in self.wins)
        gross_loss = -sum(t.pnl for t in self.losses)
        if gross_loss == 0:
            return float("inf") if gross_win > 0 else 0.0
        return gross_win / gross_loss

    @property
    def max_drawdown_pct(self) -> float:
        """Largest peak-to-trough drop of the equity curve, as a percentage."""
        peak = float("-inf")
        max_dd = 0.0
        for eq in self.equity_curve:
            peak = max(peak, eq)
            if peak > 0:
                dd = (peak - eq) / peak
                max_dd = max(max_dd, dd)
        return 100.0 * max_dd

    def summary(self) -> str:
        lines = [
            f"Strategy        : {self.strategy_name}",
            f"Trades          : {self.num_trades}  ({len(self.wins)}W / {len(self.losses)}L)",
            f"Win rate        : {self.win_rate:.1f}%",
            f"Profit factor   : {self.profit_factor:.2f}",
            f"Net P&L         : {self.net_pnl:+,.2f}  ({self.return_pct:+.2f}%)",
            f"Start / End bal : {self.starting_balance:,.2f} -> {self.ending_balance:,.2f}",
            f"Max drawdown    : {self.max_drawdown_pct:.2f}%",
        ]
        return "\n".join(lines)


class BacktestEngine:
    def __init__(
        self,
        risk_config: Optional[RiskConfig] = None,
        spread: float = 0.0001,          # ~1 pip on a 5-decimal pair
        warmup: int = 0,                 # bars to skip before allowing trades
    ) -> None:
        self.risk_config = risk_config or RiskConfig()
        self.spread = spread
        self.warmup = warmup

    def run(self, strategy: Strategy, candles: List[Candle]) -> BacktestResult:
        risk = RiskManager(self.risk_config)
        strategy.on_start()
        strategy.prepare(candles)  # precompute indicators once (O(n) not O(n²))

        position: Optional[Position] = None
        trades: List[Trade] = []
        equity_curve: List[float] = [risk.balance]

        for idx, candle in enumerate(candles):
            # 1) Manage an open position first: did this bar hit stop or target?
            if position is not None:
                exit_price, reason = self._check_exit(position, candle)
                if exit_price is not None:
                    trade = self._close(position, exit_price, candle, reason)
                    risk.on_trade_closed(trade.pnl)
                    trades.append(trade)
                    position = None

            # 2) Ask the strategy for a signal on this closed bar.
            history = candles[: idx + 1]
            if position is None and idx >= self.warmup:
                if not risk.trading_halted_for_day(candle.time.date()):
                    signal = strategy.on_candle(candle, history, None)
                    if signal is not None:
                        position = self._open(signal, candle, risk)

            # 3) Mark-to-market equity for the drawdown curve.
            unrealized = position.unrealized_pnl(candle.close) if position else 0.0
            equity_curve.append(risk.balance + unrealized)

        # Close any position still open at the end of the data.
        if position is not None and candles:
            last = candles[-1]
            trade = self._close(position, last.close, last, "end_of_data")
            risk.on_trade_closed(trade.pnl)
            trades.append(trade)
            equity_curve.append(risk.balance)

        return BacktestResult(
            strategy_name=strategy.name,
            starting_balance=self.risk_config.starting_balance,
            ending_balance=risk.balance,
            trades=trades,
            equity_curve=equity_curve,
        )

    # ── helpers ─────────────────────────────────────────────────────────────
    def _open(self, signal, candle: Candle, risk: RiskManager) -> Optional[Position]:
        # Apply spread as a worse entry price.
        entry = candle.close + self.spread * signal.side.sign
        order = risk.size_order(signal, entry)
        if order is None:
            return None
        return Position(
            side=order.side,
            units=order.units,
            entry_price=entry,
            entry_time=candle.time,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            reason=order.reason,
        )

    def _check_exit(self, pos: Position, candle: Candle):
        """Return (exit_price, reason) if the bar hits stop/target, else (None, '')."""
        if pos.side is Side.BUY:
            hit_stop = candle.low <= pos.stop_loss
            hit_tp = pos.take_profit is not None and candle.high >= pos.take_profit
        else:  # SELL
            hit_stop = candle.high >= pos.stop_loss
            hit_tp = pos.take_profit is not None and candle.low <= pos.take_profit

        # Pessimistic: if both could hit in the same bar, assume the stop hit first.
        if hit_stop:
            return pos.stop_loss, "stop_loss"
        if hit_tp:
            return pos.take_profit, "take_profit"
        return None, ""

    def _close(self, pos: Position, exit_price: float, candle: Candle, reason: str) -> Trade:
        pnl = (exit_price - pos.entry_price) * pos.side.sign * pos.units
        return Trade(
            side=pos.side,
            units=pos.units,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=candle.time,
            pnl=pnl,
            exit_reason=reason,
            reason=pos.reason,
        )
