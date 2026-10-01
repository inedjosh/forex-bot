"""A simulated broker for exercising the live trading loop without a real account.

It replays a candle series through the *same* Broker interface OANDA implements, so the
LiveTrader loop can be run and tested end-to-end with zero credentials. Positions,
stop-loss/take-profit fills, and account balance are all simulated locally.

This is the bridge between backtesting and real money: same loop, same strategy, same
risk manager — only the broker is fake.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from ..core.types import Candle, Order, Position, Side
from .base import Broker

log = logging.getLogger("forexbot.sim")


class SimulatedBroker(Broker):
    def __init__(
        self,
        candles: List[Candle],
        starting_balance: float = 10_000.0,
        spread: float = 0.0001,
        warmup: int = 50,
    ) -> None:
        if len(candles) <= warmup + 1:
            raise ValueError("not enough candles for the requested warmup")
        self._candles = candles
        self._cursor = warmup            # index of the "current" (latest closed) candle
        self._balance = starting_balance
        self._spread = spread
        self._position: Optional[Position] = None
        self._closed: list = []          # trades closed since the last drain

    # ── clock: advance one candle, processing any stop/target fills ─────────
    def wait_next(self, poll_seconds: float) -> bool:
        """Advance simulated time by one bar. Returns False when data is exhausted."""
        if self._cursor >= len(self._candles) - 1:
            return False
        self._cursor += 1
        self._process_bar(self._candles[self._cursor])
        return True

    def _process_bar(self, candle: Candle) -> None:
        pos = self._position
        if pos is None:
            return
        if pos.side is Side.BUY:
            hit_stop = candle.low <= pos.stop_loss
            hit_tp = pos.take_profit is not None and candle.high >= pos.take_profit
        else:
            hit_stop = candle.high >= pos.stop_loss
            hit_tp = pos.take_profit is not None and candle.low <= pos.take_profit

        exit_price = reason = None
        if hit_stop:                                   # pessimistic: stop before target
            exit_price, reason = pos.stop_loss, "stop_loss"
        elif hit_tp:
            exit_price, reason = pos.take_profit, "take_profit"

        if exit_price is not None:
            pnl = (exit_price - pos.entry_price) * pos.side.sign * pos.units
            self._balance += pnl
            log.info("CLOSE %s @ %.5f (%s)  pnl=%.2f  balance=%.2f",
                     pos.side.value, exit_price, reason, pnl, self._balance)
            self._closed.append({
                "side": pos.side.value, "units": round(pos.units),
                "entry": round(pos.entry_price, 5), "exit": round(exit_price, 5),
                "pnl": round(pnl, 2), "reason": pos.reason, "exit_reason": reason,
                "opened_at": pos.entry_time.isoformat(), "closed_at": candle.time.isoformat(),
            })
            self._position = None

    def drain_closed_trades(self) -> list:
        out = self._closed
        self._closed = []
        return out

    # ── Broker interface ────────────────────────────────────────────────────
    def get_candles(self, instrument: str, granularity: str, count: int) -> List[Candle]:
        end = self._cursor + 1
        start = max(0, end - count)
        return self._candles[start:end]

    def account_balance(self) -> float:
        return self._balance

    def has_open_position(self, instrument: str) -> bool:
        return self._position is not None

    def position_info(self, instrument: str):
        p = self._position
        if p is None:
            return None
        price = self._candles[self._cursor].close
        return {
            "side": p.side.value,
            "units": round(p.units, 0),
            "entry": round(p.entry_price, 5),
            "stop": round(p.stop_loss, 5),
            "target": (round(p.take_profit, 5) if p.take_profit else None),
            "unrealized": round(p.unrealized_pnl(price), 2),
        }

    def place_order(self, instrument: str, order: Order) -> str:
        candle = self._candles[self._cursor]
        entry = candle.close + self._spread * order.side.sign
        self._position = Position(
            side=order.side,
            units=order.units,
            entry_price=entry,
            entry_time=candle.time,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            reason=order.reason,
        )
        log.info("OPEN  %s %.0f units @ %.5f  sl=%.5f tp=%s  (%s)",
                 order.side.value, order.units, entry, order.stop_loss,
                 f"{order.take_profit:.5f}" if order.take_profit else "none", order.reason)
        return f"sim-{self._cursor}"
