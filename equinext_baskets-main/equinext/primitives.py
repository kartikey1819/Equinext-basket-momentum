"""
Primitives — the shared maths. Build once; everyone reuses. These functions must
mean the SAME thing to all three interns, so they live here and nowhere else.

All take an `end` date and only look at data on/before it (no look-ahead).
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def _trailing_years(series: pd.Series, end, years: int) -> pd.Series:
    """Slice `series` to the trailing `years` calendar window ending at `end`."""
    end = pd.Timestamp(end)
    cutoff = end - pd.Timedelta(days=int(years * 365))
    s = series[(series.index <= end) & (series.index >= cutoff)]
    return s.dropna()


def trailing_stats(series: pd.Series, end, years: int = 5) -> dict:
    """Median, mean, std of a multiple over the trailing window ending `end`."""
    w = _trailing_years(series, end, years)
    return {"median": w.median(), "mean": w.mean(), "std": w.std()}


def valuation_zscore(series: pd.Series, end, years: int = 5) -> float:
    """How cheap/expensive is TODAY vs the stock's OWN history.
    Negative = cheap vs own history. The spine of the whole project.
    `series` is one multiple (e.g. pe) indexed by date.
    """
    w = _trailing_years(series, end, years)
    if w.empty:
        return np.nan
    cur = w.iloc[-1]
    mu, sd = w.mean(), w.std()
    return float((cur - mu) / sd) if sd and not np.isnan(sd) else np.nan


def valuation_percentile(series: pd.Series, end, years: int = 5) -> float:
    """Percentile rank (0-1) of today's multiple within its own history.
    0 = cheapest it's ever been; 1 = most expensive.
    """
    w = _trailing_years(series, end, years)
    if w.empty:
        return np.nan
    cur = w.iloc[-1]
    return float((w < cur).mean())


def rerating_decomposition(price_return: float, earnings_growth: float) -> tuple[float, float]:
    """Split a holding-period return into earnings-driven vs multiple-driven parts.
    Identity: (1+r) = (1+earnings_growth)*(1+multiple_change).
    Returns (earnings_contribution, multiple_contribution) in LOG terms so they add.
    Durable re-raters: earnings_contribution dominates. Froth: multiple does.
    """
    multiple_change = (1 + price_return) / (1 + earnings_growth) - 1
    e = np.log1p(earnings_growth)
    m = np.log1p(multiple_change)
    return float(e), float(m)


def momentum_12_1(close: pd.Series, end) -> float:
    """12-month return skipping the most recent month (avoids short-term reversal)."""
    end = pd.Timestamp(end)
    s = close[close.index <= end].dropna()
    if s.empty:
        return np.nan
    p_now = s.asof(end - pd.Timedelta(days=30))
    p_then = s.asof(end - pd.Timedelta(days=365))
    if not p_then or np.isnan(p_then) or not p_now or np.isnan(p_now):
        return np.nan
    return float(p_now / p_then - 1)


def realized_vol(close: pd.Series, end, days: int = 252) -> float:
    """Annualised volatility from the last `days` trading observations on/before end."""
    end = pd.Timestamp(end)
    r = close[close.index <= end].pct_change(fill_method=None).dropna()
    r = r.iloc[-days:]
    if r.empty:
        return np.nan
    return float(r.std() * np.sqrt(252))


def trend_above_ma(close: pd.Series, end, ma: int = 200) -> bool:
    """Is the latest close above its `ma`-day moving average (a trend / not-a-falling-knife gate)?"""
    end = pd.Timestamp(end)
    s = close[close.index <= end].dropna()
    if len(s) < ma:
        return False
    return bool(s.iloc[-1] > s.rolling(ma).mean().iloc[-1])
