"""
Add the Mode C strategy (V2 stack, but the tier logic = FIXED large-cap anchor +
mid<->small momentum rotation, the user's design) on all three universes, both windows
-> dynamic_results.json as n500v2c / n750v2c / rcv2c (x rc, full). Uses the best config
from the test: anchor 40%, small ceiling 40%, hard switch.

    python scripts/build_modec.py     # run AFTER the other build_* scripts
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
from baskets.equinext_v2 import EquinextV2, EquinextV2N500, EquinextV2RC  # noqa: E402
from scripts.backtest_allocator import (                              # noqa: E402
    run_switch, gold_returns, metrics, worst_drawdowns, switch_asset_split,
)
from scripts.dynamic_common import (                                  # noqa: E402
    series_json, bench_curve, rebalance_history, current_holdings, period_returns, sector_analysis,
)

EquinextV2._CACHE_ROWS = True
UNIS = [("n750v2c", "Total Market · Mode C", EquinextV2,      False),
        ("n500v2c", "Nifty 500 · Mode C",    EquinextV2N500,  False),
        ("rcv2c",   "RC Stocks · Mode C",    EquinextV2RC,    True)]
WINDOWS = [("rc", "RupeeCase window", "2022-11-18"), ("full", "Full window", "2017-08-01")]


def build(cls):
    b = cls()
    b.TIER_MODE = "C"; b.LARGE_ANCHOR = 0.30; b.SATELLITE_TILT = 1.0; b.SMALL_CAP_MAX = 0.40
    b.TIER_BOUNDS = (100, 250, 500)
    b.USE_TREND_GATE = False          # RSI + multi-TF, NO 200-DMA (the winning gate combo)
    # RSI_MAX=80, USE_MULTI_TF=True, SECTOR_WEIGHT_CAP=0.25, MAX_STOCK_WEIGHT=0.08 -> class defaults
    return b


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

    for uni_key, label, cls, momo in UNIS:
        for win_key, window, start_s in sorted(WINDOWS, key=lambda w: w[2]):
            start = pd.Timestamp(start_s)
            print(f"computing {uni_key}_{win_key} ...", flush=True)
            cfg = BacktestConfig(start=start.date(), end=end.date(), rebalance="ME")
            res = run_backtest(build(cls), ctx, cfg)
            r_dyn, avgeq = run_switch(res.returns, rg, "NIFTY500", "ME")
            idx = r_dyn.index
            eqc = (1 + r_dyn).cumprod() * 100
            n500c = bench_curve(ctx, "NIFTY500", start, end, idx)
            n50c = bench_curve(ctx, "NIFTY50", start, end, idx)
            m = metrics(r_dyn); m["avg_eq"] = round(avgeq, 0)
            cur = switch_asset_split("NIFTY500", res.returns.index)
            reb = rebalance_history(res.holdings, secs)
            data["variants"][f"{uni_key}_{win_key}"] = {
                "label": label, "window": window,
                "start": str(idx[0].date()), "end": str(idx[-1].date()),
                "strategy_v2": True, "mode_c": True, "momentum_only": momo,
                "sector_capped": True, "cap_pct": 25, "anchor_pct": 30, "no_dma": True,
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
            sp = data["variants"][f"{uni_key}_{win_key}"]["sector"]["peak"]
            print(f"  {uni_key}_{win_key}: CAGR {m['cagr']:.1f}%  Sharpe {m['sharpe']:.2f}  "
                  f"maxDD {m['maxdd']:.1f}%  peak {sp['weight']}%")

    dest.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"\nmerged Mode C variants into {dest}  ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
