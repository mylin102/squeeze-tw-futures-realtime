#!/usr/bin/env python3
import sys
import os
import yaml
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from squeeze_futures.engine.simulator import PaperTrader
from historical_backtest import load_and_resample

console = Console()

def load_config():
    config_path = Path(__file__).parent.parent / "config" / "trade_config.yaml"
    with open(config_path, 'r') as f: return yaml.safe_load(f)

def execute_engine(p5, p15, p1h, cfg, use_partial=False):
    trader = PaperTrader(ticker="TMF", initial_balance=100000)
    equity_curve = []
    has_tp1_hit = False
    
    STRAT, MGMT, RISK = cfg['strategy'], cfg['trade_mgmt'], cfg['risk_mgmt']
    PB, TP = STRAT.get('pullback', {}), STRAT.get('partial_exit', {})
    
    lots_entry = 2 if use_partial else 1
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]; price, vwap = row['Close'], row['vwap']
        
        if trader.position != 0:
            trader.update_trailing_stop(price)
            if use_partial and abs(trader.position) == 2 and not has_tp1_hit:
                pnl = (price - trader.entry_price) * (1 if trader.position > 0 else -1)
                if pnl >= TP.get('tp1_pts', 40):
                    trader.execute_signal("PARTIAL_EXIT", price, curr_time, lots=1)
                    trader.current_stop_loss = trader.entry_price
                    has_tp1_hit = True

            if trader.check_stop_loss(price, curr_time): has_tp1_hit = False
            elif RISK['exit_on_vwap']:
                if (trader.position > 0 and price < vwap and not row['opening_bullish']) or \
                   (trader.position < 0 and price > vwap and not row['opening_bearish']):
                    trader.execute_signal("EXIT", price, curr_time); has_tp1_hit = False
        
        m15 = p15[p15.index <= curr_time]
        if not m15.empty:
            score = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": m15, "1h": p1h[p1h.index <= curr_time]}, weights=STRAT['weights'])['score']
            if trader.position == 0:
                has_tp1_hit = False
                sqz_buy = (not row['sqz_on']) and score >= STRAT['entry_score'] and price > vwap and row['mom_state'] == 3
                pb_buy = p5['is_new_high'].iloc[max(0, i-12):i].any() and row['in_bull_pb_zone'] and price > row['Open'] and row['bullish_align']
                sqz_sell = (not row['sqz_on']) and score <= -STRAT['entry_score'] and price < vwap and row['mom_state'] == 0
                pb_sell = p5['is_new_low'].iloc[max(0, i-12):i].any() and row['in_bear_pb_zone'] and price < row['Open'] and row['bearish_align']
                if (sqz_buy or pb_buy): trader.execute_signal("BUY", price, curr_time, lots=lots_entry, max_lots=lots_entry, stop_loss=RISK['stop_loss_pts'], break_even_trigger=RISK['break_even_pts'])
                elif (sqz_sell or pb_sell): trader.execute_signal("SELL", price, curr_time, lots=lots_entry, max_lots=lots_entry, stop_loss=RISK['stop_loss_pts'], break_even_trigger=RISK['break_even_pts'])
            elif trader.position > 0 and (row['mom_state'] < 2 or score < 20): trader.execute_signal("EXIT", price, curr_time); has_tp1_hit = False
            elif trader.position < 0 and (row['mom_state'] > 1 or score > -20): trader.execute_signal("EXIT", price, curr_time); has_tp1_hit = False
        equity_curve.append(trader.balance + ((price - trader.entry_price) * trader.position * 10 if trader.position != 0 else 0))
    return equity_curve, trader

def run_partial_pk():
    cfg = load_config()
    console.print(f"[bold cyan]📊 Running Partial Exit PK...[/bold cyan]")
    files = sorted(Path("data/taifex_raw").glob("Daily_*.rpt"))
    all_d, all_d15, all_d1h = [], [], []
    for f in files:
        d5 = load_and_resample(f, "5min", "TMF"); d15 = load_and_resample(f, "15min", "TMF"); d1h = load_and_resample(f, "1h", "TMF")
        if d5 is not None: all_d.append(d5); all_d15.append(d15); all_d1h.append(d1h)
    
    pb = cfg['strategy']['pullback']
    p_args = {'bb_length': cfg['strategy']['length'], 'ema_fast': pb['ema_fast'], 'ema_slow': pb['ema_slow'], 'lookback': pb['lookback'], 'pb_buffer': pb['buffer']}
    
    p5 = calculate_futures_squeeze(pd.concat(all_d).sort_index(), **p_args)
    p15 = calculate_futures_squeeze(pd.concat(all_d15).sort_index(), **p_args)
    p1h = calculate_futures_squeeze(pd.concat(all_d1h).sort_index(), **p_args)

    eq_single, t_single = execute_engine(p5, p15, p1h, cfg, use_partial=False)
    eq_partial, t_partial = execute_engine(p5, p15, p1h, cfg, use_partial=True)

    table = Table(title="🏆 Partial Exit Optimization PK Results")
    table.add_column("Strategy", style="cyan"); table.add_column("Net Profit", justify="right", style="bold"); table.add_column("Trades", justify="center")
    table.add_row("Single Lot (1 lot)", f"{t_single.balance-100000:+.0f}", str(len(t_single.trades)))
    table.add_row("Partial Exit (2 lots -> 1 lot)", f"{t_partial.balance-100000:+.0f}", str(len(t_partial.trades)))
    console.print(table)

    plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(15, 8))
    ax.plot(p5.index, eq_single, color='#00CCFF', label='Single Lot', alpha=0.7)
    ax.plot(p5.index, eq_partial, color='#00FF00', label='Partial Exit (2 Lots)', linewidth=2.5)
    ax.axhline(100000, color='white', linestyle=':', alpha=0.5); ax.set_title("Equity Curve: Single Lot vs. 2-Lot Partial Exit"); ax.legend(); plt.tight_layout()
    plt.savefig("exports/simulations/partial_exit_pk.png"); os.system("open exports/simulations/partial_exit_pk.png")

if __name__ == "__main__":
    run_partial_pk()
