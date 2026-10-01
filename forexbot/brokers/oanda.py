"""OANDA broker adapter (for demo/live trading later).

This is a thin wrapper over OANDA's v20 REST API. It is intentionally NOT wired into the
backtest path — backtesting needs no broker. When you're ready to paper-trade:

    1. pip install oandapyV20
    2. Open a free OANDA demo account, get an account id + API token.
    3. Fill in config.yaml (see config.example.yaml).
    4. Build scripts/run_live.py that loops: fetch candles -> strategy -> place_order.

Everything here degrades gracefully if `oandapyV20` isn't installed, so importing the
package for backtesting never fails.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from ..core.types import Candle, Order
from .base import Broker

_GRANULARITY_MAP = {
    "M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30",
    "H1": "H1", "H4": "H4", "D": "D", "W": "W",
}


class OandaBroker(Broker):
    def __init__(self, account_id: str, access_token: str, environment: str = "practice"):
        if environment not in ("practice", "live"):
            raise ValueError("environment must be 'practice' or 'live'")
        try:
            from oandapyV20 import API  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "oandapyV20 is required for live trading. Install with:\n"
                "    pip install oandapyV20"
            ) from exc

        self.account_id = account_id
        self.environment = environment
        self._api = API(access_token=access_token, environment=environment)

    def get_candles(self, instrument: str, granularity: str, count: int) -> List[Candle]:
        from oandapyV20.endpoints import instruments  # type: ignore

        gran = _GRANULARITY_MAP.get(granularity, granularity)
        params = {"granularity": gran, "count": count, "price": "M"}
        req = instruments.InstrumentsCandles(instrument=instrument, params=params)
        resp = self._api.request(req)
        candles: List[Candle] = []
        for c in resp.get("candles", []):
            if not c.get("complete", False):
                continue  # skip the still-forming current bar
            mid = c["mid"]
            candles.append(
                Candle(
                    time=datetime.fromisoformat(c["time"].replace("Z", "+00:00")),
                    open=float(mid["o"]),
                    high=float(mid["h"]),
                    low=float(mid["l"]),
                    close=float(mid["c"]),
                    volume=float(c.get("volume", 0)),
                )
            )
        return candles

    def account_balance(self) -> float:
        from oandapyV20.endpoints import accounts  # type: ignore

        req = accounts.AccountSummary(accountID=self.account_id)
        resp = self._api.request(req)
        return float(resp["account"]["balance"])

    def has_open_position(self, instrument: str) -> bool:
        from oandapyV20.endpoints import positions  # type: ignore

        req = positions.OpenPositions(accountID=self.account_id)
        resp = self._api.request(req)
        return any(p["instrument"] == instrument for p in resp.get("positions", []))

    def place_order(self, instrument: str, order: Order) -> str:
        from oandapyV20.endpoints import orders  # type: ignore

        # OANDA expects integer units, signed for direction.
        units = int(round(order.units)) * order.side.sign
        data = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": f"{order.stop_loss:.5f}"},
            }
        }
        if order.take_profit is not None:
            data["order"]["takeProfitOnFill"] = {"price": f"{order.take_profit:.5f}"}

        req = orders.OrderCreate(accountID=self.account_id, data=data)
        resp = self._api.request(req)
        fill = resp.get("orderFillTransaction") or {}
        return fill.get("id", "")
