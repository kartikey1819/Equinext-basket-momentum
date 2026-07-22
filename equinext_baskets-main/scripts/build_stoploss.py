"""
Build the STOP-LOSS PROTECTION comparison for the 12 main valuation-momentum baskets.

These are 100%-equity books (no 3-asset dial), so there is no built-in downside
control — and a stop-loss genuinely helps here (unlike on the dynamic-allocator
baskets, where the dial already de-risks). This produces, for each basket, the plain
book vs the stop-protected book (same holdings, replayed daily through the stop
engine), both metrics + curves, written to webapp/stoploss_results.json.

Winning stop config per index (from scripts/test_stop_main.py):
    Nifty 50   -> 15% FIXED stop  (higher CAGR, higher Sharpe, ~40% shallower DD)
    Nifty 500  -> 15% TRAILING    (best Sharpe/Calmar, drawdown -40% -> -24%)

    python scripts/build_stoploss.py
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
from scripts.backtest_allocator import metrics                   # noqa: E402
from scripts.dynamic_common import series_json                   # noqa: E402
from scripts.test_stop_variants import accrue_stop               # noqa: E402

PROJECT_DB = _REPO / "equinext.db"

# The 12 main baskets = 4 bases x 3 cadences. Index + winning stop config per base.
BASES = {
    "vm_pe_only": ("NIFTY50", 0.15, False),   # Nifty 50 Standard    -> 15% fixed
    "vm_pit":     ("NIFTY50", 0.15, False),   # Nifty 50 PIT         -> 15% fixed
    "vm500":      ("NIFTY500", 0.15, True),   # Nifty 500 Standard   -> 15% trailing
    "vm500_pit":  ("NIFTY500", 0.15, True),   # Nifty 500 PIT        -> 15% trailing
}
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


def main():
    ctx = ResearchContext()
    px = ctx.price_matrix()
    con = sqlite3.connect(str(PROJECT_DB))
    out = {"stop_label": {"NIFTY50": "15% fixed stop", "NIFTY500": "15% trailing stop"}, "baskets": {}}

    for base, (index, stop_pct, trailing) in BASES.items():
        for sfx in CADENCES:
            bk = base + sfx
            H = load_holdings(bk, con)
            if not H:
                print(f"skip {bk}: no holdings", flush=True)
                continue
            print(f"replaying {bk} ({index}, {int(stop_pct*100)}%{' trailing' if trailing else ' fixed'}) ...", flush=True)
            r_plain = accrue_stop(H, px, 0.99)                        # huge stop -> never triggers = plain book
            r_stop = accrue_stop(H, px, stop_pct, trailing=trailing)
            # align + benchmark on the common window
            idx0 = r_plain.index.intersection(r_stop.index)
            r_plain, r_stop = r_plain.loc[idx0], r_stop.loc[idx0]
            r_idx = ctx.benchmark_returns(idx0[0], idx0[-1], index).reindex(idx0).fillna(0.0)
            eq_plain = (1 + r_plain).cumprod() * 100
            eq_stop = (1 + r_stop).cumprod() * 100
            eq_idx = (1 + r_idx).cumprod() * 100
            out["baskets"][bk] = {
                "index": index,
                "stop_pct": int(stop_pct * 100),
                "trailing": trailing,
                "stop_desc": out["stop_label"][index],
                "plain": slim(metrics(r_plain)),
                "stop": slim(metrics(r_stop)),
                "index_metrics": slim(metrics(r_idx)),
                "curve": {"plain": series_json(eq_plain), "stop": series_json(eq_stop),
                          "index": series_json(eq_idx)},
            }
    con.close()
    p = _REPO / "webapp" / "stoploss_results.json"
    p.write_text(json.dumps(out), encoding="utf-8")
    print(f"\nwrote {p} ({len(out['baskets'])} baskets)")


if __name__ == "__main__":
    main()
