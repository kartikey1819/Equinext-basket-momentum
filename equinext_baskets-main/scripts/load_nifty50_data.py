"""
One-shot data loader — populates EVERYTHING the equinext framework needs to run
a P/E relative-value backtest on the Nifty 50, from free Yahoo Finance data.

Fills (paths match what the framework modules expect):
  ../nifty500_hrp.db          ohlcv (10y daily, 49 names), broad_indices (NIFTY50)
  ../nifty500_mapping.csv     Symbol,Name,Sector          (universe base list)
  ../nifty500_ffmc.csv        Symbol,FFMC                 (free-float gate)
  ./equinext.db               securities, valuation_series (daily P/E)

P/E DERIVATION (same calibration as scripts/pe_method_a_demo.py — see its
docstring for why): Yahoo per-share EPS line items are broken for .NS tickers
and statements come in mixed currencies, so we anchor to info['trailingEps']
(reliable, ₹) and take only the SHAPE of the annual Net Income path:
      eps(t) = trailingEps_now * NI(t) / NI_latest
stepped at fiscal-year-end + 45d reporting lag (no look-ahead), forward-filled
onto daily prices. pe = close / eps. pb & ev_ebitda left NULL for now.

HONEST LIMITS: Yahoo only exposes ~4 annual statements, so the P/E series
starts ~mid-2022 even though prices go back 10y. For the full 5-10y P/E the
same table just needs a longer EPS source (vendor / screener.in / NSE filings).
Prices are split-adjusted but NOT dividend-adjusted, matching the price-index
benchmark (^NSEI) — returns are price returns on both sides, comparable.

Resumable: symbols already in valuation_series are skipped on re-run.
    python scripts/load_nifty50_data.py            # load everything missing
    python scripts/load_nifty50_data.py --refresh  # wipe + reload all
"""
from __future__ import annotations
import sys
import sqlite3
import warnings
from pathlib import Path

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    sys.exit("Need yfinance:  pip install yfinance pandas")

warnings.simplefilter("ignore")

_REPO = Path(__file__).resolve().parents[1]          # equinext_baskets-main/
_ROOT = _REPO.parent                                 # Equinext-Basket/
SOURCE_DB = _ROOT / "nifty500_hrp.db"                # prices.py expects this
PROJECT_DB = _REPO / "equinext.db"                   # valuation.py expects this
MAPPING_CSV = _ROOT / "nifty500_mapping.csv"         # universe.py expects these
FFMC_CSV = _ROOT / "nifty500_ffmc.csv"
SCHEMA_SQL = _REPO / "sql" / "schema.sql"

PRICE_YEARS = "10y"
REPORT_LAG_DAYS = 45
NI_ROWS = ("Net Income", "Net Income Common Stockholders",
           "Net Income From Continuing Operation Net Minority Interest")

# Official NSE Nifty 50 constituents (verified list). Bare NSE symbols (DB keys)
# -> Yahoo tickers are symbol + ".NS". TMPV carries the old Tata Motors history;
# ETERNAL is ex-Zomato. JIOFIN/MAXHEALTH/ETERNAL are recent listings (partial history).
NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO",
    "HINDUNILVR", "ICICIBANK", "INDIGO", "INFY", "ITC", "JIOFIN", "JSWSTEEL",
    "KOTAKBANK", "LT", "M&M", "MARUTI", "MAXHEALTH", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM",
    "TATASTEEL", "TCS", "TECHM", "TITAN", "TMPV", "TRENT", "ULTRACEMCO", "WIPRO",
]
BENCHMARKS = {"NIFTY50": "^NSEI", "NIFTY500": "^CRSLDX"}


# ---------------------------------------------------------------- db helpers
def _init_source_db() -> sqlite3.Connection:
    con = sqlite3.connect(str(SOURCE_DB))
    con.execute("""CREATE TABLE IF NOT EXISTS ohlcv (
        date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL,
        volume REAL, PRIMARY KEY (date, symbol))""")
    con.execute("""CREATE TABLE IF NOT EXISTS broad_indices (
        index_name TEXT, date TEXT, close REAL, PRIMARY KEY (index_name, date))""")
    return con


def _init_project_db() -> sqlite3.Connection:
    con = sqlite3.connect(str(PROJECT_DB))
    con.executescript(SCHEMA_SQL.read_text())        # CREATE IF NOT EXISTS — idempotent
    return con


def _done_symbols(con: sqlite3.Connection) -> set[str]:
    try:
        return {r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM valuation_series").fetchall()}
    except sqlite3.OperationalError:
        return set()


# ------------------------------------------------------------- eps / pe math
def _eps_path(t: "yf.Ticker", info: dict, daily_index: pd.DatetimeIndex):
    """₹ EPS path: annual NI shape calibrated to today's trailingEps. Returns
    (series_on_daily_index | None, label)."""
    anchor = info.get("trailingEps")
    if not anchor:
        return None, "no-eps-anchor"

    ni = None
    a = getattr(t, "income_stmt", None)
    if a is not None and not a.empty:
        for row in NI_ROWS:
            if row in a.index:
                ni = pd.to_numeric(a.loc[row], errors="coerce").dropna()
                if len(ni):
                    break
    if ni is None or len(ni) < 2 or float(ni.iloc[0]) == 0:
        return None, "no-NI-path"

    ni.index = pd.to_datetime(ni.index)
    ni = ni.sort_index()
    eps = ni * (float(anchor) / float(ni.iloc[-1]))   # FX & share-scale cancel
    eps.index = eps.index + pd.Timedelta(days=REPORT_LAG_DAYS)   # known-after lag
    combined = daily_index.union(eps.index)
    return eps.reindex(combined).ffill().reindex(daily_index), "annual-NI-calib"


def _clean_history(t: "yf.Ticker") -> pd.DataFrame:
    px = t.history(period=PRICE_YEARS, auto_adjust=False)
    if px.empty:
        return px
    idx = pd.to_datetime(px.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    px.index = idx.normalize()
    return px[~px.index.duplicated(keep="last")]


# -------------------------------------------------------------------- loader
def load_symbol(sym: str, src: sqlite3.Connection, prj: sqlite3.Connection) -> str:
    t = yf.Ticker(sym + ".NS")
    px = _clean_history(t)
    if px.empty:
        return "SKIP no price"
    try:
        info = t.info or {}
    except Exception:
        info = {}

    # --- ohlcv rows (replace this symbol's slice; resumable) ---
    rows = [(d.strftime("%Y-%m-%d"), sym,
             float(r["Open"]), float(r["High"]), float(r["Low"]),
             float(r["Close"]), float(r["Volume"]) if pd.notna(r["Volume"]) else 0.0)
            for d, r in px.iterrows() if pd.notna(r["Close"])]
    src.execute("DELETE FROM ohlcv WHERE symbol = ?", (sym,))
    src.executemany("INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?,?,?,?)", rows)
    src.commit()

    # --- P/E series ---
    close = px["Close"].dropna()
    eps, label = _eps_path(t, info, close.index)
    n_pe = 0
    if eps is not None:
        pe = (close / eps).replace([float("inf"), float("-inf")], pd.NA).dropna()
        pe = pe[pe > 0]
        if len(pe):
            prj.execute("DELETE FROM valuation_series WHERE symbol = ?", (sym,))
            prj.executemany(
                "INSERT OR REPLACE INTO valuation_series (symbol, date, pe, pb, ev_ebitda) "
                "VALUES (?,?,?,NULL,NULL)",
                [(sym, d.strftime("%Y-%m-%d"), float(v)) for d, v in pe.items()])
            n_pe = len(pe)

    # --- securities row + universe metadata ---
    prj.execute("INSERT OR REPLACE INTO securities (symbol, name, sector, isin) VALUES (?,?,?,?)",
                (sym, info.get("longName"), info.get("sector"), info.get("isin")))
    prj.commit()

    ffmc = info.get("floatShares")
    ffmc = float(ffmc) * float(close.iloc[-1]) if ffmc else float(info.get("marketCap") or 0)
    _META[sym] = {"Symbol": sym, "Name": info.get("longName"),
                  "Sector": info.get("sector") or "Unknown", "FFMC": ffmc}

    return f"{len(rows)} px, {n_pe} pe ({label})"


_META: dict = {}


def load_benchmarks(src: sqlite3.Connection) -> None:
    for name, yft in BENCHMARKS.items():
        try:
            px = _clean_history(yf.Ticker(yft))
            if px.empty:
                print(f"  benchmark {name}: no data, skipped")
                continue
            src.execute("DELETE FROM broad_indices WHERE index_name = ?", (name,))
            src.executemany(
                "INSERT OR REPLACE INTO broad_indices VALUES (?,?,?)",
                [(name, d.strftime("%Y-%m-%d"), float(v))
                 for d, v in px["Close"].dropna().items()])
            src.commit()
            print(f"  benchmark {name} ({yft}): {len(px)} rows")
        except Exception as e:
            print(f"  benchmark {name}: FAILED ({e})")


def main(argv):
    refresh = "--refresh" in argv
    src, prj = _init_source_db(), _init_project_db()

    done = set() if refresh else _done_symbols(prj)
    todo = [s for s in NIFTY50 if s not in done]
    print(f"Loading {len(todo)} symbols ({len(done)} already done)"
          f"{' [refresh]' if refresh else ''} ...")

    failed = []
    for i, sym in enumerate(todo, 1):
        try:
            msg = load_symbol(sym, src, prj)
        except Exception as e:
            msg = f"FAILED {str(e)[:60]}"
            failed.append(sym)
        print(f"  [{i:>2}/{len(todo)}] {sym:<12} {msg}", flush=True)

    print("Benchmarks:")
    load_benchmarks(src)

    # universe CSVs — regenerate from securities table so re-runs stay complete
    sec = pd.read_sql("SELECT symbol, name, sector FROM securities", prj)
    meta = pd.DataFrame(_META.values()) if _META else pd.DataFrame()
    if not sec.empty:
        mapping = sec.rename(columns={"symbol": "Symbol", "name": "Name", "sector": "Sector"})
        mapping["Sector"] = mapping["Sector"].fillna("Unknown")
        mapping.to_csv(MAPPING_CSV, index=False)
        if not meta.empty:
            old = pd.read_csv(FFMC_CSV) if FFMC_CSV.exists() else pd.DataFrame(columns=["Symbol", "FFMC"])
            ff = pd.concat([old, meta[["Symbol", "FFMC"]]]).drop_duplicates("Symbol", keep="last")
            ff.to_csv(FFMC_CSV, index=False)
        print(f"Wrote {MAPPING_CSV.name} ({len(mapping)}) + {FFMC_CSV.name}")

    # summary
    n = prj.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(date), MAX(date) "
                    "FROM valuation_series").fetchone()
    m = src.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(date), MAX(date) "
                    "FROM ohlcv").fetchone()
    print(f"\nohlcv:            {m[0]:>7} rows, {m[1]} symbols, {m[2]} .. {m[3]}")
    print(f"valuation_series: {n[0]:>7} rows, {n[1]} symbols, {n[2]} .. {n[3]}")
    if failed:
        print(f"FAILED: {failed}  (re-run to retry just these)")
    src.close(); prj.close()


if __name__ == "__main__":
    main(sys.argv[1:])
