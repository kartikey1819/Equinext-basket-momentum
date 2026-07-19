"""
Populate the `sector` block on every Dynamic Allocator variant from the rebalance
history ALREADY stored in webapp/dynamic_results.json — no re-backtest needed, since
each rebalance already records its stocks and weights. Maps stocks -> sectors via the
securities table and computes the max-per-sector + rotation data.

    python scripts/add_sector_alloc.py
"""
from __future__ import annotations
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from scripts.dynamic_common import sector_analysis                # noqa: E402


def main():
    con = sqlite3.connect(str(_REPO / "equinext.db"))
    secs = pd.read_sql("SELECT symbol,sector FROM securities", con).set_index("symbol")
    con.close()
    sector_map = secs["sector"].to_dict()

    dest = _REPO / "webapp" / "dynamic_results.json"
    data = json.loads(dest.read_text(encoding="utf-8"))
    for key, v in data["variants"].items():
        sa = sector_analysis(v.get("rebalances", []), sector_map)
        v["sector"] = sa
        if sa:
            p = sa["peak"]; b = sa["biggest_stock"]
            print(f"{key:10} peak sector {p['sector']:<20} {p['weight']:>5}% on {p['date']}  |  "
                  f"avg sectors {sa['avg_sectors']:>4}  avg top {sa['avg_top']:>5}%  |  "
                  f"biggest stock {b['sym']} {b['weight']}%")
    dest.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"\nmerged sector data into {dest}  ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
