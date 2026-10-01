"""MetaTrader 5 broker adapter — for brokers that accept Nigerian clients.

Works with any MT5 broker (IC Markets, Pepperstone, FP Markets, Exness, XM, ...).
Uses the official `MetaTrader5` Python package, which talks to a running MT5 terminal.

    ⚠️ Platform note: the `MetaTrader5` package is Windows-only. The standard way to run
    a 24/5 bot is a cheap Windows VPS with MT5 installed. This file imports lazily and
    degrades gracefully, so the rest of the project still works on macOS/Linux.

Setup on the Windows/VPS box:
    1. Install the MetaTrader 5 terminal and log into your broker account.
    2. pip install MetaTrader5
    3. Put credentials in .env:
         MT5_LOGIN=12345678
         MT5_PASSWORD=your-password
         MT5_SERVER=ICMarkets-Demo      (exact server name from the terminal)
         INSTRUMENT=EURUSD              (MT5 symbols usually have no underscore)
    4. python scripts/run_live.py --broker mt5 --dry-run
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from ..core.types import Candle, Order, Side
from .base import Broker

log = logging.getLogger("forexbot.mt5")

# Map our granularity strings to MT5 timeframe constants (resolved lazily).
_TIMEFRAME_NAMES = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D": "TIMEFRAME_D1", "W": "TIMEFRAME_W1",
}


class Mt5Broker(Broker):
    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        deviation: int = 20,
        magic: int = 456123,
    ) -> None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "MetaTrader5 is required for MT5 trading (Windows only).\n"
                "    pip install MetaTrader5"
            ) from exc

        self._mt5 = mt5

        # The Python bridge needs terminal64.exe. initialize() without a path often
        # can't find it, so try the known install locations explicitly (this also
        # launches the terminal headlessly). Set MT5_TERMINAL_PATH to override.
        import os
        from ..config import env_str
        candidates = [
            env_str("MT5_TERMINAL_PATH", ""),
            r"C:\Program Files\MetaTrader 5\terminal64.exe",
            r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
            os.path.expandvars(r"%APPDATA%\MetaQuotes\Terminal\terminal64.exe"),
        ]
        connected = False
        last = None
        for path in candidates:
            if path and os.path.exists(path):
                if mt5.initialize(path=path, login=int(login), password=password,
                                  server=server, timeout=60000):
                    connected = True
                    break
                last = mt5.last_error()
        if not connected:
            # Last resort: let the package auto-detect.
            if mt5.initialize(login=int(login), password=password, server=server, timeout=60000):
                connected = True
            else:
                last = mt5.last_error()
        if not connected:
            raise RuntimeError(
                f"Could not start MetaTrader 5: {last}. The terminal may not be installed "
                f"on the server. Install it, or set MT5_TERMINAL_PATH to terminal64.exe.")
        self.deviation = deviation
        self.magic = magic
        self._last_deal_time = 0  # for drain_closed_trades
        log.info("Connected to MT5 server=%s login=%s", server, login)

    def _round(self, instrument: str, price: float) -> float:
        """Round a price to the symbol's decimal digits (brokers reject over-precise stops)."""
        info = self._mt5.symbol_info(instrument)
        digits = getattr(info, "digits", 5) if info else 5
        return round(float(price), digits)

    def _timeframe(self, granularity: str):
        name = _TIMEFRAME_NAMES.get(granularity)
        if name is None:
            raise ValueError(f"Unsupported granularity for MT5: {granularity}")
        return getattr(self._mt5, name)

    def get_candles(self, instrument: str, granularity: str, count: int) -> List[Candle]:
        tf = self._timeframe(granularity)
        # Make sure the symbol is in Market Watch, or copy_rates returns None.
        self._mt5.symbol_select(instrument, True)
        # position 0 = current forming bar; start at 1 so we only get closed bars.
        rates = self._mt5.copy_rates_from_pos(instrument, tf, 1, count)
        if rates is None:
            log.warning("copy_rates_from_pos returned None: %s", self._mt5.last_error())
            return []
        candles: List[Candle] = []
        for r in rates:
            candles.append(
                Candle(
                    time=datetime.fromtimestamp(int(r["time"])),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["tick_volume"]),
                )
            )
        return candles

    def account_balance(self) -> float:
        info = self._mt5.account_info()
        if info is None:
            raise RuntimeError(f"account_info() failed: {self._mt5.last_error()}")
        return float(info.balance)

    def has_open_position(self, instrument: str) -> bool:
        positions = self._mt5.positions_get(symbol=instrument)
        return bool(positions)

    def position_info(self, instrument: str):
        positions = self._mt5.positions_get(symbol=instrument)
        if not positions:
            return None
        p = positions[0]
        side = "BUY" if p.type == self._mt5.POSITION_TYPE_BUY else "SELL"
        return {
            "side": side,
            "units": round(float(p.volume) * 100_000),  # lots -> units for display
            "entry": round(float(p.price_open), 5),
            "stop": round(float(p.sl), 5),
            "target": (round(float(p.tp), 5) if p.tp else None),
            "unrealized": round(float(p.profit), 2),
        }

    def place_order(self, instrument: str, order: Order) -> str:
        mt5 = self._mt5
        # Ensure the symbol is selected/visible in the terminal.
        if not mt5.symbol_select(instrument, True):
            raise RuntimeError(f"symbol_select({instrument}) failed: {mt5.last_error()}")

        tick = mt5.symbol_info_tick(instrument)
        if tick is None:
            raise RuntimeError(f"no tick for {instrument}: {mt5.last_error()}")

        if order.side is Side.BUY:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid

        # Convert units -> lots. Standard lot = 100,000 units. Round to broker step,
        # and clamp to the symbol's min/max allowed volume.
        info = mt5.symbol_info(instrument)
        step = getattr(info, "volume_step", 0.01) or 0.01
        min_lot = getattr(info, "volume_min", 0.01) or 0.01
        max_lot = getattr(info, "volume_max", 100.0) or 100.0
        lots = round((order.units / 100_000.0) / step) * step
        lots = max(min_lot, min(max_lot, round(lots, 2)))

        base = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": instrument,
            "volume": float(lots),
            "type": order_type,
            "price": self._round(instrument, price),
            "sl": self._round(instrument, order.stop_loss),
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": (order.reason or "forexbot")[:31],
            "type_time": mt5.ORDER_TIME_GTC,
        }
        if order.take_profit is not None:
            base["tp"] = self._round(instrument, order.take_profit)

        # Brokers accept different "filling modes"; the wrong one is rejected with
        # retcode 10030. Try the common ones in order until one is accepted.
        fillings = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        last = None
        for fill in fillings:
            result = mt5.order_send({**base, "type_filling": fill})
            last = result
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                log.info("MT5 order done: %s %.2f lots @ %.5f (ticket %s)",
                         order.side.value, lots, base["price"], result.order)
                return str(result.order)
            # Only keep trying on a filling-mode rejection; otherwise stop.
            if result is None or result.retcode != 10030:  # 10030 = unsupported filling
                break
        raise RuntimeError(f"order_send failed: {getattr(last, 'comment', None)} "
                           f"({getattr(last, 'retcode', '?')})")

    def drain_closed_trades(self) -> list:
        """Best-effort: report closing deals since the last check, from MT5 history."""
        mt5 = self._mt5
        try:
            import time as _t
            now = int(_t.time())
            since = self._last_deal_time or (now - 3600)
            deals = mt5.history_deals_get(since, now + 1)
            self._last_deal_time = now
            if not deals:
                return []
            out = []
            for d in deals:
                # entry == 1 (DEAL_ENTRY_OUT) marks a position-closing deal.
                if getattr(d, "entry", None) != getattr(mt5, "DEAL_ENTRY_OUT", 1):
                    continue
                side = "SELL" if d.type == mt5.DEAL_TYPE_BUY else "BUY"  # closing deal is opposite
                from datetime import datetime as _dt
                out.append({
                    "side": side, "units": round(float(d.volume) * 100_000),
                    "entry": None, "exit": round(float(d.price), 5),
                    "pnl": round(float(d.profit), 2), "reason": d.comment,
                    "exit_reason": "broker", "opened_at": None,
                    "closed_at": _dt.fromtimestamp(int(d.time)).isoformat(),
                })
            return out
        except Exception as exc:  # noqa: BLE001
            log.warning("drain_closed_trades failed: %s", exc)
            return []

    def shutdown(self) -> None:
        try:
            self._mt5.shutdown()
        except Exception:  # pragma: no cover
            pass
