"""
Intern 1 — Relative Value (Own-History Mean Reversion).

Buy what's cheap vs its OWN history (most negative valuation z-score), confirmed
on more than one multiple, with trap guards (trend gate + quality/leverage gate).

IMPLEMENTATION NOTES (current data reality):
  - valuation_series has P/E only (pb / ev_ebitda are NULL until the loader
    derives them), so the score is the P/E z-score alone. When ev_ebitda lands,
    switch to the average of both z's as the TODO originally sketched.
  - Universe is currently the Nifty 50 (~49 investable), not the Nifty 500, so
    we hold the top 15, not 25-30 — half the index would dilute the signal.
  - Quality/leverage gate needs fundamentals_snapshot (not populated) — the
    trend gate (200DMA) is the only trap guard active. Flag in write-ups.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from equinext.backtest import Basket, Selection
from equinext.primitives import valuation_zscore, trend_above_ma

MIN_PE_OBS = 200        # ~10 months of daily P/E before we trust a z-score
Z_YEARS = 5             # own-history window for the z-score
N_HOLD = 15             # top names held (universe is ~49, not 500)
N_MIN_GATED = 8         # if fewer than this pass the trend gate, relax it


class RelativeValueBasket(Basket):
    name = "relative_value"

    def select(self, as_of, ctx) -> Selection:
        as_of = pd.Timestamp(as_of)
        rows = []
        for sym in ctx.universe(as_of):
            try:
                vs = ctx.valuation_series(sym, end=as_of, lookback_years=Z_YEARS + 2)
            except NotImplementedError:      # no valuation rows for this name yet
                continue
            pe = vs.set_index("date")["pe"].dropna()
            if len(pe) < MIN_PE_OBS:
                continue
            z = valuation_zscore(pe, as_of, years=Z_YEARS)
            if not np.isfinite(z):
                continue
            close = ctx.ohlcv(sym, as_of - pd.Timedelta(days=730), as_of)
            close = close.set_index("date")["close"].dropna()
            rows.append({"symbol": sym, "z": z,
                         "trend_ok": trend_above_ma(close, as_of, 200)})

        df = pd.DataFrame(rows)
        if df.empty:
            raise ValueError(f"relative_value: no scoreable names at {as_of.date()} "
                             "(valuation_series too thin — check the loader).")

        # trend gate (not-a-falling-knife); relax if it guts the pool
        gated = df[df["trend_ok"]]
        pool = gated if len(gated) >= N_MIN_GATED else df

        top = pool.nsmallest(N_HOLD, "z")                 # most negative z = cheapest
        w = 1.0 / len(top)                                # equal weight
        weights = {s: w for s in top["symbol"]}
        scores = dict(zip(top["symbol"], -top["z"]))      # higher = cheaper = better

        sel = Selection(as_of=as_of.date(), weights=weights, scores=scores)
        sel.validate()
        return sel
