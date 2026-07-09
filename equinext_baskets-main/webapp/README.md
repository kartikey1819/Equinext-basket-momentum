# Equinext Web App

A Groww/screener-style frontend over the local databases — every stock's price
chart, technicals, fundamentals, and valuation, plus the valuation-momentum
basket dashboard. Reads the DBs live; no data is duplicated.

## Run

```powershell
pip install flask pandas          # one-time
python webapp/app.py              # then open http://127.0.0.1:5000
```

Prereq: the DBs must be populated first —
`scripts/load_nifty50_data.py` (prices) and `scripts/scrape_screener.py`
(fundamentals). The basket view also uses `backtest_valuation_momentum.csv`
(run `scripts/run_backtest.py valuation_momentum --rebalance Q`).

## What's inside

**Stocks tab** — searchable list of all 49 names (green dot = in the basket).
Click one for:
- Candlestick price chart + volume + SMA 20/50/200, range 1M…Max
- **Overview** — returns (1M/3M/6M/1Y), momentum, RSI, volatility
- **Technicals** — SMAs with above/below signals, RSI, momentum, volume trend, trend
- **Fundamentals** — EPS, net profit, book value, ROE over ~12 years (from screener)
- **Valuation** — P/E, P/B, EV/EBITDA, FCF-yield history + own-history percentile (the basket's froth gate)

**Basket tab** — CAGR/Sharpe/drawdown vs NIFTY50, growth-of-₹100 equity curve,
and the 15 current holdings with weights & momentum scores (click a row to open the stock).

## Architecture
- `app.py` — Flask backend; computes technicals with pandas, serves JSON from the DBs
- `templates/index.html` + `static/{app.js,style.css}` — single-page frontend, Plotly charts
- Charts use Plotly via CDN (needs internet when viewing; vendor it for offline use)
