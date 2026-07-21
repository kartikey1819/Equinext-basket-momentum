"""
For the stock-capped baskets (V2 / Mode C), measure the 'biggest single stock' stat over
the rebalances where the 8% cap is actually FEASIBLE — i.e. the book's sector structure
allows every name <= 8% while sectors stay <= 25% (feasibility capacity = sum over sectors
of min(#names*8%, 25%) >= 1). Rebalances that are mathematically infeasible (too few names,
or a couple of huge sectors + single-stock sectors) are counted separately, not used for
the headline. No backtest — recomputed from the stored rebalance holdings.

    python scripts/refine_biggest_stock.py
"""
from __future__ import annotations
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

STOCK_CAP = 0.08
SECTOR_CAP = 0.25


def main():
    con = sqlite3.connect(str(_REPO / "equinext.db"))
    secs = pd.read_sql("SELECT symbol,sector FROM securities", con).set_index("symbol")["sector"].to_dict()
    con.close()

    dest = _REPO / "webapp" / "dynamic_results.json"
    data = json.loads(dest.read_text(encoding="utf-8"))
    for key, v in data["variants"].items():
        if not v.get("strategy_v2"):           # only baskets that use the 8% stock cap
            continue
        best = {"sym": None, "weight": 0.0, "date": None}
        n_infeasible = 0
        for r in v.get("rebalances", []):
            if not r["holdings"]:
                continue
            cnt: dict = {}
            for h in r["holdings"]:
                sec = secs.get(h["sym"]) or "Unknown"
                cnt[sec] = cnt.get(sec, 0) + 1
            capacity = sum(min(c * STOCK_CAP, SECTOR_CAP) for c in cnt.values())
            if capacity < 1.0 - 1e-9:          # 8% cap impossible for this book
                n_infeasible += 1
                continue
            for h in r["holdings"]:
                if h["weight"] > best["weight"]:
                    best = {"sym": h["sym"], "weight": h["weight"], "date": r["date"]}
        if best["sym"] is not None:
            v["sector"]["biggest_stock"] = best
        v["sector"]["infeasible_rebalances"] = n_infeasible
        print(f"  {key:14} biggest {best['sym'] or '-':10} {best['weight']:.2f}%   "
              f"({n_infeasible} infeasible rebals excluded)")

    dest.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"\nrefined biggest-stock stat in {dest}")


if __name__ == "__main__":
    main()
