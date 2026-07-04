"""
The monthly point-in-time fundamentals snapshot job (the heart of PIT honesty).

You DON'T have fundamentals yet. This module has:

  read_fundamentals(symbol, as_of)  -> reader the ResearchContext calls. Returns
      the latest snapshot row with captured_on <= as_of (honest about what was
      known then). Raises a clear error while the table is empty.

  snapshot_to_db(records, captured_on) -> writer (DONE). Stamps captured_on and
      writes to fundamentals_snapshot.

  fetch_from_screener(symbol)       -> TODO. Pull a company's financials from
      screener.in (login + "Export to Excel" + parse). The ONLY part left to build.

Run monthly so the forward PIT store accumulates. captured_on is the whole point:
it lets you query "what did we know on date X" honestly. Start it on day one.
"""
from __future__ import annotations
import datetime as dt
import pandas as pd

import sqlite3
from pathlib import Path

# Our derived/PIT tables DB (valuation_series, fundamentals_snapshot, ...). Created on first write.
_PROJECT_DB = Path(__file__).resolve().parents[2] / "equinext.db"


def _project_conn() -> sqlite3.Connection:
    return sqlite3.connect(str(_PROJECT_DB))

# the fundamentals fields QARP's quality leg needs
FIELDS = ["roce", "roe", "debt_equity", "interest_cover", "cfo", "pat", "eps", "book_value"]


def read_fundamentals(symbol: str, as_of) -> dict:
    """Latest snapshot known on/before `as_of` (PIT). RESTATED history => directional only."""
    as_of = pd.Timestamp(as_of)
    con = _project_conn()
    try:
        try:
            df = pd.read_sql(
                "SELECT * FROM fundamentals_snapshot WHERE symbol = ?",
                con, params=(symbol,),
            )
        except Exception:
            df = pd.DataFrame()
    finally:
        con.close()

    if df.empty:
        raise NotImplementedError(
            "fundamentals_snapshot is empty. Start the monthly screener snapshot "
            "(fetch_from_screener -> snapshot_to_db). This is QARP's quality leg — "
            "it cannot run without it. See equinext/data/snapshot.py."
        )

    df["captured_on"] = pd.to_datetime(df["captured_on"])
    known = df[df["captured_on"] <= as_of].sort_values("captured_on")
    if known.empty:
        raise LookupError(f"No fundamentals for {symbol} known as of {as_of.date()}.")
    return known.iloc[-1].to_dict()


def snapshot_to_db(records: list[dict], captured_on: dt.date) -> None:
    """Write a batch of fundamentals rows, stamped with today's capture date."""
    if not records:
        return
    df = pd.DataFrame(records)
    df["captured_on"] = pd.Timestamp(captured_on).strftime("%Y-%m-%d")
    con = _project_conn()
    try:
        df.to_sql("fundamentals_snapshot", con, if_exists="append", index=False)
        con.commit()
    finally:
        con.close()


def fetch_from_screener(symbol: str) -> list[dict]:
    """TODO (data owner): pull one company's financials from screener.in.

    Steps (discover exact endpoints via browser DevTools -> Network):
      1. log in (SCREENER_EMAIL / SCREENER_PASSWORD from .env), keep the session cookie,
      2. hit the company's "Export to Excel" endpoint, OR parse the ratios/balance-sheet
         tables from the company page HTML,
      3. extract: roce, roe, debt_equity, interest_cover, cfo, pat, eps, book_value
         (+ period_end the figures refer to),
      4. RATE-LIMIT and CACHE — respect screener's terms on automated access.

    Return one dict per fiscal period with keys: symbol, period_end, + FIELDS.
    """
    raise NotImplementedError(
        "Build the screener puller here. Respect screener's ToS: log in, rate-limit, "
        "cache. Then call snapshot_to_db(records, captured_on=today)."
    )
