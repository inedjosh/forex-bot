"""The live trading loop — works against ANY broker (real or simulated).

This is deliberately the same shape as the backtest engine, so a strategy behaves
identically across backtest -> sim -> demo -> live. The only difference is where candles
and fills come from.

Each cycle:
  1. Fetch the most recent candles from the broker.
  2. Act only when a *new* completed candle appears (avoids duplicate signals).
  3. Sync account balance from the broker (for correct position sizing).
  4. If flat, not halted by the daily-loss guard, and the strategy fires a signal:
     size the order via the RiskManager and place it (or log it, in dry-run).
  5. Wait for the next candle.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from ..brokers.base import Broker
from ..core.strategy import Strategy
from ..notify import send_telegram_to
from ..risk import RiskConfig, RiskManager

log = logging.getLogger("forexbot.live")

# Poll cadence per granularity (seconds). Real brokers poll faster than the bar so a
# freshly-closed candle is picked up promptly; the loop only acts on new candles.
_POLL_SECONDS = {
    "M1": 10, "M5": 20, "M15": 30, "M30": 45,
    "H1": 60, "H4": 120, "D": 300, "W": 600,
}


class LiveTrader:
    def __init__(
        self,
        broker: Broker,
        strategy: Strategy,
        risk_config: RiskConfig,
        instrument: str,
        granularity: str,
        history_count: int = 200,
        poll_seconds: Optional[float] = None,
        max_iterations: Optional[int] = None,
        dry_run: bool = False,
        telegram_chat_id: Optional[str] = None,
    ) -> None:
        self.broker = broker
        self.strategy = strategy
        self.risk = RiskManager(risk_config)
        self.instrument = instrument
        self.granularity = granularity
        self.history_count = history_count
        self.poll_seconds = poll_seconds or _POLL_SECONDS.get(granularity, 60)
        self.max_iterations = max_iterations
        self.dry_run = dry_run
        self.telegram_chat_id = telegram_chat_id  # THIS user's own Telegram
        self._last_candle_time: Optional[datetime] = None
        self._halt_notified = False

    def _alert(self, message: str) -> None:
        """Send an alert to this user's own Telegram (if they've set a chat id)."""
        if self.telegram_chat_id:
            send_telegram_to(self.telegram_chat_id, message)

    def run(self) -> None:
        mode = "DRY-RUN (no orders)" if self.dry_run else "LIVE"
        log.info("Starting %s | %s | %s %s | strategy=%s | poll=%ss | alerts=%s",
                 mode, type(self.broker).__name__, self.instrument,
                 self.granularity, self.strategy.name, self.poll_seconds,
                 "telegram" if self.telegram_chat_id else "none")
        self.strategy.on_start()

        iterations = 0
        while True:
            try:
                self._cycle()
            except Exception:  # keep the bot alive across transient broker errors
                log.exception("cycle error — continuing")

            iterations += 1
            if self.max_iterations is not None and iterations >= self.max_iterations:
                log.info("Reached max_iterations=%d, stopping.", self.max_iterations)
                break

            if not self.broker.wait_next(self.poll_seconds):
                log.info("Broker signalled no more data, stopping.")
                break

    def _cycle(self) -> None:
        candles = self.broker.get_candles(
            self.instrument, self.granularity, self.history_count
        )
        if len(candles) < 30:
            return
        latest = candles[-1]

        # Only act once per completed candle.
        if self._last_candle_time == latest.time:
            return
        self._last_candle_time = latest.time

        # Precompute indicators over the current window (cheap; ~history_count bars).
        self.strategy.prepare(candles)

        # Keep the risk manager's balance in sync with the real account.
        self.risk.balance = self.broker.account_balance()

        if self.broker.has_open_position(self.instrument):
            return  # one position at a time; broker manages its SL/TP

        halt = self.risk.halt_reason(latest.time.date())
        if halt:
            log.warning("Trading paused: %s", halt)
            if not self._halt_notified:
                self._alert(f"{self.instrument}: trading paused for today, {halt}.")
                self._halt_notified = True
            return
        self._halt_notified = False  # reset once a new day / no longer halted

        signal = self.strategy.on_candle(latest, candles, None)
        if signal is None:
            return

        order = self.risk.size_order(signal, latest.close)
        if order is None:
            log.warning("Signal %s ignored: could not size safely.", signal.side.value)
            return

        if self.dry_run:
            log.info("[DRY-RUN] would %s %.0f units @ ~%.5f  sl=%.5f tp=%s  (%s)",
                     order.side.value, order.units, latest.close, order.stop_loss,
                     f"{order.take_profit:.5f}" if order.take_profit else "none",
                     order.reason)
            return

        order_id = self.broker.place_order(self.instrument, order)
        self.risk.on_trade_opened(latest.time.date())
        log.info("Placed order %s: %s %.0f units (%s)",
                 order_id, order.side.value, order.units, order.reason)
        self._alert(
            f"{self.instrument} {order.side.value} {order.units:.0f} units\n"
            f"entry ~{latest.close:.5f}  stop {order.stop_loss:.5f}  "
            f"target {f'{order.take_profit:.5f}' if order.take_profit else 'none'}\n"
            f"reason: {order.reason}  (order {order_id})"
        )
