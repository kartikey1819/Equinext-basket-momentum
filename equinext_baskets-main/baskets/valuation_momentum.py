"""
Intern 3 — Valuation-Momentum (Durable Re-Raters).   <-- THE target basket.

Ride momentum, but only where it is earnings-backed, and refuse to pay frothy
prices. Four steps, combined as MOMENTUM RANKS / VALUATION GATES:

  Step 1  Universe   — ctx.universe() (liquidity + free-float + listing gates).
  Step 2  Valuation  — composite own-history froth percentile across pe, pb,
                       ev_ebitda, fcf_yield (whatever a name has). Used as a
                       GATE: drop the expensive extreme (froth > FROTH_MAX).
  Step 3  Momentum   — cross-sectional composite z of 12-1 return, distance from
                       52-week high, volume trend. This RANKS the survivors.
  Step 4  Decomp     — rerating_decomposition over the last 12m: drop names whose
                       rise is mostly multiple-expansion (froth) rather than
                       earnings. Keeps the durable re-raters.

Then: top N_HOLD by momentum, inverse-vol weighted. Rebalance cadence + no-trade
band are set by the RUNNER (this is the turnover-tax basket) — see BacktestConfig.

DATA NOTE: valuation history starts ~2023 (Yahoo gives few annual statements),
so froth/decomp gates only bite once a name has enough multiples history; before
that a name is treated as ungated (momentum-only). Flagged in write-ups.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from equinext.backtest import Basket, Selection
from equinext.scoring import composite
from equinext.primitives import (
    momentum_12_1, distance_from_high, volume_trend, realized_vol,
    return_over, valuation_froth_percentile, rerating_decomposition,
)

FROTH_MAX = 0.80          # drop names richer than this own-history percentile
N_HOLD = 15               # top momentum names held (universe ~49)
N_MIN = 8                 # if gates leave fewer than this, relax the froth gate
LOOKBACK_DAYS = 800       # ~2y+ of price history for momentum/vol
MIN_VAL_OBS = 60          # valuation rows before froth/decomp gates apply


class ValuationMomentumBasket(Basket):
    name = "valuation_momentum"
    USE_GATES = True          # False -> momentum-only ablation (see MomentumOnlyBasket)

    def select(self, as_of, ctx) -> Selection:
        as_of = pd.Timestamp(as_of)
        rows = []
        for sym in ctx.universe(as_of):
            ohlcv = ctx.ohlcv(sym, as_of - pd.Timedelta(days=LOOKBACK_DAYS), as_of)
            if ohlcv.empty:
                continue
            ohlcv = ohlcv.set_index("date")
            close, vol = ohlcv["close"].dropna(), ohlcv["volume"].dropna()
            if len(close) < 200:
                continue

            mom = momentum_12_1(close, as_of)
            if not np.isfinite(mom):
                continue
            dh = distance_from_high(close, as_of, 52)
            vt = volume_trend(vol, as_of)
            rv = realized_vol(close, as_of)
            if not np.isfinite(rv) or rv <= 0:
                continue

            # --- valuation froth + earnings-backing (only if we have history) ---
            froth, earnings_backed = np.nan, True
            try:
                vdf = ctx.valuation_series(sym, end=as_of, lookback_years=7)
            except NotImplementedError:
                vdf = None
            if vdf is not None and len(vdf) >= MIN_VAL_OBS:
                froth = valuation_froth_percentile(vdf, as_of)
                eps = pd.to_numeric(
                    vdf.assign(date=pd.to_datetime(vdf["date"])).set_index("date")["eps_ttm"],
                    errors="coerce").dropna() if "eps_ttm" in vdf.columns else pd.Series(dtype=float)
                g = _growth(eps, as_of, months=12)
                pr = return_over(close, as_of, 12)
                # need both > -100% for the log decomposition to be defined
                if np.isfinite(g) and np.isfinite(pr) and g > -0.99 and pr > -0.99:
                    e_con, m_con = rerating_decomposition(pr, g)
                    if np.isfinite(e_con) and np.isfinite(m_con):
                        earnings_backed = (e_con > 0) and (e_con >= m_con)  # earnings >= froth

            rows.append({"symbol": sym, "mom": mom, "dh": dh, "vt": vt,
                         "vol": rv, "froth": froth, "earnings_backed": earnings_backed})

        df = pd.DataFrame(rows).dropna(subset=["mom", "dh", "vt", "vol"])
        if df.empty:
            raise ValueError(f"valuation_momentum: nothing scoreable at {as_of.date()}.")

        # Step 3: momentum composite (cross-sectional z of the 3 signals) — the RANK
        df["momentum"] = composite(df, ["mom", "dh", "vt"], [True, True, True])

        # Steps 2 & 4: GATES. froth==nan means 'no valuation history yet' -> don't drop.
        if self.USE_GATES:
            gated = df[
                ((df["froth"].isna()) | (df["froth"] <= FROTH_MAX)) & (df["earnings_backed"])
            ]
            pool = gated if len(gated) >= N_MIN else df.sort_values("momentum", ascending=False)
        else:
            pool = df                                       # ablation: momentum-only, no gates

        top = pool.sort_values("momentum", ascending=False).head(N_HOLD)
        inv = 1.0 / top["vol"]                                   # inverse-vol weights
        weights = dict(zip(top["symbol"], inv / inv.sum()))
        scores = dict(zip(top["symbol"], top["momentum"]))

        sel = Selection(as_of=as_of.date(), weights=weights, scores=scores)
        sel.validate()
        return sel


class MomentumOnlyBasket(ValuationMomentumBasket):
    """Ablation twin — identical momentum ranking + inverse-vol weighting, but with
    the valuation & earnings-backing gates DISABLED. Run side-by-side with the
    gated basket over the same window to measure what the gates actually add."""
    name = "momentum_only"
    USE_GATES = False


def _growth(eps: pd.Series, end, months: int = 12) -> float:
    """Trailing earnings growth from the (annual-stepped) eps_ttm series."""
    if eps.empty:
        return np.nan
    end = pd.Timestamp(end)
    now = eps[eps.index <= end]
    then = eps[eps.index <= end - pd.Timedelta(days=int(months * 30.44))]
    if now.empty or then.empty:
        return np.nan
    e0, e1 = float(then.iloc[-1]), float(now.iloc[-1])
    if e0 == 0:
        return np.nan
    return e1 / abs(e0) - 1.0
