"""
Equinext web app — a Groww/screener-style frontend over the local databases.

Backend: Flask serving JSON computed LIVE from nifty500_hrp.db (prices) and
equinext.db (valuation, fundamentals, basket holdings). No data is duplicated;
every request reads the DBs.

    pip install flask pandas
    python webapp/app.py           # -> http://127.0.0.1:5000

Endpoints:
    GET /                       the single-page app
    GET /api/overview           all stocks: price, chg, pe, in-basket, 1y return
    GET /api/stock/<symbol>     ohlcv + technicals + valuation series + fundamentals
    GET /api/basket             latest holdings + equity curve vs NIFTY50 + metrics
"""
from __future__ import annotations
import sqlite3
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, abort

_REPO = Path(__file__).resolve().parents[1]
SOURCE_DB = _REPO.parent / "nifty500_hrp.db"
PROJECT_DB = _REPO / "equinext.db"
BASKET = "vm_pe_only"          # the final basket: P/E froth gate + earnings gate + momentum
BACKTEST_CSV = _REPO / f"backtest_{BASKET}.csv"

app = Flask(__name__)


# ----------------------------------------------------------------- data access
@lru_cache(maxsize=1)
def _prices() -> pd.DataFrame:
    con = sqlite3.connect(str(SOURCE_DB))
    df = pd.read_sql("SELECT date, symbol, open, high, low, close, volume FROM ohlcv", con)
    con.close()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.sort_values(["symbol", "date"])


@lru_cache(maxsize=1)
def _nifty() -> pd.Series:
    con = sqlite3.connect(str(SOURCE_DB))
    df = pd.read_sql("SELECT date, close FROM broad_indices WHERE index_name='NIFTY50'", con)
    con.close()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.drop_duplicates("date").set_index("date")["close"].sort_index()


@lru_cache(maxsize=1)
def _securities() -> pd.DataFrame:
    con = sqlite3.connect(str(PROJECT_DB))
    df = pd.read_sql("SELECT symbol, name, sector FROM securities", con)
    con.close()
    return df.set_index("symbol")


@lru_cache(maxsize=1)
def _latest_holdings() -> dict:
    con = sqlite3.connect(str(PROJECT_DB))
    d = con.execute("SELECT MAX(as_of) FROM basket_holdings WHERE basket=?", (BASKET,)).fetchone()[0]
    if not d:
        con.close()
        return {"as_of": None, "holdings": {}}
    rows = con.execute("SELECT symbol, weight, score FROM basket_holdings WHERE basket=? AND as_of=?",
                       (BASKET, d)).fetchall()
    con.close()
    return {"as_of": d, "holdings": {r[0]: {"weight": r[1], "score": r[2]} for r in rows}}


def _valuation(symbol: str) -> pd.DataFrame:
    con = sqlite3.connect(str(PROJECT_DB))
    df = pd.read_sql("SELECT date, pe, pb, ev_ebitda, fcf_yield, eps_ttm FROM valuation_series "
                     "WHERE symbol=? ORDER BY date", con, params=(symbol,))
    con.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def _fundamentals(symbol: str) -> pd.DataFrame:
    con = sqlite3.connect(str(PROJECT_DB))
    df = pd.read_sql("SELECT period_end, pat, eps, book_value, roe, cfo FROM fundamentals_snapshot "
                     "WHERE symbol=? ORDER BY period_end", con, params=(symbol,))
    con.close()
    return df


# ----------------------------------------------------------------- helpers
def _clean(x):
    """NaN/inf -> None, numpy -> native, for JSON."""
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if (x is None or pd.isna(x) or np.isinf(x)) else round(float(x), 4)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _ret(close: pd.Series, days: int) -> float:
    if len(close) <= days:
        return np.nan
    return close.iloc[-1] / close.iloc[-1 - days] - 1


def _pct_rank(series: pd.Series) -> float:
    s = series.dropna()
    if len(s) < 30:
        return np.nan
    return float((s < s.iloc[-1]).mean())


# ----------------------------------------------------------------- API
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/overview")
def overview():
    px = _prices()
    secs = _securities()
    held = _latest_holdings()["holdings"]
    out = []
    for sym, g in px.groupby("symbol"):
        c = g.set_index("date")["close"]
        if len(c) < 2:
            continue
        last, prev = c.iloc[-1], c.iloc[-2]
        val = _valuation(sym)
        pe = val["pe"].dropna().iloc[-1] if not val.empty and val["pe"].notna().any() else None
        info = secs.loc[sym] if sym in secs.index else None
        out.append({
            "symbol": sym,
            "name": (info["name"] if info is not None and pd.notna(info["name"]) else sym),
            "sector": (info["sector"] if info is not None and pd.notna(info["sector"]) else "—"),
            "price": _clean(last),
            "change_pct": _clean((last / prev - 1) * 100),
            "ret_1y": _clean(_ret(c, 252) * 100 if not pd.isna(_ret(c, 252)) else None),
            "pe": _clean(pe),
            "in_basket": sym in held,
            "weight": _clean(held.get(sym, {}).get("weight")) if sym in held else None,
        })
    out.sort(key=lambda r: (not r["in_basket"], r["symbol"]))
    return jsonify({"stocks": out, "as_of": held and _latest_holdings()["as_of"]})


@app.route("/api/stock/<symbol>")
def stock(symbol):
    symbol = symbol.upper()
    px = _prices()
    g = px[px["symbol"] == symbol]
    if g.empty:
        abort(404)
    g = g.set_index("date")
    close, vol = g["close"], g["volume"]

    # --- OHLCV for chart (send all; frontend zooms) ---
    ohlcv = [{"t": d.strftime("%Y-%m-%d"), "o": _clean(r.open), "h": _clean(r.high),
              "l": _clean(r.low), "c": _clean(r.close), "v": _clean(r.volume)}
             for d, r in g.iterrows()]
    sma = {n: [_clean(v) for v in close.rolling(n).mean().tolist()] for n in (20, 50, 200)}

    # --- technicals ---
    hi52 = close.iloc[-252:].max() if len(close) >= 5 else close.max()
    lo52 = close.iloc[-252:].min() if len(close) >= 5 else close.min()
    r = close.pct_change().dropna()
    tech = {
        "sma20": _clean(close.rolling(20).mean().iloc[-1]),
        "sma50": _clean(close.rolling(50).mean().iloc[-1]),
        "sma200": _clean(close.rolling(200).mean().iloc[-1]),
        "rsi14": _clean(_rsi(close).iloc[-1]),
        "high_52w": _clean(hi52), "low_52w": _clean(lo52),
        "pct_from_high": _clean((close.iloc[-1] / hi52 - 1) * 100),
        "mom_12_1": _clean((close.asof(close.index[-1] - pd.Timedelta(days=30)) /
                            close.asof(close.index[-1] - pd.Timedelta(days=365)) - 1) * 100)
                    if len(close) > 260 else None,
        "vol_annual": _clean(r.iloc[-252:].std() * np.sqrt(252) * 100),
        "vol_trend": _clean((vol.iloc[-21:].mean() / vol.iloc[-126:].mean() - 1) * 100) if len(vol) >= 126 else None,
        "ret_1m": _clean(_ret(close, 21) * 100), "ret_3m": _clean(_ret(close, 63) * 100),
        "ret_6m": _clean(_ret(close, 126) * 100), "ret_1y": _clean(_ret(close, 252) * 100),
    }

    # --- valuation series + current + own-history percentile (froth) ---
    val = _valuation(symbol)
    valuation = {"dates": [], "pe": [], "pb": [], "ev_ebitda": [], "fcf_yield": [], "current": {}, "percentile": {}}
    if not val.empty:
        valuation["dates"] = val["date"].dt.strftime("%Y-%m-%d").tolist()
        for col in ("pe", "pb", "ev_ebitda", "fcf_yield"):
            valuation[col] = [_clean(v) for v in val[col].tolist()]
            s = val[col].dropna()
            valuation["current"][col] = _clean(s.iloc[-1]) if len(s) else None
            valuation["percentile"][col] = _clean(_pct_rank(val[col]) * 100 if not pd.isna(_pct_rank(val[col])) else None)

    # --- fundamentals (annual) ---
    fund = _fundamentals(symbol)
    fundamentals = [{"year": str(pd.to_datetime(row.period_end).year), "pat": _clean(row.pat),
                     "eps": _clean(row.eps), "book_value": _clean(row.book_value),
                     "roe": _clean(row.roe * 100 if pd.notna(row.roe) else None), "cfo": _clean(row.cfo)}
                    for row in fund.itertuples()]

    # --- basket status ---
    held = _latest_holdings()
    secs = _securities()
    info = secs.loc[symbol] if symbol in secs.index else None
    return jsonify({
        "symbol": symbol,
        "name": (info["name"] if info is not None and pd.notna(info["name"]) else symbol),
        "sector": (info["sector"] if info is not None and pd.notna(info["sector"]) else "—"),
        "price": _clean(close.iloc[-1]),
        "change_pct": _clean((close.iloc[-1] / close.iloc[-2] - 1) * 100),
        "ohlcv": ohlcv, "sma": sma, "technicals": tech,
        "valuation": valuation, "fundamentals": fundamentals,
        "basket": {"in_basket": symbol in held["holdings"], "as_of": held["as_of"],
                   "weight": _clean(held["holdings"].get(symbol, {}).get("weight")),
                   "score": _clean(held["holdings"].get(symbol, {}).get("score"))},
    })


@app.route("/api/basket")
def basket():
    held = _latest_holdings()
    px = _prices()
    secs = _securities()
    rows = []
    for sym, h in held["holdings"].items():
        g = px[px["symbol"] == sym].set_index("date")["close"]
        last, prev = (g.iloc[-1], g.iloc[-2]) if len(g) >= 2 else (None, None)
        info = secs.loc[sym] if sym in secs.index else None
        rows.append({"symbol": sym, "name": (info["name"] if info is not None and pd.notna(info["name"]) else sym),
                     "sector": (info["sector"] if info is not None and pd.notna(info["sector"]) else "—"),
                     "weight": _clean(h["weight"] * 100), "score": _clean(h["score"]),
                     "price": _clean(last), "change_pct": _clean((last / prev - 1) * 100 if last else None)})
    rows.sort(key=lambda r: -(r["weight"] or 0))

    curve, metrics = {}, {}
    if BACKTEST_CSV.exists():
        df = pd.read_csv(BACKTEST_CSV, index_col=0, parse_dates=True)
        b = df["basket"].dropna(); n = df["nifty50"].reindex(b.index).fillna(0)
        cb = (1 + b).cumprod() * 100; cn = (1 + n).cumprod() * 100
        curve = {"dates": cb.index.strftime("%Y-%m-%d").tolist(),
                 "basket": [_clean(v) for v in cb.tolist()], "nifty": [_clean(v) for v in cn.tolist()]}
        yrs = (b.index[-1] - b.index[0]).days / 365
        cagr = (cb.iloc[-1] / 100) ** (1 / yrs) - 1
        dd = (cb / cb.cummax() - 1).min()
        cagr_n = (cn.iloc[-1] / 100) ** (1 / yrs) - 1
        metrics = {"cagr": _clean(cagr * 100), "cagr_nifty": _clean(cagr_n * 100),
                   "sharpe": _clean(cagr / (b.std() * np.sqrt(252))),
                   "max_dd": _clean(dd * 100), "final": _clean(cb.iloc[-1]),
                   "final_nifty": _clean(cn.iloc[-1]), "years": _clean(yrs)}
    return jsonify({"as_of": held["as_of"], "holdings": rows, "curve": curve, "metrics": metrics})


@app.route("/api/rebalances")
def rebalances():
    """The basket's trade history — what was bought/sold at each quarterly rebalance."""
    con = sqlite3.connect(str(PROJECT_DB))
    df = pd.read_sql("SELECT as_of, symbol, weight FROM basket_holdings WHERE basket=? ORDER BY as_of",
                     con, params=(BASKET,))
    con.close()
    if df.empty:
        return jsonify({"rebalances": []})
    out, prev = [], {}
    for d in sorted(df["as_of"].unique()):
        cur = dict(zip(df[df.as_of == d].symbol, df[df.as_of == d].weight))
        cs, ps = set(cur), set(prev)
        turnover = sum(abs(cur.get(s, 0) - prev.get(s, 0)) for s in cs | ps) * 100
        out.append({"date": d, "bought": sorted(cs - ps), "sold": sorted(ps - cs),
                    "kept": len(cs & ps), "n": len(cur), "turnover": round(turnover, 1)})
        prev = cur
    out.reverse()   # most recent first
    return jsonify({"rebalances": out})


@app.route("/api/strategy")
def strategy():
    """The basket's construction criteria — the 'why', with real thresholds."""
    n_universe = len(_securities())
    return jsonify({
        "name": "Equinext Valuation-Momentum Basket",
        "tagline": "Own the strongest Nifty 50 stocks — but only the ones that aren't overpriced and whose rise is backed by real earnings.",
        "n_universe": n_universe,
        "n_hold": 15,
        "rebalance": "Quarterly",
        "weighting": "Inverse-volatility (calmer stocks get more)",
        "steps": [
            {"n": 1, "key": "universe", "title": "Universe Filter",
             "icon": "filter",
             "why": "Only large, liquid, established companies you can actually trade without moving the price.",
             "criteria": [f"{n_universe} official Nifty 50 constituents",
                          "Median traded value ≥ ₹5 cr/day (63-day)",
                          "Free-float market cap ≥ ₹100 cr",
                          "At least ~1 year of price history"]},
            {"n": 2, "key": "valuation", "title": "Valuation Gate (P/E)",
             "icon": "shield",
             "why": "Don't chase froth. A stock trading at its own most-expensive extreme falls hardest when sentiment turns.",
             "criteria": ["Rank today's P/E within the stock's own 5-year history",
                          "Drop any stock above its 80th percentile (its own expensive extreme)",
                          "This filters out the frothy; it does not rank"]},
            {"n": 3, "key": "momentum", "title": "Momentum Score",
             "icon": "trend",
             "why": "Ride the strongest, most broadly-confirmed uptrends — stocks going up tend to keep going up.",
             "criteria": ["12-month return (skipping the last month)",
                          "Distance from the 52-week high",
                          "Volume trend (rising participation)",
                          "Each z-scored vs peers, then averaged into one score"]},
            {"n": 4, "key": "earnings", "title": "Earnings-Backed Gate",
             "icon": "check",
             "why": "Keep only rises driven by real profit growth, not hype. Story stocks collapse in downturns.",
             "criteria": ["Split the 12-month rise into earnings vs multiple (hype)",
                          "Keep only if earnings did at least half the work",
                          "Drops pure multiple-expansion names"]},
        ],
        "selection": {
            "title": "How the 15 stocks are chosen & weighted",
            "points": [
                "Every quarter, all 50 stocks pass through the funnel above.",
                "The valuation & earnings gates remove the risky names.",
                "Survivors are ranked by momentum score — the top 15 are held.",
                "Each is weighted by inverse-volatility: steadier stocks get a bigger slice, so no single wild stock dominates the risk.",
                "No stock is picked on one raw number — it's the combined, peer-relative score that decides.",
            ],
        },
    })


if __name__ == "__main__":
    app.run(debug=False, port=5000)
