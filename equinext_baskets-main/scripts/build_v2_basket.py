"""
Add the multi-layer V2 strategy (cap-tiers + trend + multi-TF + RSI + regime dial +
25% sector cap + 8% stock cap) run on RupeeCase's own ~240 stocks, for both windows,
as rcv2_rc / rcv2_full in dynamic_results.json. Lets the site show the V2 strategy
next to the plain RC-stocks basket for comparison.

    python scripts/build_v2_basket.py     # run AFTER the other build_* scripts
"""
from __future__ import annotations
import json
import sqlite3
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
from baskets.equinext_v2 import EquinextV2RC, EquinextV2              # noqa: E402
from scripts.backtest_allocator import (                              # noqa: E402
    run_switch, gold_returns, metrics, worst_drawdowns, switch_asset_split,
)
from scripts.dynamic_common import (                                  # noqa: E402
    series_json, bench_curve, rebalance_history, current_holdings, period_returns, sector_analysis,
)

EquinextV2._CACHE_ROWS = True
VARIANTS = [("rcv2_rc", "RupeeCase window", "2022-11-18"),
            ("rcv2_full", "Full window", "2017-08-01")]


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    con = sqlite3.connect(str(_REPO / "equinext.db"))
    secs = pd.read_sql("SELECT symbol,name,sector FROM securities", con).set_index("symbol")
    con.close()
    sector_map = secs["sector"].to_dict()

    dest = _REPO / "webapp" / "dynamic_results.json"
    data = json.loads(dest.read_text(encoding="utf-8"))

    for key, window, start_s in VARIANTS:
        start = pd.Timestamp(start_s)
        print(f"computing {key} ...", flush=True)
        cfg = BacktestConfig(start=start.date(), end=end.date(), rebalance="ME")
        res = run_backtest(EquinextV2RC(), ctx, cfg)
        r_dyn, avgeq = run_switch(res.returns, rg, "NIFTY500", "ME")
        idx = r_dyn.index
        eqc = (1 + r_dyn).cumprod() * 100
        n500c = bench_curve(ctx, "NIFTY500", start, end, idx)
        n50c = bench_curve(ctx, "NIFTY50", start, end, idx)
        m = metrics(r_dyn); m["avg_eq"] = round(avgeq, 0)
        cur = switch_asset_split("NIFTY500", res.returns.index)
        reb = rebalance_history(res.holdings, secs)
        data["variants"][key] = {
            "label": "RC Stocks · V2", "window": window,
            "start": str(idx[0].date()), "end": str(idx[-1].date()),
            "strategy_v2": True, "momentum_only": True, "sector_capped": True, "cap_pct": 25,
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
        sp = data["variants"][key]["sector"]["peak"]
        print(f"  {key}: CAGR {m['cagr']:.1f}%  Sharpe {m['sharpe']:.2f}  maxDD {m['maxdd']:.1f}%  "
              f"peak {sp['sector']} {sp['weight']}%  rebals {len(reb)}")

    dest.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"\nmerged V2 RC variants into {dest}  ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
