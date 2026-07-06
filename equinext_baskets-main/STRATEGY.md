# Valuation-Momentum Basket — Strategy Specification

**Goal:** a Nifty 50 stock basket that beats the NIFTY50 index on a risk-adjusted
basis, by riding **momentum** but only where it is **earnings-backed** and not
**frothy**. Implemented in [`baskets/valuation_momentum.py`](baskets/valuation_momentum.py),
run through the shared harness in [`equinext/`](equinext/).

Design principle: **momentum RANKS, valuation GATES.** Momentum picks the
winners; valuation and earnings-backing decide who is *eligible* to be picked.

---

## 1. Data pipeline

| Data | Source | Script | Store |
|---|---|---|---|
| Daily prices (10y) | Yahoo Finance | [`scripts/load_nifty50_data.py`](scripts/load_nifty50_data.py) | `nifty500_hrp.db` → `ohlcv` |
| Benchmarks (NIFTY50/500) | Yahoo Finance | same | `nifty500_hrp.db` → `broad_indices` |
| Fundamentals (10y annual) | **screener.in** (scraped, cached, rate-limited) | [`scripts/scrape_screener.py`](scripts/scrape_screener.py) | `equinext.db` → `valuation_series`, `fundamentals_snapshot` |
| Readable CSV exports | derived from DBs | [`scripts/export_tables.py`](scripts/export_tables.py) | `exports/*.csv` |

**Coverage:** 49 Nifty 50 names (TATAMOTORS excluded — delisted on Yahoo post-demerger),
daily prices and derived multiples **2016-07-04 → 2026-07-03**. 48/49 have full
valuation multiples; SBILIFE failed to parse on screener (insurer page) and runs
momentum-only.

**Valuation multiples** are derived per share, all in ₹ (screener is INR-native,
no currency issues), stepped at fiscal year-end **+ 75-day reporting lag** (so a
year's results are only "known" after they would have been announced — no
look-ahead), then forward-filled onto daily prices:

```
shares(yr) = Net Profit / EPS                       (both from screener P&L)
pe         = close / EPS
pb         = close / [(Equity Capital + Reserves) / shares]
ev_ebitda  = (close + Borrowings/shares) / (Operating Profit / shares)   [non-financials]
fcf_yield  = (Free Cash Flow / shares) / close                          [non-financials]
```

---

## 2. Selection criteria — the four-step funnel

Applied at every rebalance, using **only data on/before the rebalance date**.

### Step 1 — Universe (eligibility)
`ctx.universe(as_of)` in [`equinext/universe.py`](equinext/universe.py):
- Base list: Nifty 50 (49 names)
- **Liquidity gate:** median daily traded value (close × volume) over trailing **63 days** ≥ **₹5 crore**
- **Free-float gate:** free-float market cap ≥ **₹100 crore**
- **History gate:** ≥ **200 days** price history; valuation gates require ≥ **60** valuation rows (`MIN_VAL_OBS`)

### Step 2 — Valuation froth gate (filter)
Composite **own-history froth percentile** over a trailing **5-year** window
(`valuation_froth_percentile` in [`equinext/primitives.py`](equinext/primitives.py)),
averaged across whatever multiples the name has:

| Multiple | Meaning | Direction |
|---|---|---|
| P/E | price ÷ EPS | higher = richer |
| P/B | price ÷ book value/share | higher = richer |
| EV/EBITDA | enterprise value ÷ EBITDA | higher = richer |
| FCF yield | free cash flow ÷ market cap | higher = **cheaper** (inverted) |

- Financials (banks/NBFCs/insurers) use **P/E + P/B only**.
- **Rule:** drop names with composite froth percentile **> 0.80** (`FROTH_MAX`) — the own-history expensive extreme.

### Step 3 — Momentum score (rank)
Cross-sectional composite z-score (each factor winsorized at **1%/99%**, z-scored,
equal-weighted — `composite` in [`equinext/scoring.py`](equinext/scoring.py)) of:

| Signal | Definition | Primitive |
|---|---|---|
| 12-1 momentum | 12-month return skipping the last month | `momentum_12_1` |
| Distance from 52-wk high | close ÷ trailing 52-week high | `distance_from_high` (weeks=52) |
| Volume trend | 21-day avg volume ÷ 126-day avg volume − 1 | `volume_trend` (short=21, long=126) |

### Step 4 — Earnings-backed gate (filter)
Re-rating decomposition (`rerating_decomposition`) splits the trailing 12-month
price return into earnings-driven vs multiple-driven.
- **Rule:** keep only names where earnings contribution ≥ multiple contribution (drop pure multiple-expansion "story stocks").

### Selection & weighting
- **Combine:** momentum ranks the survivors of Steps 2 & 4. If gates leave fewer than **8** names (`N_MIN`), the froth gate relaxes so the book isn't too thin.
- **Hold:** top **15** by momentum (`N_HOLD`).
- **Weight:** **inverse-volatility** — 1 ÷ (252-day annualized vol), normalized to sum to 1. Calmer names get more.

---

## 3. Backtest mechanics

Shared harness [`equinext/backtest.py`](equinext/backtest.py), runner
[`scripts/run_backtest.py`](scripts/run_backtest.py).

| Setting | Value |
|---|---|
| Period | 2017-08 → 2026-07 (~9 years) |
| Rebalance cadence | **Quarterly** (quarter-end) |
| Trading cost | **25 bps per side** (brokerage + impact + STT) on traded fraction |
| Tax | FIFO capital gains — **20%** short-term (<1yr), **12.5%** long-term (>1yr) |
| No-trade band | 0 by default (drift tolerance; tested at 3%) |
| Benchmark | NIFTY50 **price** index (^NSEI); price-return both sides |
| Returns | daily, weights drift between rebalances; costs charged the day after a trade |
| Look-ahead protection | signals use data ≤ rebalance date; fundamentals lagged 75 days |

**Why quarterly?** A 12-1 momentum signal barely changes month to month; monthly
rebalancing churned ~1041%/yr and — after costs and short-term-gains tax — dragged
after-tax CAGR to ~5%. Quarterly cut turnover to ~337%/yr and lifted after-tax
CAGR to ~12%. Cadence was the single biggest performance lever.

---

## 4. Results (2017-08 → 2026-07, quarterly)

| Metric | Basket | NIFTY50 |
|---|---|---|
| CAGR (gross) | **16.1%** | 10.6% |
| CAGR (after tax) | 12.3% | — |
| Sharpe | **1.01** | 0.63 |
| Max drawdown | **−32.0%** | −38.4% |
| ₹100 became | **₹360** | ₹248 |

**Regime test (excess vs NIFTY50):** 2018 +7.1% · 2020 (COVID) +14.7% ·
2022 (rotation) +1.6% · COVID crash Feb–Mar '20 fell −31.3% vs index −36.5%.
No momentum crash.

### Ablation — do the valuation gates earn their place?
Same data, same period, gates OFF vs ON (`momentum_only` vs `valuation_momentum`):

| Metric | Gates OFF | Gates ON | Gate effect |
|---|---|---|---|
| CAGR (gross) | 13.3% | 16.1% | **+2.7%/yr** |
| Sharpe | 0.74 | 1.01 | **+0.27** |
| Max drawdown | −37.0% | −32.0% | **+5 pts** |
| Turnover | 394%/yr | 337%/yr | lower |

The gates **help in reversals** (2020 +11.3%, 2022 +9.1%) and **cost in bulls**
(2021 −14.4%, 2023 −7.1%) — they are insurance that nets positive across a full
cycle, improving risk metrics most. This is the documented value+momentum
interaction (Asness, "Value and Momentum Everywhere").

---

## 5. Known limitations (honest caveats)

1. **Survivorship bias** — universe is *today's* Nifty 50 applied backward; names
   that were relegated are excluded, inflating the CAGR edge. Fix: point-in-time
   index membership (`universe_membership` table + NSE reconstitution history).
   Drawdown / crash-protection findings are far more robust to this than the CAGR.
2. **Thresholds not yet stress-tested** — froth 0.80, 15 holdings, momentum
   windows are sensible a-priori defaults, not swept. Robustness sweep still owed.
3. **Annual fundamentals granularity** — screener annual + 75-day lag; within a
   year multiples move only with price, not quarterly earnings.
4. **Price-return benchmark** — excludes dividends on both sides (fair comparison,
   but absolute CAGRs understate reality ~1–1.5%; TRI is the eventual benchmark).
5. **SBILIFE** runs momentum-only (screener parse failure).

---

## 6. How to run

```powershell
# 1. Load data (one-time / refresh)
python scripts/load_nifty50_data.py          # 10y prices + benchmarks
python scripts/scrape_screener.py            # 10y fundamentals -> valuation_series

# 2. Backtest
python scripts/run_backtest.py valuation_momentum --rebalance Q   # the strategy
python scripts/run_backtest.py momentum_only   --rebalance Q      # gates-off ablation

# 3. Reports (close the .xlsx in Excel first)
python scripts/export_tables.py                          # refresh readable CSVs
python scripts/format_monthly_report.py valuation_momentum   # formatted Excel
```

Optional flags: `--start YYYY-MM-DD` (custom window), `--band 0.03` (no-trade band).

---

## 7. File map

| File | Role |
|---|---|
| `baskets/valuation_momentum.py` | the strategy — `ValuationMomentumBasket.select()` + `MomentumOnlyBasket` ablation |
| `equinext/primitives.py` | shared signals: momentum, distance-from-high, volume-trend, froth percentile, re-rating, vol |
| `equinext/scoring.py` | winsorize / z-score / composite |
| `equinext/backtest.py` | rebalance loop, costs, FIFO tax, cadence |
| `equinext/universe.py` | liquidity + free-float + listing gates |
| `equinext/data/valuation.py` | reads `valuation_series` |
| `scripts/load_nifty50_data.py` | Yahoo prices + benchmarks loader |
| `scripts/scrape_screener.py` | screener.in fundamentals scraper → 10y multiples |
| `scripts/run_backtest.py` | generalized runner (any basket + cadence) |
| `scripts/export_tables.py` | regenerate readable CSVs from live DB |
| `scripts/format_monthly_report.py` | formatted Excel report |
| `exports/` | readable CSV/XLSX snapshots |
