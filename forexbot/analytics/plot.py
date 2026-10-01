"""Plot a backtest's equity curve to a PNG (matplotlib, optional dependency)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..backtest.engine import BacktestResult


def plot_equity(result: "BacktestResult", path: str = "equity_curve.png") -> str:
    """Save an equity-curve chart. Returns the path. Raises if matplotlib is missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless-safe backend
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover
        raise ImportError("matplotlib is required for plotting.\n"
                          "    pip install matplotlib") from exc

    eq = result.equity_curve
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(eq, linewidth=1.3, color="#1f77b4", label="Equity")
    ax.axhline(result.starting_balance, color="#999", linestyle="--",
               linewidth=0.9, label="Start")

    # Shade the max-drawdown region for a quick visual read.
    peak = float("-inf")
    trough_idx = peak_idx = 0
    max_dd = 0.0
    cur_peak_idx = 0
    for i, v in enumerate(eq):
        if v > peak:
            peak = v
            cur_peak_idx = i
        elif peak > 0 and (peak - v) / peak > max_dd:
            max_dd = (peak - v) / peak
            trough_idx, peak_idx = i, cur_peak_idx
    if max_dd > 0:
        ax.axvspan(peak_idx, trough_idx, color="#d62728", alpha=0.10,
                   label=f"Max DD {result.max_drawdown_pct:.1f}%")

    ax.set_title(f"{result.strategy_name} — Equity Curve  "
                 f"(net {result.return_pct:+.2f}%, {result.num_trades} trades, "
                 f"win {result.win_rate:.0f}%)")
    ax.set_xlabel("Bars")
    ax.set_ylabel("Account balance")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
