"""
Build the 25%-sector-cap comparison for the 12 main valuation-momentum baskets (Nifty 50 /
Nifty 500 × Standard / PIT × Q/M/2M). Same holdings, but each rebalance's inverse-vol weights
are passed through a hard 25% per-sector cap (overflow redistributed to sectors with room) —
so no single sector runs the book. Uncapped vs capped, both replayed daily through the same
engine, written to webapp/sectorcap_results.json.

    python scripts/build_sectorcap_main.py
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

from equinext.context import ResearchContext                     # noqa: E402
from baskets.valuation_momentum import cap_weights               # noqa: E402
from scripts.backtest_allocator import metrics                   # noqa: E402
from scripts.dynamic_common import series_json, sector_analysis   # noqa: E402
from scripts.test_stop_variants import accrue_stop               # noqa: E402

PROJECT_DB = _REPO / "equinext.db"
CAP = 0.25
BASES = {"vm_pe_only": "NIFTY50", "vm_pit": "NIFTY50", "vm500": "NIFTY500", "vm500_pit": "NIFTY500"}
CADENCES = ["", "_M", "_2M"]


def load_holdings(basket, con):
    df = pd.read_sql("SELECT as_of, symbol, weight FROM basket_holdings WHERE basket=? ORDER BY as_of",
                     con, params=(basket,))
    if df.empty:
        return {}
    H = {}
    for d in sorted(df["as_of"].unique()):
        sub = df[df.as_of == d]
        H[pd.Timestamp(d)] = dict(zip(sub.symbol, sub.weight))
    return H


def slim(m):
    return {k: round(float(m[k]), 3) for k in ("cagr", "vol", "sharpe", "maxdd", "calmar", "final")}


def peak_sector(weights, sector_of):
    agg = {}
    for s, w in weights.items():
        sec = sector_of(s) or "Unknown"
        agg[sec] = agg.get(sec, 0.0) + w
    if not agg:
        return None, 0.0
    sec = max(agg, key=agg.get)
    return sec, agg[sec] * 100


def main():
    ctx = ResearchContext()
    px = ctx.price_matrix()
    sector_of = lambda s: ctx.sector(s)
    con = sqlite3.connect(str(PROJECT_DB))
    secs = pd.read_sql("SELECT symbol, sector FROM securities", con)
    sector_map = dict(zip(secs["symbol"], secs["sector"]))       # same source the webapp uses
    out = {"cap_pct": int(CAP * 100), "baskets": {}}

    for base, index in BASES.items():
        for sfx in CADENCES:
            bk = base + sfx
            H = load_holdings(bk, con)
            if not H:
                print(f"skip {bk}: no holdings", flush=True)
                continue
            Hcap = {d: cap_weights(w, sector_of, sector_cap=CAP) for d, w in H.items()}
            print(f"replaying {bk} ({index}) uncapped vs 25% cap ...", flush=True)
            r_un = accrue_stop(H, px, 0.99)                          # plain (never stops) = uncapped book
            r_cap = accrue_stop(Hcap, px, 0.99)                      # capped book
            idx0 = r_un.index.intersection(r_cap.index)
            r_un, r_cap = r_un.loc[idx0], r_cap.loc[idx0]
            r_idx = ctx.benchmark_returns(idx0[0], idx0[-1], index).reindex(idx0).fillna(0.0)

            last = sorted(H)[-1]
            wl_un, wl_cap = H[last], Hcap[last]
            psec, pbefore = peak_sector(wl_un, sector_of)
            _, pafter = peak_sector(wl_cap, sector_of)
            recs_cap = [{"date": str(pd.Timestamp(d).date()),
                         "holdings": [{"sym": sym, "weight": w * 100.0} for sym, w in Hcap[d].items()]}
                        for d in sorted(Hcap)]
            sec = sector_analysis(recs_cap, sector_map)
            if sec:                                                # rebalances too concentrated for 25% to be feasible
                sec["cap_pct"] = int(CAP * 100)
                sec["infeasible_rebalances"] = int(sum(1 for t in sec["top_series"] if t > CAP * 100 + 0.5))
            out["baskets"][bk] = {
                "index": index,
                "sector": sec,
                "uncapped": slim(metrics(r_un)),
                "capped": slim(metrics(r_cap)),
                "index_metrics": slim(metrics(r_idx)),
                "curve": {"uncapped": series_json((1 + r_un).cumprod() * 100),
                          "capped": series_json((1 + r_cap).cumprod() * 100),
                          "index": series_json((1 + r_idx).cumprod() * 100)},
                "latest": {"asof": str(pd.Timestamp(last).date()),
                           "weights": {s: round(w * 100, 2) for s, w in sorted(wl_cap.items(), key=lambda x: -x[1])},
                           "peak_sector": psec, "peak_before": round(pbefore, 1), "peak_after": round(pafter, 1)},
            }
    con.close()
    p = _REPO / "webapp" / "sectorcap_results.json"
    p.write_text(json.dumps(out), encoding="utf-8")
    print(f"\nwrote {p} ({len(out['baskets'])} baskets)")


if __name__ == "__main__":
    main()
