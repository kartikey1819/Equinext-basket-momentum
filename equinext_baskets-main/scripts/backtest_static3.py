"""
Fixed-weight 3-asset (35% equity / 40% debt / 25% gold) static allocator.

Equity sleeve = valuation-momentum on the STANDARD Nifty 500, up to 50 stocks
(inverse-vol weighted). Debt = 6.5%/yr liquid accrual. Gold = GoldBees.
Weights are RESET to 35/40/25 at every rebalance; no regime dial.

Runs 3 cadences (quarterly / monthly / bi-monthly) over two periods:
  - RupeeCase window  (2022-11-18 .. latest)   -- their exact backtest period
  - Full window       (2017-08-01 .. latest)   -- our full-cycle test incl. COVID

    python scripts/backtest_static3.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

try:                                          # Windows console is cp1252 by default
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from equinext.context import ResearchContext                      # noqa: E402
from baskets.valuation_momentum import VM500Standard50            # noqa: E402
from scripts.backtest_allocator import (                          # noqa: E402
    equity_returns, run_static, gold_returns, metrics,
)

WEIGHTS = (0.35, 0.40, 0.25)                 # equity / debt / gold
CADENCES = [("Quarterly", "QE"), ("Monthly", "ME"), ("Bi-monthly", "2M")]


def hdr(title):
    print(f"\n{'='*94}\n{title}\n{'='*94}")
    print(f"{'strategy':<40}{'CAGR':>7}{'Vol':>7}{'Sharpe':>8}{'Sortino':>8}"
          f"{'maxDD':>8}{'Calmar':>8}{'R100->':>9}")
    print("-" * 94)


def line(nm, m):
    print(f"{nm:<40}{m['cagr']:>6.1f}%{m['vol']:>6.1f}%{m['sharpe']:>8.2f}"
          f"{m['sortino']:>8.2f}{m['maxdd']:>7.1f}%{m['calmar']:>8.2f}{m['final']:>8.0f}")


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    periods = [
        ("RUPEECASE WINDOW", pd.Timestamp("2022-11-18")),
        ("FULL WINDOW (incl. COVID)", pd.Timestamp("2017-08-01")),
    ]

    for pname, start in periods:
        hdr(f"{pname}   {start.date()} .. {end.date()}   |   35% equity / 40% debt / 25% gold  |  Std Nifty 500, up to 50 stocks")
        line("Nifty 50 (RupeeCase benchmark)", metrics(ctx.benchmark_returns(start, end, "NIFTY50")))
        line("Nifty 500 (our universe index)", metrics(ctx.benchmark_returns(start, end, "NIFTY500")))
        for cname, code in CADENCES:
            r_eq = equity_returns(VM500Standard50, start, end, rebalance=code)
            r_static = run_static(r_eq, rg, WEIGHTS, code)
            line(f"3-ASSET static · {cname} rebalance", metrics(r_static))
        if pname.startswith("RUPEECASE"):
            print("-" * 94)
            print(f"{'RupeeCase claimed (same window)':<40}{'45.2%':>7}{'16.5%':>7}"
                  f"{'2.32':>8}{'2.30':>8}{'-10.6%':>8}{'4.25':>8}{'386':>9}")


if __name__ == "__main__":
    main()
