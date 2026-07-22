"""
Add the 'switch signal: index-timed vs sleeve-timed' comparison to EVERY Dynamic Allocator
variant (base, sector-capped, V2, Mode C — 24 in all), so the card matches whatever strategy
is on screen. For each variant, rebuild its exact equity sleeve, then run the 3-asset dial two
ways off that SAME sleeve:
  index  : eq_mom = NIFTY500 index 63-day return   (deployed default — the live baskets)
  sleeve : eq_mom = the equity sleeve's OWN 63-day return
and merge a `timing` block {index:{metrics,curve}, sleeve:{metrics,curve}, bench} into each
variant. The live baskets stay index-timed; only the new `timing` block is added.

    python scripts/add_sleeve_timing.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from equinext.context import ResearchContext                              # noqa: E402
from equinext.backtest import BacktestConfig, run_backtest, Basket, Selection  # noqa: E402
from baskets.valuation_momentum import (                                  # noqa: E402
    VM500Standard50, VMTotalMarket50, VMRupeeCaseUniverse, cap_weights,
)
from baskets.equinext_v2 import EquinextV2, EquinextV2N500, EquinextV2RC   # noqa: E402
from scripts.backtest_allocator import run_switch, gold_returns, metrics   # noqa: E402
from scripts.dynamic_common import series_json, bench_curve                # noqa: E402

EquinextV2._CACHE_ROWS = True
LOOKBACK, CAP = 63, 0.25
#       uni_prefix,  base VM class,       V2 class
UNIS = [("n750", VMTotalMarket50, EquinextV2),      # widest first -> warms the V2 score cache
        ("n500", VM500Standard50, EquinextV2N500),
        ("rc",   VMRupeeCaseUniverse, EquinextV2RC)]
WINDOWS = [("full", "2017-08-01"), ("rc", "2022-11-18")]   # full first (warms cache), rc replays


class ReplayBasket(Basket):
    name = "replay_cap"

    def __init__(self, sel):
        self._sel = sel

    def select(self, as_of, ctx):
        return self._sel[pd.Timestamp(as_of)]


def modec(cls):
    """Mode C config (matches build_modec.py): fixed 30% large anchor + mid/small rotation,
    RSI + multi-TF gates, no 200-DMA, 25% sector + 8% stock cap (class defaults)."""
    b = cls()
    b.TIER_MODE = "C"; b.LARGE_ANCHOR = 0.30; b.SATELLITE_TILT = 1.0; b.SMALL_CAP_MAX = 0.40
    b.TIER_BOUNDS = (100, 250, 500); b.USE_TREND_GATE = False
    return b


def slim(m, avg_eq):
    d = {k: round(float(m[k]), 3) for k in ("cagr", "vol", "sharpe", "sortino", "maxdd", "calmar", "final", "years")}
    d["avg_eq"] = round(float(avg_eq), 0)
    return d


def timing_block(ctx, r_eq, rg, start, end):
    """Index-timed vs sleeve-timed dial on the SAME sleeve returns r_eq."""
    c = (1 + r_eq).cumprod()
    em = c / c.shift(LOOKBACK) - 1
    r_i, ae_i = run_switch(r_eq, rg, "NIFTY500", "ME")                      # default: index-timed
    r_s, ae_s = run_switch(r_eq, rg, "NIFTY500", "ME", eq_mom_series=em)    # sleeve-timed
    n500c = bench_curve(ctx, "NIFTY500", start, end, r_i.index)
    return {
        "index":  {"metrics": slim(metrics(r_i), ae_i), "curve": series_json((1 + r_i).cumprod() * 100)},
        "sleeve": {"metrics": slim(metrics(r_s), ae_s), "curve": series_json((1 + r_s).cumprod() * 100)},
        "bench":  series_json(n500c),
    }


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    rg = gold_returns()
    sector_of = lambda s: ctx.sector(s)
    p = _REPO / "webapp" / "dynamic_results.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    V = data["variants"]

    def stash(key, r_eq, start):
        if key in V:
            V[key]["timing"] = timing_block(ctx, r_eq, rg, start, end)
            i, s = V[key]["timing"]["index"]["metrics"], V[key]["timing"]["sleeve"]["metrics"]
            print(f"  {key:14} index {i['cagr']:>5.1f}%/{i['maxdd']:>6.1f}%  "
                  f"sleeve {s['cagr']:>5.1f}%/{s['maxdd']:>6.1f}%", flush=True)

    for uni, vmcls, v2cls in UNIS:
        for wk, start_s in WINDOWS:
            start = pd.Timestamp(start_s)
            cfg = BacktestConfig(start=start.date(), end=end.date(), rebalance="ME")
            print(f"\n{uni}_{wk}: rebuilding sleeves ...", flush=True)

            base = run_backtest(vmcls(), ctx, cfg)                          # base (uncapped)
            stash(f"{uni}_{wk}", base.returns, start)

            capped = {pd.Timestamp(d): Selection(as_of=pd.Timestamp(d).date(),
                                                 weights=cap_weights(w, sector_of, sector_cap=CAP),
                                                 scores={s: 0.0 for s in w})
                      for d, w in base.holdings.items()}                    # sector-capped replay
            stash(f"{uni}cap_{wk}", run_backtest(ReplayBasket(capped), ctx, cfg).returns, start)

            stash(f"{uni}v2_{wk}", run_backtest(v2cls(), ctx, cfg).returns, start)          # V2
            stash(f"{uni}v2c_{wk}", run_backtest(modec(v2cls), ctx, cfg).returns, start)    # Mode C

    p.write_text(json.dumps(data, indent=1), encoding="utf-8")
    n = sum(1 for v in V.values() if "timing" in v)
    print(f"\nwrote {p} ({p.stat().st_size // 1024} KB) — timing on {n}/{len(V)} variants")


if __name__ == "__main__":
    main()
