"""
Price + benchmark loaders, built on the raw `ohlcv` and `broad_indices` tables.

Provides:
  - load_ohlcv(symbol, start, end)  -> per-symbol OHLCV DataFrame
  - price_matrix()                  -> wide close matrix (dates x symbols), cached
  - load_benchmark(index_name, ...) -> benchmark close series

`price_matrix` is loaded once and cached in memory — almost every later
computation is either "down a column over time" or "across a row at one date",
and a dates x symbols grid makes both one-liners.
"""
from __future__ import annotations
import datetime as dt
import pandas as pd

import sqlite3
from pathlib import Path

# Raw source DB (read-only): ohlcv + broad_indices. Sits one level above the repo.
_SOURCE_DB = Path(__file__).resolve().parents[3] / "nifty500_hrp.db"


def _source_conn() -> sqlite3.Connection:
    if not _SOURCE_DB.exists():
        raise FileNotFoundError(
            f"Source DB not found at {_SOURCE_DB} (expected nifty500_hrp.db)."
        )
    return sqlite3.connect(str(_SOURCE_DB))

_PRICE_MATRIX: pd.DataFrame | None = None       # close, dates x symbols
_VOLUME_MATRIX: pd.DataFrame | None = None      # volume, dates x symbols


def _parse_dates(s: pd.Series) -> pd.Series:
    # the raw `date` column mixes 'YYYY-MM-DD HH:MM:SS' and 'YYYY-MM-DD'
    return pd.to_datetime(s, format="ISO8601").dt.normalize()


def _load_matrices() -> None:
    global _PRICE_MATRIX, _VOLUME_MATRIX
    if _PRICE_MATRIX is not None:
        return
    con = _source_conn()
    try:
        df = pd.read_sql("SELECT date, symbol, close, volume FROM ohlcv", con)
    finally:
        con.close()
    df["date"] = _parse_dates(df["date"])
    df = df.drop_duplicates(subset=["date", "symbol"], keep="last")
    _PRICE_MATRIX = df.pivot(index="date", columns="symbol", values="close").sort_index()
    _VOLUME_MATRIX = df.pivot(index="date", columns="symbol", values="volume").sort_index()


def price_matrix() -> pd.DataFrame:
    """Wide close-price matrix (index = trading days, cols = symbols). Cached."""
    _load_matrices()
    return _PRICE_MATRIX


def volume_matrix() -> pd.DataFrame:
    """Wide volume matrix (index = trading days, cols = symbols). Cached."""
    _load_matrices()
    return _VOLUME_MATRIX


def trading_days() -> pd.DatetimeIndex:
    return price_matrix().index


def load_ohlcv(symbol: str, start, end) -> pd.DataFrame:
    """Per-symbol OHLCV. Columns: [date, open, high, low, close, volume].

    POINT-IN-TIME: never returns a row dated after `end`.
    """
    con = _source_conn()
    try:
        df = pd.read_sql(
            "SELECT date, open, high, low, close, volume FROM ohlcv WHERE symbol = ?",
            con, params=(symbol,),
        )
    finally:
        con.close()
    df["date"] = _parse_dates(df["date"])
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    return df.sort_values("date").reset_index(drop=True)


def load_benchmark(index_name: str, start, end) -> pd.Series:
    """Benchmark close series from `broad_indices` (e.g. NIFTY500).

    Returns a Series indexed by date. NOTE: this is the PRICE index; the brief
    asks for the Total Return (TRI) version — source that later, or flag the gap.
    """
    con = _source_conn()
    try:
        df = pd.read_sql(
            "SELECT date, close FROM broad_indices WHERE index_name = ?",
            con, params=(index_name,),
        )
    finally:
        con.close()
    df["date"] = _parse_dates(df["date"])
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    df = df[(df["date"] >= start) & (df["date"] <= end)].drop_duplicates("date")
    return df.set_index("date")["close"].sort_index()


def clear_cache() -> None:
    """Drop the in-memory matrices (used by tests)."""
    global _PRICE_MATRIX, _VOLUME_MATRIX
    _PRICE_MATRIX = None
    _VOLUME_MATRIX = None
