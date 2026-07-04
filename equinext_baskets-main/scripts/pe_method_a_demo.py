"""
Method A demo — P/E z-score & percentile vs each stock's OWN history, Nifty 50.

Standalone (no framework imports). Shows the mechanic before wiring it into
equinext: build a daily P/E series (price / EPS, forward-filled), then locate
TODAY inside the stock's trailing 5-year P/E distribution.

    z-score    = (pe_today - mean) / std        negative = cheap vs own history
    percentile = mean(pe_history < pe_today)     0 = cheapest ever, 1 = richest

Mirrors equinext/primitives.py::valuation_zscore / valuation_percentile.

DATA HONESTY (why the EPS handling looks elaborate):
  Yahoo's fundamentals are unreliable for NSE (.NS) tickers in two ways —
    * per-share "Diluted/Basic EPS" line items are broken (INFY shows 0.80 vs the
      real 75.5), and
    * income statements come in MIXED currencies (INFY in USD, HDFCBANK in INR),
      so any absolute EPS derivation is off by the FX rate for some names.
  Reliable, by contrast: info['trailingEps'] (correct current EPS in ₹) and the
  *shape* of the Net Income series. So we ANCHOR to the current trailing EPS and
  use Net Income only for the relative historical path:
        eps(t) = trailingEps_now * NetIncome(t) / NetIncome_latest
  Currency and share-scale cancel in the ratio. Assumes share count is roughly
  constant over the window (fine for large caps, absent big buybacks/dilution).

  History is annual (Yahoo gives ~4-5 yrs of annual Net Income, only a few
  quarters), so EPS steps once a year and intra-year P/E variation comes from
  price. That's a coarse-but-honest Method A. For a true point-in-time series,
  wire this into equinext/data/valuation.py::build_valuation_series_from_fundamentals.

Run:
    pip install yfinance pandas
    python scripts/pe_method_a_demo.py
    python scripts/pe_method_a_demo.py INFY.NS TCS.NS HDFCBANK.NS   # subset
"""
from __future__ import annotations
import sys
from pathlib import Path
import warnings
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    sys.exit("Need yfinance:  pip install yfinance pandas")

warnings.simplefilter("ignore")

LOOKBACK_YEARS = 5
REPORT_LAG_DAYS = 45          # approx gap between period-end and announcement (avoid look-ahead)
MIN_PE_DAYS = 30              # need at least this many daily P/E obs to bother

NI_ROWS = ("Net Income", "Net Income Common Stockholders",
           "Net Income From Continuing Operation Net Minority Interest")

# Nifty 50 constituents (Yahoo tickers, .NS = NSE). Constituents rotate ~2x/yr —
# edit this list to match the current index. Pass tickers as CLI args to override.
NIFTY50 = [
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "AXISBANK.NS",
    "BAJAJ-AUTO.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "BEL.NS", "BHARTIARTL.NS",
    "BPCL.NS", "BRITANNIA.NS", "CIPLA.NS", "COALINDIA.NS", "DRREDDY.NS",
    "EICHERMOT.NS", "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS",
    "HEROMOTOCO.NS", "HINDALCO.NS", "HINDUNILVR.NS", "ICICIBANK.NS", "INDUSINDBK.NS",
    "INFY.NS", "ITC.NS", "JSWSTEEL.NS", "KOTAKBANK.NS", "LT.NS",
    "M&M.NS", "MARUTI.NS", "NESTLEIND.NS", "NTPC.NS", "ONGC.NS",
    "POWERGRID.NS", "RELIANCE.NS", "SBILIFE.NS", "SBIN.NS", "SHRIRAMFIN.NS",
    "SUNPHARMA.NS", "TATACONSUM.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "TCS.NS",
    "TECHM.NS", "TITAN.NS", "TRENT.NS", "ULTRACEMCO.NS", "WIPRO.NS",
]


def _stepwise_eps(eps: pd.Series, daily_index: pd.DatetimeIndex) -> pd.Series:
    """Forward-fill a sparse EPS series (indexed by period-end) onto the daily price
    index — the 'stepwise EPS' of Method A. A reporting lag is added so we only
    'know' an EPS after it would have been announced (no look-ahead). Leading days
    before the first known EPS stay NaN and get dropped downstream.
    """
    eps = eps.sort_index()
    eps.index = eps.index + pd.Timedelta(days=REPORT_LAG_DAYS)
    combined = daily_index.union(eps.index)
    return eps.reindex(combined).ffill().reindex(daily_index)


def calibrated_eps_series(t: "yf.Ticker", daily_index: pd.DatetimeIndex):
    """Return (eps_aligned_to_daily_index, method_label, yahoo_trailing_pe).

    Anchor to the reliable current trailing EPS; take only the *shape* of the
    annual Net Income series for history (currency/scale cancel in the ratio).
    """
    try:
        info = t.info or {}
    except Exception:
        info = {}
    anchor = info.get("trailingEps")
    yf_pe = info.get("trailingPE")
    if not anchor:
        return None, "no-eps-anchor", yf_pe

    a = getattr(t, "income_stmt", None)
    ni = None
    if a is not None and not a.empty:
        for row in NI_ROWS:
            if row in a.index:
                ni = pd.to_numeric(a.loc[row], errors="coerce").dropna()
                if len(ni):
                    break

    if ni is None or len(ni) < 2:
        # no usable history path -> current EPS held flat (percentile = price only)
        return pd.Series(float(anchor), index=daily_index), "flat-eps*", yf_pe

    ni.index = pd.to_datetime(ni.index)
    ni = ni.sort_index()
    latest = float(ni.iloc[-1])
    if latest == 0:
        return pd.Series(float(anchor), index=daily_index), "flat-eps*", yf_pe

    k = float(anchor) / latest                 # maps NI_latest -> trailingEps (₹)
    eps_path = ni * k                          # ₹ EPS path, FX/share-scale cancelled
    return _stepwise_eps(eps_path, daily_index), "annual-NI-calib", yf_pe


def analyze(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    px = t.history(period=f"{LOOKBACK_YEARS}y", auto_adjust=False)  # split-adj, NOT div-adj
    if px.empty:
        return {"ticker": ticker.replace(".NS", ""), "error": "no price"}

    col = "Close" if "Close" in px.columns else "Adj Close"
    close = px[col].copy()
    idx = pd.to_datetime(close.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    close.index = idx.normalize()
    close = close[~close.index.duplicated(keep="last")]

    eps, method, yf_pe = calibrated_eps_series(t, close.index)
    if eps is None:
        return {"ticker": ticker.replace(".NS", ""), "error": method}

    pe = (close / eps).replace([float("inf"), float("-inf")], pd.NA).dropna()
    pe = pe[pe > 0]                            # negative EPS -> P/E undefined, drop
    if len(pe) < MIN_PE_DAYS:
        return {"ticker": ticker.replace(".NS", ""), "error": f"thin hist ({len(pe)}d)"}

    cur = float(pe.iloc[-1])
    mu, sd = float(pe.mean()), float(pe.std())
    z = (cur - mu) / sd if sd else float("nan")
    pctile = float((pe < cur).mean())
    years = (pe.index[-1] - pe.index[0]).days / 365.0

    return {
        "ticker": ticker.replace(".NS", ""),
        "pe": round(cur, 1),
        "PEyf": round(float(yf_pe), 1) if yf_pe else None,   # sanity: should ~ match pe
        "median": round(float(pe.median()), 1),
        "z": round(z, 2),
        "pctile": round(pctile, 2),
        "years": round(years, 1),
        "method": method,
        "error": None,
    }


def main(argv):
    tickers = argv or NIFTY50
    rows, errs = [], []
    for i, tk in enumerate(tickers, 1):
        print(f"  [{i:>2}/{len(tickers)}] {tk:<16}", end="\r", flush=True)
        try:
            r = analyze(tk)
        except Exception as e:                # network / schema hiccup — skip, keep going
            r = {"ticker": tk.replace(".NS", ""), "error": str(e)[:40]}
        (errs if r.get("error") else rows).append(r)

    print(" " * 60, end="\r")
    if not rows:
        sys.exit("No results — check network / yfinance install.")

    df = pd.DataFrame(rows).sort_values("z").reset_index(drop=True)

    def flag(r):
        if str(r["method"]).endswith("*"):
            return "flat-EPS"
        if r["z"] <= -1.0:
            return "CHEAP vs self"
        if r["z"] >= 1.0:
            return "RICH vs self"
        return ""
    df["flag"] = df.apply(flag, axis=1)

    cols = ["ticker", "pe", "PEyf", "median", "z", "pctile", "years", "method", "flag"]

    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 130)
    print(f"\nMethod A — P/E vs own {LOOKBACK_YEARS}y history  (cheapest -> richest by z)\n")
    print(df[cols].to_string(index=False))

    out = Path(__file__).resolve().parent.parent / "pe_nifty50.csv"
    df[cols].to_csv(out, index=False)
    print(f"\nSaved -> {out}   (open in Excel / VSCode and sort any column)")

    print(f"\n{len(rows)} scored, {len(errs)} skipped.")
    if errs:
        print("skipped:", ", ".join(f"{e['ticker']}({e['error']})" for e in errs))
    print(
        "\npe vs PEyf: computed current P/E should ~match Yahoo's trailingPE (sanity check). "
        "\nz<0 & low pctile = cheap vs its OWN history (NOT vs peers). "
        "'flat-EPS' rows lack a Net Income path -> read as price-percentile only. "
        "\nValue-trap guards (trend / quality) are NOT applied here — see baskets/relative_value.py."
    )


if __name__ == "__main__":
    main(sys.argv[1:])
