"""
Sector-weight-cap sweep. Measures how a hard sector cap (25% etc.) reshapes the
dynamic-monthly baskets — return, risk AND concentration — vs the un-capped book.

Efficient: the heavy momentum selection runs ONCE per universe (no cap); each cap
level is then a cheap 'replay' that re-sizes the SAME selections through the waterfall
and re-accrues net-of-cost returns. Both windows use a fresh 3-asset dial on the
appropriate equity-return slice (selections don't depend on the start date).

    python scripts/sweep_sector_cap.py
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
from equinext.backtest import BacktestConfig, run_backtest, Basket, Selection  # noqa: E402
from baskets.valuation_momentum import (                              # noqa: E402
    VM500Standard50, VMTotalMarket50, VMRupeeCaseUniverse, cap_weights,
)
from scripts.backtest_allocator import run_switch, gold_returns, metrics  # noqa: E402

CAPS = [("no cap", None), ("30% cap", 0.30), ("25% cap", 0.25), ("20% cap", 0.20), ("15% cap", 0.15)]
RC_START = pd.Timestamp("2022-11-18")


class ReplayBasket(Basket):
    """Returns pre-computed (already sector-capped) selections keyed by rebalance date."""
    name = "replay"

    def __init__(self, sel_by_date):
        self._sel = sel_by_date

    def select(self, as_of, ctx):
        return self._sel[pd.Timestamp(as_of)]


def sector_stats(holdings, sector_of):
    """(peak single-sector weight, avg largest-sector weight, avg #sectors held) — the
    last shows the diversification a tighter cap forces."""
    peak, tops, nsec = 0.0, [], []
    for _, w in holdings.items():
        sw = {}
        for s, x in w.items():
            sec = sector_of(s) or "Unknown"
            sw[sec] = sw.get(sec, 0.0) + x
        mx = max(sw.values()) if sw else 0.0
        tops.append(mx)
        peak = max(peak, mx)
        nsec.append(sum(1 for v in sw.values() if v > 0.005))    # sectors with >0.5% weight
    n = len(holdings) or 1
    return peak * 100, sum(tops) / n * 100, sum(nsec) / n


def hdr(title):
    print(f"\n{'='*122}\n{title}\n{'='*122}")
    print(f"{'sector cap':<12}| {'FULL WINDOW (2017-, incl COVID)':^47} | {'RUPEECASE WINDOW (2022-)':^30} | {'diversification':^20}")
    print(f"{'':<12}| {'CAGR':>6}{'Vol':>6}{'Sharpe':>7}{'Sortino':>8}{'maxDD':>7}{'Calmar':>7} | "
          f"{'CAGR':>6}{'Sharpe':>7}{'maxDD':>7} | {'peak':>6}{'avgTop':>7}{'avgSec':>7}")
    print("-" * 122)


def row(label, fm, rm, peak, avgtop, avgsec):
    print(f"{label:<12}| {fm['cagr']:>5.1f}%{fm['vol']:>5.1f}%{fm['sharpe']:>7.2f}{fm['sortino']:>8.2f}"
          f"{fm['maxdd']:>6.1f}%{fm['calmar']:>7.2f} | {rm['cagr']:>5.1f}%{rm['sharpe']:>7.2f}{rm['maxdd']:>6.1f}% | "
          f"{peak:>5.0f}%{avgtop:>6.0f}%{avgsec:>7.1f}")


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    start = pd.Timestamp("2017-08-01")
    rg = gold_returns()
    sector_of = lambda s: ctx.sector(s)
    cfg = BacktestConfig(start=start.date(), end=end.date(), rebalance="ME")

    universes = [("Nifty 500", VM500Standard50), ("Total Market", VMTotalMarket50),
                 ("RupeeCase", VMRupeeCaseUniverse)]

    for uni_label, cls in universes:
        print(f"\ncomputing base selections for {uni_label} ...", flush=True)
        base = run_backtest(cls(), ctx, cfg)                 # heavy: momentum selection, once
        hdr(f"{uni_label} — 50-stock book + dynamic monthly 3-asset dial | 25% vs 15% sector cap")
        for cap_label, cap in CAPS:
            capped = {pd.Timestamp(d): cap_weights(w, sector_of, sector_cap=cap)
                      for d, w in base.holdings.items()}
            sels = {d: Selection(as_of=d.date(), weights=w, scores={s: 0.0 for s in w})
                    for d, w in capped.items()}
            res = run_backtest(ReplayBasket(sels), ctx, cfg)  # cheap replay: re-accrue returns
            r_eq = res.returns
            r_full, _ = run_switch(r_eq, rg, "NIFTY500", "ME")
            r_eq_rc = r_eq[r_eq.index >= RC_START]
            r_rc, _ = run_switch(r_eq_rc, rg, "NIFTY500", "ME")
            peak, avgtop, avgsec = sector_stats(capped, sector_of)
            row(cap_label, metrics(r_full), metrics(r_rc), peak, avgtop, avgsec)


if __name__ == "__main__":
    main()
