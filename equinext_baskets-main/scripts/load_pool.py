"""
Load the EXPANDED point-in-time pool — the ex-Nifty-50 members that survivorship
erased — into the databases, WITHOUT touching nifty500_mapping.csv (so the current
basket's universe stays exactly the official 50).

Also backfills a `mcap` (current market cap) column on `securities` for EVERY
symbol, which the point-in-time universe uses to reconstruct the top-50-by-size
membership at each historical date:  mcap(t) = mcap_now * price(t)/price_now.

    python scripts/load_pool.py
"""
from __future__ import annotations
import sqlite3
import warnings
from pathlib import Path

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("Need yfinance:  pip install yfinance pandas")

warnings.simplefilter("ignore")

_REPO = Path(__file__).resolve().parents[1]
SOURCE_DB = _REPO.parent / "nifty500_hrp.db"
PROJECT_DB = _REPO / "equinext.db"
PRICE_YEARS = "10y"

# ex-Nifty-50 members that dropped out over 2016-2026 (the survivorship-erased losers)
POOL_EXTRA = [
    "BPCL", "BRITANNIA", "HEROMOTOCO", "INDUSINDBK", "VEDL", "ZEEL", "GAIL", "ACC",
    "AMBUJACEM", "LUPIN", "HINDPETRO", "IOC", "UPL", "YESBANK", "NMDC", "AUROPHARMA",
    "BOSCHLTD", "DIVISLAB", "SHREECEM", "BANKBARODA",
]


def _clean_history(t):
    px = t.history(period=PRICE_YEARS, auto_adjust=False)
    if px.empty:
        return px
    idx = pd.to_datetime(px.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    px.index = idx.normalize()
    return px[~px.index.duplicated(keep="last")]


def main():
    src = sqlite3.connect(str(SOURCE_DB))
    prj = sqlite3.connect(str(PROJECT_DB))
    # add mcap column if missing
    have = {r[1] for r in prj.execute("PRAGMA table_info(securities)")}
    if "mcap" not in have:
        prj.execute("ALTER TABLE securities ADD COLUMN mcap NUMERIC")
    prj.commit()

    # 1) load prices + securities(mcap) for the extra pool
    for i, sym in enumerate(POOL_EXTRA, 1):
        t = yf.Ticker(sym + ".NS")
        px = _clean_history(t)
        if px.empty:
            print(f"  [{i:>2}/{len(POOL_EXTRA)}] {sym:<12} NO PRICE"); continue
        try:
            info = t.info or {}
        except Exception:
            info = {}
        rows = [(d.strftime("%Y-%m-%d"), sym, float(r["Open"]), float(r["High"]), float(r["Low"]),
                 float(r["Close"]), float(r["Volume"]) if pd.notna(r["Volume"]) else 0.0)
                for d, r in px.iterrows() if pd.notna(r["Close"])]
        src.execute("DELETE FROM ohlcv WHERE symbol = ?", (sym,))
        src.executemany("INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?,?,?,?)", rows)
        src.commit()
        prj.execute("INSERT OR REPLACE INTO securities (symbol, name, sector, mcap) VALUES (?,?,?,?)",
                    (sym, info.get("longName"), info.get("sector"), info.get("marketCap")))
        prj.commit()
        print(f"  [{i:>2}/{len(POOL_EXTRA)}] {sym:<12} {len(rows)} px  mcap={info.get('marketCap')}")

    # 2) backfill mcap for the current-50 securities that don't have it yet
    missing = [r[0] for r in prj.execute("SELECT symbol FROM securities WHERE mcap IS NULL")]
    print(f"\nBackfilling mcap for {len(missing)} existing symbols...")
    for sym in missing:
        try:
            mc = (yf.Ticker(sym + ".NS").info or {}).get("marketCap")
        except Exception:
            mc = None
        if mc:
            prj.execute("UPDATE securities SET mcap = ? WHERE symbol = ?", (float(mc), sym))
    prj.commit()

    n = prj.execute("SELECT COUNT(*), COUNT(mcap) FROM securities").fetchone()
    m = src.execute("SELECT COUNT(DISTINCT symbol) FROM ohlcv").fetchone()[0]
    print(f"\nsecurities: {n[0]} rows, {n[1]} with mcap | ohlcv symbols: {m}")
    src.close(); prj.close()


if __name__ == "__main__":
    main()
