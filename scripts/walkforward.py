#!/usr/bin/env python3
"""Walk-forward validation — realistic, curve-fit-resistant performance estimate.

Examples:
    python scripts/walkforward.py --csv data/EURUSD_1h.csv
    python scripts/walkforward.py --synthetic --bars 6000 --is-bars 1000 --oos-bars 300

If the out-of-sample result here is decent, the edge is more likely real. If it's much
worse than a plain optimized backtest, the optimizer was fitting noise.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forexbot.config import env_float
from forexbot.data import load_csv, synthetic_candles
from forexbot.optimize import walk_forward


def main() -> int:
    p = argparse.ArgumentParser(description="Walk-forward validate MyFormula.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", action="store_true")
    src.add_argument("--csv", metavar="PATH")
    p.add_argument("--bars", type=int, default=6000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--is-bars", type=int, default=1000, help="in-sample window size")
    p.add_argument("--oos-bars", type=int, default=300, help="out-of-sample window size")
    p.add_argument("--spread", type=float, default=0.0001)
    args = p.parse_args()

    candles = (synthetic_candles(n=args.bars, seed=args.seed)
               if args.synthetic else load_csv(args.csv))
    source = f"synthetic({args.bars})" if args.synthetic else args.csv

    if len(candles) < args.is_bars + args.oos_bars:
        print(f"Need at least {args.is_bars + args.oos_bars} candles, have {len(candles)}.")
        return 1

    print(f"Walk-forward on {source} ({len(candles)} candles) "
          f"IS={args.is_bars} OOS={args.oos_bars}...\n")
    wf = walk_forward(
        candles,
        is_bars=args.is_bars,
        oos_bars=args.oos_bars,
        starting_balance=env_float("STARTING_BALANCE", 10_000.0),
        risk_pct=env_float("RISK_PCT", 1.0),
        spread=args.spread,
    )

    if wf.windows == 0:
        print("No complete IS+OOS window fit in the data. Reduce --is-bars/--oos-bars.")
        return 1

    print("=" * 55)
    print(wf.summary())
    print("=" * 55)
    print("\nParams chosen per window (shows how stable the optimum is):")
    for i, params in enumerate(wf.chosen_params, 1):
        print(f"  window {i}: " + " ".join(f"{k}={v}" for k, v in params.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
