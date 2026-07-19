"""
MOMENTUM-ONLY (no valuation/earnings gates) + RupeeCase-style dynamic 3-asset switch,
on the NIFTY TOTAL MARKET (~750). Isolates what our risk-control gates cost: same
universe, same switch (core 35 + eq/debt 40 + eq/gold 25), same windows — only the
equity selection differs (pure momentum vs gated momentum).

Prints Quarterly / Monthly / Bi-monthly for both windows, momentum-only computed
fresh, with the GATED numbers (from the identical prior run) shown for comparison.

    python scripts/backtest_momonly.py
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

from equinext.context import ResearchContext                      # noqa: E402
from baskets.valuation_momentum import VMTotalMarketMomOnly50     # noqa: E402
from scripts.backtest_allocator import (                          # noqa: E402
    equity_returns, run_switch, gold_returns, metrics,
)

CADENCES = [("Quarterly", "QE"), ("Monthly", "ME"), ("Bi-monthly", "2M")]

# GATED (our froth + earnings gates ON) dynamic-switch results from the identical
# prior Total-Market run — shown for direct A/B comparison.
GATED = {
    ("rc", "QE"):   dict(cagr=26.4, vol=16.4, sharpe=1.61, sortino=1.77, maxdd=-14.8, calmar=1.78, avg_eq=73, final=229),
    ("rc", "ME"):   dict(cagr=30.9, vol=15.5, sharpe=2.00, sortino=2.20, maxdd=-12.3, calmar=2.51, avg_eq=68, final=265),
    ("rc", "2M"):   dict(cagr=26.5, vol=15.4, sharpe=1.72, sortino=1.88, maxdd=-12.7, calmar=2.08, avg_eq=69, final=234),
    ("full", "QE"): dict(cagr=18.2, vol=21.3, sharpe=0.85, sortino=0.92, maxdd=-35.3, calmar=0.52, avg_eq=73, final=434),
    ("full", "ME"): dict(cagr=20.7, vol=14.5, sharpe=1.43, sortino=1.62, maxdd=-21.1, calmar=0.98, avg_eq=72, final=530),
    ("full", "2M"): dict(cagr=20.0, vol=15.6, sharpe=1.29, sortino=1.37, maxdd=-32.2, calmar=0.65, avg_eq=73, final=505),
}


def hdr(title):
    print(f"\n{'='*104}\n{title}\n{'='*104}")
    print(f"{'strategy':<44}{'CAGR':>7}{'Vol':>7}{'Sharpe':>8}{'Sortino':>8}"
          f"{'maxDD':>8}{'Calmar':>8}{'AvgEq%':>8}{'R100->':>9}")
    print("-" * 104)


def line(nm, m, avgeq=None):
    ae = f"{avgeq:>7.0f}%" if avgeq is not None else f"{'-':>8}"
    print(f"{nm:<44}{m['cagr']:>6.1f}%{m['vol']:>6.1f}%{m['sharpe']:>8.2f}"
          f"{m['sortino']:>8.2f}{m['maxdd']:>7.1f}%{m['calmar']:>8.2f}{ae}{m['final']:>8.0f}")


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    periods = [("RUPEECASE WINDOW", "rc", pd.Timestamp("2022-11-18")),
               ("FULL WINDOW (incl. COVID)", "full", pd.Timestamp("2017-08-01"))]

    for pname, wk, start in periods:
        hdr(f"{pname}   {start.date()} .. {end.date()}   |   MOMENTUM-ONLY (no gates) + dynamic switch   |  Nifty Total Market ~750, 50 stocks")
        line("Nifty 50 index", metrics(ctx.benchmark_returns(start, end, "NIFTY50")))
        line("Nifty 500 index", metrics(ctx.benchmark_returns(start, end, "NIFTY500")))
        for cname, code in CADENCES:
            r_eq = equity_returns(VMTotalMarketMomOnly50, start, end, rebalance=code)
            r_dyn, avgeq = run_switch(r_eq, rg, "NIFTY500", code)
            line(f"MOMENTUM-ONLY · {cname}", metrics(r_dyn), avgeq)
            g = GATED[(wk, code)]
            line(f"   (gated, our filters) · {cname}", g, g["avg_eq"])
        if wk == "rc":
            print("-" * 104)
            print(f"{'RupeeCase claimed (same window)':<44}{'45.2%':>7}{'16.5%':>7}"
                  f"{'2.32':>8}{'2.30':>8}{'-10.6%':>8}{'4.25':>8}{'-':>8}{'386':>9}")


if __name__ == "__main__":
    main()
