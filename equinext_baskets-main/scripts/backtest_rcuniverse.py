"""
Backtest using RUPEECASE'S OWN equity-holdings universe (~240 of their published
rebalance stocks we have prices for), ranked by MOMENTUM (no gates), + the dynamic
3-asset switch. 'Use their stocks, pick by momentum.'

NOTE (honest): this universe IS the set RupeeCase's momentum eventually held, so it is
SURVIVORSHIP-TILTED toward their winners — the return is an UPPER-biased estimate,
especially on the full window. Not a clean forward test.

    python scripts/backtest_rcuniverse.py
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
from baskets.valuation_momentum import VMRupeeCaseUniverse        # noqa: E402
from scripts.backtest_allocator import (                          # noqa: E402
    equity_returns, run_switch, gold_returns, metrics,
)

CADENCES = [("Quarterly", "QE"), ("Monthly", "ME"), ("Bi-monthly", "2M")]


def hdr(title):
    print(f"\n{'='*104}\n{title}\n{'='*104}")
    print(f"{'strategy':<46}{'CAGR':>7}{'Vol':>7}{'Sharpe':>8}{'Sortino':>8}"
          f"{'maxDD':>8}{'Calmar':>8}{'AvgEq%':>8}{'R100->':>9}")
    print("-" * 104)


def line(nm, m, avgeq=None):
    ae = f"{avgeq:>7.0f}%" if avgeq is not None else f"{'-':>8}"
    print(f"{nm:<46}{m['cagr']:>6.1f}%{m['vol']:>6.1f}%{m['sharpe']:>8.2f}"
          f"{m['sortino']:>8.2f}{m['maxdd']:>7.1f}%{m['calmar']:>8.2f}{ae}{m['final']:>8.0f}")


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    periods = [("RUPEECASE WINDOW", pd.Timestamp("2022-11-18")),
               ("FULL WINDOW (incl. COVID)", pd.Timestamp("2017-08-01"))]

    for pname, start in periods:
        hdr(f"{pname}   {start.date()} .. {end.date()}   |   RUPEECASE'S OWN STOCKS (~240) · momentum + dynamic switch")
        line("Nifty 50 index", metrics(ctx.benchmark_returns(start, end, "NIFTY50")))
        line("Nifty 500 index", metrics(ctx.benchmark_returns(start, end, "NIFTY500")))
        for cname, code in CADENCES:
            r_eq = equity_returns(VMRupeeCaseUniverse, start, end, rebalance=code)
            r_dyn, avgeq = run_switch(r_eq, rg, "NIFTY500", code)
            line(f"RC-universe momentum · {cname}", metrics(r_dyn), avgeq)
        if pname.startswith("RUPEECASE"):
            print("-" * 104)
            print(f"{'RupeeCase claimed (same window)':<46}{'45.2%':>7}{'16.5%':>7}"
                  f"{'2.32':>8}{'2.30':>8}{'-10.6%':>8}{'4.25':>8}{'-':>8}{'386':>9}")


if __name__ == "__main__":
    main()
