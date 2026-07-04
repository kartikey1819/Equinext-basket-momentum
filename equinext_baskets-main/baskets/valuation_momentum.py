"""
Intern 3 — Valuation-Momentum (Durable Re-Raters).

Ride momentum, but only where it is earnings-backed (use the re-rating
decomposition), and filter out froth (extreme own-history valuation percentile).

SKELETON: fill in select(). Uses only ctx + shared primitives.
"""
from __future__ import annotations
from equinext.backtest import Basket, Selection
from equinext.primitives import momentum_12_1, valuation_percentile, rerating_decomposition


class ValuationMomentumBasket(Basket):
    name = "valuation_momentum"

    def select(self, as_of, ctx) -> Selection:
        # TODO (Intern 3):
        #   for sym in ctx.universe(as_of):
        #     close = ctx.ohlcv(sym, <2y back>, as_of).set_index("date")["close"]
        #     mom = momentum_12_1(close, as_of)
        #     pe  = ctx.valuation_series(sym, end=as_of)["pe"]
        #     val_pctile = valuation_percentile(pe, as_of)
        #     e, m = rerating_decomposition(<window return>, <earnings growth>)  # earnings vs froth
        #   drop frothy (val_pctile high), tilt to earnings-backed momentum,
        #   take top 25-30, weight equal or by momentum, return Selection.
        #   NOTE: this is also the turnover-tax basket — sweep cadence + no-trade bands.
        raise NotImplementedError("Valuation-Momentum select() — Intern 3 to implement.")
