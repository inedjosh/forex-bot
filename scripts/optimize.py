#!/usr/bin/env python3
"""Grid-search the formula's parameters over a dataset.

Examples:
    python scripts/optimize.py --synthetic --bars 3000
    python scripts/optimize.py --csv data/EURUSD_1h.csv --top 15

Prints the best-performing parameter sets. Copy the winner into .env — but ALWAYS
validate it out-of-sample first:  python scripts/walkforward.py --csv <same file>
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forexbot.config import env_float
from forexbot.data import load_csv, synthetic_candles
from forexbot.optimize import grid_search
from forexbot.risk import RiskConfig


def main() -> int:
    p = argparse.ArgumentParser(description="Optimize CRT strategy parameters.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", action="store_true")
    src.add_argument("--csv", metavar="PATH")
    p.add_argument("--bars", type=int, default=3000, help="synthetic bar count")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--top", type=int, default=10, help="how many results to show")
    p.add_argument("--min-trades", type=int, default=10)
    p.add_argument("--spread", type=float, default=0.0001)
    args = p.parse_args()

    candles = (synthetic_candles(n=args.bars, seed=args.seed)
               if args.synthetic else load_csv(args.csv))
    source = f"synthetic({args.bars})" if args.synthetic else args.csv

    risk = RiskConfig(starting_balance=env_float("STARTING_BALANCE", 10_000.0),
                      risk_pct=env_float("RISK_PCT", 1.0))

    print(f"Optimizing on {source} ({len(candles)} candles)...\n")
    ranked = grid_search(candles, risk_config=risk, spread=args.spread,
                         min_trades=args.min_trades)

    valid = [r for r in ranked if r.score != float("-inf")]
    if not valid:
        print("No parameter set produced enough trades. Lower --min-trades or add data.")
        return 1

    header = f"{'rank':>4} {'net P&L':>10} {'PF':>5} {'win%':>6} {'trades':>7}  params"
    print(header)
    print("-" * len(header))
    for i, pr in enumerate(valid[: args.top], 1):
        r = pr.result
        params = " ".join(f"{k}={v}" for k, v in pr.params.items())
        print(f"{i:>4} {r.net_pnl:>+10.2f} {r.profit_factor:>5.2f} "
              f"{r.win_rate:>5.1f}% {r.num_trades:>7}  {params}")

    best = valid[0]
    print("\nBest params -> put these in .env:")
    env_names = {"range_lookback": "CRT_RANGE_LOOKBACK", "target_mode": "CRT_TARGET_MODE",
                 "risk_reward": "CRT_RISK_REWARD", "min_rr": "CRT_MIN_RR",
                 "stop_buffer_pct": "CRT_STOP_BUFFER_PCT"}
    for k, v in best.params.items():
        print(f"    {env_names.get(k, k.upper())}={v}")
    print("\n⚠️  These are fit to THIS data. Validate out-of-sample:")
    print(f"    python scripts/walkforward.py "
          f"{'--synthetic' if args.synthetic else '--csv ' + args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
