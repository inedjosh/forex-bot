"""Walk-forward validation — the antidote to curve-fitting.

Optimizing parameters on all your data and then quoting that return is self-deception:
you've fit the noise. Walk-forward instead:

    1. Split the data into consecutive windows.
    2. Optimize on an in-sample (IS) window.
    3. Apply those winning params to the *next, unseen* out-of-sample (OOS) window.
    4. Roll forward and repeat.

The stitched-together OOS results approximate how the strategy would actually have traded
live, where you never get to see the future. If IS looks great but OOS is poor, the
"edge" was an illusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from ..backtest import BacktestEngine, BacktestResult
from ..core.types import Candle, Trade
from ..risk import RiskConfig
from ..strategies.crt import CrtStrategy
from .grid import grid_search


@dataclass
class WalkForwardResult:
    windows: int
    oos_trades: List[Trade] = field(default_factory=list)
    chosen_params: List[Dict[str, float]] = field(default_factory=list)
    starting_balance: float = 10_000.0
    ending_balance: float = 10_000.0

    @property
    def net_pnl(self) -> float:
        return self.ending_balance - self.starting_balance

    @property
    def return_pct(self) -> float:
        return 100.0 * self.net_pnl / self.starting_balance if self.starting_balance else 0.0

    @property
    def num_trades(self) -> int:
        return len(self.oos_trades)

    @property
    def win_rate(self) -> float:
        if not self.oos_trades:
            return 0.0
        return 100.0 * sum(t.won for t in self.oos_trades) / len(self.oos_trades)

    def summary(self) -> str:
        lines = [
            "Walk-forward (out-of-sample, stitched)",
            f"Windows         : {self.windows}",
            f"OOS trades      : {self.num_trades}",
            f"OOS win rate    : {self.win_rate:.1f}%",
            f"OOS net P&L     : {self.net_pnl:+,.2f}  ({self.return_pct:+.2f}%)",
            f"Start / End bal : {self.starting_balance:,.2f} -> {self.ending_balance:,.2f}",
        ]
        return "\n".join(lines)


def walk_forward(
    candles: List[Candle],
    grid: Dict[str, Sequence] | None = None,
    is_bars: int = 1000,
    oos_bars: int = 300,
    starting_balance: float = 10_000.0,
    risk_pct: float = 1.0,
    spread: float = 0.0001,
    min_trades: int = 5,
) -> WalkForwardResult:
    """Roll IS-optimize -> OOS-test across the data. Balance compounds across windows."""
    wf = WalkForwardResult(windows=0, starting_balance=starting_balance,
                           ending_balance=starting_balance)
    balance = starting_balance
    start = 0
    while start + is_bars + oos_bars <= len(candles):
        is_slice = candles[start : start + is_bars]
        oos_slice = candles[start + is_bars : start + is_bars + oos_bars]

        # Optimize on in-sample.
        ranked = grid_search(
            is_slice, grid=grid,
            risk_config=RiskConfig(starting_balance=balance, risk_pct=risk_pct),
            spread=spread, min_trades=min_trades,
        )
        if not ranked or ranked[0].score == float("-inf"):
            start += oos_bars
            continue
        best = ranked[0].params

        # Apply winning params to out-of-sample, compounding the balance.
        engine = BacktestEngine(
            risk_config=RiskConfig(starting_balance=balance, risk_pct=risk_pct),
            spread=spread,
        )
        oos_result: BacktestResult = engine.run(CrtStrategy(**best), oos_slice)
        balance = oos_result.ending_balance

        wf.windows += 1
        wf.oos_trades.extend(oos_result.trades)
        wf.chosen_params.append(best)
        start += oos_bars

    wf.ending_balance = balance
    return wf
