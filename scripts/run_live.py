#!/usr/bin/env python3
"""Run the bot in live / paper / simulated mode.

All settings default from `.env`; override any on the command line.

Examples:
    # Simulated broker — full live loop, no account needed (great for a smoke test):
    python scripts/run_live.py --broker sim --max-iterations 500

    # OANDA demo, but DON'T place orders — just log what it would do:
    python scripts/run_live.py --broker oanda --dry-run

    # OANDA demo, placing real (demo) orders:
    python scripts/run_live.py --broker oanda

    # Only after it's proven on demo, and you've set OANDA_ENVIRONMENT=live:
    python scripts/run_live.py --broker oanda
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forexbot.config import env_float, env_str
from forexbot.data import load_csv, synthetic_candles
from forexbot.live import LiveTrader
from forexbot.logging_setup import setup_logging
from forexbot.risk import RiskConfig
from forexbot.strategies import REGISTRY, get_strategy


def build_broker(args):
    """Construct the requested broker from args + .env."""
    if args.broker == "sim":
        if args.csv:
            candles = load_csv(args.csv)
        else:
            candles = synthetic_candles(n=args.bars, seed=args.seed)
        from forexbot.brokers import SimulatedBroker
        return SimulatedBroker(
            candles,
            starting_balance=env_float("STARTING_BALANCE", 10_000.0),
            spread=args.spread,
        )

    if args.broker == "mt5":
        login = env_str("MT5_LOGIN", "")
        password = env_str("MT5_PASSWORD", "")
        server = env_str("MT5_SERVER", "")
        if not (login and password and server):
            sys.exit(
                "MT5_LOGIN / MT5_PASSWORD / MT5_SERVER are not set in .env.\n"
                "Install MT5 + `pip install MetaTrader5` on a Windows box/VPS, log into\n"
                "your broker, and fill those in. Meanwhile test with:  --broker sim"
            )
        from forexbot.brokers import Mt5Broker
        return Mt5Broker(login=int(login), password=password, server=server)

    # OANDA (demo or live, per OANDA_ENVIRONMENT in .env)
    account_id = env_str("OANDA_ACCOUNT_ID", "")
    token = env_str("OANDA_ACCESS_TOKEN", "")
    environment = env_str("OANDA_ENVIRONMENT", "practice")
    if not account_id or not token:
        sys.exit(
            "OANDA_ACCOUNT_ID / OANDA_ACCESS_TOKEN are not set in .env.\n"
            "Open a free OANDA demo account, fill them in, and try again.\n"
            "Meanwhile you can run the full loop with:  --broker sim"
        )
    from forexbot.brokers import OandaBroker
    return OandaBroker(account_id=account_id, access_token=token, environment=environment)


def main() -> int:
    setup_logging()

    p = argparse.ArgumentParser(description="Run the forex bot live / paper / simulated.")
    p.add_argument("--broker", choices=["sim", "mt5", "oanda"], default="sim")
    p.add_argument("--strategy", default=env_str("STRATEGY", "crt"),
                   help=f"one of: {', '.join(sorted(REGISTRY))}")
    p.add_argument("--instrument", default=env_str("INSTRUMENT", "EUR_USD"))
    p.add_argument("--granularity", default=env_str("GRANULARITY", "H1"))
    p.add_argument("--dry-run", action="store_true",
                   help="compute + log signals but DON'T place orders")
    p.add_argument("--max-iterations", type=int, default=None,
                   help="stop after N cycles (useful for sim/testing)")
    p.add_argument("--poll-seconds", type=float, default=None,
                   help="override poll cadence")
    # sim-only knobs
    p.add_argument("--csv", help="(sim) replay this CSV instead of synthetic data")
    p.add_argument("--bars", type=int, default=2000, help="(sim) synthetic bar count")
    p.add_argument("--seed", type=int, default=42, help="(sim) synthetic seed")
    p.add_argument("--spread", type=float, default=0.0001)
    args = p.parse_args()

    # For a finite sim run, default to iterating through all the data.
    if args.broker == "sim" and args.max_iterations is None:
        args.max_iterations = args.bars

    broker = build_broker(args)
    strategy = get_strategy(args.strategy)
    risk = RiskConfig(
        starting_balance=env_float("STARTING_BALANCE", 10_000.0),
        risk_pct=env_float("RISK_PCT", 1.0),
    )

    if args.broker == "oanda" and not args.dry_run:
        env = env_str("OANDA_ENVIRONMENT", "practice")
        if env == "live":
            print("\n⚠️  You are about to trade with REAL MONEY (OANDA_ENVIRONMENT=live).")
            if input("    Type 'I ACCEPT THE RISK' to continue: ") != "I ACCEPT THE RISK":
                print("Aborted.")
                return 1

    trader = LiveTrader(
        broker=broker,
        strategy=strategy,
        risk_config=risk,
        instrument=args.instrument,
        granularity=args.granularity,
        poll_seconds=args.poll_seconds,
        max_iterations=args.max_iterations,
        dry_run=args.dry_run,
    )

    try:
        trader.run()
    except KeyboardInterrupt:
        print("\nStopped by user.")

    print(f"\nFinal simulated/reported balance: {broker.account_balance():,.2f}"
          if args.broker == "sim" else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
