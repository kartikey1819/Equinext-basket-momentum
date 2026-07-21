"""
Focused Mode C tuning on RupeeCase, keeping the GOOD default bounds (100/250/500 -> the
small tier stays empty, excluding the junkiest micro-caps). With those bounds the only
real lever is the large-cap anchor (large-RC vs mid-RC split). Sweep it, both windows.

    python scripts/tune_modec_rc2.py
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


def make(anchor, gates=True):
    b = EquinextV2RC()
    b.TIER_MODE = "C"; b.SATELLITE_TILT = 1.0
    b.LARGE_ANCHOR = anchor; b.SMALL_CAP_MAX = 0.40; b.TIER_BOUNDS = (100, 250, 500)
    if not gates:
        b.USE_TREND_GATE = False; b.USE_MULTI_TF = False; b.RSI_MAX = None
    return b


CONFIGS = [(f"default bounds · anchor {int(a*100)}%", make(a)) for a in (0.20, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70)]
CONFIGS += [("default bounds · anchor 40% · NO gates", make(0.40, gates=False)),
            ("default bounds · anchor 50% · NO gates", make(0.50, gates=False))]


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    cfg = BacktestConfig(start=pd.Timestamp("2017-08-01").date(), end=end.date(), rebalance="ME")
    print(f"{'config':<40}| {'FULL WINDOW':^24} | {'RUPEECASE WIN':^22}")
    print(f"{'':<40}| {'CAGR':>6}{'Sharpe':>8}{'maxDD':>8} | {'CAGR':>6}{'Sharpe':>8}{'maxDD':>6}")
    print("-" * 96)
    for label, b in CONFIGS:
        res = run_backtest(b, ctx, cfg)
        r_full, _ = run_switch(res.returns, rg, "NIFTY500", "ME")
        r_rc, _ = run_switch(res.returns[res.returns.index >= RC_START], rg, "NIFTY500", "ME")
        fm, rm = metrics(r_full), metrics(r_rc)
        print(f"{label:<40}| {fm['cagr']:>5.1f}%{fm['sharpe']:>8.2f}{fm['maxdd']:>7.1f}% | "
              f"{rm['cagr']:>5.1f}%{rm['sharpe']:>8.2f}{rm['maxdd']:>5.1f}%", flush=True)


if __name__ == "__main__":
    main()
