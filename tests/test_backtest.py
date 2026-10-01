"""Sanity tests. Run with: python -m pytest  (or just: python tests/test_backtest.py)"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forexbot.backtest import BacktestEngine
from forexbot.core.indicators import crossover, ema, rsi, sma
from forexbot.data import synthetic_candles
from forexbot.risk import RiskConfig
from forexbot.strategies import get_strategy


def test_synthetic_is_deterministic():
    a = synthetic_candles(n=100, seed=7)
    b = synthetic_candles(n=100, seed=7)
    assert [c.close for c in a] == [c.close for c in b]
    assert len(a) == 100


def test_indicators_align_and_warm_up():
    xs = [float(i) for i in range(1, 51)]
    assert sma(xs, 5)[3] is None and sma(xs, 5)[4] is not None
    assert ema(xs, 10)[8] is None and ema(xs, 10)[9] is not None
    r = rsi(xs, 14)
    # Steadily rising series -> RSI pinned near 100.
    assert r[-1] is not None and r[-1] > 99


def test_crossover_detects_cross():
    fast = [1.0, 1.0, 2.0]
    slow = [1.5, 1.5, 1.5]
    assert crossover(fast, slow, 2) is True
    assert crossover(fast, slow, 1) is False


def test_backtest_runs_and_reports():
    candles = synthetic_candles(n=1000, seed=1)
    engine = BacktestEngine(risk_config=RiskConfig(starting_balance=10_000))
    result = engine.run(get_strategy("ema_crossover"), candles)
    assert result.num_trades > 0, "sample strategy should trade on 1000 bars"
    assert len(result.equity_curve) > 0
    assert 0.0 <= result.win_rate <= 100.0
    # Balance and equity curve are internally consistent.
    assert abs(result.ending_balance - result.equity_curve[-1]) < 1e-6


def test_my_formula_trades_and_is_env_driven():
    # my_formula is now an active, env-tuned strategy — it should trade.
    candles = synthetic_candles(n=1500, seed=3)
    strat = get_strategy("my_formula")
    result = BacktestEngine().run(strat, candles)
    assert result.num_trades > 0, "active my_formula should trade on 1500 bars"
    # Parameters are sourced from .env / defaults, not hard-coded literals.
    assert strat.fast_period > 0 and strat.slow_period > strat.fast_period


def test_crt_strategy_trades():
    # CRT is the bot's core strategy; it should find sweep+reclaim setups.
    candles = synthetic_candles(n=1500, seed=3)
    result = BacktestEngine().run(get_strategy("crt"), candles)
    assert result.num_trades > 0
    assert 0.0 <= result.win_rate <= 100.0
    from forexbot.strategies.crt import CrtStrategy
    s = CrtStrategy()
    assert s.range_lookback >= 1 and s.target_mode in ("range", "rr")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
