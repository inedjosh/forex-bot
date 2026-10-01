#!/usr/bin/env python3
"""Run a backtest from the command line.

Examples:
    # Synthetic data, sample strategy (zero setup):
    python scripts/run_backtest.py --synthetic --strategy ema_crossover

    # Your own data + your own formula:
    python scripts/run_backtest.py --csv data/EURUSD_H1.csv --strategy my_formula
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow running this file directly without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forexbot.backtest import BacktestEngine
from forexbot.config import env_float, env_str
from forexbot.data import load_csv, synthetic_candles
from forexbot.risk import RiskConfig
from forexbot.strategies import REGISTRY, get_strategy


def main() -> int:
    p = argparse.ArgumentParser(description="Backtest a forex strategy.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", action="store_true", help="use generated data")
    src.add_argument("--csv", metavar="PATH", help="OHLC CSV file to backtest on")

    # Defaults come from .env, overridable on the command line.
    p.add_argument("--strategy", default=env_str("STRATEGY", "crt"),
                   help=f"one of: {', '.join(sorted(REGISTRY))}  (default from .env)")
    p.add_argument("--balance", type=float, default=env_float("STARTING_BALANCE", 10_000.0))
    p.add_argument("--risk-pct", type=float, default=env_float("RISK_PCT", 1.0),
                   help="%% of balance risked per trade (default from .env)")
    p.add_argument("--spread", type=float, default=0.0001, help="transaction cost in price units")
    p.add_argument("--bars", type=int, default=2000, help="number of synthetic bars")
    p.add_argument("--seed", type=int, default=42, help="synthetic data seed")
    p.add_argument("--show-trades", action="store_true", help="print every trade")
    p.add_argument("--plot", nargs="?", const="equity_curve.png", default=None,
                   metavar="PATH", help="save an equity-curve PNG (default equity_curve.png)")
    args = p.parse_args()

    # Load data.
    if args.synthetic:
        candles = synthetic_candles(n=args.bars, seed=args.seed)
        source = f"synthetic ({args.bars} bars, seed={args.seed})"
    else:
        candles = load_csv(args.csv)
        source = args.csv

    if len(candles) < 50:
        print(f"Not enough candles to backtest ({len(candles)}).", file=sys.stderr)
        return 1

    strategy = get_strategy(args.strategy)
    engine = BacktestEngine(
        risk_config=RiskConfig(starting_balance=args.balance, risk_pct=args.risk_pct),
        spread=args.spread,
    )
    result = engine.run(strategy, candles)

    print("=" * 60)
    print(f"Data source     : {source}")
    print(f"Candles         : {len(candles)}  "
          f"({candles[0].time:%Y-%m-%d} -> {candles[-1].time:%Y-%m-%d})")
    print("-" * 60)
    print(result.summary())
    print("=" * 60)

    if args.show_trades and result.trades:
        print("\nTrades:")
        print(f"{'#':>3} {'side':<5} {'entry':>10} {'exit':>10} {'pnl':>12} {'reason':<12}")
        for i, t in enumerate(result.trades, 1):
            print(f"{i:>3} {t.side.value:<5} {t.entry_price:>10.5f} "
                  f"{t.exit_price:>10.5f} {t.pnl:>12.2f} {t.exit_reason:<12}")

    if result.num_trades == 0:
        print("\n⚠️  0 trades. Loosen filters in .env (e.g. widen RSI band) or add more bars.")

    if args.plot:
        try:
            from forexbot.analytics import plot_equity
            saved = plot_equity(result, args.plot)
            print(f"\nSaved equity curve -> {saved}")
        except ImportError as exc:
            print(f"\n(plot skipped: {exc})", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
