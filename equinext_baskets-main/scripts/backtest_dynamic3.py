"""
RupeeCase-style DYNAMIC 3-asset allocator (dual-momentum switch sleeves).

  Equity CORE  35%  -> always in equity (valuation-momentum, Std Nifty 500, up to 50)
  Switch A     40%  -> equity if equity-index momentum > debt momentum, else DEBT
  Switch B     25%  -> equity if equity-index momentum > gold momentum, else GOLD

Equity weight floats 35% (fully defensive) .. 100% (both switches in equity).
Relative-momentum lookback = 63 trading days (~3 months), decided at each rebalance.
Debt = 6.5%/yr liquid accrual; Gold = GoldBees.

Runs 3 cadences (quarterly / monthly / bi-monthly) over two periods:
  - RupeeCase window  (2022-11-18 .. latest)
  - Full window       (2017-08-01 .. latest, incl. COVID)

    python scripts/backtest_dynamic3.py
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
from baskets.valuation_momentum import VM500Standard50            # noqa: E402
from scripts.backtest_allocator import (                          # noqa: E402
    equity_returns, run_switch, gold_returns, metrics,
)

CADENCES = [("Quarterly", "QE"), ("Monthly", "ME"), ("Bi-monthly", "2M")]
INDEX = "NIFTY500"


def hdr(title):
    print(f"\n{'='*100}\n{title}\n{'='*100}")
    print(f"{'strategy':<40}{'CAGR':>7}{'Vol':>7}{'Sharpe':>8}{'Sortino':>8}"
          f"{'maxDD':>8}{'Calmar':>8}{'AvgEq%':>8}{'R100->':>9}")
    print("-" * 100)


def line(nm, m, avgeq=None):
    ae = f"{avgeq:>7.0f}%" if avgeq is not None else f"{'-':>8}"
    print(f"{nm:<40}{m['cagr']:>6.1f}%{m['vol']:>6.1f}%{m['sharpe']:>8.2f}"
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
        hdr(f"{pname}   {start.date()} .. {end.date()}   |   DYNAMIC switch: core 35 + eq/debt 40 + eq/gold 25  |  Std Nifty 500, up to 50 stocks")
        line("Nifty 50 (RupeeCase benchmark)", metrics(ctx.benchmark_returns(start, end, "NIFTY50")))
        line("Nifty 500 (our universe index)", metrics(ctx.benchmark_returns(start, end, "NIFTY500")))
        for cname, code in CADENCES:
            r_eq = equity_returns(VM500Standard50, start, end, rebalance=code)
            r_dyn, avgeq = run_switch(r_eq, rg, INDEX, code)
            line(f"DYNAMIC switch · {cname} rebalance", metrics(r_dyn), avgeq)
        if pname.startswith("RUPEECASE"):
            print("-" * 100)
            print(f"{'RupeeCase claimed (same window)':<40}{'45.2%':>7}{'16.5%':>7}"
                  f"{'2.32':>8}{'2.30':>8}{'-10.6%':>8}{'4.25':>8}{'-':>8}{'386':>9}")


if __name__ == "__main__":
    main()
