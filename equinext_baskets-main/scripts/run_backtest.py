"""
Run any basket's backtest on the loaded Nifty 50 data, vs the NIFTY50 index.

    python scripts/run_backtest.py relative_value
    python scripts/run_backtest.py valuation_momentum --rebalance Q --band 0.03
    python scripts/run_backtest.py valuation_momentum --rebalance M

Args:
  <basket>       relative_value | valuation_momentum
  --rebalance    M (month-end, default) | Q (quarter-end)   [turnover lever]
  --band FLOAT   no-trade band, e.g. 0.03 = keep a name unless its target moves >3%

Window auto-derived: 12 months after the first valuation row (so froth/quality
gates have history), to the last trading day. 25 bps/side costs, FIFO STCG/LTCG.

Benchmark: NIFTY50 price index (^NSEI). Both legs are PRICE returns (no dividends
on either side) — comparable, but understates absolute CAGR ~1-1.5% (use TRI later).

Outputs (per basket, so runs don't clobber each other):
  backtest_<basket>.csv               daily returns (basket / after-tax / nifty50)
  exports/backtest_monthly_<basket>.csv   month-by-month analysis
  basket_holdings table               holdings + scores audit trail
"""
from __future__ import annotations
import sys
import sqlite3
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from equinext.context import ResearchContext              # noqa: E402
from equinext.backtest import BacktestConfig, run_backtest  # noqa: E402
from equinext.metrics import compute_metrics              # noqa: E402
from baskets.relative_value import RelativeValueBasket    # noqa: E402
from baskets.valuation_momentum import (  # noqa: E402
    ValuationMomentumBasket, MomentumOnlyBasket, ValuationMomentumPEOnly,
    ValuationMomentumGrowthAdj)

BASKETS = {
    "relative_value": RelativeValueBasket,
    "valuation_momentum": ValuationMomentumBasket,
    "momentum_only": MomentumOnlyBasket,
    "vm_pe_only": ValuationMomentumPEOnly,
    "vm_growth_adj": ValuationMomentumGrowthAdj,
}
WARMUP_DAYS = 365


def _parse(argv):
    name = next((a for a in argv if not a.startswith("--")), "valuation_momentum")
    rebal = "ME"
    band = 0.0
    start_override = None
    for i, a in enumerate(argv):
        if a == "--rebalance" and i + 1 < len(argv):
            rebal = "QE" if argv[i + 1].upper().startswith("Q") else "ME"
        if a == "--band" and i + 1 < len(argv):
            band = float(argv[i + 1])
        if a == "--start" and i + 1 < len(argv):
            start_override = argv[i + 1]   # YYYY-MM-DD; overrides the auto warm-up window
    if name not in BASKETS:
        sys.exit(f"Unknown basket '{name}'. Choose from: {', '.join(BASKETS)}")
    return name, rebal, band, start_override


def _fmt(v, name):
    if v is None:
        return " " * 10
    ratio = ("harpe" in name) or ("ortino" in name)
    return f"{v:10.2f}" if ratio else f"{v:10.2%}"


def main(argv):
    name, rebal, band, start_override = _parse(argv)
    ctx = ResearchContext()

    con = sqlite3.connect(str(_REPO / "equinext.db"))
    vmin, vmax = con.execute("SELECT MIN(date), MAX(date) FROM valuation_series").fetchone()
    con.close()
    if vmin is None:
        sys.exit("valuation_series empty — run scripts/load_nifty50_data.py + load_valuation_full.py first.")
    if start_override:
        start = pd.Timestamp(start_override)
    else:
        start = pd.Timestamp(vmin) + pd.Timedelta(days=WARMUP_DAYS)
    end = ctx.price_matrix().index[-1]
    cadence = "quarterly" if rebal == "QE" else "monthly"
    print(f"Basket: {name}   cadence: {cadence}   no-trade band: {band:.0%}")
    print(f"Valuation data: {vmin} .. {vmax}")
    print(f"Backtest: {start.date()} .. {end.date()}"
          f"{'  (custom start)' if start_override else '  (12mo valuation warm-up)'}")
    if pd.Timestamp(start) < pd.Timestamp(vmin):
        print(f"NOTE: before {vmin} there is no valuation data -> froth/earnings gates "
              f"are INACTIVE; the basket runs momentum-only in that stretch.")
    print()

    cfg = BacktestConfig(start=start.date(), end=end.date(), rebalance=rebal, no_trade_band=band)
    basket = BASKETS[name]()
    res = run_backtest(basket, ctx, cfg)

    bench = ctx.benchmark_returns(start, end, index_name="NIFTY50")
    m = compute_metrics(res.returns, bench, after_tax=res.after_tax_returns)
    mb = compute_metrics(bench, bench)

    rows = [
        ("CAGR (price, net of costs)", m["cagr"], mb["cagr"]),
        ("CAGR after tax", m["cagr_after_tax"], None),
        ("Volatility (ann.)", m["vol"], mb["vol"]),
        ("Sharpe", m["sharpe"], mb["sharpe"]),
        ("Sortino", m["sortino"], mb["sortino"]),
        ("Max drawdown", m["max_drawdown"], mb["max_drawdown"]),
        ("Up capture", m["up_capture"], None),
        ("Down capture", m["down_capture"], None),
        ("1y-rolling hit rate", m["hit_rate_1y"], None),
    ]
    print(f"{'metric':<28} {'basket':>10} {'NIFTY50':>10}")
    print("-" * 50)
    for nm, a, b in rows:
        print(f"{nm:<28} {_fmt(a, nm)} {_fmt(b, nm)}")

    reb_per_yr = 4 if rebal == "QE" else 12
    print(f"\nAvg turnover per rebalance (both sides): {res.turnover.mean():.1%}"
          f"   (~{res.turnover.mean() * reb_per_yr:.0%}/yr)")
    print(f"Rebalances: {len(res.holdings)}")

    last_date = max(res.holdings)
    print(f"\nLatest holdings ({pd.Timestamp(last_date).date()}):")
    for s, w in sorted(res.holdings[last_date].items(), key=lambda kv: -kv[1]):
        print(f"  {s:<12} {w:6.2%}")

    # ---- daily returns file ----
    out = _REPO / f"backtest_{name}.csv"
    pd.DataFrame({
        "basket": res.returns,
        "basket_after_tax": res.after_tax_returns,
        "nifty50": bench.reindex(res.returns.index),
    }).to_csv(out)
    print(f"\nDaily returns saved -> {out}")

    # ---- month-by-month analysis file ----
    _write_monthly(_REPO / "exports" / f"backtest_monthly_{name}.csv", res, bench, cfg)

    # ---- holdings + scores into the standard table ----
    con = sqlite3.connect(str(_REPO / "equinext.db"))
    con.execute("DELETE FROM basket_holdings WHERE basket = ?", (basket.name,))
    con.executemany(
        "INSERT OR REPLACE INTO basket_holdings (basket, as_of, symbol, weight, score) "
        "VALUES (?,?,?,?,?)",
        [(basket.name, str(pd.Timestamp(d).date()), s, float(w), res.scores.get(d, {}).get(s))
         for d, hs in res.holdings.items() for s, w in hs.items()])
    con.commit(); con.close()
    print("Holdings + scores written to basket_holdings (equinext.db).")


def _write_monthly(out_m: Path, res, bench, cfg) -> None:
    """One row per calendar month: returns, ₹100 curves, drawdowns, and the
    rebalance that happened that month (turnover, trades). A rebalance's cost
    lands in the FIRST day of the NEXT month's return."""
    daily = pd.DataFrame({
        "basket": res.returns,
        "after_tax": res.after_tax_returns,
        "nifty50": bench.reindex(res.returns.index).fillna(0.0),
    })
    cum = (1 + daily).cumprod() * 100.0
    dd = cum / cum.cummax() - 1.0
    pm = lambda s, f: s.groupby(s.index.to_period("M")).apply(f)

    monthly = pd.DataFrame({
        "basket_ret": pm(daily["basket"], lambda r: (1 + r).prod() - 1),
        "after_tax_ret": pm(daily["after_tax"], lambda r: (1 + r).prod() - 1),
        "nifty50_ret": pm(daily["nifty50"], lambda r: (1 + r).prod() - 1),
    })
    monthly["excess_ret"] = monthly["basket_ret"] - monthly["nifty50_ret"]
    monthly["tax_drag"] = monthly["basket_ret"] - monthly["after_tax_ret"]
    for c in ("basket", "after_tax", "nifty50"):
        monthly[f"cum_{c}_rs100"] = pm(cum[c], lambda s: s.iloc[-1])
    monthly["basket_drawdown"] = pm(dd["basket"], lambda s: s.iloc[-1])
    monthly["nifty50_drawdown"] = pm(dd["nifty50"], lambda s: s.iloc[-1])

    prev = {}
    for d in sorted(res.holdings):
        mo = pd.Timestamp(d).to_period("M")
        held, sc = set(res.holdings[d]), res.scores.get(d, {})
        monthly.loc[mo, "rebalance_date"] = str(pd.Timestamp(d).date())
        monthly.loc[mo, "n_holdings"] = len(held)
        monthly.loc[mo, "turnover_two_sided"] = float(res.turnover.get(d, float("nan")))
        monthly.loc[mo, "est_cost_pct"] = cfg.cost_bps_per_side / 1e4 * float(res.turnover.get(d, 0.0))
        monthly.loc[mo, "avg_score"] = (sum(sc.values()) / len(sc)) if sc else None
        monthly.loc[mo, "n_bought"] = len(held - set(prev))
        monthly.loc[mo, "n_sold"] = len(set(prev) - held)
        monthly.loc[mo, "bought"] = ";".join(sorted(held - set(prev)))
        monthly.loc[mo, "sold"] = ";".join(sorted(set(prev) - held))
        prev = held

    monthly = monthly.sort_index()
    monthly.index.name = "month"
    out_m.parent.mkdir(exist_ok=True)
    monthly.round(6).to_csv(out_m)
    print(f"Monthly analysis file  -> {out_m}  ({len(monthly)} rows)")


if __name__ == "__main__":
    main(sys.argv[1:])
