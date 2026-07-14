"""
The Basket contract + the shared backtest harness.

Every basket implements ONE method, select(). The harness does everything else
identically for all three: rebalance loop, no-trade bands, transaction costs,
holding-period returns, and FIFO lot tracking for after-tax returns.

The after-tax model here is a first-pass, weight-space approximation (documented
inline). Gross returns are exact; harden the tax model when you have time — the
spec warns FIFO is the fiddly part.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import datetime as dt
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# The contract every basket implements
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Selection:
    """A basket's output for one rebalance date. The standardized contract the
    firm allocator consumes identically across all three baskets."""
    as_of: dt.date
    weights: dict          # symbol -> target weight; MUST sum to 1.0
    scores: dict           # symbol -> driving score, for audit/rationale trail

    def validate(self) -> None:
        assert abs(sum(self.weights.values()) - 1.0) < 1e-6, "weights must sum to 1"
        assert set(self.weights) <= set(self.scores), "every held name needs a score"


class Basket(ABC):
    """Interns subclass this. Implement select(); inherit everything else."""
    name: str = "unnamed"

    @abstractmethod
    def select(self, as_of, ctx) -> Selection:
        """Given a date and the shared data context, return target holdings.
        This is the ONLY method an intern writes — no data-pulling, no scoring
        math reimplemented here. Call into ctx and the shared primitives."""
        ...


# ---------------------------------------------------------------------------
# Backtest config + result
# ---------------------------------------------------------------------------
@dataclass
class BacktestConfig:
    start: dt.date
    end: dt.date
    rebalance: str = "ME"             # month-end (team-wide default)
    cost_bps_per_side: float = 25.0   # brokerage + impact + STT, per side
    stcg_rate: float = 0.20           # short-term capital gains (<1yr)
    ltcg_rate: float = 0.125          # long-term capital gains (>1yr)
    no_trade_band: float = 0.0        # only trade a name beyond this drift; default off


@dataclass
class BacktestResult:
    returns: pd.Series                 # net-of-cost daily returns
    holdings: dict                     # rebalance_date -> {symbol: weight}
    turnover: pd.Series                # traded fraction at each rebalance
    after_tax_returns: pd.Series       # net-of-cost-and-tax daily returns
    scores: dict = field(default_factory=dict)  # rebalance_date -> {symbol: score} (audit trail)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _period_end_trading_days(idx: pd.DatetimeIndex, freq: str = "M") -> pd.DatetimeIndex:
    """Last actual trading day of each period (freq 'M' month / 'Q' quarter)."""
    per = idx.to_period(freq)
    last = pd.Series(idx, index=per).groupby(level=0).last()
    return pd.DatetimeIndex(sorted(last.values))


def _rebalance_dates(idx: pd.DatetimeIndex, rebalance) -> pd.DatetimeIndex:
    """Rebalance dates for a cadence: 'Q' quarterly, 'M' monthly, '2M'/'B' bi-monthly."""
    r = str(rebalance).upper()
    if r.startswith("Q"):
        return _period_end_trading_days(idx, "Q")
    monthly = _period_end_trading_days(idx, "M")
    if r.startswith("2") or r.startswith("B"):   # bi-monthly = every 2nd month-end
        return monthly[::2]
    return monthly


def _apply_no_trade_band(current: pd.Series, target: pd.Series, band: float) -> pd.Series:
    """Keep the prior weight on any name whose target moved less than `band`."""
    if band <= 0 or current.empty:
        return target
    syms = current.index.union(target.index)
    c = current.reindex(syms).fillna(0.0)
    t = target.reindex(syms).fillna(0.0)
    keep = (t - c).abs() < band
    t[keep] = c[keep]
    s = t.sum()
    if s:
        t = t / s
    return t[t.abs() > 1e-12]


def _price_on(px: pd.DataFrame, sym: str, d: pd.Timestamp) -> float:
    if sym not in px.columns:
        return np.nan
    return float(px[sym].asof(d))


def _update_lots_and_tax(lots: dict, c: pd.Series, t: pd.Series, d: pd.Timestamp,
                         px: pd.DataFrame, cfg: BacktestConfig) -> float:
    """FIFO lot tracking. On weight DECREASES, realize gains and accrue tax;
    on INCREASES, open a new lot. Gains are expressed as a FRACTION OF NAV
    (weights are fractions of NAV), so the returned tax is a NAV-fraction drag.
    """
    tax = 0.0
    for sym in c.index.union(t.index):
        cw, tw = float(c.get(sym, 0.0)), float(t.get(sym, 0.0))
        price = _price_on(px, sym, d)
        if np.isnan(price) or price <= 0:
            continue
        if tw > cw + 1e-12:                       # buy
            lots.setdefault(sym, []).append([pd.Timestamp(d), tw - cw, price])
        elif cw > tw + 1e-12:                     # sell, FIFO
            sell = cw - tw
            q = lots.get(sym, [])
            while sell > 1e-12 and q:
                lot = q[0]
                take = min(lot[1], sell)
                gain_frac = take * (1 - lot[2] / price)        # vs current NAV
                held_days = (pd.Timestamp(d) - lot[0]).days
                rate = cfg.ltcg_rate if held_days > 365 else cfg.stcg_rate
                tax += rate * max(gain_frac, 0.0)
                lot[1] -= take
                sell -= take
                if lot[1] <= 1e-12:
                    q.pop(0)
    return tax


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------
def run_backtest(basket: Basket, ctx, cfg: BacktestConfig) -> BacktestResult:
    px = ctx.price_matrix()
    start, end = pd.Timestamp(cfg.start), pd.Timestamp(cfg.end)
    px = px.loc[(px.index >= start) & (px.index <= end)]
    days = px.index
    if len(days) == 0:
        raise ValueError("No trading days in the backtest window.")
    daily_ret = px.pct_change(fill_method=None)
    rebal_dates = _rebalance_dates(days, cfg.rebalance)

    returns = pd.Series(index=days, dtype=float)
    after_tax = pd.Series(index=days, dtype=float)
    holdings: dict = {}
    turnover_rec: dict = {}
    scores_rec: dict = {}
    current = pd.Series(dtype=float)
    lots: dict = {}

    for i, d in enumerate(rebal_dates):
        sel = basket.select(d, ctx)
        sel.validate()
        target = pd.Series(sel.weights, dtype=float)
        target = _apply_no_trade_band(current, target, cfg.no_trade_band)

        syms = current.index.union(target.index)
        c = current.reindex(syms).fillna(0.0)
        t = target.reindex(syms).fillna(0.0)
        traded = float((t - c).abs().sum())                 # both sides
        cost = cfg.cost_bps_per_side / 1e4 * traded
        tax = _update_lots_and_tax(lots, c, t, d, px, cfg)

        turnover_rec[d] = traded
        holdings[d] = dict(sel.weights)
        scores_rec[d] = dict(sel.scores)
        current = t[t.abs() > 1e-12]

        # accrue daily returns until the next rebalance (weights drift with prices)
        end_d = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else days[-1]
        period = days[(days > d) & (days <= end_d)]
        if len(period) == 0 or current.empty:
            continue
        w = current.copy()
        first = True
        for day in period:
            r = daily_ret.loc[day, w.index].fillna(0.0)
            port_r = float((w * r).sum())
            charge = (cost if first else 0.0)
            returns.loc[day] = port_r - charge
            after_tax.loc[day] = port_r - charge - (tax if first else 0.0)
            w = w * (1 + r)
            sm = w.sum()
            if sm:
                w = w / sm
            first = False

    returns = returns.dropna()
    after_tax = after_tax.reindex(returns.index)
    return BacktestResult(
        returns=returns,
        holdings=holdings,
        turnover=pd.Series(turnover_rec),
        after_tax_returns=after_tax,
        scores=scores_rec,
    )
