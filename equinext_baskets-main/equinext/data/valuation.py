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


def read_valuation_series(symbol: str, end, lookback_years: int = 7) -> pd.DataFrame:
    """Read [date, pe, pb, ev_ebitda] up to `end`, trailing `lookback_years`."""
    end = pd.Timestamp(end)
    con = _project_conn()
    try:
        try:
            df = pd.read_sql(
                "SELECT date, pe, pb, ev_ebitda FROM valuation_series WHERE symbol = ?",
                con, params=(symbol,),
            )
        except Exception:
            df = pd.DataFrame()
    finally:
        con.close()

    if df.empty:
        raise NotImplementedError(
            "valuation_series is empty. Populate it first: derive multiples from "
            "prices x fundamentals via build_valuation_series_from_fundamentals(), "
            "or load a vendor series. See equinext/data/valuation.py."
        )

    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    cutoff = end - pd.Timedelta(days=int(lookback_years * 365))
    df = df[(df["date"] <= end) & (df["date"] >= cutoff)]
    return df.sort_values("date").reset_index(drop=True)


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
