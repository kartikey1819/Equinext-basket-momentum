"""
Stronger stop-loss designs on the Total Market 25%-capped dynamic book: a TRAILING stop
(exit X% below the peak since entry — locks gains), wider fixed stops, and a
redistribute-to-survivors variant (instead of parking in cash). Answers whether ANY
stop-loss design beats the plain baseline. Base selection runs once; stops replay cheaply.

    python scripts/test_stop_variants.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from equinext.context import ResearchContext                          # noqa: E402
from equinext.backtest import BacktestConfig, run_backtest            # noqa: E402
from baskets.valuation_momentum import VMTotalMarket50                # noqa: E402
from scripts.backtest_allocator import run_switch, gold_returns, metrics  # noqa: E402

RC_START = pd.Timestamp("2022-11-18")
COST = 25.0 / 1e4


def accrue_stop(holdings, px, stop_pct, trailing=False, to_cash=True):
    pxf = px.ffill()
    dr = px.pct_change(fill_method=None)
    days = px.index
    rebs = sorted(holdings)
    ret = pd.Series(index=days, dtype=float)
    prev = {}
    for i, d in enumerate(rebs):
        tgt = holdings[d]
        syms = [s for s in tgt if s in px.columns]
        entry = pxf.loc[pxf.index <= d].iloc[-1][syms]
        end_d = rebs[i + 1] if i + 1 < len(rebs) else days[-1]
        period = days[(days > d) & (days <= end_d)]
        turnover = sum(abs(tgt.get(s, 0) - prev.get(s, 0)) for s in set(tgt) | set(prev))
        w = pd.Series({s: float(tgt[s]) for s in syms}, dtype=float)
        peak = entry.copy()
        cash, first = 0.0, True
        for day in period:
            r = dr.loc[day, w.index].fillna(0.0)
            ret[day] = float((w * r).sum()) - (COST * turnover if first else 0.0)
            w = w * (1 + r)
            tot = w.sum() + cash
            if tot > 0:
                w, cash = w / tot, cash / tot
            cur = pxf.loc[day, w.index]
            if trailing:
                peak = pd.Series(np.maximum(peak.values, cur.values), index=w.index)
            ref = peak if trailing else entry
            stopped = w.index[(w > 0) & (cur < ref * (1 - stop_pct))]
            if len(stopped):
                ex = float(w[stopped].sum())
                ret[day] -= COST * ex
                w[stopped] = 0.0
                if to_cash:
                    cash += ex
                else:
                    surv = w.index[w > 0]
                    if len(surv) and w[surv].sum() > 0:
                        w[surv] += ex * w[surv] / w[surv].sum()
                    else:
                        cash += ex
            first = False
        prev = w[w > 0].to_dict()
    return ret.dropna()


def dial(r_eq, rg):
    r_full, _ = run_switch(r_eq, rg, "NIFTY500", "ME")
    r_rc, _ = run_switch(r_eq[r_eq.index >= RC_START], rg, "NIFTY500", "ME")
    return metrics(r_full), metrics(r_rc)


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    px = ctx.price_matrix()
    rg = gold_returns()
    cfg = BacktestConfig(start=pd.Timestamp("2017-08-01").date(), end=end.date(), rebalance="ME")
    print("computing base selection (Total Market, 25% cap) ...", flush=True)
    b = VMTotalMarket50(); b.SECTOR_WEIGHT_CAP = 0.25
    base = run_backtest(b, ctx, cfg)
    H = base.holdings

    rows = [("Baseline (no stop)", base.returns)]
    for s in (0.25, 0.30):
        rows.append((f"fixed {int(s*100)}% -> cash", accrue_stop(H, px, s)))
    for s in (0.15, 0.20, 0.25):
        rows.append((f"TRAILING {int(s*100)}% -> cash", accrue_stop(H, px, s, trailing=True)))
    rows.append(("fixed 20% -> survivors", accrue_stop(H, px, 0.20, to_cash=False)))
    rows.append(("TRAILING 20% -> survivors", accrue_stop(H, px, 0.20, trailing=True, to_cash=False)))

    print(f"\n{'stop design (25% cap book)':<30}| {'FULL WINDOW':^26} | {'RUPEECASE WIN':^22}")
    print(f"{'':<30}| {'CAGR':>6}{'Sharpe':>8}{'maxDD':>8} | {'CAGR':>6}{'Sharpe':>8}{'maxDD':>6}")
    print("-" * 88)
    for label, r_eq in rows:
        fm, rm = dial(r_eq, rg)
        print(f"{label:<30}| {fm['cagr']:>5.1f}%{fm['sharpe']:>8.2f}{fm['maxdd']:>7.1f}% | "
              f"{rm['cagr']:>5.1f}%{rm['sharpe']:>8.2f}{rm['maxdd']:>5.1f}%", flush=True)


if __name__ == "__main__":
    main()
