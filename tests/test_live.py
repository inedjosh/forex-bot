"""Tests for the simulated broker and the live trading loop.

Run with: python -m pytest  (or just: python tests/test_live.py)
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forexbot.brokers import SimulatedBroker
from forexbot.core.types import Order, Side
from forexbot.data import synthetic_candles
from forexbot.live import LiveTrader
from forexbot.risk import RiskConfig
from forexbot.strategies import get_strategy

logging.disable(logging.CRITICAL)  # keep test output quiet


def test_sim_broker_fills_take_profit_and_updates_balance():
    candles = synthetic_candles(n=200, seed=5)
    broker = SimulatedBroker(candles, starting_balance=10_000, warmup=10)
    # Place a BUY with a target just above and a far stop, then advance.
    entry = broker.get_candles("EUR_USD", "H1", 1)[-1].close
    broker.place_order("EUR_USD", Order(
        side=Side.BUY, units=1000,
        stop_loss=entry * 0.90, take_profit=entry * 1.0005,
    ))
    assert broker.has_open_position("EUR_USD")
    # Advance until it either fills or data runs out.
    while broker.wait_next(0):
        if not broker.has_open_position("EUR_USD"):
            break
    assert not broker.has_open_position("EUR_USD"), "TP should have filled eventually"
    assert broker.account_balance() != 10_000, "balance should change after a fill"


def test_sim_broker_exhausts_data():
    candles = synthetic_candles(n=60, seed=1)
    broker = SimulatedBroker(candles, warmup=50)
    steps = 0
    while broker.wait_next(0):
        steps += 1
        assert steps < 100  # guard against infinite loop
    assert steps == len(candles) - 51


def test_live_loop_runs_and_trades_on_sim():
    candles = synthetic_candles(n=1200, seed=7)
    broker = SimulatedBroker(candles, starting_balance=10_000, warmup=50)
    trader = LiveTrader(
        broker=broker,
        strategy=get_strategy("my_formula"),
        risk_config=RiskConfig(starting_balance=10_000, risk_pct=1.0),
        instrument="EUR_USD",
        granularity="H1",
        max_iterations=len(candles),
    )
    trader.run()
    # The loop should have driven the account somewhere other than flat-start.
    assert broker.account_balance() != 10_000


def test_dry_run_places_no_orders():
    candles = synthetic_candles(n=600, seed=7)
    broker = SimulatedBroker(candles, starting_balance=10_000, warmup=50)
    trader = LiveTrader(
        broker=broker,
        strategy=get_strategy("my_formula"),
        risk_config=RiskConfig(starting_balance=10_000),
        instrument="EUR_USD",
        granularity="H1",
        max_iterations=len(candles),
        dry_run=True,
    )
    trader.run()
    assert broker.account_balance() == 10_000, "dry-run must not change balance"
    assert not broker.has_open_position("EUR_USD")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
