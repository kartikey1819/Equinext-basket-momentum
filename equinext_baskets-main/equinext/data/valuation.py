"""
Valuation series (P/E, P/B, EV/EBITDA over time).

You DON'T have this data yet. Two jobs live here:

  read_valuation_series(...)            -> reader the ResearchContext calls.
  build_valuation_series_from_fundamentals(...) -> the recommended way to CREATE
      the series: derive multiples from prices (you have) x fundamentals (you
      must pull). pe = price/eps_ttm, pb = price/bvps, ev_ebitda = (mcap+netdebt)/ebitda.
      This is cheaper + more point-in-time-robust than scraping the multiples.

Until the `valuation_series` table is populated, read_valuation_series raises a
clear error so callers know exactly what is missing.
"""
from __future__ import annotations
import pandas as pd

import sqlite3
from pathlib import Path

# Our derived/PIT tables DB (valuation_series, fundamentals_snapshot, ...). Created on first write.
_PROJECT_DB = Path(__file__).resolve().parents[2] / "equinext.db"


def _project_conn() -> sqlite3.Connection:
    return sqlite3.connect(str(_PROJECT_DB))


_VAL_BY_SYM: dict | None = None       # per-symbol valuation series, loaded once


def _val_by_sym() -> dict:
    global _VAL_BY_SYM
    if _VAL_BY_SYM is None:
        con = _project_conn()
        try:
            df = pd.read_sql(
                "SELECT symbol, date, pe, pb, ev_ebitda, fcf_yield, eps_ttm FROM valuation_series", con)
        except Exception:
            df = pd.DataFrame()
        finally:
            con.close()
        if df.empty:
            _VAL_BY_SYM = {}
        else:
            df["date"] = pd.to_datetime(df["date"]).dt.normalize()
            df = df.sort_values(["symbol", "date"])
            _VAL_BY_SYM = {s: g.drop(columns="symbol").reset_index(drop=True)
                           for s, g in df.groupby("symbol")}
    return _VAL_BY_SYM


def read_valuation_series(symbol: str, end, lookback_years: int = 7) -> pd.DataFrame:
    """Read [date, pe, pb, ev_ebitda, fcf_yield, eps_ttm] up to `end`, trailing
    `lookback_years`. Served from an in-memory cache (identical data, no per-call SQL)."""
    end = pd.Timestamp(end)
    df = _val_by_sym().get(symbol)
    if df is None or df.empty:
        raise NotImplementedError(
            "valuation_series is empty for this symbol. Populate it first (screener/"
            "fundamentals x prices). See equinext/data/valuation.py.")
    cutoff = end - pd.Timedelta(days=int(lookback_years * 365))
    return df[(df["date"] <= end) & (df["date"] >= cutoff)].reset_index(drop=True)


def build_valuation_series_from_fundamentals(symbol: str) -> pd.DataFrame:
    """RECOMMENDED builder (skeleton). Combine daily price with step-function
    per-share fundamentals to produce a daily multiples series.

    TODO (data owner):
      1. pull trailing EPS, book value/share, EBITDA, net debt, shares from the
         fundamentals_snapshot table (forward-filled between report dates),
      2. align to the daily price index from prices.price_matrix()[symbol],
      3. pe = price/eps_ttm; pb = price/bvps; ev_ebitda=(price*shares+net_debt)/ebitda,
      4. sanity check: multiple * per-share-fundamental should reconcile to price,
      5. write rows to the valuation_series table.
    """
    raise NotImplementedError(
        "Implement once fundamentals_snapshot is populated (see data/snapshot.py)."
    )
