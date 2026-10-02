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


def _parse_instruments(instrument) -> List[str]:
    """Accept 'EURUSD', 'EURUSD,GBPUSD', or a list -> clean list of symbols."""
    if isinstance(instrument, (list, tuple)):
        raw = list(instrument)
    else:
        raw = str(instrument or "").replace(";", ",").replace(" ", ",").split(",")
    seen, out = set(), []
    for s in raw:
        s = s.strip().upper()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out or ["EURUSD"]


class LiveTrader:
    def __init__(
        self,
        broker: Broker,
        risk_config: RiskConfig,
        instrument,                       # str, comma-separated str, or list
        granularity: str,
        strategy: Optional[Strategy] = None,       # single-pair: one strategy object
        strategy_name: Optional[str] = None,       # multi-pair: build one per pair
        history_count: int = 200,
        poll_seconds: Optional[float] = None,
        max_iterations: Optional[int] = None,
        dry_run: bool = False,
        telegram_chat_id: Optional[str] = None,
    ) -> None:
        from ..strategies import get_strategy
        self.broker = broker
        self.risk = RiskManager(risk_config)
        self.instruments = _parse_instruments(instrument)
        self.instrument = self.instruments[0]      # primary (for chart/state compat)
        self.granularity = granularity
        # One INDEPENDENT strategy instance per pair, so each keeps its own key levels.
        if strategy_name:
            self.strategies = {s: get_strategy(strategy_name) for s in self.instruments}
        elif strategy is not None and len(self.instruments) == 1:
            self.strategies = {self.instruments[0]: strategy}
        elif strategy is not None:
            # A single object was given but we have several pairs -> rebuild per pair
            # from its registry name so they don't share state.
            name = getattr(type(strategy), "_registry_name", None)
            self.strategies = {s: (strategy if i == 0 else get_strategy(name))
                               for i, s in enumerate(self.instruments)} if name else \
                              {s: strategy for s in self.instruments}
        else:
            raise ValueError("LiveTrader needs strategy or strategy_name")
        self.strategy = self.strategies[self.instrument]   # primary (compat)
        self.history_count = history_count
        self.poll_seconds = poll_seconds or _POLL_SECONDS.get(granularity, 60)
        self.max_iterations = max_iterations
        self.dry_run = dry_run
        self.telegram_chat_id = telegram_chat_id  # THIS user's own Telegram
        self._last_candle_time: dict = {}          # per-instrument last acted candle
        self._halt_notified = False

    def _alert(self, message: str) -> None:
        """Send an alert to this user's own Telegram (if they've set a chat id)."""
        if self.telegram_chat_id:
            send_telegram_to(self.telegram_chat_id, message)

    def run(self) -> None:
        mode = "DRY-RUN (no orders)" if self.dry_run else "LIVE"
        log.info("Starting %s | %s | %s %s | strategy=%s | poll=%ss | alerts=%s",
                 mode, type(self.broker).__name__, ",".join(self.instruments),
                 self.granularity, self.strategy.name, self.poll_seconds,
                 "telegram" if self.telegram_chat_id else "none")
        for s in self.strategies.values():
            s.on_start()

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
        # Keep the risk manager's balance in sync with the real account (once/cycle).
        try:
            self.risk.balance = self.broker.account_balance()
        except Exception:  # noqa: BLE001
            pass
        # Scan every pair the formula watches; trade whichever gives a setup.
        for inst in self.instruments:
            try:
                self._scan_instrument(inst)
            except Exception:  # keep scanning the others if one pair errors
                log.exception("scan error on %s — continuing", inst)

    def _scan_instrument(self, inst: str) -> None:
        candles = self.broker.get_candles(inst, self.granularity, self.history_count)
        if len(candles) < 30:
            return
        latest = candles[-1]

        # Only act once per completed candle, per pair.
        if self._last_candle_time.get(inst) == latest.time:
            return
        self._last_candle_time[inst] = latest.time

        strategy = self.strategies[inst]
        strategy.prepare(candles)  # precompute indicators over the window (cheap)

        if self.broker.has_open_position(inst):
            return  # one position per pair; broker manages its SL/TP

        halt = self.risk.halt_reason(latest.time.date())  # account-wide
        if halt:
            log.warning("Trading paused: %s", halt)
            if not self._halt_notified:
                self._alert(f"Trading paused for today, {halt}.")
                self._halt_notified = True
            return
        self._halt_notified = False  # reset once a new day / no longer halted

        # Cap total simultaneous positions across all pairs.
        cap = self.risk.config.max_open_positions
        if cap and cap > 0:
            try:
                if len(self.broker.open_positions()) >= cap:
                    return
            except Exception:  # noqa: BLE001
                pass

        signal = strategy.on_candle(latest, candles, None)
        if signal is None:
            return

        order = self.risk.size_order(signal, latest.close)
        if order is None:
            log.warning("%s signal %s ignored: could not size safely.",
                        inst, signal.side.value)
            return

        if self.dry_run:
            log.info("[DRY-RUN] %s would %s %.0f units @ ~%.5f  sl=%.5f tp=%s  (%s)",
                     inst, order.side.value, order.units, latest.close, order.stop_loss,
                     f"{order.take_profit:.5f}" if order.take_profit else "none",
                     order.reason)
            return

        order_id = self.broker.place_order(inst, order)
        self.risk.on_trade_opened(latest.time.date())
        log.info("Placed order %s on %s: %s %.0f units (%s)",
                 order_id, inst, order.side.value, order.units, order.reason)
        self._alert(
            f"{inst} {order.side.value} {order.units:.0f} units\n"
            f"entry ~{latest.close:.5f}  stop {order.stop_loss:.5f}  "
            f"target {f'{order.take_profit:.5f}' if order.take_profit else 'none'}\n"
            f"reason: {order.reason}  (order {order_id})"
        )
