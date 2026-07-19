"""
Precompute the 'Equinext Dynamic' page data: valuation-momentum equity + monthly
3-asset dynamic switch (core 35 / eq-debt 40 / eq-gold 25), for
  - Nifty 500 (Standard, 50 stocks)  and  Nifty Total Market (~750, 50 stocks)
  - x RupeeCase window (2022-11-18) and Full window (2017-08-01)
Each variant: metrics, benchmark metrics, equity curve (weekly, base 100), and the
REAL worst-5 drawdown episodes. Writes webapp/dynamic_results.json for the site.

    python scripts/build_dynamic_page.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from equinext.context import ResearchContext                      # noqa: E402
from equinext.backtest import BacktestConfig, run_backtest         # noqa: E402
from baskets.valuation_momentum import VM500Standard50, VMTotalMarket50  # noqa: E402
from scripts.backtest_allocator import (                          # noqa: E402
    run_switch, gold_returns, metrics, worst_drawdowns, switch_asset_split,
)
from scripts.dynamic_common import (                              # noqa: E402
    series_json, bench_curve, rebalance_history, current_holdings, period_returns,
    sector_analysis,
)

VARIANTS = [
    ("n500_rc",   "Nifty 500",           "RupeeCase window", VM500Standard50,  "2022-11-18"),
    ("n500_full", "Nifty 500",           "Full window",      VM500Standard50,  "2017-08-01"),
    ("n750_rc",   "Nifty Total Market",  "RupeeCase window", VMTotalMarket50,  "2022-11-18"),
    ("n750_full", "Nifty Total Market",  "Full window",      VMTotalMarket50,  "2017-08-01"),
]

STRATEGY = {
    "name": "Equinext Dynamic",
    "tagline": "Valuation-momentum stocks wrapped in a monthly 3-asset risk switch (equity · debt · gold).",
    "cadence": "Monthly rebalance",
    "weighting": "Equity: inverse-volatility over up to 50 names. Assets: 35% equity core + 40% equity/debt switch + 25% equity/gold switch.",
    "steps": [
        {"n": 1, "title": "Universe", "role": "Eligibility",
         "why": "Start from the whole index (Nifty 500 or Nifty Total Market ~750), keep only liquid, free-float-eligible names.",
         "criteria": ["Liquidity & free-float gates", "Point-in-time tradability"]},
        {"n": 2, "title": "Valuation Gate (P/E froth)", "role": "Filter",
         "why": "Drop any stock trading above the 80th percentile of its own 5-year P/E — refuse to buy froth.",
         "criteria": ["Own-history P/E percentile < 0.80"]},
        {"n": 3, "title": "Earnings-Backed Gate", "role": "Filter",
         "why": "Keep only rises backed by real earnings growth, not multiple-expansion hype.",
         "criteria": ["Earnings contribution ≥ multiple-expansion contribution"]},
        {"n": 4, "title": "Momentum Score", "role": "Ranks",
         "why": "Rank the survivors by trend strength; take the top 50, inverse-vol weighted.",
         "criteria": ["12-1 month return", "Distance from 52-week high", "Volume trend"]},
        {"n": 5, "title": "Dynamic 3-Asset Switch", "role": "Risk dial",
         "why": "Every month, a fixed 35% equity core stays invested; a 40% sleeve switches equity↔debt and a 25% sleeve switches equity↔gold by relative momentum. Equity floats 35%→100%.",
         "criteria": ["Core 35% always equity", "40% eq↔debt by 3-mo relative momentum",
                      "25% eq↔gold by 3-mo relative momentum", "Debt = liquid ~6.5%/yr · Gold = GoldBees"]},
    ],
}

RUPEECASE = {"window": "RupeeCase window", "cagr": 45.2, "vol": 16.5, "sharpe": 2.32,
             "sortino": 2.30, "maxdd": -10.6, "calmar": 4.25, "final": 386}


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    import sqlite3
    con = sqlite3.connect(str(_REPO / "equinext.db"))
    secs = pd.read_sql("SELECT symbol,name,sector FROM securities", con).set_index("symbol")
    con.close()
    sector_map = secs["sector"].to_dict()
    out = {"strategy": STRATEGY, "rupeecase": RUPEECASE, "generated_end": str(end.date()), "variants": {}}

    for key, index_name, window, cls, start_s in VARIANTS:
        start = pd.Timestamp(start_s)
        print(f"computing {key} ...", flush=True)
        cfg = BacktestConfig(start=start.date(), end=end.date(), rebalance="ME")
        res = run_backtest(cls(), ctx, cfg)              # capture equity holdings too
        r_dyn, avgeq = run_switch(res.returns, rg, "NIFTY500", "ME")
        idx = r_dyn.index
        eqc = (1 + r_dyn).cumprod() * 100
        n500c = bench_curve(ctx, "NIFTY500", start, end, idx)
        n50c = bench_curve(ctx, "NIFTY50", start, end, idx)
        m = metrics(r_dyn)
        m["avg_eq"] = round(avgeq, 0)
        cur = switch_asset_split("NIFTY500", res.returns.index)
        reb = rebalance_history(res.holdings, secs)
        out["variants"][key] = {
            "label": index_name, "window": window,
            "start": str(idx[0].date()), "end": str(idx[-1].date()),
            "metrics": m,
            "bench": {"nifty500": metrics(ctx.benchmark_returns(start, end, "NIFTY500").reindex(idx).dropna()),
                      "nifty50": metrics(ctx.benchmark_returns(start, end, "NIFTY50").reindex(idx).dropna())},
            "curve": {"strategy": series_json(eqc), "nifty500": series_json(n500c), "nifty50": series_json(n50c)},
            "drawdowns": worst_drawdowns(eqc, 5),
            "current": cur,
            "current_holdings": current_holdings(res.holdings, secs, cur["eq"]),
            "periods": period_returns(eqc, n500c, n50c),
            "rebalances": reb,
            "sector": sector_analysis(reb, sector_map),
        }
        print(f"  {key}: CAGR {m['cagr']:.1f}%  Sharpe {m['sharpe']:.2f}  maxDD {m['maxdd']:.1f}%  "
              f"avgEq {avgeq:.0f}%  now eq/debt/gold {cur['eq']}/{cur['debt']}/{cur['gold']}  "
              f"rebals {len(out['variants'][key]['rebalances'])}")

    dest = _REPO / "webapp" / "dynamic_results.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nwrote {dest}  ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
