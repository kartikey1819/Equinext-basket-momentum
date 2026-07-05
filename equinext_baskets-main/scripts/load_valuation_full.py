"""
Derive the FULL valuation multiples series for the Nifty 50 and (re)populate
valuation_series with pe, pb, ev_ebitda, fcf_yield, eps_ttm.

Prereq: scripts/load_nifty50_data.py has already loaded 10y prices into
        nifty500_hrp.db (we read close from there, no re-download).

METHOD — everything in ₹-per-share via one currency-cancelling scale factor.
  Yahoo's per-share EPS is broken and statements come in mixed currencies (INFY
  in USD, most in INR) — and Yahoo's own enterpriseToEbitda / freeCashflow
  snapshots are ALSO currency-broken for USD reporters (₹ EV over $ EBITDA).
  So we anchor only on the two reliable ₹-per-share snapshots (trailingEps,
  bookValue) and convert every absolute statement figure to ₹/share with the
  same scale:
        k = trailingEps / NI_latest        [₹ per statement-currency unit]
  in which FX and share count cancel. Then:

    eps(t)      = k * NI(t)                          ; pe = close/eps
    bvps(t)     = bookValue * equity(t)/equity_last  ; pb = close/bvps
    ev_ebitda(t)= (close + k*netdebt(t)) / (k*EBITDA(t))
    fcf_yield(t)= k*FCF(t) / close

  Annual fundamentals step at fiscal year-end + 45d reporting lag (no
  look-ahead), forward-filled onto daily prices.

PER-STOCK AVAILABILITY: financials (banks/NBFCs/insurers) have no meaningful
EV/EBITDA or FCF -> skipped by sector; pe & pb still populate. Non-financials
missing an EBITDA/FCF row also skip those. The basket's valuation gate
composites over whichever multiples are non-null.

HONEST LIMITS: annual granularity, history starts ~2023 (only ~4-5 annual
statements on Yahoo), approximate. For a longer/cleaner series, swap in a real
fundamentals vendor — the table schema and the basket don't change.

    python scripts/load_valuation_full.py            # (re)derive all
    python scripts/load_valuation_full.py INFY HDFCBANK   # subset (debug)
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

_REPO = Path(__file__).resolve().parents[1]
_ROOT = _REPO.parent
SOURCE_DB = _ROOT / "nifty500_hrp.db"        # prices (read)
PROJECT_DB = _REPO / "equinext.db"           # valuation_series (write)

REPORT_LAG_DAYS = 45
NI_ROWS = ("Net Income", "Net Income Common Stockholders",
           "Net Income From Continuing Operation Net Minority Interest")
EQUITY_ROWS = ("Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest")
EBITDA_ROWS = ("EBITDA", "Normalized EBITDA")
FCF_ROWS = ("Free Cash Flow",)
DEBT_ROWS = ("Total Debt", "Long Term Debt And Capital Lease Obligation")
CASH_ROWS = ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")

NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "BPCL", "BRITANNIA", "CIPLA",
    "COALINDIA", "DRREDDY", "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC",
    "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM",
    "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]


# ---------------------------------------------------------------- helpers
def _ensure_columns(con: sqlite3.Connection) -> None:
    have = {r[1] for r in con.execute("PRAGMA table_info(valuation_series)")}
    for col in ("pb", "ev_ebitda", "fcf_yield", "eps_ttm"):
        if col not in have:
            con.execute(f"ALTER TABLE valuation_series ADD COLUMN {col} NUMERIC")
    con.commit()


def _annual(df, rows) -> pd.Series | None:
    """First present row of an annual statement as a clean, date-sorted Series."""
    if df is None or df.empty:
        return None
    for r in rows:
        if r in df.index:
            s = pd.to_numeric(df.loc[r], errors="coerce").dropna()
            if len(s):
                s.index = pd.to_datetime(s.index)
                return s.sort_index()
    return None


def _step(series: pd.Series, daily: pd.DatetimeIndex) -> pd.Series:
    """Forward-fill an annual series onto the daily index, +reporting lag."""
    s = series.copy()
    s.index = s.index + pd.Timedelta(days=REPORT_LAG_DAYS)
    return s.reindex(daily.union(s.index)).ffill().reindex(daily)


def _daily_close(sym: str, src: sqlite3.Connection) -> pd.Series:
    df = pd.read_sql("SELECT date, close FROM ohlcv WHERE symbol = ? ORDER BY date",
                     src, params=(sym,))
    if df.empty:
        return pd.Series(dtype=float)
    s = df.set_index(pd.to_datetime(df["date"]))["close"].astype(float)
    return s[s > 0]


# ---------------------------------------------------------------- derivation
def derive(sym: str, src: sqlite3.Connection) -> pd.DataFrame:
    close = _daily_close(sym, src)
    if close.empty:
        return pd.DataFrame()
    t = yf.Ticker(sym + ".NS")
    try:
        info = t.info or {}
    except Exception:
        info = {}
    idx = close.index
    out = pd.DataFrame(index=idx)
    is_fin = (info.get("sector") == "Financial Services")

    # --- scale factor k = trailingEps / NI_latest  (₹ per statement unit) ---
    eps_anchor = info.get("trailingEps")
    ni = _annual(t.income_stmt, NI_ROWS)
    k = None
    if eps_anchor and ni is not None and len(ni) >= 2 and float(ni.iloc[-1]) != 0:
        k = float(eps_anchor) / float(ni.iloc[-1])

    # --- P/E + eps_ttm (eps = k * NI) ---
    if k is not None:
        eps = _step(ni * k, idx)
        out["eps_ttm"] = eps
        pe = close / eps
        out["pe"] = pe.where(pe > 0)

    # --- P/B (anchor bookValue/share ₹, shape = annual equity) ---
    bv_anchor = info.get("bookValue")
    eq = _annual(t.balance_sheet, EQUITY_ROWS)
    if bv_anchor and bv_anchor > 0 and eq is not None and len(eq) >= 2 and float(eq.iloc[-1]) != 0:
        bvps = _step(eq * (float(bv_anchor) / float(eq.iloc[-1])), idx)
        pb = close / bvps
        out["pb"] = pb.where(pb > 0)

    # --- EV/EBITDA = (close + k*netdebt) / (k*EBITDA)   [non-financials only] ---
    ebitda = _annual(t.income_stmt, EBITDA_ROWS)
    if k is not None and not is_fin and ebitda is not None and len(ebitda) >= 2 and float(ebitda.iloc[-1]) > 0:
        ebitda_ps = _step(ebitda * k, idx)                       # ₹/share
        debt = _annual(t.balance_sheet, DEBT_ROWS)
        cash = _annual(t.balance_sheet, CASH_ROWS)
        netdebt_ps = 0.0
        if debt is not None:
            nd = debt.subtract(cash, fill_value=0.0) if cash is not None else debt
            netdebt_ps = _step(nd * k, idx).fillna(0.0)          # ₹/share
        vv = (close + netdebt_ps) / ebitda_ps
        out["ev_ebitda"] = vv.where(ebitda_ps > 0)

    # --- FCF yield = k*FCF / close   [non-financials only; can be negative] ---
    fcf = _annual(t.cashflow, FCF_ROWS)
    if k is not None and not is_fin and fcf is not None and len(fcf) >= 2:
        fcf_ps = _step(fcf * k, idx)                             # ₹/share
        out["fcf_yield"] = fcf_ps / close

    for c in ("pe", "pb", "ev_ebitda", "fcf_yield", "eps_ttm"):
        if c not in out.columns:
            out[c] = pd.NA
    out = out.dropna(how="all", subset=["pe", "pb", "ev_ebitda", "fcf_yield"])
    return out


def main(argv):
    syms = [a.upper() for a in argv] or NIFTY50
    src = sqlite3.connect(str(SOURCE_DB))
    prj = sqlite3.connect(str(PROJECT_DB))
    _ensure_columns(prj)

    tally = {"pe": 0, "pb": 0, "ev_ebitda": 0, "fcf_yield": 0}
    for i, sym in enumerate(syms, 1):
        try:
            df = derive(sym, src)
        except Exception as e:
            print(f"  [{i:>2}/{len(syms)}] {sym:<12} FAILED {str(e)[:50]}")
            continue
        if df.empty:
            print(f"  [{i:>2}/{len(syms)}] {sym:<12} no valuation")
            continue
        prj.execute("DELETE FROM valuation_series WHERE symbol = ?", (sym,))
        prj.executemany(
            "INSERT OR REPLACE INTO valuation_series "
            "(symbol, date, pe, pb, ev_ebitda, fcf_yield, eps_ttm) VALUES (?,?,?,?,?,?,?)",
            [(sym, d.strftime("%Y-%m-%d"),
              _f(r["pe"]), _f(r["pb"]), _f(r["ev_ebitda"]), _f(r["fcf_yield"]), _f(r["eps_ttm"]))
             for d, r in df.iterrows()])
        prj.commit()
        cov = {c: int(df[c].notna().sum()) for c in tally}
        for c in tally:
            tally[c] += 1 if cov[c] else 0
        avail = "+".join(c.replace("_yield", "").replace("ev_ebitda", "ev/eb").upper()
                         for c in ("pe", "pb", "ev_ebitda", "fcf_yield") if cov[c])
        print(f"  [{i:>2}/{len(syms)}] {sym:<12} {len(df):>4} rows  [{avail}]")

    n = prj.execute("SELECT COUNT(*), COUNT(pe), COUNT(pb), COUNT(ev_ebitda), COUNT(fcf_yield), "
                    "MIN(date), MAX(date) FROM valuation_series").fetchone()
    print(f"\nvaluation_series: {n[0]:,} rows  |  non-null: pe={n[1]:,} pb={n[2]:,} "
          f"ev_ebitda={n[3]:,} fcf_yield={n[4]:,}  |  {n[5]} .. {n[6]}")
    print(f"symbols with each multiple: {tally}")
    src.close(); prj.close()


def _f(v):
    return None if v is None or pd.isna(v) else float(v)


if __name__ == "__main__":
    main(sys.argv[1:])
