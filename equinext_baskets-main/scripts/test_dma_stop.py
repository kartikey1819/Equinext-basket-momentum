"""
Test a short-DMA trend gate (10/15/20-day) + a hard per-stock stop-loss on the Total
Market 25%-sector-capped dynamic-monthly book. The stop-loss exits a held stock INTRA-
month when its price falls stop% below its entry (rebalance) price, parking the proceeds
in cash until the next rebalance. Both windows, net of cost.

    python scripts/test_dma_stop.py
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
from baskets.valuation_momentum import VMTotalMarket50                # noqa: E402
from scripts.backtest_allocator import run_switch, gold_returns, metrics  # noqa: E402

RC_START = pd.Timestamp("2022-11-18")
COST = 25.0 / 1e4


def accrue_with_stop(holdings: dict, px: pd.DataFrame, stop_pct: float) -> pd.Series:
    """Re-accrue the equity book's daily returns with a hard stop-loss: a held stock that
    trades below entry x (1-stop_pct) is sold that day (25 bps cost) and its weight parked
    in cash (0% return) until the next monthly rebalance. Mirrors the engine's 25 bps/side
    rebalance cost otherwise."""
    pxf = px.ffill()
    dr = px.pct_change(fill_method=None)
    days = px.index
    rebs = sorted(holdings)
    ret = pd.Series(index=days, dtype=float)
    prev: dict = {}
    for i, d in enumerate(rebs):
        tgt = holdings[d]
        syms = [s for s in tgt if s in px.columns]
        entry = pxf.loc[pxf.index <= d].iloc[-1]
        end_d = rebs[i + 1] if i + 1 < len(rebs) else days[-1]
        period = days[(days > d) & (days <= end_d)]
        turnover = sum(abs(tgt.get(s, 0) - prev.get(s, 0)) for s in set(tgt) | set(prev))
        w = pd.Series({s: float(tgt[s]) for s in syms}, dtype=float)
        cash, first = 0.0, True
        for day in period:
            r = dr.loc[day, w.index].fillna(0.0)
            ret[day] = float((w * r).sum()) - (COST * turnover if first else 0.0)
            w = w * (1 + r)
            tot = w.sum() + cash
            if tot > 0:
                w, cash = w / tot, cash / tot
            cur = pxf.loc[day, w.index]
            stopped = w.index[(cur < entry[w.index] * (1 - stop_pct)) & (w > 0)]
            if len(stopped):
                ex = float(w[stopped].sum())
                cash += ex
                ret[day] -= COST * ex
                w[stopped] = 0.0
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

    print("computing base + DMA-gated selections (Total Market, 25% cap) ...", flush=True)
    base = run_backtest(_cap(VMTotalMarket50()), ctx, cfg)
    dma = {}
    for ma in (10, 15, 20):
        b = _cap(VMTotalMarket50()); b.USE_TREND_GATE = True; b.TREND_MA = ma
        dma[ma] = run_backtest(b, ctx, cfg)

    rows = [("Baseline (25% cap, no DMA/stop)", base.returns)]
    for ma in (10, 15, 20):
        rows.append((f"+ {ma}-DMA gate", dma[ma].returns))
    for stop in (0.10, 0.15, 0.20):
        rows.append((f"+ {int(stop*100)}% stop-loss", accrue_with_stop(base.holdings, px, stop)))
    rows.append(("+ 15-DMA + 15% stop (combined)", accrue_with_stop(dma[15].holdings, px, 0.15)))
    rows.append(("+ 20-DMA + 15% stop (combined)", accrue_with_stop(dma[20].holdings, px, 0.15)))

    print(f"\n{'config':<34}| {'FULL WINDOW':^26} | {'RUPEECASE WIN':^22}")
    print(f"{'':<34}| {'CAGR':>6}{'Sharpe':>8}{'maxDD':>8} | {'CAGR':>6}{'Sharpe':>8}{'maxDD':>6}")
    print("-" * 92)
    for label, r_eq in rows:
        fm, rm = dial(r_eq, rg)
        print(f"{label:<34}| {fm['cagr']:>5.1f}%{fm['sharpe']:>8.2f}{fm['maxdd']:>7.1f}% | "
              f"{rm['cagr']:>5.1f}%{rm['sharpe']:>8.2f}{rm['maxdd']:>5.1f}%", flush=True)


def _cap(b):
    b.SECTOR_WEIGHT_CAP = 0.25
    return b


if __name__ == "__main__":
    main()
