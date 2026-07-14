"""
Load the full Nifty 500 universe — prices + market cap — into the databases,
and tag index-pool membership so universes can be scoped per index WITHOUT
touching the existing Nifty-50 baskets.

Resumable & retry-tolerant (Yahoo rate-limits at 500-scale): re-run to fill gaps.
Does NOT touch nifty500_mapping.csv (the Nifty-50 base list), so the existing
Nifty-50 baskets are unaffected.

    python scripts/load_universe.py            # load missing
    python scripts/load_universe.py --refresh  # reload all 500
"""
from __future__ import annotations
import sys
import csv
import time
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
_ROOT = _REPO.parent
SOURCE_DB = _ROOT / "nifty500_hrp.db"
PROJECT_DB = _REPO / "equinext.db"
LIST_CSV = _REPO / "nifty500_official.csv"
PRICE_YEARS = "10y"
DELAY = 0.4          # polite gap between Yahoo calls

# the 50 official Nifty-50 + the 20 ex-Nifty-50 dropouts already loaded (for pool tags)
N50 = ["ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK","BAJAJ-AUTO","BAJFINANCE",
    "BAJAJFINSV","BEL","BHARTIARTL","CIPLA","COALINDIA","DRREDDY","EICHERMOT","ETERNAL","GRASIM",
    "HCLTECH","HDFCBANK","HDFCLIFE","HINDALCO","HINDUNILVR","ICICIBANK","INDIGO","INFY","ITC","JIOFIN",
    "JSWSTEEL","KOTAKBANK","LT","M&M","MARUTI","MAXHEALTH","NESTLEIND","NTPC","ONGC","POWERGRID",
    "RELIANCE","SBILIFE","SBIN","SHRIRAMFIN","SUNPHARMA","TATACONSUM","TATASTEEL","TCS","TECHM",
    "TITAN","TMPV","TRENT","ULTRACEMCO","WIPRO"]
N50_DROP = ["BPCL","BRITANNIA","HEROMOTOCO","INDUSINDBK","VEDL","ZEEL","GAIL","ACC","AMBUJACEM","LUPIN",
    "HINDPETRO","IOC","UPL","YESBANK","NMDC","AUROPHARMA","BOSCHLTD","DIVISLAB","SHREECEM","BANKBARODA"]


def _read_syms(path):
    with open(path, encoding="utf-8") as f:
        return [r["Symbol"].strip() for r in csv.DictReader(f) if r.get("Symbol")]


def _clean_history(t):
    px = t.history(period=PRICE_YEARS, auto_adjust=False)
    if px.empty:
        return px
    idx = pd.to_datetime(px.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    px.index = idx.normalize()
    return px[~px.index.duplicated(keep="last")]


def _ensure(prj):
    prj.execute("CREATE TABLE IF NOT EXISTS pools (symbol TEXT, pool TEXT, PRIMARY KEY (symbol, pool))")
    have = {r[1] for r in prj.execute("PRAGMA table_info(securities)")}
    if "mcap" not in have:
        prj.execute("ALTER TABLE securities ADD COLUMN mcap NUMERIC")
    prj.commit()


def _tag(prj, syms, pool):
    prj.executemany("INSERT OR REPLACE INTO pools VALUES (?,?)", [(s, pool) for s in syms])
    prj.commit()


def main(argv):
    refresh = "--refresh" in argv
    src = sqlite3.connect(str(SOURCE_DB))
    prj = sqlite3.connect(str(PROJECT_DB))
    _ensure(prj)

    n500 = _read_syms(LIST_CSV)
    tm_csv = _REPO / "nifty_totalmarket.csv"
    tm = _read_syms(tm_csv) if tm_csv.exists() else n500
    pool = list(dict.fromkeys(n500 + tm))            # union: reconstruction pool for PIT-500
    _tag(prj, N50, "n50_current")
    _tag(prj, N50_DROP, "n50_dropout")
    _tag(prj, n500, "n500_current")
    _tag(prj, pool, "n500_pool")
    print(f"Tagged pools: n500_current={len(n500)}, n500_pool={len(pool)}")

    have = {r[0] for r in src.execute("SELECT DISTINCT symbol FROM ohlcv")}
    todo = pool if refresh else [s for s in pool if s not in have]
    print(f"Prices to load: {len(todo)} of {len(pool)} ({len(pool)-len(todo)} already present)\n")

    ok, fail = 0, []
    for i, sym in enumerate(todo, 1):
        px = pd.DataFrame()
        for attempt in range(3):
            try:
                t = yf.Ticker(sym + ".NS")
                px = _clean_history(t)
                if not px.empty:
                    break
            except Exception:
                pass
            time.sleep(1.0 + attempt)
        if px.empty:
            fail.append(sym)
            if i % 25 == 0:
                print(f"  [{i:>3}/{len(todo)}] ... {ok} ok, {len(fail)} failed")
            continue
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
        ok += 1
        if i % 25 == 0:
            print(f"  [{i:>3}/{len(todo)}] ... {ok} ok, {len(fail)} failed", flush=True)
        time.sleep(DELAY)

    m = src.execute("SELECT COUNT(DISTINCT symbol) FROM ohlcv").fetchone()[0]
    print(f"\nLoaded {ok} new. ohlcv now has {m} symbols. Failed: {len(fail)}")
    if fail:
        print("FAILED (re-run to retry):", fail)
    src.close(); prj.close()


if __name__ == "__main__":
    main(sys.argv[1:])
