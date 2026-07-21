"""
Equinext V2 ablation — add one layer at a time and measure the delta, so every piece
earns its place. All on Total Market + the dynamic monthly dial, net of cost, both
windows, with the resulting sector concentration and small-cap exposure.

Uses the per-stock row cache (_CACHE_ROWS) so the heavy scoring runs once and every
later step replays from cache.

    python scripts/ablation_v2.py
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
from baskets.equinext_v2 import EquinextV2, TierMap                   # noqa: E402
from scripts.backtest_allocator import run_switch, gold_returns, metrics  # noqa: E402

EquinextV2._CACHE_ROWS = True
RC_START = pd.Timestamp("2022-11-18")

BASE = dict(USE_TIERS=False, USE_TREND_GATE=False, USE_MULTI_TF=False,
            RSI_MAX=None, SECTOR_WEIGHT_CAP=0.25, MAX_STOCK_WEIGHT=None)


def step(**kw):
    d = dict(BASE); d.update(kw); return d


STEPS = [
    ("S0 baseline (sector cap 25)", step()),
    ("S1 +200-DMA trend gate",      step(USE_TREND_GATE=True)),
    ("S2 +multi-TF momentum",       step(USE_TREND_GATE=True, USE_MULTI_TF=True)),
    ("S3 +8% stock cap",            step(USE_TREND_GATE=True, USE_MULTI_TF=True, MAX_STOCK_WEIGHT=0.08)),
    ("S4 +cap-tiers A (fixed)",     step(USE_TREND_GATE=True, USE_MULTI_TF=True, MAX_STOCK_WEIGHT=0.08, USE_TIERS=True, TIER_MODE="A")),
    ("S5 +cap-tiers B (regime)",    step(USE_TREND_GATE=True, USE_MULTI_TF=True, MAX_STOCK_WEIGHT=0.08, USE_TIERS=True, TIER_MODE="B")),
    ("S6 +RSI(30)>80 exclude",      step(USE_TREND_GATE=True, USE_MULTI_TF=True, MAX_STOCK_WEIGHT=0.08, USE_TIERS=True, TIER_MODE="B", RSI_MAX=80)),
]


def sector_peak(holdings, sector_of):
    peak, tops = 0.0, []
    for _, w in holdings.items():
        sw = {}
        for s, x in w.items():
            sec = sector_of(s) or "Unknown"
            sw[sec] = sw.get(sec, 0.0) + x
        mx = max(sw.values()) if sw else 0.0
        tops.append(mx); peak = max(peak, mx)
    return peak * 100


def tier_mix(holdings, tm):
    """Average book weight in each tier — rank ALL stocks (not just the held ~50, which
    would all rank 'large') so held names get their true Large/Mid/Small label."""
    allsyms = list(tm.shares.keys())
    L = M = S = 0.0
    for d, w in holdings.items():
        tiers = tm.assign(d, allsyms)
        L += sum(x for s, x in w.items() if tiers.get(s) == "L")
        M += sum(x for s, x in w.items() if tiers.get(s) == "M")
        S += sum(x for s, x in w.items() if tiers.get(s) == "S")
    n = len(holdings) or 1
    return L / n * 100, M / n * 100, S / n * 100


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    sector_of = lambda s: ctx.sector(s)
    tm = TierMap(ctx)
    cfg = BacktestConfig(start=pd.Timestamp("2017-08-01").date(), end=end.date(), rebalance="ME")

    print(f"{'step':<30}| {'FULL WINDOW (incl COVID)':^40} | {'RUPEECASE WINDOW':^22} | {'concentration':^10} | {'tier mix L/M/S':^16}")
    print(f"{'':<30}| {'CAGR':>6}{'Vol':>6}{'Sharpe':>7}{'Sortino':>8}{'maxDD':>7} | {'CAGR':>6}{'Sharpe':>7}{'maxDD':>7} | {'secPk':>10} | {'L':>5}{'M':>5}{'S':>5}")
    print("-" * 132)
    for label, ov in STEPS:
        b = EquinextV2()
        for k, v in ov.items():
            setattr(b, k, v)
        res = run_backtest(b, ctx, cfg)
        r_full, _ = run_switch(res.returns, rg, "NIFTY500", "ME")
        r_rc, _ = run_switch(res.returns[res.returns.index >= RC_START], rg, "NIFTY500", "ME")
        fm, rm = metrics(r_full), metrics(r_rc)
        pk = sector_peak(res.holdings, sector_of)
        L, M, S = tier_mix(res.holdings, tm)
        print(f"{label:<30}| {fm['cagr']:>5.1f}%{fm['vol']:>5.1f}%{fm['sharpe']:>7.2f}{fm['sortino']:>8.2f}{fm['maxdd']:>6.1f}% | "
              f"{rm['cagr']:>5.1f}%{rm['sharpe']:>7.2f}{rm['maxdd']:>6.1f}% | {pk:>9.0f}% | {L:>4.0f}%{M:>4.0f}%{S:>4.0f}%", flush=True)


if __name__ == "__main__":
    main()
