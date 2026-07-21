"""
Settle it: on RC Mode C (anchor 30%), test RSI+DMA (no multiTF) vs RSI+multiTF (no DMA,
the deployed) vs all-gates vs RSI-alone — one clean run, apples to apples.

    python scripts/test_rsi_dma.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from equinext.context import ResearchContext                          # noqa: E402
from equinext.backtest import BacktestConfig, run_backtest            # noqa: E402
from baskets.equinext_v2 import EquinextV2, EquinextV2RC              # noqa: E402
from scripts.backtest_allocator import run_switch, gold_returns, metrics  # noqa: E402

EquinextV2._CACHE_ROWS = True
RC_START = pd.Timestamp("2022-11-18")


def make(trend, mtf, rsi):
    b = EquinextV2RC()
    b.TIER_MODE = "C"; b.LARGE_ANCHOR = 0.30; b.SATELLITE_TILT = 1.0
    b.SMALL_CAP_MAX = 0.40; b.TIER_BOUNDS = (100, 250, 500)
    b.USE_TREND_GATE = trend; b.USE_MULTI_TF = mtf; b.RSI_MAX = (80 if rsi else None)
    return b


CONFIGS = [
    ("RSI + 200-DMA  (no multiTF)",              make(True, False, True)),
    ("RSI + multiTF  (no DMA)  [DEPLOYED]",      make(False, True, True)),
    ("All gates  (DMA + multiTF + RSI)",         make(True, True, True)),
    ("RSI alone",                                make(False, False, True)),
]


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    cfg = BacktestConfig(start=pd.Timestamp("2017-08-01").date(), end=end.date(), rebalance="ME")
    print(f"{'gate config (RC · Mode C · anchor 30%)':<44}| {'FULL WINDOW':^24} | {'RUPEECASE WIN':^22}")
    print(f"{'':<44}| {'CAGR':>6}{'Sharpe':>8}{'maxDD':>8} | {'CAGR':>6}{'Sharpe':>8}{'maxDD':>6}")
    print("-" * 102)
    for label, b in CONFIGS:
        res = run_backtest(b, ctx, cfg)
        r_full, _ = run_switch(res.returns, rg, "NIFTY500", "ME")
        r_rc, _ = run_switch(res.returns[res.returns.index >= RC_START], rg, "NIFTY500", "ME")
        fm, rm = metrics(r_full), metrics(r_rc)
        print(f"{label:<44}| {fm['cagr']:>5.1f}%{fm['sharpe']:>8.2f}{fm['maxdd']:>7.1f}% | "
              f"{rm['cagr']:>5.1f}%{rm['sharpe']:>8.2f}{rm['maxdd']:>5.1f}%", flush=True)


if __name__ == "__main__":
    main()
