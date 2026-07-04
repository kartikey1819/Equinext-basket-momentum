"""
Metrics — the one standard set, computed identically for all three baskets.
Returns a flat dict so the joint side-by-side table is a simple concat.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def compute_metrics(returns: pd.Series, benchmark: pd.Series,
                    after_tax: pd.Series | None = None) -> dict:
    returns = returns.dropna()
    benchmark = benchmark.reindex(returns.index).fillna(0.0)

    def cagr(r):
        r = r.dropna()
        return (1 + r).prod() ** (252 / len(r)) - 1 if len(r) else np.nan

    def vol(r):
        return r.std() * np.sqrt(252)

    def sharpe(r):
        v = vol(r)
        return cagr(r) / v if v else np.nan

    def sortino(r):
        dn = r[r < 0].std() * np.sqrt(252)
        return cagr(r) / dn if dn else np.nan

    def max_dd(r):
        c = (1 + r).cumprod()
        return float((c / c.cummax() - 1).min())

    excess = returns - benchmark
    up = benchmark[benchmark > 0]
    dn = benchmark[benchmark < 0]
    return {
        "cagr": cagr(returns),
        "cagr_after_tax": cagr(after_tax) if after_tax is not None else None,
        "vol": vol(returns),
        "sharpe": sharpe(returns),
        "sortino": sortino(returns),
        "max_drawdown": max_dd(returns),
        "up_capture": (returns[benchmark > 0].mean() / up.mean()) if len(up) else np.nan,
        "down_capture": (returns[benchmark < 0].mean() / dn.mean()) if len(dn) else np.nan,
        "hit_rate_1y": float((excess.rolling(252).sum() > 0).mean()),
        # turnover + tax drag are filled from BacktestResult by the caller
    }
