"""
3-asset allocator on the FULL NIFTY TOTAL MARKET (~750 stocks we have data for).

Same strategy as the Nifty-500 runs, only the equity universe is the whole Total
Market pool. Equity engine = valuation-momentum, up to 50 stocks. For each period &
cadence the equity backtest is computed ONCE and both blends are applied:
  - STATIC  35/40/25  (fixed weights, reset each rebalance)
  - DYNAMIC switch     (core 35 + eq/debt switch 40 + eq/gold switch 25, rel-momentum)

Debt = 6.5%/yr liquid accrual; Gold = GoldBees. Two periods (RupeeCase window +
full incl. COVID) x 3 cadences (Q/M/2M). Benchmarks: Nifty 50 & Nifty 500.

    python scripts/backtest_totalmarket.py
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
from baskets.valuation_momentum import VMTotalMarket50            # noqa: E402
from scripts.backtest_allocator import (                          # noqa: E402
    equity_returns, run_static, run_switch, gold_returns, metrics,
)

WEIGHTS = (0.35, 0.40, 0.25)
CADENCES = [("Quarterly", "QE"), ("Monthly", "ME"), ("Bi-monthly", "2M")]
INDEX = "NIFTY500"          # broad-market trend proxy for the switch signal


def hdr(title):
    print(f"\n{'='*102}\n{title}\n{'='*102}")
    print(f"{'strategy':<42}{'CAGR':>7}{'Vol':>7}{'Sharpe':>8}{'Sortino':>8}"
          f"{'maxDD':>8}{'Calmar':>8}{'AvgEq%':>8}{'R100->':>9}")
    print("-" * 102)


def line(nm, m, avgeq=None):
    ae = f"{avgeq:>7.0f}%" if avgeq is not None else f"{'-':>8}"
    print(f"{nm:<42}{m['cagr']:>6.1f}%{m['vol']:>6.1f}%{m['sharpe']:>8.2f}"
          f"{m['sortino']:>8.2f}{m['maxdd']:>7.1f}%{m['calmar']:>8.2f}{ae}{m['final']:>8.0f}")


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    periods = [
        ("RUPEECASE WINDOW", pd.Timestamp("2022-11-18")),
        ("FULL WINDOW (incl. COVID)", pd.Timestamp("2017-08-01")),
    ]
    for pname, start in periods:
        hdr(f"{pname}   {start.date()} .. {end.date()}   |   NIFTY TOTAL MARKET (~750), up to 50 stocks   |  35/40/25")
        line("Nifty 50 index", metrics(ctx.benchmark_returns(start, end, "NIFTY50")))
        line("Nifty 500 index", metrics(ctx.benchmark_returns(start, end, "NIFTY500")))
        for cname, code in CADENCES:
            r_eq = equity_returns(VMTotalMarket50, start, end, rebalance=code)   # computed ONCE
            r_static = run_static(r_eq, rg, WEIGHTS, code)
            r_dyn, avgeq = run_switch(r_eq, rg, INDEX, code)
            line(f"STATIC 35/40/25 · {cname}", metrics(r_static))
            line(f"DYNAMIC switch · {cname}", metrics(r_dyn), avgeq)
        if pname.startswith("RUPEECASE"):
            print("-" * 102)
            print(f"{'RupeeCase claimed (same window)':<42}{'45.2%':>7}{'16.5%':>7}"
                  f"{'2.32':>8}{'2.30':>8}{'-10.6%':>8}{'4.25':>8}{'-':>8}{'386':>9}")


if __name__ == "__main__":
    main()
