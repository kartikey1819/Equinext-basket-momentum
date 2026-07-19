"""
Add the 25%-sector-capped 'sector-controlled' variants to dynamic_results.json:
  n500cap / n750cap / rccap  x  {rc, full} window.
Same full structure as the un-capped dynamic variants (metrics, curve, drawdowns,
current, current_holdings, periods, rebalances, sector) + a `sector_capped` flag.

Efficient: the heavy momentum selection runs ONCE per universe (the cap only re-sizes,
never re-selects); each window is a cheap replay of the capped selections.

    python scripts/build_capped_baskets.py     # run AFTER build_dynamic_page + build_rc_baskets
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
from equinext.backtest import BacktestConfig, run_backtest, Basket, Selection  # noqa: E402
from baskets.valuation_momentum import (                              # noqa: E402
    VM500Standard50, VMTotalMarket50, VMRupeeCaseUniverse, cap_weights,
)
from scripts.backtest_allocator import (                              # noqa: E402
    run_switch, gold_returns, metrics, worst_drawdowns, switch_asset_split,
)
from scripts.dynamic_common import (                                  # noqa: E402
    series_json, bench_curve, rebalance_history, current_holdings, period_returns, sector_analysis,
)

CAP = 0.25
FULL_START = pd.Timestamp("2017-08-01")
RC_START = pd.Timestamp("2022-11-18")
UNIS = [("n500", "Nifty 500", VM500Standard50, False),
        ("n750", "Total Market", VMTotalMarket50, False),
        ("rc", "RupeeCase Stocks", VMRupeeCaseUniverse, True)]


class ReplayBasket(Basket):
    name = "replay_cap"

    def __init__(self, sel):
        self._sel = sel

    def select(self, as_of, ctx):
        return self._sel[pd.Timestamp(as_of)]


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    sector_of = lambda s: ctx.sector(s)
    con = sqlite3.connect(str(_REPO / "equinext.db"))
    secs = pd.read_sql("SELECT symbol,name,sector FROM securities", con).set_index("symbol")
    con.close()
    sector_map = secs["sector"].to_dict()

    dest = _REPO / "webapp" / "dynamic_results.json"
    data = json.loads(dest.read_text(encoding="utf-8"))
    cfg_full = BacktestConfig(start=FULL_START.date(), end=end.date(), rebalance="ME")

    for uni_key, label, cls, momo in UNIS:
        print(f"base selection {uni_key} ...", flush=True)
        base = run_backtest(cls(), ctx, cfg_full)                     # heavy, once per universe
        capped = {pd.Timestamp(d): Selection(as_of=pd.Timestamp(d).date(),
                                             weights=cap_weights(w, sector_of, sector_cap=CAP),
                                             scores={s: 0.0 for s in w})
                  for d, w in base.holdings.items()}
        replay = ReplayBasket(capped)
        for win_key, start in [("rc", RC_START), ("full", FULL_START)]:
            cfg = BacktestConfig(start=start.date(), end=end.date(), rebalance="ME")
            res = run_backtest(replay, ctx, cfg)                      # cheap replay
            r_dyn, avgeq = run_switch(res.returns, rg, "NIFTY500", "ME")
            idx = r_dyn.index
            eqc = (1 + r_dyn).cumprod() * 100
            n500c = bench_curve(ctx, "NIFTY500", start, end, idx)
            n50c = bench_curve(ctx, "NIFTY50", start, end, idx)
            m = metrics(r_dyn); m["avg_eq"] = round(avgeq, 0)
            cur = switch_asset_split("NIFTY500", res.returns.index)
            reb = rebalance_history(res.holdings, secs)
            key = f"{uni_key}cap_{win_key}"
            data["variants"][key] = {
                "label": label,
                "window": "RupeeCase window" if win_key == "rc" else "Full window",
                "start": str(idx[0].date()), "end": str(idx[-1].date()),
                "sector_capped": True, "cap_pct": int(CAP * 100), "momentum_only": momo,
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
                  f"peak {sp['sector']} {sp['weight']}%")

    dest.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"\nmerged capped variants into {dest}  ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
