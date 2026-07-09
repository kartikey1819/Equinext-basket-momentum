"""
Robustness sweep of the froth-gate threshold.

Runs the valuation-momentum backtest (2017-08 -> latest, quarterly) at several
FROTH_MAX cutoffs and prints the metrics side by side. The point is NOT to pick
the single best number (that's overfitting) — it's to see whether results are
STABLE across a range (robust: pick a round central value) or SPIKY (fragile:
be suspicious). 1.01 = froth gate effectively OFF.

    python scripts/sweep_froth.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from equinext.context import ResearchContext              # noqa: E402
from equinext.backtest import BacktestConfig, run_backtest  # noqa: E402
from equinext.metrics import compute_metrics              # noqa: E402
from baskets.valuation_momentum import ValuationMomentumBasket  # noqa: E402

THRESHOLDS = [0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 1.01]


def main():
    ctx = ResearchContext()
    start = pd.Timestamp("2017-08-01")
    end = ctx.price_matrix().index[-1]
    bench = ctx.benchmark_returns(start, end, index_name="NIFTY50")
    mb = compute_metrics(bench, bench)

    print(f"Froth-threshold sweep  |  {start.date()} .. {end.date()}  quarterly")
    print(f"(NIFTY50: CAGR {mb['cagr']:.1%}, Sharpe {mb['sharpe']:.2f}, maxDD {mb['max_drawdown']:.1%})\n")
    print(f"{'froth_max':>9} | {'CAGR':>7} | {'after-tax':>9} | {'Sharpe':>6} | {'max DD':>7} | {'turnover/yr':>11}")
    print("-" * 66)

    orig = ValuationMomentumBasket.FROTH_MAX
    try:
        for thr in THRESHOLDS:
            ValuationMomentumBasket.FROTH_MAX = thr
            cfg = BacktestConfig(start=start.date(), end=end.date(), rebalance="QE")
            res = run_backtest(ValuationMomentumBasket(), ctx, cfg)
            m = compute_metrics(res.returns, bench, after_tax=res.after_tax_returns)
            label = f"{thr:.2f}" + (" (off)" if thr > 1.0 else "")
            print(f"{label:>9} | {m['cagr']:>7.2%} | {m['cagr_after_tax']:>9.2%} | "
                  f"{m['sharpe']:>6.2f} | {m['max_drawdown']:>7.2%} | "
                  f"{res.turnover.mean() * 4:>10.0%}")
    finally:
        ValuationMomentumBasket.FROTH_MAX = orig

    print("\nRead it as: is the CAGR/Sharpe column FLAT across 0.70-0.90 (robust -> keep a")
    print("round central value) or does it SWING a lot (fragile -> the gate is overfit)?")


if __name__ == "__main__":
    main()
