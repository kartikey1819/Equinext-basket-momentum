"""
Tune Mode C on the RupeeCase universe (where it beats Base): sweep the fixed large-cap
anchor and the small-cap ceiling, using TERTILE tier bounds so the ~240-stock RC book
actually has a real Small tier (the mid<->small rotation then works). Both windows.

    python scripts/tune_modec_rc.py
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
from equinext.backtest import BacktestConfig, run_backtest            # noqa: E402
from baskets.equinext_v2 import EquinextV2, EquinextV2RC, TierMap     # noqa: E402
from scripts.backtest_allocator import run_switch, gold_returns, metrics  # noqa: E402

EquinextV2._CACHE_ROWS = True
RC_START = pd.Timestamp("2022-11-18")
TERTILE = (0.3333, 0.6667, 1.0)


def make(anchor, ceil, bounds=TERTILE, gates=True):
    b = EquinextV2RC()
    b.TIER_MODE = "C"; b.SATELLITE_TILT = 1.0
    b.LARGE_ANCHOR = anchor; b.SMALL_CAP_MAX = ceil; b.TIER_BOUNDS = bounds
    if not gates:
        b.USE_TREND_GATE = False; b.USE_MULTI_TF = False; b.RSI_MAX = None
    return b


CONFIGS = [("REF: current deployed (bounds 100/250/500, a40, c40)", make(0.40, 0.40, bounds=(100, 250, 500)))]
for a in (0.25, 0.30, 0.35, 0.40):
    for c in (0.40, 0.60, 1.00):
        CONFIGS.append((f"tertile · anchor {int(a*100)}% · small<={int(c*100)}%", make(a, c)))
CONFIGS.append(("tertile · anchor 30% · small<=100% · NO gates", make(0.30, 1.00, gates=False)))
CONFIGS.append(("tertile · anchor 25% · small<=100% · NO gates", make(0.25, 1.00, gates=False)))


def tier_mix(holdings, tm):
    allsyms = list(tm.shares.keys())
    L = M = S = 0.0
    for d, w in holdings.items():
        ti = tm.assign(d, allsyms)
        L += sum(x for s, x in w.items() if ti.get(s) == "L")
        M += sum(x for s, x in w.items() if ti.get(s) == "M")
        S += sum(x for s, x in w.items() if ti.get(s) == "S")
    n = len(holdings) or 1
    return L / n * 100, M / n * 100, S / n * 100


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    tm_full = TierMap(ctx, (100, 250, 500))       # for reporting mix (market-wide L/M/S)
    cfg = BacktestConfig(start=pd.Timestamp("2017-08-01").date(), end=end.date(), rebalance="ME")

    print(f"{'config':<52}| {'FULL WINDOW':^24} | {'RUPEECASE WIN':^22}")
    print(f"{'':<52}| {'CAGR':>6}{'Sharpe':>8}{'maxDD':>8} | {'CAGR':>6}{'Sharpe':>8}{'maxDD':>6}")
    print("-" * 108)
    for label, b in CONFIGS:
        res = run_backtest(b, ctx, cfg)
        r_full, _ = run_switch(res.returns, rg, "NIFTY500", "ME")
        r_rc, _ = run_switch(res.returns[res.returns.index >= RC_START], rg, "NIFTY500", "ME")
        fm, rm = metrics(r_full), metrics(r_rc)
        print(f"{label:<52}| {fm['cagr']:>5.1f}%{fm['sharpe']:>8.2f}{fm['maxdd']:>7.1f}% | "
              f"{rm['cagr']:>5.1f}%{rm['sharpe']:>8.2f}{rm['maxdd']:>5.1f}%", flush=True)


if __name__ == "__main__":
    main()
