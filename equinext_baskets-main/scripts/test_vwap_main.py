"""
Test the ANCHORED-VWAP-since-52wk-high selection gate on the MAIN valuation-momentum
baskets (Nifty 50 & Nifty 500) — 100% EQUITY, NO 3-asset dial. On the dynamic (dial-hedged)
books this gate hurt (whipsaw + concentration, same as the DMA gate); here the book is
un-hedged, so a selection filter has more room. Keep a name only if close >= AVWAP*(1-tol).
Quarterly rebalance, full period incl. COVID. Net of 25 bps/side.

    python scripts/test_vwap_main.py
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
from baskets.valuation_momentum import ValuationMomentumPEOnly, VM500Standard  # noqa: E402
from scripts.backtest_allocator import metrics                            # noqa: E402


def avg_hold(bt):
    return sum(len(h) for h in bt.holdings.values()) / max(1, len(bt.holdings))


def build(cls, tol=None):
    b = cls()
    b._CACHE_ROWS = True                 # memoize scores across the tolerance variants
    if tol is not None:
        b.USE_VWAP_GATE = True
        b.VWAP_TOL = tol
    return b


def row(label, nhold, m):
    h = f"{nhold:>5.1f}" if nhold is not None else f"{'—':>5}"
    print(f"{label:<32}{h} {m['cagr']:>6.1f}%{m['vol']:>7.1f}%{m['sharpe']:>8.2f}"
          f"{m['maxdd']:>8.1f}%{m['calmar']:>8.2f}")


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    start = pd.Timestamp("2017-08-01")
    cfg = BacktestConfig(start=start.date(), end=end.date(), rebalance="QE")   # quarterly (canonical)

    universes = [("Nifty 50", ValuationMomentumPEOnly, "NIFTY50"),
                 ("Nifty 500", VM500Standard, "NIFTY500")]

    for uni_label, cls, index in universes:
        print(f"\ncomputing {uni_label} base + VWAP-gated books ...", flush=True)
        base = run_backtest(build(cls), ctx, cfg)
        gated = {}
        for tol in (0.0, 0.02, 0.05):
            gated[tol] = run_backtest(build(cls, tol), ctx, cfg)

        print(f"\n{'='*95}\n{uni_label} — valuation-momentum, 100% EQUITY (no dial), quarterly · Anchored-VWAP gate\n{'='*95}")
        print(f"{'config':<32}{'#hold':>5} {'CAGR':>7}{'Vol':>7}{'Sharpe':>8}{'maxDD':>8}{'Calmar':>8}")
        print("-" * 95)
        row(f"{index} index (benchmark)", None, metrics(ctx.benchmark_returns(start, end, index)))
        row("Baseline (no VWAP gate)", avg_hold(base), metrics(base.returns))
        for tol in (0.0, 0.02, 0.05):
            lbl = "strict (close ≥ AVWAP)" if tol == 0 else f"{int(tol*100)}% band below AVWAP"
            row(f"+ VWAP · {lbl}", avg_hold(gated[tol]), metrics(gated[tol].returns))


if __name__ == "__main__":
    main()
