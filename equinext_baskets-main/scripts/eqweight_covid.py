"""
Equity-weight timeline through the COVID crash (Dec 2019 - Jun 2020) for the 3-asset dial
timed INDEX vs SLEEVE, on the Mode C · RupeeCase full-window book. Shows *why* sleeve-timing
deepens the drawdown: it sits near 100% equity into the crash while the index signal has
already stepped down. Emits a JSON the artifact chart reads.

    python scripts/eqweight_covid.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from equinext.context import ResearchContext                     # noqa: E402
from equinext.backtest import BacktestConfig, run_backtest        # noqa: E402
from baskets.equinext_v2 import EquinextV2RC                      # noqa: E402
from scripts.backtest_allocator import run_switch, gold_returns   # noqa: E402

LOOKBACK = 63
WIN0, WIN1 = pd.Timestamp("2019-12-01"), pd.Timestamp("2020-06-30")


def modec_rc():
    b = EquinextV2RC()
    b.TIER_MODE = "C"; b.LARGE_ANCHOR = 0.30; b.SATELLITE_TILT = 1.0; b.SMALL_CAP_MAX = 0.40
    b.TIER_BOUNDS = (100, 250, 500); b.USE_TREND_GATE = False
    return b


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    cfg = BacktestConfig(start=pd.Timestamp("2017-08-01").date(), end=end.date(), rebalance="ME")
    print("building Mode C · RupeeCase full-window sleeve ...", flush=True)
    r_eq = run_backtest(modec_rc(), ctx, cfg).returns
    c = (1 + r_eq).cumprod()
    em = c / c.shift(LOOKBACK) - 1

    # both dials, daily equity-weight series
    _, w_idx = run_switch(r_eq, rg, "NIFTY500", "ME", return_weights=True)
    _, w_slv = run_switch(r_eq, rg, "NIFTY500", "ME", eq_mom_series=em, return_weights=True)
    book = (1 + r_eq).cumprod() * 100                              # the equity book level (base 100)

    days = w_idx.index[(w_idx.index >= WIN0) & (w_idx.index <= WIN1)]
    out = {"dates": [d.strftime("%Y-%m-%d") for d in days],
           "index_eq": [round(float(w_idx.loc[d]) * 100, 1) for d in days],
           "sleeve_eq": [round(float(w_slv.loc[d]) * 100, 1) for d in days],
           "book": [round(float(book.loc[d]), 1) for d in days]}
    (_REPO / "webapp" / "eqweight_covid.json").write_text(json.dumps(out), encoding="utf-8")

    # console: month-end snapshots so the story is legible without the chart
    print(f"\n{'date':<12}{'RC book':>9}{'  index-eq':>11}{'  sleeve-eq':>12}")
    print("-" * 46)
    peak = book.loc[book.index <= WIN1].cummax()
    for d in days:
        if d.day <= 3 or d == days[-1] or (d.month != (d - pd.Timedelta(days=1)).month):
            dd = book.loc[d] / peak.loc[d] - 1
            print(f"{d.strftime('%Y-%m-%d'):<12}{book.loc[d]:>8.1f}{'  ('+format(dd*100,'.0f')+'%)':>9}"
                  f"{w_idx.loc[d]*100:>9.0f}%{w_slv.loc[d]*100:>11.0f}%")


if __name__ == "__main__":
    main()
