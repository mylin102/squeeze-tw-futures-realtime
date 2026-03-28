#!/usr/bin/env python3
import sys
import os
import yaml
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
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

def execute_engine(p5, p15, p1h, cfg, use_mid_f=False, use_open_f=False):
    """
    回測引擎
    use_mid_f: 是否啟動 15m EMA 60 過濾
    use_open_f: 是否啟動 開盤強弱過濾
    """
    trader = PaperTrader(ticker="TMF", initial_balance=100000)
    equity_curve = []
    
    STRAT, MGMT, RISK = cfg['strategy'], cfg['trade_mgmt'], cfg['risk_mgmt']
    PB = STRAT.get('pullback', {})
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row, row_15m = p5.iloc[i], p15[p15.index <= curr_time].iloc[-1]
        price, vwap = row['Close'], row['vwap']
        
        # --- 1. 風控 ---
        if trader.position != 0:
            trader.update_trailing_stop(price)
            if not trader.check_stop_loss(price, curr_time):
                # 加入開盤法對 VWAP 停損的放寬邏輯
                opening_strong = row['opening_bullish']
                opening_weak = row['opening_bearish']
                if RISK['exit_on_vwap']:
                    if (trader.position > 0 and price < vwap and not (use_open_f and opening_strong)) or \
                       (trader.position < 0 and price > vwap and not (use_open_f and opening_weak)):
                        trader.execute_signal("EXIT", price, curr_time)
        
        # --- 2. 進場判定 ---
        alignment = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": p15[p15.index <= curr_time], "1h": p1h[p1h.index <= curr_time]}, weights=STRAT['weights'])
        score = alignment['score']
        
        # 環境過濾
        can_long, can_short = True, True
        if use_mid_f:
            mid_trend = "BULL" if row_15m['Close'] > row_15m['ema_filter'] else "BEAR"
            is_sideways = abs(row_15m['Close'] - row_15m['ema_filter']) / row_15m['ema_filter'] < 0.003
            can_long, can_short = (mid_trend == "BULL" or is_sideways), (mid_trend == "BEAR" or is_sideways)
        
        if use_open_f:
            if row['opening_bullish']: can_short = False
            if row['opening_bearish']: can_long = False

        if trader.position == 0:
            sqz_buy = (not row['sqz_on']) and score >= STRAT['entry_score'] and price > vwap and row['mom_state'] == 3
            sqz_sell = (not row['sqz_on']) and score <= -STRAT['entry_score'] and price < vwap and row['mom_state'] == 0
            lb = PB.get('lookback', 60) // 5
            pb_buy = p5['is_new_high'].iloc[max(0, i-lb):i].any() and row['in_bull_pb_zone'] and price > row['Open'] and row['bullish_align']
            pb_sell = p5['is_new_low'].iloc[max(0, i-lb):i].any() and row['in_bear_pb_zone'] and price < row['Open'] and row['bearish_align']

            if (sqz_buy or pb_buy) and can_long:
                trader.execute_signal("BUY", price, curr_time, lots=MGMT['lots_per_trade'], max_lots=MGMT['max_positions'], stop_loss=RISK['stop_loss_pts'], break_even_trigger=RISK['break_even_pts'])
            elif (sqz_sell or pb_sell) and can_short:
                trader.execute_signal("SELL", price, curr_time, lots=MGMT['lots_per_trade'], max_lots=MGMT['max_positions'], stop_loss=RISK['stop_loss_pts'], break_even_trigger=RISK['break_even_pts'])
        
        elif trader.position > 0 and (row['mom_state'] < 2 or score < 20):
            trader.execute_signal("EXIT", price, curr_time)
        elif trader.position < 0 and (row['mom_state'] > 1 or score > -20):
            trader.execute_signal("EXIT", price, curr_time)

        cur_eq = trader.balance + ((price - trader.entry_price) * trader.position * 10 if trader.position != 0 else 0)
        equity_curve.append(cur_eq)
        
    return equity_curve, trader

def run_ultimate_pk():
    cfg = load_config()
    console.print(f"[bold cyan]📊 Running Ultimate Evolution PK (None vs Mid vs Mid+Open)...[/bold cyan]")
    
    files = sorted(Path("data/taifex_raw").glob("Daily_*.rpt"))
    all_d, all_d15, all_d1h = [], [], []
    for f in files:
        d5 = load_and_resample(f, "5min", "TMF"); d15 = load_and_resample(f, "15min", "TMF"); d1h = load_and_resample(f, "1h", "TMF")
        if d5 is not None: all_d.append(d5); all_d15.append(d15); all_d1h.append(d1h)
    
    pb_cfg = cfg['strategy']['pullback']
    common_args = {'bb_length': cfg['strategy']['length'], 'ema_fast': pb_cfg['ema_fast'], 'ema_slow': pb_cfg['ema_slow'], 'lookback': pb_cfg['lookback'], 'pb_buffer': pb_cfg['buffer']}
    
    p5 = calculate_futures_squeeze(pd.concat(all_d).sort_index(), **common_args)
    p15 = calculate_futures_squeeze(pd.concat(all_d15).sort_index(), **common_args)
    p1h = calculate_futures_squeeze(pd.concat(all_d1h).sort_index(), **common_args)

    modes = [("Basic Hybrid", False, False), ("Mid Filter", True, False), ("🚀 Mid + Open Filter", True, True)]
    results = []
    for name, mid, op in modes:
        console.print(f"Testing: {name}...")
        eq, t = execute_engine(p5, p15, p1h, cfg, use_mid_f=mid, use_open_f=op)
        results.append((name, eq, t))

    table = Table(title="🏆 Ultimate Strategy PK Results")
    table.add_column("Strategy", style="cyan"); table.add_column("Net Profit", justify="right", style="bold"); table.add_column("Trades", justify="center")
    for name, eq, t in results:
        table.add_row(name, f"{t.balance-100000:+.0f}", str(len(t.trades)))
    console.print(table)

    plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(15, 8))
    clrs = ['#FF00FF', '#00CCFF', '#00FF00']
    for i, (name, eq, _) in enumerate(results):
        ax.plot(p5.index, eq, color=clrs[i], label=name, linewidth=2 if i==2 else 1.5)
    ax.axhline(100000, color='white', linestyle=':', alpha=0.5); ax.set_title("Strategy Evolution: Impact of Opening Regime Filter"); ax.legend(); plt.tight_layout()
    plt.savefig("exports/simulations/ultimate_pk.png"); os.system("open exports/simulations/ultimate_pk.png")

if __name__ == "__main__":
    run_ultimate_pk()
