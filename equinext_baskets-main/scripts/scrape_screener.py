"""
Screener.in -> real 10-year fundamentals -> rebuild valuation_series (2016+).

Pulls each Nifty-50 company's annual Profit&Loss / Balance-Sheet / Cash-Flow
tables (~12 years, public, no login) and derives TRUE historical multiples,
replacing the ~3yr Yahoo-calibrated series. Also fills fundamentals_snapshot
(pat, eps, book_value, cfo, roe, debt_equity) as a bonus (unlocks QARP later).

PER-SHARE math (screener is all-INR, so no currency issues):
    shares(yr)   = Net Profit / EPS                 (both from P&L, same yr)
    bvps         = (Equity Capital + Reserves) / shares
    ebitda_ps    = Operating Profit / shares         (non-financials)
    netdebt_ps   = Borrowings / shares               (gross-debt proxy)
    fcf_ps       = Free Cash Flow / shares           (non-financials)
Then forward-fill onto daily prices (fiscal year-end + 75d reporting lag, so no
look-ahead) and:
    pe = close/eps   pb = close/bvps
    ev_ebitda = (close + netdebt_ps)/ebitda_ps   fcf_yield = fcf_ps/close

RESPECTFUL USE: real browser UA, 2.5s between requests, HTML cached to
.cache/screener/ so each page is fetched at most once. Personal research only —
do not redistribute screener's data or hammer the site.

    python scripts/scrape_screener.py RELIANCE HDFCBANK INFY   # test a few
    python scripts/scrape_screener.py                          # all 49 (cached)
    python scripts/scrape_screener.py --refetch RELIANCE       # ignore cache
"""
from __future__ import annotations
import sys
import time
import sqlite3
import warnings
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

warnings.simplefilter("ignore")

_REPO = Path(__file__).resolve().parents[1]
_ROOT = _REPO.parent
SOURCE_DB = _ROOT / "nifty500_hrp.db"
PROJECT_DB = _REPO / "equinext.db"
CACHE = _REPO / ".cache" / "screener"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) personal-research"}
DELAY_S = 2.5
LAG_DAYS = 75          # fiscal-year-end -> results announced (~mid-June for Mar y/e)

NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "BPCL", "BRITANNIA", "CIPLA",
    "COALINDIA", "DRREDDY", "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC",
    "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM",
    "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]


# ---------------------------------------------------------------- fetch (cached)
def fetch(sym: str, refetch: bool = False) -> str | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{sym}.html"
    if cached.exists() and cached.stat().st_size > 5000 and not refetch:
        return cached.read_text(encoding="utf-8", errors="ignore")
    for suffix in ("consolidated/", ""):          # prefer consolidated, fall back to standalone
        url = f"https://www.screener.in/company/{sym}/{suffix}"
        try:
            r = requests.get(url, headers=UA, timeout=30)
        except Exception:
            continue
        time.sleep(DELAY_S)                        # be gentle regardless of outcome
        if r.status_code == 200 and 'id="profit-loss"' in r.text:
            cached.write_text(r.text, encoding="utf-8")
            return r.text
    return None


# ---------------------------------------------------------------- parse
def _table(soup: BeautifulSoup, section: str) -> pd.DataFrame | None:
    node = soup.find(id=section)
    if not node:
        return None
    tbl = node.find("table")
    if tbl is None:
        return None
    df = pd.read_html(StringIO(str(tbl)))[0]
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(columns={df.columns[0]: "item"})
    df["item"] = df["item"].astype(str).str.replace("\xa0", " ").str.replace("+", "", regex=False).str.strip()
    return df.set_index("item")


def _year_cols(df: pd.DataFrame) -> list[str]:
    out = []
    for c in df.columns:
        try:
            pd.to_datetime("01 " + c)              # "Mar 2020" -> valid
            out.append(c)
        except Exception:
            pass                                    # skip 'TTM', 'Unnamed', etc.
    return out


def _row(df: pd.DataFrame, name: str, ycols: list[str]) -> pd.Series | None:
    if df is None or name not in df.index:
        return None
    raw = df.loc[name, ycols]
    if isinstance(raw, pd.DataFrame):              # duplicate row label -> take first
        raw = raw.iloc[0]
    vals = (raw.astype(str).str.replace(",", "", regex=False)
            .str.replace("%", "", regex=False).str.strip())
    s = pd.to_numeric(vals, errors="coerce")
    s.index = [pd.to_datetime("01 " + c) + pd.offsets.MonthEnd(0) for c in ycols]
    return s.dropna()


def parse_annual(html: str) -> dict | None:
    """Return dict of annual per-share Series indexed by fiscal-year-end date."""
    soup = BeautifulSoup(html, "html.parser")
    pl, bs, cf = _table(soup, "profit-loss"), _table(soup, "balance-sheet"), _table(soup, "cash-flow")
    if pl is None:
        return None
    yc = _year_cols(pl)
    net = _row(pl, "Net Profit", yc)
    eps = _row(pl, "EPS in Rs", yc)
    if net is None or eps is None or eps.empty:
        return None

    # shares(yr) = NetProfit/EPS; fill sparse/loss years by nearest (count is stable)
    valid = eps.abs() > 1e-9
    shares = (net[valid] / eps[valid]).reindex(net.index).ffill().bfill()
    shares = shares[shares > 0]
    if shares.empty:
        return None

    def ps(section_df, name):
        r = _row(section_df, name, _year_cols(section_df)) if section_df is not None else None
        if r is None:
            return None
        return (r.reindex(shares.index) / shares).dropna()

    equity = _row(bs, "Equity Capital", _year_cols(bs)) if bs is not None else None
    reserves = _row(bs, "Reserves", _year_cols(bs)) if bs is not None else None
    book = None
    if equity is not None and reserves is not None:
        book = (equity.add(reserves, fill_value=0.0).reindex(shares.index) / shares).dropna()

    return {
        "eps": eps.reindex(shares.index).dropna(),
        "bvps": book,
        "ebitda_ps": ps(pl, "Operating Profit"),
        "netdebt_ps": ps(bs, "Borrowings"),
        "fcf_ps": ps(cf, "Free Cash Flow") if (cf is not None and "Free Cash Flow" in cf.index)
                  else ps(cf, "Cash from Operating Activity"),
        "net_profit": net, "book_abs": (equity.add(reserves, fill_value=0.0) if book is not None else None),
        "cfo": _row(cf, "Cash from Operating Activity", _year_cols(cf)) if cf is not None else None,
    }


# ---------------------------------------------------------------- rebuild series
def _daily_close(sym: str, src) -> pd.Series:
    df = pd.read_sql("SELECT date, close FROM ohlcv WHERE symbol=? ORDER BY date", src, params=(sym,))
    if df.empty:
        return pd.Series(dtype=float)
    s = df.set_index(pd.to_datetime(df["date"]))["close"].astype(float)
    return s[s > 0]


def _step(annual: pd.Series, daily: pd.DatetimeIndex) -> pd.Series:
    a = annual.copy()
    a.index = a.index + pd.Timedelta(days=LAG_DAYS)          # known-after-announcement
    return a.reindex(daily.union(a.index)).ffill().reindex(daily)


def build_series(sym: str, ann: dict, is_fin: bool, src) -> pd.DataFrame:
    close = _daily_close(sym, src)
    if close.empty:
        return pd.DataFrame()
    idx = close.index
    out = pd.DataFrame(index=idx)

    eps = _step(ann["eps"], idx)
    out["eps_ttm"] = eps
    out["pe"] = (close / eps).where(eps > 0)
    if ann["bvps"] is not None and not ann["bvps"].empty:
        bv = _step(ann["bvps"], idx)
        out["pb"] = (close / bv).where(bv > 0)
    if not is_fin and ann["ebitda_ps"] is not None and not ann["ebitda_ps"].empty:
        eb = _step(ann["ebitda_ps"], idx)
        nd = _step(ann["netdebt_ps"], idx).fillna(0.0) if ann["netdebt_ps"] is not None else 0.0
        out["ev_ebitda"] = ((close + nd) / eb).where(eb > 0)
    if not is_fin and ann["fcf_ps"] is not None and not ann["fcf_ps"].empty:
        out["fcf_yield"] = _step(ann["fcf_ps"], idx) / close

    for c in ("pe", "pb", "ev_ebitda", "fcf_yield", "eps_ttm"):
        if c not in out.columns:
            out[c] = pd.NA
    return out.dropna(how="all", subset=["pe", "pb", "ev_ebitda", "fcf_yield"])


# ---------------------------------------------------------------- main
def _f(v):
    return None if v is None or pd.isna(v) else float(v)


def main(argv):
    refetch = "--refetch" in argv
    syms = [a.upper() for a in argv if not a.startswith("--")] or NIFTY50

    prj = sqlite3.connect(str(PROJECT_DB))
    src = sqlite3.connect(str(SOURCE_DB))
    fins = {r[0] for r in prj.execute(
        "SELECT symbol FROM securities WHERE sector = 'Financial Services'")}

    ok, fail, tally = 0, [], {"pe": 0, "pb": 0, "ev_ebitda": 0, "fcf_yield": 0}
    for i, sym in enumerate(syms, 1):
        html = fetch(sym, refetch)
        if not html:
            print(f"  [{i:>2}/{len(syms)}] {sym:<12} FETCH FAILED"); fail.append(sym); continue
        ann = parse_annual(html)
        if not ann:
            print(f"  [{i:>2}/{len(syms)}] {sym:<12} PARSE FAILED"); fail.append(sym); continue
        df = build_series(sym, ann, sym in fins, src)
        if df.empty:
            print(f"  [{i:>2}/{len(syms)}] {sym:<12} no series"); fail.append(sym); continue

        prj.execute("DELETE FROM valuation_series WHERE symbol=?", (sym,))
        prj.executemany(
            "INSERT OR REPLACE INTO valuation_series (symbol,date,pe,pb,ev_ebitda,fcf_yield,eps_ttm) "
            "VALUES (?,?,?,?,?,?,?)",
            [(sym, d.strftime("%Y-%m-%d"), _f(r["pe"]), _f(r["pb"]), _f(r["ev_ebitda"]),
              _f(r["fcf_yield"]), _f(r["eps_ttm"])) for d, r in df.iterrows()])

        # bonus: annual fundamentals_snapshot rows (PIT-stamped at announcement)
        _write_snapshot(prj, sym, ann)
        prj.commit()

        for c in tally:
            tally[c] += 1 if df[c].notna().any() else 0
        yrs = (df.index[-1] - df.index[0]).days / 365
        avail = "+".join(c[:4].upper() for c in ("pe", "pb", "ev_ebitda", "fcf_yield") if df[c].notna().any())
        print(f"  [{i:>2}/{len(syms)}] {sym:<12} {len(df):>5} rows  {yrs:.1f}y  [{avail}]")
        ok += 1

    n = prj.execute("SELECT COUNT(*), COUNT(pe), COUNT(pb), COUNT(ev_ebitda), COUNT(fcf_yield), "
                    "MIN(date), MAX(date) FROM valuation_series").fetchone()
    print(f"\nvaluation_series: {n[0]:,} rows | pe={n[1]:,} pb={n[2]:,} ev={n[3]:,} fcf={n[4]:,} | {n[5]}..{n[6]}")
    print(f"symbols scored: {ok}/{len(syms)}  with-multiple: {tally}")
    if fail:
        print(f"FAILED (check screener symbol): {fail}")
    prj.close(); src.close()


def _write_snapshot(prj, sym, ann):
    net, book, cfo, eps = ann["net_profit"], ann["book_abs"], ann["cfo"], ann["eps"]
    if book is None:
        return
    for d in net.index:
        pat = _f(net.get(d)); bk = _f(book.get(d)); ep = _f(eps.get(d))
        roe = (pat / bk) if (pat and bk) else None
        prj.execute(
            "INSERT OR REPLACE INTO fundamentals_snapshot "
            "(symbol, captured_on, period_end, roe, cfo, pat, eps, book_value) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (sym, (d + pd.Timedelta(days=LAG_DAYS)).strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"),
             roe, _f(cfo.get(d)) if cfo is not None else None, pat, ep, bk))


if __name__ == "__main__":
    main(sys.argv[1:])
