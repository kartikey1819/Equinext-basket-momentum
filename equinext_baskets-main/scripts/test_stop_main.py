"""
Test short-DMA gates (10/15/20) + stop-loss on the MAIN valuation-momentum baskets
(Nifty 50 & Nifty 500) — 100% EQUITY, NO 3-asset dial. Here there's no built-in downside
control, so a stop / trend gate has a real chance to reduce the (deep) equity drawdown.
Quarterly rebalance, full period incl. COVID. Net of cost.

    python scripts/test_stop_main.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from equinext.context import ResearchContext                          # noqa: E402
from equinext.backtest import BacktestConfig, run_backtest            # noqa: E402
from baskets.valuation_momentum import ValuationMomentumPEOnly, VM500Standard  # noqa: E402
from scripts.backtest_allocator import metrics                        # noqa: E402
from scripts.test_stop_variants import accrue_stop                    # noqa: E402


def row(label, m):
    print(f"{label:<30}{m['cagr']:>6.1f}%{m['vol']:>7.1f}%{m['sharpe']:>8.2f}{m['sortino']:>8.2f}"
          f"{m['maxdd']:>8.1f}%{m['calmar']:>8.2f}")


def main():
    ctx = ResearchContext()
    end = ctx.price_matrix().index[-1]
    px = ctx.price_matrix()
    start = pd.Timestamp("2017-08-01")
    cfg = BacktestConfig(start=start.date(), end=end.date(), rebalance="QE")   # quarterly (canonical)

    universes = [("Nifty 50", ValuationMomentumPEOnly, "NIFTY50"),
                 ("Nifty 500", VM500Standard, "NIFTY500")]

    for uni_label, cls, index in universes:
        print(f"\ncomputing {uni_label} base + DMA-gated books ...", flush=True)
        base = run_backtest(cls(), ctx, cfg)                          # 100% equity, no dial
        dma = {}
        for ma in (10, 15, 20):
            b = cls(); b.USE_TREND_GATE = True; b.TREND_MA = ma
            dma[ma] = run_backtest(b, ctx, cfg)
        H = base.holdings

        print(f"\n{'='*88}\n{uni_label} — valuation-momentum, 100% EQUITY (no dial), quarterly\n{'='*88}")
        print(f"{'config':<30}{'CAGR':>7}{'Vol':>7}{'Sharpe':>8}{'Sortino':>8}{'maxDD':>8}{'Calmar':>8}")
        print("-" * 88)
        row(f"{index} index (benchmark)", metrics(ctx.benchmark_returns(start, end, index)))
        row("Baseline (no DMA/stop)", metrics(base.returns))
        for ma in (10, 15, 20):
            row(f"+ {ma}-DMA gate", metrics(dma[ma].returns))
        for s in (0.10, 0.15, 0.20):
            row(f"+ {int(s*100)}% stop -> cash", metrics(accrue_stop(H, px, s)))
        for s in (0.15, 0.20):
            row(f"+ TRAILING {int(s*100)}% -> cash", metrics(accrue_stop(H, px, s, trailing=True)))


if __name__ == "__main__":
    main()
