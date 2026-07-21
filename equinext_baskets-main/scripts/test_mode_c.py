"""
Test the user's tier design (Mode C: FIXED large-cap anchor + satellite that rotates to
whichever of mid/small has stronger trailing momentum) vs the baseline and my Mode A/B,
on Total Market + dynamic dial, both windows, net of cost.

    python scripts/test_mode_c.py
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
from baskets.equinext_v2 import EquinextV2, TierMap                   # noqa: E402
from scripts.backtest_allocator import run_switch, gold_returns, metrics  # noqa: E402

EquinextV2._CACHE_ROWS = True
RC_START = pd.Timestamp("2022-11-18")

BASE = dict(USE_TIERS=False, USE_TREND_GATE=False, USE_MULTI_TF=False, RSI_MAX=None,
            SECTOR_WEIGHT_CAP=0.25, MAX_STOCK_WEIGHT=None)
FULL_GATES = dict(USE_TREND_GATE=True, USE_MULTI_TF=True, RSI_MAX=80, MAX_STOCK_WEIGHT=0.08)


def cfgC(anchor, tilt, gates=True):
    d = dict(BASE); d.update(USE_TIERS=True, TIER_MODE="C", LARGE_ANCHOR=anchor,
                             SATELLITE_TILT=tilt, MAX_STOCK_WEIGHT=0.08)
    if gates:
        d.update(FULL_GATES)
    return d


STEPS = [
    ("Baseline (no tiers, cap25)",        dict(BASE)),
    ("Mode A fixed 50/30/20 (V2)",        {**BASE, **FULL_GATES, "USE_TIERS": True, "TIER_MODE": "A"}),
    ("Mode B regime (V2)",                {**BASE, **FULL_GATES, "USE_TIERS": True, "TIER_MODE": "B"}),
    ("Mode C hard, anchor 40% (V2)",      cfgC(0.40, 1.0)),
    ("Mode C soft 70/30, anchor 40% (V2)", cfgC(0.40, 0.70)),
    ("Mode C hard, anchor 30% (V2)",      cfgC(0.30, 1.0)),
    ("Mode C hard, anchor 50% (V2)",      cfgC(0.50, 1.0)),
    ("Mode C hard, anchor 40%, small<=40% (V2)", {**cfgC(0.40, 1.0), "SMALL_CAP_MAX": 0.40}),
    ("Mode C hard, anchor 40% (tiers only, no gates)", cfgC(0.40, 1.0, gates=False)),
    ("Mode C hard, anchor 40%, small<=40% (tiers only)", {**cfgC(0.40, 1.0, gates=False), "SMALL_CAP_MAX": 0.40}),
]


def sector_peak(holdings, sector_of):
    peak = 0.0
    for _, w in holdings.items():
        sw = {}
        for s, x in w.items():
            sw[sector_of(s) or "Unknown"] = sw.get(sector_of(s) or "Unknown", 0.0) + x
        peak = max(peak, max(sw.values()) if sw else 0.0)
    return peak * 100


def tier_mix(holdings, tm):
    allsyms = list(tm.shares.keys())
    L = M = S = 0.0
    for d, w in holdings.items():
        ti = tm.assign(d, allsyms)
        L += sum(x for s, x in w.items() if ti.get(s) == "L")
        M += sum(x for s, x in w.items() if ti.get(s) == "M")
        S += sum(x for s, x in w.items() if ti.get(s) == "S")
    n = len(holdings) or 1
    return L / n * 100, M / n * 100, S / n * 100


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    sector_of = lambda s: ctx.sector(s)
    tm = TierMap(ctx)
    cfg = BacktestConfig(start=pd.Timestamp("2017-08-01").date(), end=end.date(), rebalance="ME")

    print(f"{'config':<44}| {'FULL WINDOW':^26} | {'RUPEECASE WIN':^22} | {'tier mix L/M/S':^16}")
    print(f"{'':<44}| {'CAGR':>6}{'Sharpe':>8}{'maxDD':>8} | {'CAGR':>6}{'Sharpe':>8}{'maxDD':>6} | {'L':>5}{'M':>5}{'S':>5}")
    print("-" * 118)
    for label, ov in STEPS:
        b = EquinextV2()
        for k, v in ov.items():
            setattr(b, k, v)
        res = run_backtest(b, ctx, cfg)
        r_full, _ = run_switch(res.returns, rg, "NIFTY500", "ME")
        r_rc, _ = run_switch(res.returns[res.returns.index >= RC_START], rg, "NIFTY500", "ME")
        fm, rm = metrics(r_full), metrics(r_rc)
        L, M, S = tier_mix(res.holdings, tm) if ov.get("USE_TIERS") else (0, 0, 0)
        print(f"{label:<44}| {fm['cagr']:>5.1f}%{fm['sharpe']:>8.2f}{fm['maxdd']:>7.1f}% | "
              f"{rm['cagr']:>5.1f}%{rm['sharpe']:>8.2f}{rm['maxdd']:>5.1f}% | {L:>4.0f}%{M:>4.0f}%{S:>4.0f}%", flush=True)


if __name__ == "__main__":
    main()
