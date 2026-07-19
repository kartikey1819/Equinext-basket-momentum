"""
Shared builders for the Dynamic Allocator page data so every variant (Nifty 500,
Total Market, RupeeCase Stocks × both windows) carries the SAME extra fields:

  rebalance_history  -> per-rebalance stock buys/sells (newest first)
  current_holdings   -> the latest equity book (stocks held right now, weighted)
  period_returns     -> trailing 1M/3M/6M/1Y/3Y/5Y/since-inception returns
                        (basket vs Nifty 500 vs Nifty 50) from the daily curve

Used by build_dynamic_page.py and build_rc_baskets.py.
"""
from __future__ import annotations

import pandas as pd

# (label, trailing months) ; None = since inception
PERIODS = [("1 month", 1), ("3 months", 3), ("6 months", 6),
           ("1 year", 12), ("3 years", 36), ("5 years", 60),
           ("Since inception", None)]


def series_json(eq: pd.Series, step: int = 5) -> dict:
    """Downsample a daily equity curve for the web (keep the final point)."""
    e = eq.iloc[::step]
    if len(e) == 0 or e.index[-1] != eq.index[-1]:
        e = pd.concat([e, eq.iloc[[-1]]])
    return {"dates": [d.strftime("%Y-%m-%d") for d in e.index],
            "values": [round(float(v), 2) for v in e.values]}


def bench_curve(ctx, name: str, start, end, idx) -> pd.Series:
    """Benchmark curve (base 100) reindexed onto the strategy's trading days."""
    b = ctx.benchmark_returns(start, end, name).reindex(idx).fillna(0.0)
    return (1 + b).cumprod() * 100


def _name(secs, s):
    return secs.loc[s, "name"] if s in secs.index and pd.notna(secs.loc[s, "name"]) else s


def rebalance_history(holdings: dict, secs) -> list:
    """Per-rebalance stock buys/sells from the equity holdings, newest first."""
    dates = sorted(holdings)
    prev, out = {}, []
    for d in dates:
        cur = holdings[d]
        bought = sorted([s for s in cur if s not in prev])
        sold = sorted([s for s in prev if s not in cur])
        kept = len([s for s in cur if s in prev])
        turnover = sum(abs(cur.get(s, 0) - prev.get(s, 0)) for s in set(cur) | set(prev))
        top = sorted(cur.items(), key=lambda kv: -kv[1])
        out.append({
            "date": str(pd.Timestamp(d).date()),
            "n": len(cur),
            "bought": bought, "sold": sold, "kept": kept,
            "turnover": round(turnover * 100, 1),
            "holdings": [{"sym": s, "weight": round(w * 100, 2), "name": _name(secs, s)}
                         for s, w in top],
        })
        prev = cur
    return out[::-1]                                   # newest first


def current_holdings(holdings: dict, secs, eq_pct: float) -> dict:
    """The latest equity book: stocks held at the last rebalance, with their weight
    inside the stock sleeve (w_book, sums to 100%) and their effective weight in the
    whole portfolio right now (w_port = w_book x current equity fraction)."""
    if not holdings:
        return {"asof": None, "stocks": []}
    d = max(holdings)
    cur = holdings[d]
    top = sorted(cur.items(), key=lambda kv: -kv[1])
    return {
        "asof": str(pd.Timestamp(d).date()),
        "stocks": [{"sym": s, "name": _name(secs, s),
                    "w_book": round(w * 100, 2),
                    "w_port": round(w * eq_pct, 2)}       # eq_pct already a percentage
                   for s, w in top],
    }


def sector_analysis(rebalances: list, sector_map: dict) -> dict | None:
    """Sector composition of the equity book across the rebalance history.

    Consumes the same per-rebalance `holdings` we already store (sym + weight in % of
    the ≤50-stock equity book), maps each stock to its sector, and returns:
      sectors        ordered sector list (by all-time peak weight, biggest first)
      dates/series   the sector mix at every rebalance -> 100% stacked rotation chart
      max_by_sector  each sector's PEAK book weight and the date it hit it
      peak           the single most concentrated the book ever got in one sector
      top_series     the largest-single-sector weight at each rebalance (concentration line)
      avg_sectors    average number of distinct sectors held (diversification)
      avg_top        average largest-sector weight (typical concentration)
      biggest_stock  the largest single-stock position the book ever held
    All weights are % of the equity book (which itself floats 35-100% of the portfolio).
    """
    if not rebalances:
        return None
    revs = sorted(rebalances, key=lambda r: r["date"])          # oldest -> newest for the timeline
    per, peak_of, biggest = [], {}, {"sym": None, "weight": 0.0, "date": None}
    for r in revs:
        sw = {}
        for h in r.get("holdings", []):
            sec = sector_map.get(h["sym"]) or "Unknown"
            w = float(h["weight"])
            sw[sec] = sw.get(sec, 0.0) + w
            if w > biggest["weight"]:
                biggest = {"sym": h["sym"], "weight": round(w, 2), "date": r["date"]}
        per.append((r["date"], sw))
        for sec, v in sw.items():
            if v > peak_of.get(sec, 0.0):
                peak_of[sec] = v
    order = sorted(peak_of, key=lambda k: -peak_of[k])
    max_by_sector = []
    for sec in order:
        bv, bd = 0.0, None
        for d, sw in per:
            if sw.get(sec, 0.0) > bv:
                bv, bd = sw.get(sec, 0.0), d
        max_by_sector.append({"sector": sec, "weight": round(bv, 1), "date": bd})
    top_series = [round(max(sw.values()) if sw else 0.0, 1) for _, sw in per]
    return {
        "sectors": order,
        "dates": [d for d, _ in per],
        "series": {sec: [round(sw.get(sec, 0.0), 2) for _, sw in per] for sec in order},
        "top_series": top_series,
        "max_by_sector": max_by_sector,
        "peak": max_by_sector[0] if max_by_sector else None,
        "avg_sectors": round(sum(len(sw) for _, sw in per) / len(per), 1),
        "avg_top": round(sum(top_series) / len(top_series), 1),
        "biggest_stock": biggest,
    }


def period_returns(sc: pd.Series, n5c: pd.Series, n50c: pd.Series) -> list:
    """Trailing total (and, for windows >= 1yr, annualised) returns ending at the last
    date, for the strategy vs the two benchmarks. sc/n5c/n50c are daily base-100 curves
    sharing one index. Windows longer than the available history are skipped."""
    end = sc.index[-1]
    out = []
    for label, months in PERIODS:
        if months is None:
            i0 = 0
        else:
            cut = end - pd.DateOffset(months=months)
            if cut <= sc.index[0]:
                continue                                 # window longer than history
            i0 = int(sc.index.searchsorted(cut))
            if i0 >= len(sc) - 1:
                continue
        yrs = (end - sc.index[i0]).days / 365.25
        ann = yrs >= 0.999

        def tr(c):
            return c.iloc[-1] / c.iloc[i0] - 1

        rec = {"label": label, "from": str(sc.index[i0].date()), "to": str(end.date()),
               "yrs": round(yrs, 2), "ann": ann,
               "s": round(tr(sc) * 100, 1),
               "n500": round(tr(n5c) * 100, 1),
               "n50": round(tr(n50c) * 100, 1)}
        if ann:
            def cg(c):
                return ((c.iloc[-1] / c.iloc[i0]) ** (1 / yrs) - 1) * 100
            rec["s_cagr"] = round(cg(sc), 1)
            rec["n500_cagr"] = round(cg(n5c), 1)
            rec["n50_cagr"] = round(cg(n50c), 1)
        out.append(rec)
    return out
