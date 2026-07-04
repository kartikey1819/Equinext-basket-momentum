"""
Investable universe, as-of a date.

Base list = the Nifty 500 names in nifty500_mapping.csv. We then apply:
  - a liquidity gate (median daily traded value over a trailing window), and
  - a free-float gate (free-float market cap from nifty500_ffmc.csv).

LIMITATION (write this in your gotchas): we only have CURRENT index membership,
not as-of history, so this is mildly survivorship-biased. The honest fix is the
`universe_membership` table (as-of from/to dates) — populate it when you can.
"""
from __future__ import annotations
import functools
import pandas as pd

from pathlib import Path
from equinext.data import prices

# Data files live one level above the repo (alongside the source DB).
_DATA_ROOT = Path(__file__).resolve().parents[2]
_MAPPING_CSV = _DATA_ROOT / "nifty500_mapping.csv"
_FFMC_CSV = _DATA_ROOT / "nifty500_ffmc.csv"

# Universe gates (team-agreed; placeholders to start).
_LIQUIDITY_LOOKBACK_DAYS = 63                 # ~3 months of trading
_LIQUIDITY_MIN_ADV_INR = 5_00_00_000.0        # ₹5 crore median daily traded value
_FREE_FLOAT_MIN_INR = 1_00_00_00_000.0        # ₹100 crore min free-float market cap


@functools.lru_cache(maxsize=1)
def _mapping() -> pd.DataFrame:
    df = pd.read_csv(_MAPPING_CSV)
    df.columns = [c.strip() for c in df.columns]
    return df


@functools.lru_cache(maxsize=1)
def _ffmc() -> pd.Series:
    df = pd.read_csv(_FFMC_CSV)
    df.columns = [c.strip() for c in df.columns]
    return df.set_index("Symbol")["FFMC"]


@functools.lru_cache(maxsize=1)
def base_symbols() -> tuple[str, ...]:
    """All Nifty 500 names we have a mapping row for."""
    return tuple(_mapping()["Symbol"].dropna().unique())


def sector_of(symbol: str) -> str | None:
    m = _mapping()
    row = m[m["Symbol"] == symbol]
    return None if row.empty else str(row.iloc[0]["Sector"])


def investable_universe(as_of) -> list[str]:
    """Symbols investable as of `as_of`, after liquidity + free-float gates."""
    as_of = pd.Timestamp(as_of).normalize()
    px = prices.price_matrix()
    vol = prices.volume_matrix()
    ffmc = _ffmc()

    # trailing window ending as_of
    window = px.index[(px.index <= as_of)]
    if len(window) == 0:
        return []
    window = window[-_LIQUIDITY_LOOKBACK_DAYS:]

    out = []
    for sym in base_symbols():
        if sym not in px.columns:
            continue
        # must be trading as of this date
        last_px = px.loc[window, sym].dropna()
        if last_px.empty:
            continue
        # liquidity gate: median daily traded value (close * volume)
        traded_val = (px.loc[window, sym] * vol.loc[window, sym]).dropna()
        if traded_val.empty or traded_val.median() < _LIQUIDITY_MIN_ADV_INR:
            continue
        # free-float gate
        ff = ffmc.get(sym)
        if ff is None or float(ff) < _FREE_FLOAT_MIN_INR:
            continue
        out.append(sym)
    return sorted(out)
