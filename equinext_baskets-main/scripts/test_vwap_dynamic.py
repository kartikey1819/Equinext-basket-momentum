"""
Test an ANCHORED-VWAP selection gate on the dynamic-allocator baskets.

Idea (user's): from each stock's 52-week high to today, take the volume-weighted average
price (Anchored VWAP). If the stock is trading BELOW that average (the average buyer since
the peak is underwater = distribution/weakness), drop it — same shape as the RSI gate we
tried before. Implemented as `anchored_vwap_high` (primitives.py): keep a name only if
close >= AVWAP_since_52wk_high * (1 - VWAP_TOL). Tested strict (0%) and with 2%/5% bands.

Run on the 25%-sector-capped Total Market and Nifty 500 books, monthly, through the 3-asset
dial — full window (incl. COVID) and the RupeeCase window. Net of 25 bps/side.

    python scripts/test_vwap_dynamic.py
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


def dial(r_eq, rg):
    r_full, _ = run_switch(r_eq, rg, "NIFTY500", "ME")
    r_rc, _ = run_switch(r_eq[r_eq.index >= RC_START], rg, "NIFTY500", "ME")
    return metrics(r_full), metrics(r_rc)


def avg_hold(bt):
    return sum(len(h) for h in bt.holdings.values()) / max(1, len(bt.holdings))


def build(cls, tol=None):
    b = cls()
    b.SECTOR_WEIGHT_CAP = 0.25
    b._CACHE_ROWS = True                 # memoize scores across the tolerance variants (cheap replays)
    if tol is not None:
        b.USE_VWAP_GATE = True
        b.VWAP_TOL = tol
    return b


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    cfg = BacktestConfig(start=pd.Timestamp("2017-08-01").date(), end=end.date(), rebalance="ME")

    universes = [("Total Market", VMTotalMarket50), ("Nifty 500", VM500Standard50)]
    for uni_label, cls in universes:
        print(f"\ncomputing {uni_label} base + VWAP-gated books (monthly, 25% cap) ...", flush=True)
        variants = [("Baseline (no VWAP gate)", build(cls))]
        for tol in (0.0, 0.02, 0.05):
            lbl = "strict (close ≥ AVWAP)" if tol == 0 else f"{int(tol*100)}% band below AVWAP"
            variants.append((f"+ VWAP gate · {lbl}", build(cls, tol)))
        bts = [(lbl, run_backtest(b, ctx, cfg)) for lbl, b in variants]

        print(f"\n{'='*104}\n{uni_label} · dynamic monthly · 25% sector cap — Anchored-VWAP-since-52wk-high gate\n{'='*104}")
        print(f"{'config':<34}{'#hold':>6} | {'FULL WINDOW':^26} | {'RUPEECASE WINDOW':^24}")
        print(f"{'':<34}{'':>6} | {'CAGR':>6}{'Sharpe':>8}{'maxDD':>8} | {'CAGR':>6}{'Sharpe':>8}{'maxDD':>7}")
        print("-" * 104)
        for lbl, bt in bts:
            fm, rm = dial(bt.returns, rg)
            print(f"{lbl:<34}{avg_hold(bt):>6.1f} | {fm['cagr']:>5.1f}%{fm['sharpe']:>8.2f}{fm['maxdd']:>7.1f}% | "
                  f"{rm['cagr']:>5.1f}%{rm['sharpe']:>8.2f}{rm['maxdd']:>6.1f}%", flush=True)


if __name__ == "__main__":
    main()
