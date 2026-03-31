#!/usr/bin/env python3
"""
Vectorized parameter optimization — grid search over entry_score, sl_pts, tp1_pts.
Automatically uses all accumulated TMF kbars snapshots.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import numpy as np
import pandas as pd
from itertools import product
from rich.console import Console
from rich.table import Table
from squeeze_futures.engine.indicators import calculate_futures_squeeze
from kbars_loader import load_all_kbars

console = Console()

df_raw = load_all_kbars()

df = calculate_futures_squeeze(df_raw, bb_length=20)
close     = df["Close"].values
sqz_off   = ~df["sqz_on"].values
mom_state = df["mom_state"].values
momentum  = df["momentum"].values
ema_filt  = df["ema_filter"].values
ob        = df["opening_bullish"].values
os_       = df["opening_bearish"].values

POINT_VALUE = 10
FEE         = 40.0
TAX_RATE    = 2e-5
LOTS        = 2
TP1_LOTS    = 1

# ── Parameter grid ────────────────────────────────────────────────────────────
ENTRY_SCORES = [15, 20, 25, 30, 40]
SL_PTS_LIST  = [40, 50, 60, 80]
TP1_PTS_LIST = [30, 40, 50, 60, 80]

def run(entry_score, sl_pts, tp1_pts):
    be_pts    = tp1_pts
    strength  = np.where(np.isin(mom_state, [0, 3]), 1.5, 1.0)
    direction = np.where(momentum > 0, 1.0, -1.0)
    score     = direction * strength * 100 / 1.5
    can_long  = (close > ema_filt * 0.998) | ob
    can_short = (close < ema_filt * 1.002) | os_
    long_sig  = sqz_off & (mom_state >= 2) & can_long  & (score >= entry_score)
    short_sig = sqz_off & (mom_state <= 1) & can_short & (score <= -entry_score)

    pos = 0; ep = 0.0; stop = 0.0; be_hit = False; tp1_hit = False
    pnls = []

    for i in range(1, len(close)):
        p = close[i]
        if pos != 0:
            pnl_pts = (p - ep) * (1 if pos > 0 else -1)
            if not be_hit and pnl_pts >= be_pts:
                stop = ep + (2 if pos > 0 else -2); be_hit = True
            if not tp1_hit and abs(pos) == LOTS and pnl_pts >= tp1_pts:
                cost = FEE * TP1_LOTS + ep * POINT_VALUE * TAX_RATE * TP1_LOTS
                pnls.append(pnl_pts * POINT_VALUE * TP1_LOTS - cost)
                pos -= TP1_LOTS if pos > 0 else -TP1_LOTS
                stop = ep; tp1_hit = True; continue
            if (pos > 0 and p <= stop) or (pos < 0 and p >= stop):
                lots = abs(pos)
                cost = FEE * lots + ep * POINT_VALUE * TAX_RATE * lots
                pnls.append(pnl_pts * POINT_VALUE * lots - cost)
                pos = 0; be_hit = False; tp1_hit = False; continue
        if pos == 0:
            be_hit = False; tp1_hit = False
            if long_sig[i]:
                pos = LOTS; ep = p; stop = p - sl_pts
            elif short_sig[i]:
                pos = -LOTS; ep = p; stop = p + sl_pts

    if pos != 0:
        p = close[-1]; pnl_pts = (p - ep) * (1 if pos > 0 else -1)
        lots = abs(pos); cost = FEE * lots + ep * POINT_VALUE * TAX_RATE * lots
        pnls.append(pnl_pts * POINT_VALUE * lots - cost)

    if not pnls:
        return None
    arr    = np.array(pnls)
    equity = np.cumsum(arr)
    dd     = equity - np.maximum.accumulate(equity)
    gross_w = arr[arr > 0].sum()
    gross_l = abs(arr[arr < 0].sum())
    return dict(
        trades   = len(arr),
        net_pnl  = float(equity[-1]),
        win_rate = float((arr > 0).mean() * 100),
        pf       = float(gross_w / gross_l) if gross_l > 0 else 999.0,
        max_dd   = float(dd.min()),
    )

# ── Grid search ───────────────────────────────────────────────────────────────
total = len(ENTRY_SCORES) * len(SL_PTS_LIST) * len(TP1_PTS_LIST)
console.print(f"[bold cyan]Running {total} combos...[/bold cyan]")

results = []
for es, sl, tp1 in product(ENTRY_SCORES, SL_PTS_LIST, TP1_PTS_LIST):
    r = run(es, sl, tp1)
    if r and r["trades"] >= 3:
        results.append(dict(entry_score=es, sl_pts=sl, tp1_pts=tp1, **r))

df_res = pd.DataFrame(results).sort_values("net_pnl", ascending=False)

console.print(f"\n[bold]Top 10 by Net PnL[/bold] (min 3 trades)\n")
t = Table(show_header=True, header_style="bold cyan")
for col in ["entry_score","sl_pts","tp1_pts","trades","win_rate","pf","net_pnl","max_dd"]:
    t.add_column(col, justify="right")
for _, row in df_res.head(10).iterrows():
    t.add_row(
        str(int(row.entry_score)), str(int(row.sl_pts)), str(int(row.tp1_pts)),
        str(int(row.trades)),
        f"{row.win_rate:.0f}%",
        f"{row.pf:.2f}",
        f"{row.net_pnl:+,.0f}",
        f"{row.max_dd:,.0f}",
    )
console.print(t)

best = df_res.iloc[0]
console.print(f"\n[green]✓ Best params: entry_score={int(best.entry_score)}, sl={int(best.sl_pts)}, tp1={int(best.tp1_pts)} → Net PnL={best.net_pnl:+,.0f} TWD | WR={best.win_rate:.0f}% | PF={best.pf:.2f} | MaxDD={best.max_dd:,.0f}[/green]")

out = f"exports/simulations/param_optimization_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
os.makedirs("exports/simulations", exist_ok=True)
df_res.to_csv(out, index=False)
console.print(f"[dim]Full results: {out}[/dim]")
