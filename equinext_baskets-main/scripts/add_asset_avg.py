"""
Add avg_debt and avg_gold to every Dynamic-Allocator variant's metrics (the dial's average
gold/debt exposure) — computed from the index-driven switch, so no backtest is needed. The
existing avg_eq is kept; the non-equity remainder is split between debt and gold by the
dial's average target ratio.

    python scripts/add_asset_avg.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from equinext.context import ResearchContext                          # noqa: E402
from scripts.backtest_allocator import switch_avg_split               # noqa: E402


def main():
    ctx = ResearchContext()
    px = ctx.price_matrix()
    dest = _REPO / "webapp" / "dynamic_results.json"
    data = json.loads(dest.read_text(encoding="utf-8"))
    for k, v in data["variants"].items():
        m = v["metrics"]
        if m.get("avg_eq") is None:
            continue
        start, end = pd.Timestamp(v["start"]), pd.Timestamp(v["end"])
        days = px.index[(px.index >= start) & (px.index <= end)]
        if len(days) < 2:
            continue
        sp = switch_avg_split("NIFTY500", days, "ME")
        non_eq = max(0.0, 100.0 - m["avg_eq"])
        dg = sp["debt"] + sp["gold"]
        if dg > 0:
            m["avg_debt"] = round(non_eq * sp["debt"] / dg, 0)
            m["avg_gold"] = round(non_eq * sp["gold"] / dg, 0)
        else:
            m["avg_debt"], m["avg_gold"] = 0.0, round(non_eq, 0)
        print(f"  {k:14} eq {m['avg_eq']:.0f}%  debt {m['avg_debt']:.0f}%  gold {m['avg_gold']:.0f}%  vol {m['vol']:.1f}%")
    dest.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"\nadded avg debt/gold to {dest}")


if __name__ == "__main__":
    main()
