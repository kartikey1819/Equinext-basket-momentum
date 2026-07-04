"""
ResearchContext — the single object handed to every basket's select().

Wraps ALL shared data access so baskets never touch the DB directly. Every
accessor takes an as_of / end and MUST NOT return data dated after it.

WHAT WORKS TODAY (data you have):  universe(), ohlcv(), sector(), price helpers.
WHAT IS STUBBED (data you must source): valuation_series(), fundamentals().
Those two read from the project DB tables that the screener puller + valuation
builder will populate (see equinext/data/snapshot.py and data/valuation.py).
Until then they raise a clear error telling you what's missing.
"""
from __future__ import annotations
import datetime as dt
import pandas as pd

from equinext import universe
from equinext.data import prices, valuation, snapshot


class ResearchContext:
    def universe(self, as_of) -> list[str]:
        """Investable symbols as of this date (post liquidity + exclusion gates)."""
        return universe.investable_universe(as_of)

    def ohlcv(self, symbol: str, start, end) -> pd.DataFrame:
        """Adjusted OHLCV. Columns: [date, open, high, low, close, volume]."""
        return prices.load_ohlcv(symbol, start, end)

    def sector(self, symbol: str) -> str | None:
        return universe.sector_of(symbol)

    def valuation_series(self, symbol: str, end, lookback_years: int = 7) -> pd.DataFrame:
        """Continuous P/E, P/B, EV/EBITDA up to `end` (no look-ahead).
        Columns: [date, pe, pb, ev_ebitda]. Trailing `lookback_years` only.

        STUB until the valuation_series table is populated. The recommended way
        to fill it: derive multiples from prices (you have them) x fundamentals
        (you must pull) — see equinext/data/valuation.py.
        """
        return valuation.read_valuation_series(symbol, end, lookback_years)

    def fundamentals(self, symbol: str, as_of) -> dict:
        """PIT fundamentals as known at `as_of` (from the snapshot store).

        Pre-snapshot history is RESTATED => directional only (flag this).
        STUB until the fundamentals_snapshot table is populated by the monthly
        screener job — see equinext/data/snapshot.py.
        """
        return snapshot.read_fundamentals(symbol, as_of)

    # ---- convenience helpers the backtest harness uses (not basket-facing) ----
    def price_matrix(self) -> pd.DataFrame:
        return prices.price_matrix()

    def benchmark_returns(self, start, end, index_name: str = "NIFTY500") -> pd.Series:
        close = prices.load_benchmark(index_name, start, end)
        return close.pct_change(fill_method=None).dropna()
