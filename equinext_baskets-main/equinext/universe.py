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
import sqlite3
import pandas as pd

from pathlib import Path
from equinext.data import prices

# Data files live one level above the repo (alongside the source DB).
_DATA_ROOT = Path(__file__).resolve().parents[2]
_MAPPING_CSV = _DATA_ROOT / "nifty500_mapping.csv"
_FFMC_CSV = _DATA_ROOT / "nifty500_ffmc.csv"
_PROJECT_DB = Path(__file__).resolve().parents[1] / "equinext.db"

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


@functools.lru_cache(maxsize=1)
def _mcaps() -> dict:
    """Current market cap per symbol (from securities.mcap), for PIT reconstruction."""
    con = sqlite3.connect(str(_PROJECT_DB))
    try:
        rows = con.execute("SELECT symbol, mcap FROM securities WHERE mcap IS NOT NULL").fetchall()
    finally:
        con.close()
    return {r[0]: float(r[1]) for r in rows}


@functools.lru_cache(maxsize=8)
def _pool(name: str) -> frozenset:
    """Symbols tagged into an index pool (n50_current / n50_dropout / n500_current / ...)."""
    con = sqlite3.connect(str(_PROJECT_DB))
    try:
        rows = con.execute("SELECT symbol FROM pools WHERE pool = ?", (name,)).fetchall()
    finally:
        con.close()
    return frozenset(r[0] for r in rows)


def _trading_liquid(as_of, symbols) -> dict:
    """{symbol: last_close} for symbols trading AND liquid as of `as_of`."""
    as_of = pd.Timestamp(as_of).normalize()
    px = prices.price_matrix(); vol = prices.volume_matrix()
    window = px.index[px.index <= as_of]
    if len(window) == 0:
        return {}
    day = window[-1]; liq = window[-_LIQUIDITY_LOOKBACK_DAYS:]
    out = {}
    for sym in symbols:
        if sym not in px.columns:
            continue
        s = px.loc[:day, sym].dropna()
        if s.empty or (day - s.index[-1]).days > 20:         # not trading (unlisted/delisted)
            continue
        tv = (px.loc[liq, sym] * vol.loc[liq, sym]).dropna()
        if tv.empty or tv.median() < _LIQUIDITY_MIN_ADV_INR:
            continue
        out[sym] = float(s.iloc[-1])
    return out


def standard_universe(as_of, members) -> list[str]:
    """Standard (current-membership) universe: `members` trading + liquid at `as_of`."""
    return sorted(_trading_liquid(as_of, members).keys())


def pit_universe(as_of, pool=None, top_n: int = 50) -> list[str]:
    """POINT-IN-TIME universe: the top `top_n` by RECONSTRUCTED market cap on `as_of`,
    drawn from `pool` (default: the Nifty-50 pool = current 50 + dropped ex-members).

    mcap(t) = mcap_now * price(t)/price_now  ( == shares_now * price(t) ), so a stock
    that was large then but shrank later is IN early and OUT later — removing the
    survivorship bias of testing a fixed *current* membership list backward.
    """
    if pool is None:
        pool = _pool("n50_current") | _pool("n50_dropout")
    prices_at = _trading_liquid(as_of, pool)
    mcaps = _mcaps()
    px = prices.price_matrix()
    scores = {}
    for sym, p_t in prices_at.items():
        mc_now = mcaps.get(sym)
        if mc_now is None:
            continue
        pnow = px[sym].dropna()
        if pnow.empty or pnow.iloc[-1] <= 0:
            continue
        scores[sym] = mc_now * p_t / pnow.iloc[-1]           # reconstructed mcap at `as_of`
    return sorted(sorted(scores, key=lambda k: -scores[k])[:top_n])
