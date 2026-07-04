"""
Intern 2 — Quality at Reasonable Price (QARP).   <-- this is YOUR basket.

Own good businesses, but refuse to overpay:
  - Quality composite (sector-neutral z-score of ROCE, ROE, low D/E, interest
    cover, earnings stability, accruals = CFO/PAT).
  - Valuation gate: drop names in their expensive extreme (own valuation
    percentile above ~0.70). Valuation FILTERS; quality RANKS.
  - Take top 25-30 by quality, weight inverse-volatility.

STATUS: this skeleton is wired to the library and will RUN AS-IS the moment the
fundamentals_snapshot + valuation_series tables are populated. Until then
ctx.fundamentals() raises a clear "no data yet" error — that's expected.

Two factors still need derivation from snapshot HISTORY (marked TODO):
earnings_stability and (optionally) a cleaner accruals measure.
"""
from __future__ import annotations
import pandas as pd

from equinext.backtest import Basket, Selection
from equinext.primitives import valuation_percentile, realized_vol
from equinext.scoring import sector_neutral_zscore

# (fundamentals key, higher_is_better)
QUALITY_FACTORS = [
    ("roce", True), ("roe", True), ("debt_equity", False),
    ("interest_cover", True), ("earnings_stability", True), ("accruals", True),
]
EXPENSIVE_PERCENTILE = 0.70   # drop names richer than this vs their own history
N_HOLD = 30


class QARPBasket(Basket):
    name = "qarp"

    def select(self, as_of, ctx) -> Selection:
        rows = []
        for sym in ctx.universe(as_of):
            f = ctx.fundamentals(sym, as_of)                      # PIT snapshot
            pe = ctx.valuation_series(sym, end=as_of)["pe"]
            close = ctx.ohlcv(sym, as_of.replace(year=as_of.year - 1), as_of)
            close = close.set_index("date")["close"]
            rows.append({
                "symbol": sym,
                "sector": ctx.sector(sym),
                "roce": f.get("roce"),
                "roe": f.get("roe"),
                "debt_equity": f.get("debt_equity"),
                "interest_cover": f.get("interest_cover"),
                # TODO: derive earnings_stability from snapshot history (low EPS-growth vol)
                "earnings_stability": f.get("earnings_stability"),
                "accruals": (f["cfo"] / f["pat"]) if f.get("pat") else None,
                "val_pctile": valuation_percentile(pe, as_of),
                "vol": realized_vol(close, as_of),
            })

        df = pd.DataFrame(rows).dropna()

        # quality composite: sector-neutral z of each factor, sign-flipped where low is better
        parts = []
        for col, higher_is_better in QUALITY_FACTORS:
            z = sector_neutral_zscore(df, col)
            parts.append(z if higher_is_better else -z)
        df["quality"] = sum(parts) / len(parts)

        # valuation discipline: drop the expensive extreme
        df = df[df["val_pctile"] <= EXPENSIVE_PERCENTILE]

        top = df.sort_values("quality", ascending=False).head(N_HOLD)

        inv = 1.0 / top["vol"]                                    # inverse-vol weights
        weights = dict(zip(top["symbol"], inv / inv.sum()))
        scores = dict(zip(top["symbol"], top["quality"]))

        sel = Selection(as_of=as_of, weights=weights, scores=scores)
        sel.validate()
        return sel
