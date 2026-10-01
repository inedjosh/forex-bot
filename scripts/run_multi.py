#!/usr/bin/env python3
"""Backtest the formula across several pairs at once and aggregate the results.

Each pair is backtested independently (its own balance slice), then combined into a
portfolio-level summary. This shows whether the formula generalizes across markets or
only works on one pair (a common overfitting tell).

Examples:
    # From CSVs you've already downloaded:
    python scripts/run_multi.py --csv data/EURUSD_1h.csv data/GBPUSD_1h.csv data/USDJPY_1h.csv

    # Quick synthetic multi-pair smoke test (different seeds = different "markets"):
    python scripts/run_multi.py --synthetic --pairs 3
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forexbot.backtest import BacktestEngine
from forexbot.config import env_float, env_str
from forexbot.data import load_csv, synthetic_candles
from forexbot.risk import RiskConfig
from forexbot.strategies import get_strategy


def main() -> int:
    p = argparse.ArgumentParser(description="Multi-pair backtest.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", nargs="+", metavar="PATH", help="one or more OHLC CSVs")
    src.add_argument("--synthetic", action="store_true")
    p.add_argument("--pairs", type=int, default=3, help="(synthetic) number of markets")
    p.add_argument("--bars", type=int, default=2000)
    p.add_argument("--strategy", default=env_str("STRATEGY", "crt"))
    p.add_argument("--spread", type=float, default=0.0001)
    args = p.parse_args()

    # Build the list of (label, candles) datasets.
    datasets = []
    if args.synthetic:
        for i in range(args.pairs):
            datasets.append((f"SYN{i+1}", synthetic_candles(n=args.bars, seed=100 + i)))
    else:
        for path in args.csv:
            label = os.path.splitext(os.path.basename(path))[0]
            datasets.append((label, load_csv(path)))

    per_pair_balance = env_float("STARTING_BALANCE", 10_000.0)
    risk_pct = env_float("RISK_PCT", 1.0)
    engine = BacktestEngine(
        risk_config=RiskConfig(starting_balance=per_pair_balance, risk_pct=risk_pct),
        spread=args.spread,
    )

    print(f"{'pair':<14} {'trades':>7} {'win%':>6} {'PF':>5} {'net P&L':>12} {'return':>9}")
    print("-" * 60)

    total_start = total_end = 0.0
    total_trades = total_wins = 0
    for label, candles in datasets:
        if len(candles) < 50:
            print(f"{label:<14}  (skipped — only {len(candles)} candles)")
            continue
        result = engine.run(get_strategy(args.strategy), candles)
        total_start += result.starting_balance
        total_end += result.ending_balance
        total_trades += result.num_trades
        total_wins += len(result.wins)
        print(f"{label:<14} {result.num_trades:>7} {result.win_rate:>5.1f}% "
              f"{result.profit_factor:>5.2f} {result.net_pnl:>+12.2f} "
              f"{result.return_pct:>+8.2f}%")

    print("-" * 60)
    port_return = (100.0 * (total_end - total_start) / total_start) if total_start else 0.0
    port_win = (100.0 * total_wins / total_trades) if total_trades else 0.0
    print(f"{'PORTFOLIO':<14} {total_trades:>7} {port_win:>5.1f}% "
          f"{'':>5} {total_end - total_start:>+12.2f} {port_return:>+8.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
