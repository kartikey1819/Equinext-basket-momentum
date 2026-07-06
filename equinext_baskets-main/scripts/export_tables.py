"""
Regenerate the human-readable CSV snapshots from the CURRENT databases.

Run this whenever the DB changes (after a loader / scraper / backtest) so the
exports/ folder never goes stale. Writes:
  exports/valuation_long.csv    symbol,date,pe,pb,ev_ebitda,fcf_yield,eps_ttm (all multiples)
  exports/pe_matrix.csv         dates x symbols, P/E only (easy to eyeball)
  exports/close_matrix.csv      dates x symbols, closing price
  exports/holdings.csv          basket_holdings (all baskets)
  exports/securities.csv        symbol,name,sector

    python scripts/export_tables.py
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
OUT = _REPO / "exports"


def main():
    OUT.mkdir(exist_ok=True)
    prj = sqlite3.connect(str(_REPO / "equinext.db"))
    src = sqlite3.connect(str(_REPO.parent / "nifty500_hrp.db"))

    val = pd.read_sql("SELECT symbol,date,pe,pb,ev_ebitda,fcf_yield,eps_ttm "
                      "FROM valuation_series ORDER BY symbol,date", prj)
    val.round(4).to_csv(OUT / "valuation_long.csv", index=False)
    val.pivot(index="date", columns="symbol", values="pe").round(2).to_csv(OUT / "pe_matrix.csv")

    px = pd.read_sql("SELECT date,symbol,close FROM ohlcv", src)
    px.pivot(index="date", columns="symbol", values="close").round(2).to_csv(OUT / "close_matrix.csv")

    pd.read_sql("SELECT basket,as_of,symbol,weight,score FROM basket_holdings "
                "ORDER BY basket,as_of,weight DESC", prj).to_csv(OUT / "holdings.csv", index=False)
    pd.read_sql("SELECT symbol,name,sector FROM securities ORDER BY symbol", prj).to_csv(
        OUT / "securities.csv", index=False)

    span = (val["date"].min(), val["date"].max())
    print(f"Regenerated exports/ from live DB. valuation spans {span[0]} .. {span[1]} "
          f"({val['symbol'].nunique()} symbols, {len(val):,} rows).")
    for f in sorted(OUT.glob("*.csv")):
        print(f"  {f.name:<22} {f.stat().st_size/1024:>7,.0f} KB")
    prj.close(); src.close()


if __name__ == "__main__":
    main()
