"""
Scoring — winsorize, z-score, sector-neutral z-score, composite.

This is how raw factors (ROCE, debt/equity, ...) become one comparable score.
QARP's quality leg lives on sector_neutral_zscore + composite.
"""
from __future__ import annotations
import pandas as pd


def winsorize(s: pd.Series, lo: float = 0.01, hi: float = 0.99) -> pd.Series:
    """Clip a column to its [lo, hi] quantiles to tame outliers."""
    return s.clip(s.quantile(lo), s.quantile(hi))


def zscore(s: pd.Series) -> pd.Series:
    sd = s.std()
    if not sd:
        return s * 0.0
    return (s - s.mean()) / sd


def sector_neutral_zscore(df: pd.DataFrame, col: str, sector_col: str = "sector") -> pd.Series:
    """Z-score WITHIN sector. Use for quality factors (else you get an accidental
    FMCG/IT bet). Do NOT use for theme/sector baskets.
    """
    def _z(v: pd.Series) -> pd.Series:
        sd = v.std()
        return v * 0.0 if not sd else (v - v.mean()) / sd
    return df.groupby(sector_col)[col].transform(_z)


def composite(df: pd.DataFrame, cols: list[str], higher_is_better: list[bool],
              weights: list[float] | None = None) -> pd.Series:
    """Combine several factors into one z-scored composite. Flip sign where lower
    is better. Each factor is winsorized then z-scored before combining.
    """
    weights = weights or [1.0] * len(cols)
    parts = []
    for c, hib, w in zip(cols, higher_is_better, weights):
        z = zscore(winsorize(df[c]))
        parts.append((z if hib else -z) * w)
    return sum(parts) / sum(weights)
