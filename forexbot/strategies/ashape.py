"""
╔══════════════════════════════════════════════════════════════════════════╗
║  A-SHAPE / V-SHAPE KEY LEVEL  (the user's supply/demand + engulfing model)  ║
╠══════════════════════════════════════════════════════════════════════════╣
║  A-SHAPE (sell):  a BULLISH candle immediately followed by a BEARISH one    ║
║    forms a peak -> a supply zone (the "key level"). When price later        ║
║    RETURNS up into that zone and prints a BEARISH ENGULFING candle, SELL.    ║
║    Stop above the zone; target a reward:risk multiple below.                 ║
║                                                                            ║
║  V-SHAPE (buy): the mirror — a BEARISH then BULLISH candle forms a demand   ║
║    zone; price returns down into it + a BULLISH ENGULFING -> BUY.           ║
║                                                                            ║
║  NOTE: the original model reads the zone on 4H/2H and the engulfing on 1H.  ║
║  This v1 runs on ONE timeframe (whatever the bot is set to). Run it on your ║
║  execution timeframe (e.g. 1H). True multi-timeframe is a planned upgrade.  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

from typing import List, Optional

from ..config import env_bool, env_float, env_int
from ..core.strategy import Strategy
from ..core.types import Candle, Position, Side, Signal


def _bullish(c: Candle) -> bool:
    return c.close > c.open


def _bearish(c: Candle) -> bool:
    return c.close < c.open


def _bearish_engulf(c: Candle, p: Candle) -> bool:
    # current bearish, its body engulfs the prior candle's body
    return _bearish(c) and c.open >= p.close and c.close <= p.open


def _bullish_engulf(c: Candle, p: Candle) -> bool:
    return _bullish(c) and c.open <= p.close and c.close >= p.open


class AShapeKL(Strategy):
    name = "A-Shape / V-Shape Key Level"

    def __init__(
        self,
        risk_reward: Optional[float] = None,
        stop_buffer_pct: Optional[float] = None,
        max_age: Optional[int] = None,
        require_engulfing: Optional[bool] = None,
        require_return: Optional[bool] = None,
        trade_sells: Optional[bool] = None,
        trade_buys: Optional[bool] = None,
        htf_multiple: Optional[int] = None,
    ) -> None:
        self.risk_reward = risk_reward if risk_reward is not None else env_float("KL_RISK_REWARD", 2.0)
        self.stop_buffer_pct = stop_buffer_pct if stop_buffer_pct is not None else env_float("KL_STOP_BUFFER_PCT", 0.05)
        # How many candles a key level stays valid before we forget it.
        self.max_age = max_age if max_age is not None else env_int("KL_MAX_AGE", 40)
        # Require a bearish/bullish engulfing candle as confirmation (your model: yes).
        self.require_engulfing = require_engulfing if require_engulfing is not None else env_bool("KL_REQUIRE_ENGULFING", True)
        # Require price to leave the zone and RETURN before triggering (your model: yes).
        self.require_return = require_return if require_return is not None else env_bool("KL_REQUIRE_RETURN", True)
        self.trade_sells = trade_sells if trade_sells is not None else env_bool("KL_TRADE_SELLS", True)
        self.trade_buys = trade_buys if trade_buys is not None else env_bool("KL_TRADE_BUYS", True)
        # Higher-timeframe multiple: the key level is read on this many base candles grouped
        # together. e.g. bot on 1H with multiple=4 -> key levels come from 4H candles.
        self.htf_multiple = max(1, (htf_multiple if htf_multiple is not None else env_int("KL_HTF_MULTIPLE", 4)))
        self._zones: list = []    # active key levels (prices from the higher timeframe)
        self._htf: list = []      # completed higher-timeframe candles

    def _add_zone_from(self, a: Candle, b: Candle, idx: int) -> None:
        if self.trade_sells and _bullish(a) and _bearish(b):  # A-shape -> supply (sell)
            top, bottom = max(a.high, b.high), min(a.open, b.close)
            if top > bottom:
                self._zones.append({"type": "sell", "top": top, "bottom": bottom,
                                    "idx": idx, "armed": False, "used": False})
        if self.trade_buys and _bearish(a) and _bullish(b):  # V-shape -> demand (buy)
            bottom, top = min(a.low, b.low), max(a.open, b.close)
            if top > bottom:
                self._zones.append({"type": "buy", "top": top, "bottom": bottom,
                                    "idx": idx, "armed": False, "used": False})

    def on_candle(
        self,
        candle: Candle,
        history: List[Candle],
        position: Optional[Position],
    ) -> Optional[Signal]:
        if position is not None:
            return None
        i = len(history) - 1
        if i < 2:
            return None

        # When a higher-timeframe group just completed, build its candle and look for a
        # new key level from the last two HTF candles.
        n = self.htf_multiple
        if (i + 1) % n == 0 and i >= n - 1:
            grp = history[i - n + 1:i + 1]
            htf = Candle(time=grp[0].time, open=grp[0].open,
                         high=max(x.high for x in grp), low=min(x.low for x in grp),
                         close=grp[-1].close)
            self._htf.append(htf)
            if len(self._htf) >= 2:
                self._add_zone_from(self._htf[-2], self._htf[-1], i)

        c, prev = candle, history[i - 1]
        buf = self.stop_buffer_pct / 100.0
        signal: Optional[Signal] = None

        # 1) Update zones: arm (price moved away) + drop broken/old ones.
        kept = []
        for z in self._zones:
            if z["used"] or (i - z["idx"]) > self.max_age:
                continue
            if z["type"] == "sell":
                if c.close > z["top"]:      # price closed above supply -> invalid
                    continue
                if c.high < z["bottom"]:    # price dropped away below -> now armed to re-test
                    z["armed"] = True
            else:  # buy
                if c.close < z["bottom"]:   # closed below demand -> invalid
                    continue
                if c.low > z["top"]:        # price rose away above -> armed
                    z["armed"] = True
            kept.append(z)
        self._zones = kept

        # 2) Entry: price back in a zone + (engulfing confirmation).
        for z in self._zones:
            armed_ok = z["armed"] or not self.require_return
            touched = c.high >= z["bottom"] and c.low <= z["top"]
            if not (armed_ok and touched):
                continue
            if z["type"] == "sell" and self.trade_sells:
                if self.require_engulfing and not _bearish_engulf(c, prev):
                    continue
                if not self.require_engulfing and not _bearish(c):
                    continue
                entry = c.close
                sl = z["top"] * (1 + buf)
                risk = sl - entry
                if risk > 0:
                    tp = entry - self.risk_reward * risk
                    if tp < entry:
                        signal = Signal(Side.SELL, stop_loss=sl, take_profit=tp,
                                        reason="A-shape KL + bearish engulf")
                        z["used"] = True
                        break
            elif z["type"] == "buy" and self.trade_buys:
                if self.require_engulfing and not _bullish_engulf(c, prev):
                    continue
                if not self.require_engulfing and not _bullish(c):
                    continue
                entry = c.close
                sl = z["bottom"] * (1 - buf)
                risk = entry - sl
                if risk > 0:
                    tp = entry + self.risk_reward * risk
                    if tp > entry:
                        signal = Signal(Side.BUY, stop_loss=sl, take_profit=tp,
                                        reason="V-shape KL + bullish engulf")
                        z["used"] = True
                        break

        return signal
