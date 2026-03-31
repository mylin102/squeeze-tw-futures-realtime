#!/usr/bin/env python3
"""
Vectorized backtest — merges all accumulated TMF kbars snapshots.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import numpy as np
import pandas as pd
import yaml
from rich.console import Console
from rich.table import Table
from squeeze_futures.engine.indicators import calculate_futures_squeeze
from kbars_loader import load_all_kbars

console = Console()

# ── Config ────────────────────────────────────────────────────────────────────
with open(os.path.join(os.path.dirname(__file__), "..", "..", "config", "trade_config.yaml")) as f:
    cfg = yaml.safe_load(f)

ENTRY_SCORE  = cfg["strategy"]["entry_score"]
SL_PTS       = cfg["risk_mgmt"]["stop_loss_pts"]
TP1_PTS      = cfg["strategy"]["partial_exit"]["tp1_pts"]
BE_PTS       = cfg["risk_mgmt"]["break_even_pts"]
LOTS         = cfg["trade_mgmt"]["lots_per_trade"]
TP1_LOTS     = cfg["strategy"]["partial_exit"]["tp1_lots"]
POINT_VALUE  = 10
FEE          = cfg["execution"]["broker_fee_per_side"] * 2
TAX_RATE     = cfg["execution"]["tax_rate"]
FILTER_MODE  = cfg["strategy"]["regime_filter"]

df_raw = load_all_kbars()

# ── Indicators ────────────────────────────────────────────────────────────────
df = calculate_futures_squeeze(df_raw, bb_length=cfg["strategy"]["length"])

# ── Signal generation (vectorized) ───────────────────────────────────────────
# Score: simplified single-TF version (mom_state direction × strength)
strength = np.where(df["mom_state"].isin([0, 3]), 1.5, 1.0)
direction = np.where(df["momentum"] > 0, 1, -1)
score = direction * strength * 100 / 1.5   # normalise to ±100

sqz_off = ~df["sqz_on"]

if FILTER_MODE == "loose":
    can_long = can_short = np.ones(len(df), dtype=bool)
else:  # mid / strict
    tol = 0.998 if FILTER_MODE == "mid" else 0.999
    can_long  = (df["Close"].values > df["ema_filter"].values * tol) | df["opening_bullish"].values
    can_short = (df["Close"].values < df["ema_filter"].values * (2 - tol)) | df["opening_bearish"].values

long_entry  = sqz_off.values & (score >= ENTRY_SCORE)  & (df["mom_state"].values >= 2) & can_long
short_entry = sqz_off.values & (score <= -ENTRY_SCORE) & (df["mom_state"].values <= 1) & can_short

# ── Vectorized portfolio simulation ──────────────────────────────────────────
close   = df["Close"].values
n       = len(close)

position    = 0          # current lots (+ long, - short)
entry_price = 0.0
stop        = 0.0
be_hit      = False
tp1_hit     = False

trades = []

for i in range(1, n):
    price = close[i]
    ts    = df.index[i]

    # ── Risk management (existing position) ──────────────────────────────────
    if position != 0:
        pnl_pts = (price - entry_price) * (1 if position > 0 else -1)

        # Break-even → move stop to entry
        if not be_hit and pnl_pts >= BE_PTS:
            stop = entry_price + (2 if position > 0 else -2)
            be_hit = True

        # TP1: partial exit 1 lot
        if not tp1_hit and abs(position) == LOTS and pnl_pts >= TP1_PTS:
            exit_lots = TP1_LOTS
            cost = FEE * exit_lots + entry_price * POINT_VALUE * TAX_RATE * exit_lots
            pnl_cash = pnl_pts * POINT_VALUE * exit_lots - cost
            trades.append(dict(ts=ts, direction="LONG" if position>0 else "SHORT",
                               entry=entry_price, exit=price, lots=exit_lots,
                               pnl_pts=pnl_pts, pnl_cash=pnl_cash, reason="TP1"))
            position -= exit_lots if position > 0 else -exit_lots
            stop = entry_price  # move to breakeven
            tp1_hit = True
            continue

        # Stop loss
        hit_stop = (position > 0 and price <= stop) or (position < 0 and price >= stop)
        if hit_stop:
            exit_lots = abs(position)
            cost = FEE * exit_lots + entry_price * POINT_VALUE * TAX_RATE * exit_lots
            pnl_cash = pnl_pts * POINT_VALUE * exit_lots - cost
            trades.append(dict(ts=ts, direction="LONG" if position>0 else "SHORT",
                               entry=entry_price, exit=stop, lots=exit_lots,
                               pnl_pts=pnl_pts, pnl_cash=pnl_cash, reason="STOP_LOSS"))
            position = 0; be_hit = False; tp1_hit = False
            continue

    # ── Entry ─────────────────────────────────────────────────────────────────
    if position == 0:
        be_hit = False; tp1_hit = False
        if long_entry[i]:
            position    = LOTS
            entry_price = price
            stop        = price - SL_PTS
        elif short_entry[i]:
            position    = -LOTS
            entry_price = price
            stop        = price + SL_PTS

# Close any open position at end
if position != 0:
    price = close[-1]
    pnl_pts = (price - entry_price) * (1 if position > 0 else -1)
    cost = FEE * abs(position) + entry_price * POINT_VALUE * TAX_RATE * abs(position)
    pnl_cash = pnl_pts * POINT_VALUE * abs(position) - cost
    trades.append(dict(ts=df.index[-1], direction="LONG" if position>0 else "SHORT",
                       entry=entry_price, exit=price, lots=abs(position),
                       pnl_pts=pnl_pts, pnl_cash=pnl_cash, reason="EOD"))

# ── Stats ─────────────────────────────────────────────────────────────────────
if not trades:
    console.print("[yellow]No trades generated.[/yellow]")
    sys.exit(0)

tdf = pd.DataFrame(trades)
total_pnl    = tdf["pnl_cash"].sum()
win_rate     = (tdf["pnl_cash"] > 0).mean() * 100
profit_factor= tdf.loc[tdf.pnl_cash>0,"pnl_cash"].sum() / max(abs(tdf.loc[tdf.pnl_cash<0,"pnl_cash"].sum()), 1)
avg_trade    = tdf["pnl_cash"].mean()
best         = tdf["pnl_cash"].max()
worst        = tdf["pnl_cash"].min()
total_cost   = (tdf["lots"] * FEE).sum()

# Equity curve
equity = 100000 + tdf["pnl_cash"].cumsum()
drawdown = equity - equity.cummax()
max_dd   = drawdown.min()

# ── Print ─────────────────────────────────────────────────────────────────────
console.print(f"\n[bold cyan]═══ Vectorized Backtest: TWII 5m ({df.index[0].date()} ~ {df.index[-1].date()}) ═══[/bold cyan]\n")

t = Table(show_header=False, box=None, padding=(0,2))
t.add_column(style="dim")
t.add_column(style="bold")
rows = [
    ("Total Trades",    str(len(tdf))),
    ("Win Rate",        f"{win_rate:.1f}%"),
    ("Profit Factor",   f"{profit_factor:.2f}"),
    ("Net PnL",         f"{'+'if total_pnl>=0 else ''}{total_pnl:,.0f} TWD"),
    ("Avg Trade",       f"{avg_trade:+,.0f} TWD"),
    ("Best Trade",      f"{best:+,.0f} TWD"),
    ("Worst Trade",     f"{worst:+,.0f} TWD"),
    ("Max Drawdown",    f"{max_dd:,.0f} TWD"),
    ("Total Cost",      f"{total_cost:,.0f} TWD"),
    ("Final Equity",    f"{100000+total_pnl:,.0f} TWD"),
]
for k, v in rows:
    t.add_row(k, v)
console.print(t)

# Breakdown by reason
console.print("\n[dim]Exit Reason Breakdown:[/dim]")
console.print(tdf.groupby("reason")["pnl_cash"].agg(["count","sum","mean"]).rename(
    columns={"count":"Trades","sum":"Total PnL","mean":"Avg PnL"}).to_string())

# Save
out = f"exports/simulations/backtest_vbt_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.md"
os.makedirs("exports/simulations", exist_ok=True)
with open(out, "w") as f:
    f.write(f"# Vectorized Backtest Report\n\n")
    f.write(f"Data: TWII 5m | {df.index[0].date()} ~ {df.index[-1].date()}\n\n")
    for k, v in rows:
        f.write(f"- **{k}**: {v}\n")
    f.write(f"\n## Trades\n\n{tdf.to_markdown(index=False)}\n")
console.print(f"\n[green]✓ Report saved: {out}[/green]")
