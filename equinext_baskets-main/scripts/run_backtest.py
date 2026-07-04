"""
Run the Relative Value basket backtest on the loaded Nifty 50 data.

Prereq: python scripts/load_nifty50_data.py  (fills prices + valuation_series).

Window is auto-derived from the data: starts 12 months after the earliest P/E
row (so every name can clear MIN_PE_OBS before its first possible selection),
ends at the last trading day. Monthly rebalance, 25 bps/side costs, FIFO
STCG/LTCG — all from the shared harness (equinext/backtest.py).

Benchmark: NIFTY50 price index (^NSEI). Both legs are PRICE returns (no
dividends on either side) — comparable, but understates absolute CAGR ~1-1.5%.

    python scripts/run_backtest.py
"""
from __future__ import annotations
import sys
import sqlite3
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from equinext.context import ResearchContext          # noqa: E402
from equinext.backtest import BacktestConfig, run_backtest  # noqa: E402
from equinext.metrics import compute_metrics          # noqa: E402
from baskets.relative_value import RelativeValueBasket, MIN_PE_OBS  # noqa: E402


def main():
    ctx = ResearchContext()

    # window: start when BREADTH exists — the date the 30th name clears the
    # MIN_PE_OBS warm-up (else early rebalances hold a 1-2 stock "portfolio").
    con = sqlite3.connect(str(_REPO / "equinext.db"))
    pe_min, pe_max = con.execute("SELECT MIN(date), MAX(date) FROM valuation_series").fetchone()
    if pe_min is None:
        sys.exit("valuation_series is empty — run scripts/load_nifty50_data.py first.")
    ready = [r[0] for r in con.execute(
        """SELECT date FROM (
               SELECT symbol, date,
                      ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date) AS rn
               FROM valuation_series WHERE pe IS NOT NULL
           ) WHERE rn = ?""", (MIN_PE_OBS,)).fetchall()]
    con.close()
    if len(ready) < 30:
        sys.exit(f"Only {len(ready)} names ever clear {MIN_PE_OBS} P/E obs — load more data.")
    start = pd.Timestamp(sorted(ready)[29])           # 30th name becomes selectable
    end = ctx.price_matrix().index[-1]
    print(f"P/E data: {pe_min} .. {pe_max}")
    print(f"Backtest: {start.date()} .. {end.date()}  "
          f"(starts when 30 names clear the {MIN_PE_OBS}-obs P/E warm-up)\n")

    cfg = BacktestConfig(start=start.date(), end=end.date())
    basket = RelativeValueBasket()
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
    for name, a, b in rows:
        fa = f"{a:10.2%}" if isinstance(a, float) and abs(a) < 3 and "harpe" not in name and "ortino" not in name else (f"{a:10.2f}" if a is not None else " " * 10)
        fb = f"{b:10.2%}" if isinstance(b, float) and abs(b) < 3 and "harpe" not in name and "ortino" not in name else (f"{b:10.2f}" if b is not None else " " * 10)
        print(f"{name:<28} {fa} {fb}")

    print(f"\nAvg monthly turnover (both sides): {res.turnover.mean():.1%}")
    print(f"Rebalances: {len(res.holdings)}")

    last_date = max(res.holdings)
    last = res.holdings[last_date]
    print(f"\nLatest holdings ({last_date.date() if hasattr(last_date, 'date') else last_date}):")
    for s, w in sorted(last.items(), key=lambda kv: -kv[1]):
        print(f"  {s:<12} {w:6.2%}")

    # persist for inspection / plotting
    out = _REPO / "backtest_relative_value.csv"
    pd.DataFrame({
        "basket": res.returns,
        "basket_after_tax": res.after_tax_returns,
        "nifty50": bench.reindex(res.returns.index),
    }).to_csv(out)
    print(f"\nDaily returns saved -> {out}")

    # ---- month-by-month analysis file -------------------------------------
    # One row per calendar month: returns, cumulative ₹100 curves, drawdowns,
    # plus the rebalance that happened at that month's END (turnover, trades,
    # avg cheapness of the picked book). NOTE: a month-end rebalance's costs
    # land in the FIRST day of the NEXT month's return.
    daily = pd.DataFrame({
        "basket": res.returns,
        "after_tax": res.after_tax_returns,
        "nifty50": bench.reindex(res.returns.index).fillna(0.0),
    })
    cum = (1 + daily).cumprod() * 100.0
    dd = cum / cum.cummax() - 1.0

    def _per_month(df, f):
        return df.groupby(df.index.to_period("M")).apply(f)

    monthly = pd.DataFrame({
        "basket_ret": _per_month(daily["basket"], lambda r: (1 + r).prod() - 1),
        "after_tax_ret": _per_month(daily["after_tax"], lambda r: (1 + r).prod() - 1),
        "nifty50_ret": _per_month(daily["nifty50"], lambda r: (1 + r).prod() - 1),
    })
    monthly["excess_ret"] = monthly["basket_ret"] - monthly["nifty50_ret"]
    monthly["tax_drag"] = monthly["basket_ret"] - monthly["after_tax_ret"]
    for c in ("basket", "after_tax", "nifty50"):
        monthly[f"cum_{c}_rs100"] = _per_month(cum[c], lambda s: s.iloc[-1])
    monthly["basket_drawdown"] = _per_month(dd["basket"], lambda s: s.iloc[-1])
    monthly["nifty50_drawdown"] = _per_month(dd["nifty50"], lambda s: s.iloc[-1])

    # rebalance facts (keyed by the month the rebalance happened in)
    prev = {}
    for d in sorted(res.holdings):
        m = pd.Timestamp(d).to_period("M")
        held = set(res.holdings[d])
        sc = res.scores.get(d, {})
        monthly.loc[m, "rebalance_date"] = str(pd.Timestamp(d).date())
        monthly.loc[m, "n_holdings"] = len(held)
        monthly.loc[m, "turnover_two_sided"] = float(res.turnover.get(d, float("nan")))
        monthly.loc[m, "est_cost_pct"] = cfg.cost_bps_per_side / 1e4 * float(res.turnover.get(d, 0.0))
        monthly.loc[m, "avg_score"] = (sum(sc.values()) / len(sc)) if sc else None
        monthly.loc[m, "n_bought"] = len(held - set(prev))
        monthly.loc[m, "n_sold"] = len(set(prev) - held)
        monthly.loc[m, "bought"] = ";".join(sorted(held - set(prev)))
        monthly.loc[m, "sold"] = ";".join(sorted(set(prev) - held))
        prev = held

    monthly = monthly.sort_index()
    monthly.index.name = "month"
    out_m = _REPO / "exports" / "backtest_monthly.csv"
    out_m.parent.mkdir(exist_ok=True)
    monthly.round(6).to_csv(out_m)
    print(f"Monthly analysis file  -> {out_m}  ({len(monthly)} rows)")

    # also record holdings + scores into the standard basket_holdings table
    con = sqlite3.connect(str(_REPO / "equinext.db"))
    con.execute("DELETE FROM basket_holdings WHERE basket = ?", (basket.name,))
    con.executemany(
        "INSERT OR REPLACE INTO basket_holdings (basket, as_of, symbol, weight, score) "
        "VALUES (?,?,?,?,?)",
        [(basket.name, str(pd.Timestamp(d).date()), s, float(w),
          res.scores.get(d, {}).get(s))
         for d, hs in res.holdings.items() for s, w in hs.items()])
    con.commit(); con.close()
    print("Holdings + scores written to basket_holdings (equinext.db).")


if __name__ == "__main__":
    main()
