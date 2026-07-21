"""
Equinext V2 — the multi-tier, multi-signal engine (a NEW basket; existing baskets are
untouched). Layers on top of the valuation-momentum funnel:

  L1  cap tiers        Large / Mid / Small by market-cap rank (price-scaled proxy)
  L2  selection        froth + earnings + 200-DMA trend + multi-TF momentum + RSI-extreme,
                       ranked by momentum, inverse-vol weighted, per tier
  L3  cap-tier dial     large-cap CORE + mid/small SATELLITE; satellite scaled by regime
  (L4 asset dial + L5 caps are applied by the runner / base class as before)

Every gate/tier is a config flag so the ablation can turn them on one at a time. The
tier split is either fixed (mode A) or regime-scaled (mode B).
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

import pandas as pd

from equinext.backtest import Selection
from equinext.data import prices
from baskets.valuation_momentum import VMTotalMarket50, cap_weights

_PROJECT_DB = Path(__file__).resolve().parents[1] / "equinext.db"


class TierMap:
    """Assigns Large / Mid / Small by market-cap rank as-of a date. Point-in-time mcap
    isn't available, so we approximate: implied_shares = current_mcap / current_price
    (assumed ~constant), then mcap(t) = implied_shares x price(t). That makes a stock
    that was cheaper (smaller) in the past rank lower back then — far better than using a
    single static current-mcap snapshot. Flagged as an approximation to refine later."""

    def __init__(self, ctx, bounds=(100, 250, 500)):
        self.bounds = bounds
        con = sqlite3.connect(str(_PROJECT_DB))
        mc = pd.read_sql("SELECT symbol, mcap FROM securities", con)
        con.close()
        mc = pd.to_numeric(mc.set_index("symbol")["mcap"], errors="coerce").dropna()
        self.pxf = ctx.price_matrix().ffill()         # forward-filled: last known price per stock
        last = self.pxf.iloc[-1]
        self.shares = {s: float(mc[s] / last[s]) for s in mc.index
                       if s in last.index and pd.notna(last[s]) and last[s] > 0 and mc[s] > 0}

    def assign(self, as_of, syms) -> dict:
        rows = self.pxf.loc[self.pxf.index <= pd.Timestamp(as_of)]
        if rows.empty:
            return {}
        p = rows.iloc[-1]
        mcap_t = {s: self.shares[s] * p[s] for s in syms
                  if s in self.shares and s in p.index and pd.notna(p[s])}
        ranked = sorted(mcap_t, key=lambda s: -mcap_t[s])
        b1, b2, b3 = self.bounds
        if max(self.bounds) <= 1.0:                   # fractional bounds -> scale to universe size
            n = len(ranked)
            b1, b2, b3 = int(b1 * n), int(b2 * n), int(b3 * n)
        return {s: ("L" if i < b1 else "M" if i < b2 else "S" if i < b3 else "X")
                for i, s in enumerate(ranked)}


class EquinextV2(VMTotalMarket50):
    """Total-Market valuation-momentum + trend/multi-TF/RSI gates + cap-tiers + regime
    satellite dial + 25% sector cap + 8% stock cap. Config-driven for the ablation."""
    name = "equinext_v2"

    # L2 gates (default = full strategy on; the ablation driver flips these per step)
    USE_TREND_GATE = True
    USE_MULTI_TF = True
    RSI_MAX = 80
    RSI_WINDOW = 30
    RSI_SOFT = False

    # L5 caps
    SECTOR_WEIGHT_CAP = 0.25
    MAX_STOCK_WEIGHT = 0.08

    # L1 / L3 cap-tiers
    USE_TIERS = True
    TIER_MODE = "B"                       # "A" fixed split / "B" regime-scaled satellite
    TIER_BOUNDS = (100, 250, 500)         # Large<=100, Mid<=250, Small<=500 by mcap rank
    FIXED_SPLIT = (0.50, 0.30, 0.20)      # (L, M, S) for mode A
    SMALL_CAP_MAX = 0.20                  # hard ceiling on small-cap share of equity
    N_TIER = {"L": 20, "M": 15, "S": 15}  # top-N momentum names per tier
    #                     risk-off      neutral        risk-on
    SPLITS_B = {0: (1.00, 0.00, 0.00), 1: (0.70, 0.20, 0.10), 2: (0.45, 0.35, 0.20)}
    # Mode C — FIXED large-cap anchor + satellite that rotates to whichever of mid/small
    # has stronger trailing momentum (the user's design).
    LARGE_ANCHOR = 0.40        # fixed large-cap weight
    SATELLITE_TILT = 1.0       # 1.0 = hard switch (100% of satellite to the winner); 0.70 = soft 70/30
    MOM_MONTHS = 6             # mid-vs-small relative-momentum lookback (months)

    _tiermap = None                       # lazily built, shared across instances

    def _get_tiermap(self, ctx) -> TierMap:
        if EquinextV2._tiermap is None or EquinextV2._tiermap.bounds != tuple(self.TIER_BOUNDS):
            EquinextV2._tiermap = TierMap(ctx, tuple(self.TIER_BOUNDS))
        return EquinextV2._tiermap

    def _regime_score(self, as_of, ctx) -> int:
        """0 = risk-off, 1 = neutral, 2 = risk-on, from the index's 200-DMA trend + 6-mo
        absolute momentum (same logic the asset dial uses)."""
        idx = prices.load_benchmark("NIFTY500", as_of - pd.Timedelta(days=460), as_of).dropna()
        if len(idx) < 200:
            return 2
        trend = int(idx.iloc[-1] > idx.rolling(200).mean().iloc[-1])
        p6 = idx.asof(pd.Timestamp(as_of) - pd.Timedelta(days=182))
        absmom = int(pd.notna(p6) and (idx.iloc[-1] / p6 - 1) > 0)
        return trend + absmom

    def _tier_mom(self, as_of, syms, tm) -> float:
        """Median trailing MOM_MONTHS return of a tier's constituents — a cap-tier index
        proxy (we have no Nifty Midcap/Smallcap index, so build it from our own stocks)."""
        if not syms:
            return -1e9
        pxf = tm.pxf
        now_rows = pxf.loc[pxf.index <= pd.Timestamp(as_of)]
        then_rows = pxf.loc[pxf.index <= pd.Timestamp(as_of) - pd.Timedelta(days=int(self.MOM_MONTHS * 30.44))]
        if now_rows.empty or then_rows.empty:
            return -1e9
        p_now, p_then = now_rows.iloc[-1], then_rows.iloc[-1]
        rets = [p_now[s] / p_then[s] - 1 for s in syms
                if s in p_now.index and s in p_then.index and pd.notna(p_now[s]) and pd.notna(p_then[s]) and p_then[s] > 0]
        return float(pd.Series(rets).median()) if rets else -1e9

    def _tier_weights(self, as_of, ctx, tier_syms=None, tm=None) -> dict:
        if self.TIER_MODE == "A":
            L, M, S = self.FIXED_SPLIT
            S = min(S, self.SMALL_CAP_MAX)
            L = max(0.0, 1.0 - M - S)
        elif self.TIER_MODE == "B":
            L, M, S = self.SPLITS_B[self._regime_score(as_of, ctx)]
            S = min(S, self.SMALL_CAP_MAX)
            L = max(0.0, 1.0 - M - S)
        else:  # mode C: fixed large anchor + mid<->small rotation by relative momentum
            L = self.LARGE_ANCHOR
            sat = 1.0 - L
            mid_m = self._tier_mom(as_of, (tier_syms or {}).get("M", []), tm)
            small_m = self._tier_mom(as_of, (tier_syms or {}).get("S", []), tm)
            t = self.SATELLITE_TILT
            M, S = (sat * t, sat * (1 - t)) if mid_m >= small_m else (sat * (1 - t), sat * t)
            S = min(S, self.SMALL_CAP_MAX)          # liquidity ceiling; overflow -> mid, large stays fixed
            M = sat - S
        return {"L": L, "M": M, "S": S}

    def select(self, as_of, ctx) -> Selection:
        as_of = pd.Timestamp(as_of)
        if not self.USE_TIERS:
            return super().select(as_of, ctx)            # single-pool path (baseline)

        uni = list(self._universe(as_of, ctx))
        tm = self._get_tiermap(ctx)
        tiers = tm.assign(as_of, uni)
        tier_syms = {t: [s for s in uni if tiers.get(s) == t] for t in ("L", "M", "S")}
        tw = self._tier_weights(as_of, ctx, tier_syms, tm)
        combined, scores = {}, {}
        for t in ("L", "M", "S"):
            if tw[t] <= 0 or not tier_syms[t]:
                continue
            w, sc = self._select_pool(tier_syms[t], as_of, ctx, self.N_TIER[t])
            for s, x in w.items():
                combined[s] = combined.get(s, 0.0) + tw[t] * x
            scores.update(sc)

        tot = sum(combined.values())
        if tot <= 0:
            raise ValueError(f"equinext_v2: empty book at {as_of.date()}")
        combined = {s: x / tot for s, x in combined.items()}   # renormalize (empty tiers)
        if self.SECTOR_WEIGHT_CAP is not None or self.MAX_STOCK_WEIGHT is not None:
            combined = cap_weights(combined, lambda s: ctx.sector(s),
                                   self.SECTOR_WEIGHT_CAP, self.MAX_STOCK_WEIGHT)
        sel = Selection(as_of=as_of.date(), weights=combined,
                        scores={s: scores.get(s, 0.0) for s in combined})
        sel.validate()
        return sel


class EquinextV2N500(EquinextV2):
    """The full multi-layer V2 strategy on the Nifty 500 universe (froth/earnings gates
    ON, since these names have valuation history)."""
    name = "equinext_v2_n500"

    def _universe(self, as_of, ctx):
        from equinext.universe import standard_universe, _pool
        return standard_universe(as_of, _pool("n500_current"))


class EquinextV2RC(EquinextV2):
    """The full multi-layer V2 strategy run on RupeeCase's own ~240 published stocks.
    Momentum-only (their universe has no valuation history), so the froth/earnings gates
    are off; everything else (200-DMA trend + multi-TF + RSI + cap-tiers + regime dial +
    25% sector cap + 8% stock cap) is on. Survivorship-tilted like the other RC baskets."""
    name = "equinext_v2_rc"
    USE_GATES = False                     # RC stocks are momentum-only (no valuation history)

    def _universe(self, as_of, ctx):
        from equinext.universe import standard_universe, _pool
        return standard_universe(as_of, _pool("rupeecase"))
