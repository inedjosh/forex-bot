"""Grid-search optimizer for the MyFormula parameters.

Runs a backtest for every combination in a parameter grid and ranks them by a scoring
function. This finds settings that performed best *on the given data* — which is exactly
why you must then validate out-of-sample (see walkforward.py) to avoid curve-fitting.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Sequence

from ..backtest import BacktestEngine, BacktestResult
from ..core.types import Candle
from ..risk import RiskConfig
from ..strategies.crt import CrtStrategy


@dataclass
class ParamResult:
    params: Dict[str, float]
    result: BacktestResult
    score: float = field(default=0.0)


def score_result(result: BacktestResult, min_trades: int = 10) -> float:
    """Default objective: net P&L, but disqualify samples with too few trades.

    Too-few-trades runs are statistically meaningless, so they score -inf and can never
    win. Swap this out for profit-factor, Sharpe, etc. if you prefer.
    """
    if result.num_trades < min_trades:
        return float("-inf")
    return result.net_pnl


def _default_grid() -> Dict[str, Sequence]:
    return {
        "range_lookback": [1, 2, 3],
        "target_mode": ["range", "rr"],
        "risk_reward": [1.5, 2.0, 3.0],
        "min_rr": [1.0, 1.5, 2.0],
    }


def grid_search(
    candles: List[Candle],
    grid: Dict[str, Sequence] | None = None,
    risk_config: RiskConfig | None = None,
    spread: float = 0.0001,
    min_trades: int = 10,
    scorer: Callable[[BacktestResult], float] | None = None,
) -> List[ParamResult]:
    """Backtest every parameter combination; return results sorted best-first."""
    grid = grid or _default_grid()
    risk_config = risk_config or RiskConfig()
    scorer = scorer or (lambda r: score_result(r, min_trades))

    keys = list(grid.keys())
    combos = list(itertools.product(*(grid[k] for k in keys)))

    engine = BacktestEngine(risk_config=risk_config, spread=spread)
    out: List[ParamResult] = []
    for combo in combos:
        params = dict(zip(keys, combo))
        strat = CrtStrategy(**params)
        result = engine.run(strat, candles)
        out.append(ParamResult(params=params, result=result, score=scorer(result)))

    out.sort(key=lambda pr: pr.score, reverse=True)
    return out
