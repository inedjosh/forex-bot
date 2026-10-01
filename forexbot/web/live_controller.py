"""Runs a live/practice trading loop in a background thread for the web UI.

- **Practice** mode uses the SimulatedBroker, so it runs on any computer (great for
  learning what live trading feels like, with fake money and no broker account).
- **Live** mode uses the MT5 broker (Windows/VPS only). On a Mac it will report that
  MetaTrader5 isn't available, which is expected.

The controller captures the bot's log lines and current state (balance, open position)
so the browser can poll and display them.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

from ..config import env_float, env_str
from ..risk import RiskConfig
from ..strategies import get_strategy

_log = logging.getLogger("forexbot")


class _BufferHandler(logging.Handler):
    """A logging handler that keeps the most recent lines in a ring buffer."""

    def __init__(self, buf: deque) -> None:
        super().__init__()
        self.buf = buf

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buf.append(self.format(record))
        except Exception:  # pragma: no cover
            pass


class LiveController:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.logs: deque = deque(maxlen=300)
        self.mode: str | None = None
        self.dry_run = False
        self.running = False
        self.finished = False
        self.error: str | None = None
        self.broker = None
        self.instrument = "EURUSD"
        self.start_balance = 0.0
        self.email = None  # set by the app so closed trades can be saved per user
        self.telegram_chat_id = None
        self._handler = _BufferHandler(self.logs)
        self._handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    # ── control ──────────────────────────────────────────────────────────────
    def start(self, mode: str, dry_run: bool = False, csv_path: str | None = None,
              tick: float = 0.7, bars: int = 1500, seed: int = 42,
              mt5: dict | None = None, instrument: str | None = None,
              telegram_chat_id: str | None = None):
        self.telegram_chat_id = telegram_chat_id
        if self.running:
            return False, "A run is already in progress. Stop it first."

        self.logs.clear()
        self.error = None
        self.finished = False
        self.mode = mode
        self.dry_run = dry_run

        try:
            if mode == "practice":
                from ..brokers import SimulatedBroker
                from ..data import load_csv, synthetic_candles
                candles = (load_csv(csv_path) if csv_path else
                           synthetic_candles(n=bars, seed=seed))
                self.broker = SimulatedBroker(
                    candles, starting_balance=env_float("STARTING_BALANCE", 10_000.0))
                is_sim = True
            else:  # "live" — uses THIS user's own MT5 account credentials
                from ..brokers import Mt5Broker
                mt5 = mt5 or {}
                self.broker = Mt5Broker(
                    login=int(mt5.get("login") or "0"),
                    password=mt5.get("password", ""),
                    server=mt5.get("server", ""))
                is_sim = False
        except Exception as exc:  # noqa: BLE001 — surface setup errors to the UI
            self.error = str(exc)
            return False, str(exc)

        self.instrument = instrument or env_str("INSTRUMENT", "EURUSD")
        try:
            self.start_balance = self.broker.account_balance()
        except Exception:  # noqa: BLE001
            self.start_balance = env_float("STARTING_BALANCE", 10_000.0)

        if self._handler not in _log.handlers:
            _log.addHandler(self._handler)
            _log.setLevel(logging.INFO)

        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._run, args=(is_sim, tick), daemon=True)
        self._thread.start()
        return True, "started"

    def _save_closed_trades(self) -> None:
        if self.broker is None or not self.email:
            return
        try:
            from . import auth
            for t in self.broker.drain_closed_trades():
                t.setdefault("instrument", self.instrument)
                auth.add_trade(self.email, self.mode, t)
        except Exception:  # noqa: BLE001 — never let history writing break trading
            pass

    def stop(self):
        self._stop.set()
        return True

    # ── the loop ─────────────────────────────────────────────────────────────
    def _run(self, is_sim: bool, tick: float) -> None:
        from ..live import LiveTrader
        try:
            trader = LiveTrader(
                broker=self.broker,
                strategy=get_strategy(env_str("STRATEGY", "crt")),
                risk_config=RiskConfig(
                    starting_balance=self.start_balance,
                    risk_pct=env_float("RISK_PCT", 1.0)),
                instrument=self.instrument,
                granularity=env_str("GRANULARITY", "D"),
                dry_run=self.dry_run,
                telegram_chat_id=self.telegram_chat_id,
            )
            trader.strategy.on_start()
            _log.info("Started %s mode on %s  (%s)", self.mode, self.instrument,
                      "DRY-RUN, no orders" if self.dry_run else "placing orders")

            while not self._stop.is_set():
                if is_sim:
                    has_more = self.broker.wait_next(0)  # advance one bar instantly
                    trader._cycle()
                    self._save_closed_trades()
                    if not has_more:
                        _log.info("Practice data finished. Final balance %.2f",
                                  self.broker.account_balance())
                        break
                    time.sleep(tick)  # pace it so the browser can watch
                else:
                    trader._cycle()
                    self._save_closed_trades()
                    self.broker.wait_next(max(tick, 5.0))  # real broker: poll cadence
            else:
                _log.info("Stopped by user.")
            self._save_closed_trades()
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            _log.info("Stopped on error: %s", exc)
        finally:
            self.running = False
            self.finished = True

    # ── status for the browser ───────────────────────────────────────────────
    def state(self) -> dict:
        bal = 0.0
        pos = None
        prices = []
        if self.broker is not None:
            try:
                bal = self.broker.account_balance()
            except Exception:  # noqa: BLE001
                bal = self.start_balance
            try:
                pos = self.broker.position_info(self.instrument)
            except Exception:  # noqa: BLE001
                pos = None
            try:
                gran = env_str("GRANULARITY", "D")
                candles = self.broker.get_candles(self.instrument, gran, 120)
                prices = [round(c.close, 5) for c in candles]
            except Exception:  # noqa: BLE001
                prices = []
        return {
            "prices": prices,
            "running": self.running,
            "finished": self.finished,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "error": self.error,
            "balance": round(bal, 2),
            "start_balance": round(self.start_balance, 2),
            "pnl": round(bal - self.start_balance, 2),
            "instrument": self.instrument,
            "position": pos,
            "log": list(self.logs)[-40:],
        }
