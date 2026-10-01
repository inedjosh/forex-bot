# forex-bot

An automated forex trading bot with a **broker-agnostic core**, a **backtest engine**,
and pluggable strategies. Ships with a sample EMA-crossover strategy as a placeholder —
**drop your own formula into `forexbot/strategies/my_formula.py` when you're ready.**

## Design philosophy

- **Backtest first.** Prove the formula works on historical data before risking money.
- **Broker-agnostic core.** Your formula knows nothing about OANDA/MT5/IBKR. Only a thin
  adapter changes if you switch brokers.
- **Safety baked in.** Position sizing and risk guards (max daily loss, max positions,
  stop-loss on every trade) are enforced by the engine, not left to the strategy.

> 📖 **New here / not a coder?** Read **[GUIDE.md](GUIDE.md)** — a super-detailed,
> plain-English, step-by-step manual covering running it, backtesting, hosting on a VPS,
> connecting a broker, and going live safely.

## Easiest start: the web UI (no coding)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/run_ui.py           # then open http://127.0.0.1:5000
```

A dead-simple dashboard opens in your browser. Everything runs locally — nothing leaves
your machine. From there you can, with clicks:

1. **Download** real market data (free, no account).
2. **Adjust** the strategy with plain-language settings (hover each for what it means).
3. **Run a backtest** and see results + an equity-curve chart.
4. **Auto-tune** to find the best-performing settings on your data.

Prefer the command line? Everything the UI does is also available as scripts below.

## Quick start (command line)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # only needed for real-data download

# 1) Backtest on synthetic data (pure stdlib, no install needed at all)
python scripts/run_backtest.py --synthetic

# 2) Download REAL EUR/USD data — free, no account, works in any country
python scripts/fetch_free_data.py --pair EURUSD --interval 1h --period 2y
python scripts/run_backtest.py --csv data/EURUSD_1h.csv

# 3) Run the FULL live loop against a simulated broker (no account needed)
python scripts/run_live.py --broker sim --max-iterations 500
```

Backtest prints net P&L, win rate, profit factor, and max drawdown. The live loop logs
every order open/close and the running balance — the same code path that will drive
OANDA, just with a fake broker.

## Tune the formula without touching code

Every parameter lives in [`.env`](.env). Edit values, re-run — no code changes:

```ini
STRATEGY=my_formula
FAST_EMA=12
SLOW_EMA=26
RSI_PERIOD=14 ; RSI_LOWER=30 ; RSI_UPPER=70
ATR_PERIOD=14 ; ATR_MULT=2.0 ; RISK_REWARD=1.5
STARTING_BALANCE=10000 ; RISK_PCT=1.0
```

Changing the *logic* (different indicators / entry conditions) means editing the entry
rules in [`forexbot/strategies/my_formula.py`](forexbot/strategies/my_formula.py).

## Where your formula goes

Open [`forexbot/strategies/my_formula.py`](forexbot/strategies/my_formula.py). It's a
fill-in-the-blanks template with three methods to complete:

- `entry_signal(candle, history)` — return `BUY`, `SELL`, or `None`
- `stop_loss(...)` / `take_profit(...)` — where to exit
- everything else (sizing, risk, order routing) is handled for you

Then run it:

```bash
python scripts/run_backtest.py --synthetic --strategy my_formula
```

## Going live (Nigeria-friendly path)

OANDA and (likely) Deriv do **not** accept Nigerian clients. Brokers that do and support
automation are **MetaTrader 5** brokers: **IC Markets, Pepperstone, FP Markets, Exness,
XM**. Automation uses the `MetaTrader5` Python package.

> ⚠️ The `MetaTrader5` package is **Windows-only**. Since a bot must run 24/5 anyway, the
> standard setup is a cheap **Windows VPS** (~$5–15/mo) running MT5 + this bot. That
> solves both the "not on my Mac" and "my laptop can't stay on" problems at once.

The safe progression (nothing here is built yet — it's the plan for when you pick a broker):

1. Prove the formula in **backtest** on free Yahoo data (works today, on your Mac).
2. Run the **simulated** live loop (`--broker sim`) — no account.
3. Open an **MT5 demo** account with a Nigeria-accepting broker.
4. Build + run the **MT5 adapter** in dry-run on the demo account (on a Windows VPS).
5. Let it place demo orders; then, only once proven, switch to a funded live account.

The broker-agnostic core means step 4 only adds one file (`forexbot/brokers/mt5.py`) — the
strategy, risk manager, backtest, and live loop are all unchanged.

## Validate & tune the formula

```bash
# Grid-search the best parameters on your data (fast: ~1-2s for 100+ combos)
python scripts/optimize.py --csv data/EURUSD_1h.csv --top 10

# Walk-forward validation — the honest, curve-fit-resistant test.
# If out-of-sample is poor, the "edge" was an illusion.
python scripts/walkforward.py --csv data/EURUSD_1h.csv

# Test across several pairs at once (does the formula generalize?)
python scripts/run_multi.py --csv data/EURUSD_1h.csv data/GBPUSD_1h.csv

# Save an equity-curve chart
python scripts/run_backtest.py --csv data/EURUSD_1h.csv --plot equity.png
```

**Always walk-forward before trusting optimizer output.** A backtest optimized over all
your data tells you the past; walk-forward approximates the future.

## Trade alerts

Set any of `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` or the `SMTP_*` vars in `.env` and the
live loop will ping you on every trade and when the daily-loss guard trips. Unset channels
are silently skipped; a failed alert never stops the bot.

## Project layout

```
forexbot/
  core/         types, indicators, Strategy base class (with prepare() hook)
  strategies/   your formula lives here (+ sample strategy)
  backtest/     historical replay engine + performance stats
  live/         live/paper trading loop (broker-agnostic)
  optimize/     grid search + walk-forward validation
  analytics/    equity-curve plotting
  risk/         position sizing + risk guards
  brokers/      base + simulated + MT5 (Nigeria) + OANDA adapters
  data/         CSV loader + synthetic data generator
  web/          local browser dashboard (Flask)
  notify.py     Telegram/email trade alerts
  config.py     loads + saves .env
scripts/
  run_ui.py          ← START HERE: local web dashboard (no coding)
  run_backtest.py    backtest on synthetic or CSV data (--plot)
  run_live.py        live/paper/sim loop (--broker sim|mt5|oanda, --dry-run)
  run_multi.py       multi-pair backtest + portfolio summary
  optimize.py        grid-search parameters
  walkforward.py     out-of-sample validation
  fetch_free_data.py free Yahoo Finance data (no account) ← use this
  fetch_mt5_data.py  broker-accurate data from MT5 (Windows/VPS)
  fetch_data.py      OANDA data (unavailable in Nigeria)
tests/          sanity tests (run: python -m pytest)
```

## Testing

```bash
python -m pytest          # or: python tests/test_backtest.py && python tests/test_live.py
```

## ⚠️ Disclaimer

Trading forex carries substantial risk of loss. This software is provided for
educational purposes. Backtested results do not guarantee future performance.
Always test on a demo account first. Never trade money you can't afford to lose.
