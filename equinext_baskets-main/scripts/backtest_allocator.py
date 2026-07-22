"""
Equinext Dynamic — 3-asset (equity / debt / gold) tactical allocator backtest.

Wraps the valuation-momentum EQUITY engine (sector-capped, survivorship-free) in a
monthly RISK DIAL that shifts money between equity, debt and gold based on a slow,
whipsaw-resistant regime signal:

  Regime signal (evaluated at each month-end on the equity index):
    trend  = index close > its 200-day moving average
    absmom = index trailing 6-month return > 0
  score = trend + absmom  ->  ON (2) / NEUTRAL (1) / OFF (0)

  DEFENSIVE tier weights (equity / debt / gold):
    ON      85 /  0 / 15
    NEUTRAL 55 / 25 / 20
    OFF     30 / 40 / 30            (30% permanent equity floor -> never fully miss a rebound)

Cadence: stocks rebalance QUARTERLY (tax-efficient); the asset dial adjusts MONTHLY.
Assets: equity = run_backtest(net-of-cost) on the sector-capped basket; gold = GoldBees
daily; debt = constant 6.5%/yr liquid-debt accrual (short-duration shelter proxy).
Switch cost = 25 bps/side on the asset weights traded at each monthly reweight.

    python scripts/backtest_allocator.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from equinext.context import ResearchContext                     # noqa: E402
from equinext.backtest import BacktestConfig, run_backtest, _rebalance_dates  # noqa: E402
from equinext.data import prices                                 # noqa: E402
from baskets.valuation_momentum import (                         # noqa: E402
    VMSectorCapPIT, VM500SectorCapPIT, ValuationMomentumPIT, VM500PIT,
)

COST = 25.0 / 1e4                 # 25 bps per side on asset-level switches
DEBT_YIELD = 0.065                # liquid/short G-Sec debt annual accrual
DEBT_DAILY = (1 + DEBT_YIELD) ** (1 / 252) - 1

# Defensive tier: score -> (equity, debt, gold)
TIERS = {2: (0.85, 0.00, 0.15),
         1: (0.55, 0.25, 0.20),
         0: (0.30, 0.40, 0.30)}


# --------------------------------------------------------------------------- #
# data helpers
# --------------------------------------------------------------------------- #
def gold_close() -> pd.Series:
    df = pd.read_csv(_REPO / "assets" / "goldbees.csv", parse_dates=["date"])
    return df.set_index("date")["close"].sort_index()


def gold_returns() -> pd.Series:
    return gold_close().pct_change(fill_method=None)


def index_signals(index_name: str, start, end):
    """Return (score_fn) giving the regime score asof a date, using history that
    starts ~1y before `start` so the 200-DMA is warm from day one."""
    idx = prices.load_benchmark(index_name, pd.Timestamp(start) - pd.Timedelta(days=420), end)
    sma200 = idx.rolling(200).mean()
    mom6 = idx / idx.shift(126) - 1

    def score(d):
        c, s, m = idx.asof(d), sma200.asof(d), mom6.asof(d)
        trend = int(pd.notna(c) and pd.notna(s) and c > s)
        absm = int(pd.notna(m) and m > 0)
        return trend + absm
    return score


def month_end_days(days: pd.DatetimeIndex) -> list:
    per = days.to_period("M")
    last = pd.Series(days, index=per).groupby(level=0).last()
    return sorted(last.values)


# --------------------------------------------------------------------------- #
# the dial simulation
# --------------------------------------------------------------------------- #
def run_dynamic(r_eq: pd.Series, r_gold: pd.Series, index_name: str) -> pd.Series:
    """Blend equity/debt/gold daily with a monthly regime dial + drift + switch cost.
    r_eq is the equity basket's net-of-cost daily return series (the master calendar)."""
    days = r_eq.index
    R = pd.DataFrame({
        "eq": r_eq,
        "debt": pd.Series(DEBT_DAILY, index=days),
        "gold": r_gold.reindex(days).fillna(0.0),
    })
    score = index_signals(index_name, days[0], days[-1])
    rebs = sorted(set([days[0]] + list(month_end_days(days))))

    port = pd.Series(index=days, dtype=float)
    cur = None                                          # drifted asset weights carried across periods
    for i, d in enumerate(rebs):
        tgt = pd.Series(dict(zip(("eq", "debt", "gold"), TIERS[score(d)])))
        traded = tgt.abs().sum() if cur is None else (tgt - cur).abs().sum()
        cost = COST * traded
        w = tgt.copy()
        end_d = rebs[i + 1] if i + 1 < len(rebs) else days[-1]
        period = days[(days > d) & (days <= end_d)]
        first = True
        for day in period:
            r = R.loc[day]
            port.loc[day] = float((w * r).sum()) - (cost if first else 0.0)
            w = w * (1 + r)
            sm = w.sum()
            if sm:
                w = w / sm
            first = False
        cur = w                                         # hand drifted weights to next reweight
    return port.dropna()


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def metrics(r: pd.Series) -> dict:
    r = r.dropna()
    eq = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(252)
    dvol = r[r < 0].std() * np.sqrt(252)
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": cagr * 100, "vol": vol * 100,
            "sharpe": cagr / vol if vol else np.nan,
            "sortino": cagr / dvol if dvol else np.nan,
            "maxdd": dd * 100, "calmar": cagr / abs(dd) if dd else np.nan,
            "final": eq.iloc[-1] * 100, "years": yrs}


def run_switch(r_eq: pd.Series, r_gold: pd.Series, index_name: str, rebalance,
               core=0.35, wA=0.40, wB=0.25, lookback=63, eq_mom_series=None, return_weights=False):
    """RupeeCase-style dual-momentum dial. A fixed `core` equity sleeve, plus two
    SWITCH sleeves decided by RELATIVE MOMENTUM at each rebalance:
      switch A (wA): hold EQUITY if the equity index's trailing return beats debt's,
                     else hold DEBT.
      switch B (wB): hold EQUITY if it beats gold's trailing return, else hold GOLD.
    So equity floats between `core` (both switches defensive) and core+wA+wB (both in
    equity). `lookback` = momentum window in trading days (63 ~ 3 months).

    Equity-momentum source: by default the broad `index_name` benchmark (a clean, low-noise
    market-regime read). Pass `eq_mom_series` (a date-indexed trailing-return series) to time
    the switch off the equity SLEEVE's own momentum instead — used for the sleeve-vs-index
    ablation. Default None -> unchanged (deployed baskets are index-timed).
    Returns (port_returns, avg_equity_weight)."""
    days = r_eq.index
    R = pd.DataFrame({"eq": r_eq,
                      "debt": pd.Series(DEBT_DAILY, index=days),
                      "gold": r_gold.reindex(days).fillna(0.0)})
    gc = gold_close()
    if eq_mom_series is not None:
        eq_mom = eq_mom_series
    else:
        idx = prices.load_benchmark(index_name, days[0] - pd.Timedelta(days=320), days[-1])
        eq_mom = idx / idx.shift(lookback) - 1
    gold_mom = gc / gc.shift(lookback) - 1
    debt_mom = (1 + DEBT_YIELD) ** (lookback / 252) - 1

    def target(d):
        em = eq_mom.asof(d); gm = gold_mom.asof(d)
        em = float(em) if pd.notna(em) else 0.0
        gm = float(gm) if pd.notna(gm) else 0.0
        a_eq, b_eq = em > debt_mom, em > gm            # switch A vs debt, switch B vs gold
        eq = core + (wA if a_eq else 0.0) + (wB if b_eq else 0.0)
        return pd.Series({"eq": eq, "debt": 0.0 if a_eq else wA, "gold": 0.0 if b_eq else wB})

    rebs = sorted(set([days[0]] + list(_rebalance_dates(days, rebalance))))
    port = pd.Series(index=days, dtype=float)
    eqw = pd.Series(index=days, dtype=float)
    cur = None
    for i, d in enumerate(rebs):
        tgt = target(d)
        traded = tgt.abs().sum() if cur is None else (tgt - cur).abs().sum()
        cost = COST * traded
        w = tgt.copy()
        end_d = rebs[i + 1] if i + 1 < len(rebs) else days[-1]
        period = days[(days > d) & (days <= end_d)]
        first = True
        for day in period:
            r = R.loc[day]
            port.loc[day] = float((w * r).sum()) - (cost if first else 0.0)
            eqw.loc[day] = w["eq"]
            w = w * (1 + r)
            sm = w.sum()
            if sm:
                w = w / sm
            first = False
        cur = w
    port = port.dropna()
    if return_weights:
        return port, eqw.reindex(port.index)                # full daily equity-weight series (0-1)
    return port, eqw.reindex(port.index).mean() * 100


def switch_asset_split(index_name: str, days, rebalance="ME",
                       core=0.35, wA=0.40, wB=0.25, lookback=63) -> dict:
    """The dual-momentum switch's LATEST target asset split (eq/debt/gold, %), evaluated
    at the final rebalance date over `days`. Mirrors run_switch's signal exactly so the
    'current allocation' shown on the site matches what the backtest is holding today."""
    days = pd.DatetimeIndex(days)
    idx = prices.load_benchmark(index_name, days[0] - pd.Timedelta(days=320), days[-1])
    gc = gold_close()
    eq_mom = idx / idx.shift(lookback) - 1
    gold_mom = gc / gc.shift(lookback) - 1
    debt_mom = (1 + DEBT_YIELD) ** (lookback / 252) - 1
    rebs = sorted(set([days[0]] + list(_rebalance_dates(days, rebalance))))
    d = rebs[-1]
    em, gm = eq_mom.asof(d), gold_mom.asof(d)
    em = float(em) if pd.notna(em) else 0.0
    gm = float(gm) if pd.notna(gm) else 0.0
    a_eq, b_eq = em > debt_mom, em > gm                 # switch A vs debt, switch B vs gold
    eq = core + (wA if a_eq else 0.0) + (wB if b_eq else 0.0)
    return {"asof": str(pd.Timestamp(d).date()),
            "eq": round(eq * 100, 1),
            "debt": round((0.0 if a_eq else wA) * 100, 1),
            "gold": round((0.0 if b_eq else wB) * 100, 1)}


def switch_avg_split(index_name: str, days, rebalance="ME",
                     core=0.35, wA=0.40, wB=0.25, lookback=63) -> dict:
    """AVERAGE target asset split (eq/debt/gold, %) of the dual-momentum switch across every
    rebalance over `days` — how the dial sat on average. Same signal as run_switch."""
    days = pd.DatetimeIndex(days)
    idx = prices.load_benchmark(index_name, days[0] - pd.Timedelta(days=320), days[-1])
    gc = gold_close()
    eq_mom = idx / idx.shift(lookback) - 1
    gold_mom = gc / gc.shift(lookback) - 1
    debt_mom = (1 + DEBT_YIELD) ** (lookback / 252) - 1
    rebs = sorted(set([days[0]] + list(_rebalance_dates(days, rebalance))))
    eqs, debts, golds = [], [], []
    for d in rebs:
        em, gm = eq_mom.asof(d), gold_mom.asof(d)
        em = float(em) if pd.notna(em) else 0.0
        gm = float(gm) if pd.notna(gm) else 0.0
        a_eq, b_eq = em > debt_mom, em > gm
        eqs.append(core + (wA if a_eq else 0.0) + (wB if b_eq else 0.0))
        debts.append(0.0 if a_eq else wA)
        golds.append(0.0 if b_eq else wB)
    n = len(rebs) or 1
    return {"eq": sum(eqs) / n * 100, "debt": sum(debts) / n * 100, "gold": sum(golds) / n * 100}


def worst_drawdowns(equity: pd.Series, n: int = 5) -> list[dict]:
    """Top-n worst peak-to-trough drawdown EPISODES from a daily equity curve.
    Each: started (peak date), recovered (back-to-peak date or 'ongoing'), trough
    date, max_dd %, duration in days. Sorted most-severe first. Real data only."""
    eq = equity.dropna()
    if eq.empty:
        return []
    peak = eq.cummax()
    dd = eq / peak - 1
    episodes, start, trough, trough_date, peak_date = [], None, 0.0, None, eq.index[0]
    for date, val in dd.items():
        if val < -1e-9:
            if start is None:
                start, trough, trough_date = peak_date, val, date
            elif val < trough:
                trough, trough_date = val, date
        else:
            if start is not None:
                episodes.append((start, trough_date, date, trough))
                start = None
            peak_date = date
    if start is not None:                     # drawdown still open at the series end
        episodes.append((start, trough_date, None, trough))
    episodes.sort(key=lambda e: e[3])
    out = []
    for s, t, r, mdd in episodes[:n]:
        out.append({"started": str(pd.Timestamp(s).date()),
                    "trough": str(pd.Timestamp(t).date()),
                    "recovered": (str(pd.Timestamp(r).date()) if r is not None else "ongoing"),
                    "max_dd": round(mdd * 100, 2),
                    "duration_days": int(((r if r is not None else eq.index[-1]) - s).days)})
    return out


def equity_returns(basket_cls, start, end, rebalance="QE") -> pd.Series:
    ctx = ResearchContext()
    cfg = BacktestConfig(start=start.date(), end=end.date(), rebalance=rebalance)
    return run_backtest(basket_cls(), ctx, cfg).returns


def run_static(r_eq: pd.Series, r_gold: pd.Series, weights, rebalance) -> pd.Series:
    """FIXED-weight 3-asset blend: reset to `weights` (eq,debt,gold) at each rebalance
    date, drift between. No regime dial. Switch cost applies when drift is reset to
    target. r_eq (net-of-cost equity basket returns) is the master calendar."""
    days = r_eq.index
    R = pd.DataFrame({"eq": r_eq,
                      "debt": pd.Series(DEBT_DAILY, index=days),
                      "gold": r_gold.reindex(days).fillna(0.0)})
    target = pd.Series(dict(zip(("eq", "debt", "gold"), weights)))
    rebs = sorted(set([days[0]] + list(_rebalance_dates(days, rebalance))))
    port = pd.Series(index=days, dtype=float)
    cur = None
    for i, d in enumerate(rebs):
        traded = target.abs().sum() if cur is None else (target - cur).abs().sum()
        cost = COST * traded
        w = target.copy()
        end_d = rebs[i + 1] if i + 1 < len(rebs) else days[-1]
        period = days[(days > d) & (days <= end_d)]
        first = True
        for day in period:
            r = R.loc[day]
            port.loc[day] = float((w * r).sum()) - (cost if first else 0.0)
            w = w * (1 + r)
            sm = w.sum()
            if sm:
                w = w / sm
            first = False
        cur = w
    return port.dropna()


# --------------------------------------------------------------------------- #
def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    start = pd.Timestamp("2017-08-01")
    rg = gold_returns()

    configs = [
        ("NIFTY 50",  "NIFTY50",  VMSectorCapPIT,    ValuationMomentumPIT),
        ("NIFTY 500", "NIFTY500", VM500SectorCapPIT, VM500PIT),
    ]

    for label, index_name, capped_cls, plain_cls in configs:
        print(f"\n{'='*74}\n{label}  |  {start.date()} .. {end.date()}\n{'='*74}")

        r_plain = equity_returns(plain_cls, start, end)          # 100% equity, no cap, no dial
        r_capped = equity_returns(capped_cls, start, end)        # 100% equity, sector-capped
        common = r_plain.index.intersection(r_capped.index)
        r_dyn = run_dynamic(r_capped.loc[common], rg, index_name)  # capped equity + 3-asset dial
        bench = ctx.benchmark_returns(start, end, index_name).reindex(common).dropna()

        rows = [
            (f"{label} index", metrics(bench)),
            ("Plain equity basket (100% eq)", metrics(r_plain.loc[common])),
            ("+ Sector cap (100% eq)", metrics(r_capped.loc[common])),
            ("Equinext DYNAMIC (3-asset dial)", metrics(r_dyn)),
        ]
        print(f"{'strategy':<34}{'CAGR':>7}{'Vol':>7}{'Sharpe':>8}{'Sortino':>8}"
              f"{'maxDD':>8}{'Calmar':>8}{'R100->':>9}")
        print("-" * 90)
        for nm, m in rows:
            print(f"{nm:<34}{m['cagr']:>6.1f}%{m['vol']:>6.1f}%{m['sharpe']:>8.2f}"
                  f"{m['sortino']:>8.2f}{m['maxdd']:>7.1f}%{m['calmar']:>8.2f}{m['final']:>8.0f}")


if __name__ == "__main__":
    main()
