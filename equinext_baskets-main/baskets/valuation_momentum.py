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
    trend_above_ma, rsi_wilder, multi_tf_aligned,
)

FROTH_MAX = 0.80          # drop names richer than this own-history percentile
N_HOLD = 15               # top momentum names held (universe ~49)
N_MIN = 8                 # if gates leave fewer than this, relax the froth gate
LOOKBACK_DAYS = 800       # ~2y+ of price history for momentum/vol
MIN_VAL_OBS = 60          # valuation rows before froth/decomp gates apply

# Opt-in per-stock scoring cache (used only by _CACHE_ROWS baskets, e.g. the v2 ablation,
# so the same (stock, date) isn't re-scored across configs). Existing baskets never touch it.
_ROW_CACHE: dict = {}


# --------------------------------------------------------------------------- #
# Hard sector / stock weight caps (capped-index waterfall)
# --------------------------------------------------------------------------- #
def _waterfall(w0: dict, group_of, cap: float, tol: float = 1e-12, max_iter: int = 200) -> dict:
    """Cap each GROUP's total weight at `cap` by iterative proportional redistribution
    (the 'capped index' method). Overflow from an over-cap group is pushed to the
    under-cap groups in proportion to their original weight; within a group, members keep
    their relative proportions. Caps the single most-over group each pass (monotone, so it
    always terminates). If the cap is infeasible (cap x #groups < 1) it relaxes to an equal
    split. Returns weights summing to 1."""
    orig = {s: float(x) for s, x in w0.items()}
    groups: dict = {}
    for s in orig:
        groups.setdefault(group_of(s) or "Unknown", []).append(s)
    G = list(groups)
    capped: set = set()
    for _ in range(max_iter):
        unc = [g for g in G if g not in capped]
        if not unc:
            break
        remaining = 1.0 - cap * len(capped)
        denom = sum(orig[s] for g in unc for s in groups[g])
        if denom <= tol:
            break
        worst, worst_val = None, cap + tol
        for g in unc:
            g_tot = remaining * sum(orig[s] for s in groups[g]) / denom
            if g_tot > worst_val:
                worst, worst_val = g, g_tot
        if worst is None:
            break                                   # no uncapped group exceeds the cap
        capped.add(worst)                           # freeze the most-over group, recompute
    remaining = 1.0 - cap * len(capped)
    unc = [g for g in G if g not in capped]
    denom = sum(orig[s] for g in unc for s in groups[g]) if unc else 0.0
    out: dict = {}
    for g in G:
        g_orig = sum(orig[s] for s in groups[g])
        g_tot = cap if g in capped else (remaining * g_orig / denom if denom > tol else 0.0)
        for s in groups[g]:
            out[s] = g_tot * (orig[s] / g_orig) if g_orig > tol else g_tot / len(groups[g])
    tot = sum(out.values())
    return {s: x / tot for s, x in out.items()} if tot > tol else dict(w0)


def cap_weights(weights: dict, sector_of, sector_cap=None, stock_cap=None,
                max_iter: int = 500, tol: float = 1e-12) -> dict:
    """Apply a hard sector-weight cap AND/OR per-stock cap to inverse-vol weights, jointly
    (both hold on exit when feasible). Each round: clip any over-cap stock and any over-cap
    sector, then redistribute the freed weight only to names that still have room in BOTH
    dimensions — proportional to their weight, so within-sector inverse-vol order is kept.
    Sum stays 1; selection is untouched. If a cap is infeasible (e.g. a 25% sector with < 4
    names under an 8% stock cap) it relaxes gracefully. Matches the pure-sector waterfall
    when only sector_cap is set."""
    if not weights:
        return weights
    t = sum(weights.values())
    if t <= 0:
        return weights
    w = {s: float(x) / t for s, x in weights.items()}
    if sector_cap is None and stock_cap is None:
        return w
    sec = {s: (sector_of(s) or "Unknown") for s in w}
    for _ in range(max_iter):
        excess = 0.0
        if stock_cap is not None:                          # clip over-cap stocks
            for s in w:
                if w[s] > stock_cap + tol:
                    excess += w[s] - stock_cap
                    w[s] = stock_cap
        if sector_cap is not None:                         # clip over-cap sectors (scale their names)
            st: dict = {}
            for s in w:
                st[sec[s]] = st.get(sec[s], 0.0) + w[s]
            for g, tot in st.items():
                if tot > sector_cap + tol:
                    scale = sector_cap / tot
                    for s in w:
                        if sec[s] == g:
                            excess += w[s] * (1.0 - scale)
                            w[s] *= scale
        if excess <= tol:
            break
        # redistribute the freed weight to names with room in BOTH dims, proportional to their
        # remaining STOCK headroom -> a name never overshoots its cap in one step (converges cleanly).
        st = {}
        for s in w:
            st[sec[s]] = st.get(sec[s], 0.0) + w[s]
        room = [s for s in w
                if (stock_cap is None or w[s] < stock_cap - tol)
                and (sector_cap is None or st[sec[s]] < sector_cap - tol)]
        if not room:
            break                                          # jointly infeasible (too few names)
        # weight-proportional when only a sector cap (matches the original waterfall exactly);
        # headroom-proportional when a stock cap is present (so no name overshoots 8%).
        hr = {s: (stock_cap - w[s]) for s in room} if stock_cap is not None else {s: w[s] for s in room}
        tot_hr = sum(hr.values())
        if tot_hr <= tol:
            break
        give = min(excess, tot_hr)
        for s in room:
            w[s] += give * (hr[s] / tot_hr)
    # Infeasible remainder (tiny books where 8% is impossible): place it, then re-enforce the
    # SECTOR cap (the headline promise) via the waterfall — accept the unavoidable stock overflow.
    resid = 1.0 - sum(w.values())
    if resid > tol:
        n = len(w)
        for s in w:
            w[s] += resid / n
        if sector_cap is not None:
            w = _waterfall(w, lambda s: sec[s], sector_cap)
    tot = sum(w.values())
    return {s: x / tot for s, x in w.items()} if tot > tol else dict(weights)


class ValuationMomentumBasket(Basket):
    name = "valuation_momentum"
    USE_GATES = True          # False -> momentum-only ablation (see MomentumOnlyBasket)
    FROTH_MULTIPLES = None     # None = all available (pe/pb/ev_ebitda/fcf); or e.g. ("pe",)
    GROWTH_EXEMPT = None       # None = blunt froth gate. e.g. 0.20 -> a frothy stock is
                               # EXCUSED if its earnings grow >= 20%/yr (growth-adjusted gate)
    FROTH_MAX = FROTH_MAX      # drop names richer than this own-history percentile (sweepable)
    MAX_PER_SECTOR = None      # None = no sector cap. e.g. 3 -> at most 3 names per sector in
                               # the held N_HOLD, so momentum can't pile the book into one sector.
    N_HOLD = N_HOLD            # top-N by momentum held each rebalance (overridable per basket)
    SECTOR_WEIGHT_CAP = None   # None = off. e.g. 0.25 -> no sector may exceed 25% of the book
                               # (hard weight cap via waterfall; keeps the names, tempers sizing).
    MAX_STOCK_WEIGHT = None    # None = off. e.g. 0.08 -> no single stock may exceed 8% of the book.
    # --- v2 selection gates (all OFF by default -> existing baskets are unchanged) ---
    USE_TREND_GATE = False     # True -> keep only stocks above their TREND_MA-day moving average
    TREND_MA = 200
    USE_MULTI_TF = False       # True -> keep only stocks with 3/6/12-mo momentum aligned positive
    RSI_MAX = None             # e.g. 80 -> exclude (or down-weight) names with RSI(RSI_WINDOW) above this
    RSI_WINDOW = 30
    RSI_SOFT = False           # False = hard-exclude RSI>RSI_MAX; True = halve their weight instead
    _CACHE_ROWS = False        # opt-in: cache per-stock scores across configs (ablation speed-up)

    def _universe(self, as_of, ctx):
        """Investable universe for this rebalance. Override for a different universe
        (e.g. point-in-time membership)."""
        return ctx.universe(as_of)

    def _score_one(self, sym, as_of, ctx, force_signals=False):
        """Score one symbol -> row dict (or None if unscoreable). The v2 gate signals
        (trend / multi-TF / RSI) are computed only when their flag is on — or always when
        `force_signals` (so cached rows are config-independent). Existing baskets keep
        their exact behavior."""
        ohlcv = ctx.ohlcv(sym, as_of - pd.Timedelta(days=LOOKBACK_DAYS), as_of)
        if ohlcv.empty:
            return None
        ohlcv = ohlcv.set_index("date")
        close, vol = ohlcv["close"].dropna(), ohlcv["volume"].dropna()
        if len(close) < 200:
            return None

        mom = momentum_12_1(close, as_of)
        if not np.isfinite(mom):
            return None
        dh = distance_from_high(close, as_of, 52)
        vt = volume_trend(vol, as_of)
        rv = realized_vol(close, as_of)
        if not np.isfinite(rv) or rv <= 0:
            return None

        # --- valuation froth + earnings-backing (only if we have history) ---
        froth, earnings_backed, earn_growth = np.nan, True, np.nan
        try:
            vdf = ctx.valuation_series(sym, end=as_of, lookback_years=7)
        except NotImplementedError:
            vdf = None
        if vdf is not None and len(vdf) >= MIN_VAL_OBS:
            froth = valuation_froth_percentile(vdf, as_of, cols=self.FROTH_MULTIPLES)
            eps = pd.to_numeric(
                vdf.assign(date=pd.to_datetime(vdf["date"])).set_index("date")["eps_ttm"],
                errors="coerce").dropna() if "eps_ttm" in vdf.columns else pd.Series(dtype=float)
            g = _growth(eps, as_of, months=12)
            earn_growth = g                       # trailing 12m earnings growth (for growth-adj gate)
            pr = return_over(close, as_of, 12)
            # need both > -100% for the log decomposition to be defined
            if np.isfinite(g) and np.isfinite(pr) and g > -0.99 and pr > -0.99:
                e_con, m_con = rerating_decomposition(pr, g)
                if np.isfinite(e_con) and np.isfinite(m_con):
                    earnings_backed = (e_con > 0) and (e_con >= m_con)  # earnings >= froth

        trend = trend_above_ma(close, as_of, self.TREND_MA) if (force_signals or self.USE_TREND_GATE) else True
        mtf = multi_tf_aligned(close, as_of) if (force_signals or self.USE_MULTI_TF) else True
        rsi = rsi_wilder(close, as_of, self.RSI_WINDOW) if (force_signals or self.RSI_MAX is not None) else np.nan

        return {"symbol": sym, "mom": mom, "dh": dh, "vt": vt, "vol": rv,
                "froth": froth, "earnings_backed": earnings_backed, "earn_growth": earn_growth,
                "trend": trend, "mtf_ok": mtf, "rsi": rsi}

    def _pool_rows(self, symbols, as_of, ctx) -> list:
        """Score all `symbols`. With _CACHE_ROWS, memoize per (stock, date) so repeated
        configs (the ablation) don't re-score — computing all gate signals up front so the
        cache is config-independent."""
        if not self._CACHE_ROWS:
            return [r for r in (self._score_one(s, as_of, ctx) for s in symbols) if r is not None]
        rows = []
        for sym in symbols:
            key = (sym, pd.Timestamp(as_of), self.FROTH_MULTIPLES, self.TREND_MA, self.RSI_WINDOW)
            if key not in _ROW_CACHE:
                _ROW_CACHE[key] = self._score_one(sym, as_of, ctx, force_signals=True)
            r = _ROW_CACHE[key]
            if r is not None:
                rows.append(r)
        return rows

    def _select_pool(self, symbols, as_of, ctx, n_hold) -> tuple[dict, dict]:
        """Score -> gate -> rank -> top-N -> inverse-vol weights for one pool of symbols.
        Returns (weights, scores) BEFORE any sector/stock cap (the cap is applied on the
        final book by select()). Returns ({}, {}) if nothing is scoreable."""
        rows = self._pool_rows(symbols, as_of, ctx)
        if not rows:
            return {}, {}
        df = pd.DataFrame(rows).dropna(subset=["mom", "dh", "vt", "vol"])
        if df.empty:
            return {}, {}

        df["momentum"] = composite(df, ["mom", "dh", "vt"], [True, True, True])

        # Eligibility gates. froth==nan means 'no valuation history yet' -> don't drop.
        elig = pd.Series(True, index=df.index)
        if self.USE_GATES:
            froth_ok = df["froth"].isna() | (df["froth"] <= self.FROTH_MAX)
            if self.GROWTH_EXEMPT is not None:
                exempt = (df["froth"] > self.FROTH_MAX) & (df["earn_growth"] >= self.GROWTH_EXEMPT)
                froth_ok = froth_ok | exempt
            elig &= froth_ok & df["earnings_backed"].astype(bool)
        if self.USE_TREND_GATE:
            elig &= df["trend"].astype(bool)
        if self.USE_MULTI_TF:
            elig &= df["mtf_ok"].astype(bool)
        if self.RSI_MAX is not None and not self.RSI_SOFT:
            elig &= ~(df["rsi"] > self.RSI_MAX)          # nan RSI -> not excluded (starvation guard)
        gated = df[elig]
        pool = gated if len(gated) >= N_MIN else df.sort_values("momentum", ascending=False)

        pool_sorted = pool.sort_values("momentum", ascending=False)
        top = self._pick_top(pool_sorted, ctx, n_hold)
        inv = 1.0 / top["vol"]                                   # inverse-vol weights
        weights = dict(zip(top["symbol"], inv / inv.sum()))
        if self.RSI_MAX is not None and self.RSI_SOFT:          # soft: halve blow-off-top weights
            rmap = dict(zip(top["symbol"], top["rsi"]))
            weights = {s: (w * 0.5 if pd.notna(rmap.get(s)) and rmap[s] > self.RSI_MAX else w)
                       for s, w in weights.items()}
            tot = sum(weights.values())
            weights = {s: w / tot for s, w in weights.items()} if tot else weights
        scores = dict(zip(top["symbol"], top["momentum"]))
        return weights, scores

    def select(self, as_of, ctx) -> Selection:
        as_of = pd.Timestamp(as_of)
        weights, scores = self._select_pool(self._universe(as_of, ctx), as_of, ctx, self.N_HOLD)
        if not weights:
            raise ValueError(f"valuation_momentum: nothing scoreable at {as_of.date()}.")
        if self.SECTOR_WEIGHT_CAP is not None or self.MAX_STOCK_WEIGHT is not None:
            weights = cap_weights(weights, lambda s: ctx.sector(s),
                                  self.SECTOR_WEIGHT_CAP, self.MAX_STOCK_WEIGHT)
        sel = Selection(as_of=as_of.date(), weights=weights, scores=scores)
        sel.validate()
        return sel

    def _pick_top(self, pool_sorted, ctx, n_hold=None):
        """Take the top n_hold by momentum. If MAX_PER_SECTOR is set, walk down the
        momentum ranking and skip a name whose sector is already full — so no single
        sector can dominate the book. If the cap starves us below n_hold (too few
        sectors survived the gates), top up with the next-best momentum names."""
        n_hold = self.N_HOLD if n_hold is None else n_hold
        if self.MAX_PER_SECTOR is None:
            return pool_sorted.head(n_hold)
        picked, sec_count = [], {}
        for sym in pool_sorted["symbol"]:
            sec = ctx.sector(sym) or "Unknown"
            if sec_count.get(sec, 0) < self.MAX_PER_SECTOR:
                picked.append(sym)
                sec_count[sec] = sec_count.get(sec, 0) + 1
            if len(picked) >= n_hold:
                break
        if len(picked) < n_hold:                  # cap starved us -> top up by momentum
            for sym in pool_sorted["symbol"]:
                if sym not in picked:
                    picked.append(sym)
                    if len(picked) >= n_hold:
                        break
        return pool_sorted[pool_sorted["symbol"].isin(picked)]


class MomentumOnlyBasket(ValuationMomentumBasket):
    """Ablation twin — identical momentum ranking + inverse-vol weighting, but with
    the valuation & earnings-backing gates DISABLED. Run side-by-side with the
    gated basket over the same window to measure what the gates actually add."""
    name = "momentum_only"
    USE_GATES = False


class ValuationMomentumPEOnly(ValuationMomentumBasket):
    """Ablation — same strategy but the froth gate uses P/E ONLY (no pb/ev/fcf).
    Race against the full four-multiple basket to see if the extra measures earn
    their place or whether P/E alone suffices."""
    name = "vm_pe_only"
    FROTH_MULTIPLES = ("pe",)


class ValuationMomentumPIT(ValuationMomentumPEOnly):
    """SURVIVORSHIP-FREE twin of vm_pe_only. Identical strategy (P/E froth gate +
    earnings-backed gate + momentum, top 15, inverse-vol, quarterly), but the
    universe at each rebalance is the POINT-IN-TIME top-50-by-market-cap
    reconstruction (current 50 + dropped ex-members) instead of today's fixed 50.
    This includes the 'losers' during the years they were large, removing the
    survivorship bias that flatters the fixed-membership backtest."""
    name = "vm_pit"

    def _universe(self, as_of, ctx):
        from equinext.universe import pit_universe
        return pit_universe(as_of, top_n=50)


class VM500Standard(ValuationMomentumPEOnly):
    """Nifty 500, STANDARD universe (today's 500 constituents applied backward).
    Same strategy as the Nifty-50 baskets; only the universe is broader."""
    name = "vm500"

    def _universe(self, as_of, ctx):
        from equinext.universe import standard_universe, _pool
        return standard_universe(as_of, _pool("n500_current"))


class VM500PIT(ValuationMomentumPEOnly):
    """Nifty 500, POINT-IN-TIME (approximate): top-500 by reconstructed market cap
    from the current 500 + available ex-members. NOTE: a much weaker survivorship
    fix than the Nifty-50 version — most Nifty-500 dropouts delisted and can't be
    sourced, so meaningful residual bias remains. Flagged in write-ups."""
    name = "vm500_pit"

    def _universe(self, as_of, ctx):
        from equinext.universe import pit_universe, _pool
        # reconstruct top-500 by market cap each date from the broader Nifty Total
        # Market pool (~750) — so relegated-but-still-listed ex-members are IN during
        # the years they were large. (Delisted losers still can't be included.)
        return pit_universe(as_of, pool=_pool("n500_pool"), top_n=500)


class VM500Standard50(VM500Standard):
    """Standard Nifty 500 equity engine holding up to 50 momentum names (vs the
    usual 15). Equity sleeve for the fixed-weight 3-asset static allocator."""
    name = "vm500_50"
    N_HOLD = 50


class VMTotalMarket50(VM500Standard50):
    """Equity engine on the FULL Nifty Total Market (~750 stocks we have data for),
    up to 50 momentum names. Same valuation-momentum funnel; only the universe is the
    whole Total-Market pool instead of the Nifty 500."""
    name = "vmtm_50"

    def _universe(self, as_of, ctx):
        from equinext.universe import standard_universe, _pool
        return standard_universe(as_of, _pool("n500_pool"))


class VMTotalMarketMomOnly50(VMTotalMarket50):
    """Momentum-ONLY equity engine on the Nifty Total Market (~750), up to 50 names.
    Identical to VMTotalMarket50 but with the valuation (froth) and earnings-backed
    gates DISABLED — pure momentum ranking, like RupeeCase's equity sleeve. Used to
    measure exactly what our risk-control gates cost vs. an ungated momentum book."""
    name = "vmtm_mom50"
    USE_GATES = False


class VMRupeeCaseUniverse(VMTotalMarketMomOnly50):
    """Momentum-only on RupeeCase's OWN published equity-holdings universe (~240 of
    their actual rebalance stocks that we have prices for). Pure momentum, top 50,
    inverse-vol — 'use their stocks, ranked by momentum'. NOTE: survivorship-tilted,
    since this universe IS the set their momentum eventually rode; return is an
    upper-biased estimate, not a clean forward test."""
    name = "vm_rc_uni"

    def _universe(self, as_of, ctx):
        from equinext.universe import standard_universe, _pool
        return standard_universe(as_of, _pool("rupeecase"))


class VMSectorCapPIT(ValuationMomentumPIT):
    """Equity engine for Equinext Dynamic (Nifty 50). Identical to vm_pit
    (survivorship-free, P/E froth + earnings gate, momentum, inverse-vol) but with a
    max-3-names-per-sector cap so momentum can't concentrate the book in one sector."""
    name = "vm_cap"
    MAX_PER_SECTOR = 3


class VM500SectorCapPIT(VM500PIT):
    """Equity engine for Equinext Dynamic (Nifty 500). vm500_pit + max-3/sector cap."""
    name = "vm500_cap"
    MAX_PER_SECTOR = 3


class ValuationMomentumGrowthAdj(ValuationMomentumBasket):
    """Growth-adjusted froth gate — a frothy stock (P/E above its 0.80 own-history
    percentile) is EXCUSED and kept if its earnings are genuinely growing fast
    (>= 20%/yr), so real re-raters aren't wrongly dropped for legitimate re-rating."""
    name = "vm_growth_adj"
    GROWTH_EXEMPT = 0.20


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
