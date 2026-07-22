"""
Ablation: what drives the 3-asset dial's equity-vs-debt and equity-vs-gold switches —
the broad NIFTY 500 INDEX (current/deployed) or the equity SLEEVE's OWN momentum?

Both switches compare a 63-day (~3-month) equity trailing return against debt (fixed
6.5%/yr) and gold (GoldBees). This swaps the equity-momentum SOURCE:
  index-timed  : eq_mom = NIFTY500 index 63-day return          (deployed default)
  sleeve-timed : eq_mom = the basket's OWN equity-curve 63-day return
Everything else identical. Run on the 25%-capped Total Market & Nifty 500 books, monthly,
full window (incl. COVID) + RupeeCase window. avgEQ = average equity weight held by the dial.

    python scripts/test_sleeve_timing.py
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

from equinext.context import ResearchContext                              # noqa: E402
from equinext.backtest import BacktestConfig, run_backtest                # noqa: E402
from baskets.valuation_momentum import VMTotalMarket50, VM500Standard50   # noqa: E402
from scripts.backtest_allocator import run_switch, gold_returns, metrics  # noqa: E402

RC_START = pd.Timestamp("2022-11-18")
LOOKBACK = 63


def sleeve_mom(r_eq: pd.Series, lookback=LOOKBACK) -> pd.Series:
    """The equity sleeve's OWN trailing `lookback`-day return, from its daily-return curve."""
    curve = (1 + r_eq).cumprod()
    return curve / curve.shift(lookback) - 1


def line(label, port, avgeq):
    mf = metrics(port)
    print(f"{label:<26}{avgeq:>7.1f}% | {mf['cagr']:>5.1f}%{mf['sharpe']:>8.2f}{mf['maxdd']:>8.1f}%", end="")


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    cfg = BacktestConfig(start=pd.Timestamp("2017-08-01").date(), end=end.date(), rebalance="ME")

    for uni_label, cls in [("Total Market", VMTotalMarket50), ("Nifty 500", VM500Standard50)]:
        print(f"\ncomputing {uni_label} equity sleeve (monthly, 25% cap) ...", flush=True)
        b = cls(); b.SECTOR_WEIGHT_CAP = 0.25
        r_eq = run_backtest(b, ctx, cfg).returns
        em_sleeve = sleeve_mom(r_eq)

        # full window + RC window, each timed by index vs sleeve
        variants = {
            "index-timed (NIFTY500)": None,
            "sleeve-timed (own mom)": em_sleeve,
        }
        print(f"\n{'='*100}\n{uni_label} · dynamic monthly · 25% cap — switch signal: NIFTY500 index vs equity sleeve's own momentum\n{'='*100}")
        print(f"{'signal':<26}{'avgEQ':>7} | {'FULL WINDOW':^24} || {'avgEQ':>7} | {'RUPEECASE WINDOW':^24}")
        print(f"{'':<26}{'':>7} | {'CAGR':>6}{'Sharpe':>8}{'maxDD':>8} || {'':>7} | {'CAGR':>6}{'Sharpe':>8}{'maxDD':>8}")
        print("-" * 100)
        for lbl, em in variants.items():
            pf, aef = run_switch(r_eq, rg, "NIFTY500", "ME", eq_mom_series=em)
            r_rc = r_eq[r_eq.index >= RC_START]
            em_rc = em[em.index >= RC_START] if em is not None else None
            pr, aer = run_switch(r_rc, rg, "NIFTY500", "ME", eq_mom_series=em_rc)
            line(lbl, pf, aef)
            mr = metrics(pr)
            print(f" || {aer:>6.1f}% | {mr['cagr']:>5.1f}%{mr['sharpe']:>8.2f}{mr['maxdd']:>8.1f}%", flush=True)


if __name__ == "__main__":
    main()
