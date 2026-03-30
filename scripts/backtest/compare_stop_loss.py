#!/usr/bin/env python3
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from rich.console import Console
from rich.table import Table

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment

console = Console()

def load_data(data_dir="data/taifex_raw"):
    from historical_backtest import load_and_resample
    files = sorted(Path(data_dir).glob("Daily_*.rpt"))
    all_5m, all_15m, all_1h = [], [], []
    for f in files:
        d5 = load_and_resample(f, "5min", "TMF")
        d15 = load_and_resample(f, "15min", "TMF")
        d1h = load_and_resample(f, "1h", "TMF")
        if d5 is not None: all_5m.append(d5)
        if d15 is not None: all_15m.append(d15)
        if d1h is not None: all_1h.append(d1h)
    return pd.concat(all_5m).sort_index(), pd.concat(all_15m).sort_index(), pd.concat(all_1h).sort_index()

def run_backtest_with_config(data_5m, data_15m, data_1h, sl_pts):
    trader = PaperTrader(ticker="TMF_SL_TEST")
    length = 14
    entry_score = 60
    weights = {"1h": 0.2, "15m": 0.4, "5m": 0.4}
    
    # 策略設定：SL 點數同時作為保本門檻 (1:1 邏輯)
    be_trigger = sl_pts 
    
    p5 = calculate_futures_squeeze(data_5m, bb_length=length, kc_length=length)
    p15 = calculate_futures_squeeze(data_15m, bb_length=length, kc_length=length)
    p1h = calculate_futures_squeeze(data_1h, bb_length=length, kc_length=length)
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]
        price = row['Close']
        vwap = row['vwap']
        
        if trader.position != 0:
            trader.update_trailing_stop(price)
            stop_msg = trader.check_stop_loss(price, curr_time)
            if not stop_msg: # VWAP 結構停損
                if (trader.position > 0 and price < vwap) or (trader.position < 0 and price > vwap):
                    trader.execute_signal("EXIT", price, curr_time)
        
        m15 = p15[p15.index <= curr_time]
        m1h = p1h[p1h.index <= curr_time]
        if m15.empty or m1h.empty: continue
        alignment = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": m15, "1h": m1h}, weights=weights)
        score = alignment['score']
        
        if trader.position == 0 and (not row['sqz_on']):
            if score >= entry_score and price > vwap and row['mom_state'] == 3:
                trader.execute_signal("BUY", price, curr_time, stop_loss=sl_pts, break_even_trigger=be_trigger)
            elif score <= -entry_score and price < vwap and row['mom_state'] == 0:
                trader.execute_signal("SELL", price, curr_time, stop_loss=sl_pts, break_even_trigger=be_trigger)
        elif trader.position > 0 and (row['mom_state'] < 2 or score < 20):
            trader.execute_signal("EXIT", price, curr_time)
        elif trader.position < 0 and (row['mom_state'] > 1 or score > -20):
            trader.execute_signal("EXIT", price, curr_time)
                
    return {
        "sl": sl_pts, "pnl": trader.balance - 100000, "trades": len(trader.trades),
        "win_rate": (pd.DataFrame(trader.trades)['pnl_cash'] > 0).mean() * 100 if trader.trades else 0
    }

if __name__ == "__main__":
    console.print("[bold yellow]Loading historical data for SL Sweep...[/bold yellow]")
    d5, d15, d1h = load_data()
    
    sl_options = [20, 30, 40, 50, 60, 80]
    results = []
    
    for sl in sl_options:
        res = run_backtest_with_config(d5, d15, d1h, sl)
        results.append(res)
        console.print(f"Tested SL:{sl} => PnL: {res['pnl']:+g}")

    df_res = pd.DataFrame(results).sort_values("pnl", ascending=False)
    
    table = Table(title="🎯 Detailed Stop-Loss Sweep Results (Mode: BE + VWAP)")
    table.add_column("Stop-Loss (pts)", justify="center", style="cyan")
    table.add_column("PnL (TWD)", justify="right", style="bold")
    table.add_column("Trades", justify="center")
    table.add_column("Win Rate", justify="right")
    
    for _, r in df_res.iterrows():
        color = "green" if r['pnl'] > 0 else "red"
        table.add_row(
            str(r['sl']), f"[{color}]{r['pnl']:+,.0f}[/{color}]", 
            str(int(r['trades'])), f"{r['win_rate']:.1f}%"
        )
    console.print("\n", table)
