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


_EXPENSIVE_WHEN_HIGH = ("pe", "pb", "ev_ebitda")   # higher multiple = richer
_EXPENSIVE_WHEN_LOW = ("fcf_yield",)               # higher yield = cheaper (invert)


def valuation_froth_percentile(vdf: pd.DataFrame, end, years: int = 5,
                               min_obs: int = 60) -> float:
    """Composite own-history 'expensiveness' percentile (0-1) across whatever
    multiples are populated for this name. 0 = cheapest vs its own history on
    every available multiple; 1 = richest. Financials contribute pe+pb only;
    fcf_yield is inverted (high yield = cheap). nan if nothing usable.

    This is the froth GATE for valuation-momentum: momentum ranks, this filters
    out names trading rich vs their own past.
    """
    s = vdf.copy()
    s["date"] = pd.to_datetime(s["date"])
    s = s.set_index("date").sort_index()
    pctiles = []
    for col in _EXPENSIVE_WHEN_HIGH:
        if col in s.columns:
            ser = pd.to_numeric(s[col], errors="coerce").dropna()
            if len(ser) >= min_obs:
                p = valuation_percentile(ser, end, years)
                if not np.isnan(p):
                    pctiles.append(p)
    for col in _EXPENSIVE_WHEN_LOW:
        if col in s.columns:
            ser = pd.to_numeric(s[col], errors="coerce").dropna()
            if len(ser) >= min_obs:
                p = valuation_percentile(ser, end, years)
                if not np.isnan(p):
                    pctiles.append(1.0 - p)     # high yield -> low expensiveness
    return float(np.mean(pctiles)) if pctiles else np.nan


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


def return_over(close: pd.Series, end, months: int) -> float:
    """Simple price return over the trailing `months` window ending `end`."""
    end = pd.Timestamp(end)
    s = close[close.index <= end].dropna()
    if s.empty:
        return np.nan
    p_now = s.asof(end)
    p_then = s.asof(end - pd.Timedelta(days=int(months * 30.44)))
    if not p_then or np.isnan(p_then) or not p_now or np.isnan(p_now):
        return np.nan
    return float(p_now / p_then - 1)


def distance_from_high(close: pd.Series, end, weeks: int = 52) -> float:
    """Where the latest close sits vs its trailing `weeks`-high, in [0, 1].
    1.0 = at a new high; 0.85 = 15% below the high. Grinblatt-Han's 52-week-high
    anchoring signal — nearness to the high predicts continuation. Higher = stronger.
    """
    end = pd.Timestamp(end)
    s = close[close.index <= end].dropna()
    s = s[s.index >= end - pd.Timedelta(weeks=weeks)]
    if s.empty:
        return np.nan
    hi = s.max()
    return float(s.iloc[-1] / hi) if hi else np.nan


def volume_trend(volume: pd.Series, end, short: int = 21, long: int = 126) -> float:
    """Ratio of recent (short) to baseline (long) average volume, minus 1.
    Positive = participation is picking up (confirms a move); ~0 = steady.
    The one momentum signal roughly orthogonal to price momentum.
    """
    end = pd.Timestamp(end)
    v = volume[volume.index <= end].dropna()
    if len(v) < long:
        return np.nan
    s, l = v.iloc[-short:].mean(), v.iloc[-long:].mean()
    return float(s / l - 1) if l else np.nan


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
