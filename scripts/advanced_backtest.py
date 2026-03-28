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

def execute_engine(p5, p15, p1h, cfg, filter_mode="none"):
    """
    回測引擎
    filter_mode: "none", "macro" (1h EMA 200), "mid" (15m EMA 60)
    """
    trader = PaperTrader(ticker="TMF", initial_balance=100000)
    equity_curve = []
    
    STRAT, MGMT, RISK = cfg['strategy'], cfg['trade_mgmt'], cfg['risk_mgmt']
    PB = STRAT.get('pullback', {})
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row, row_15m, row_1h = p5.iloc[i], p15[p15.index <= curr_time].iloc[-1], p1h[p1h.index <= curr_time].iloc[-1]
        price, vwap = row['Close'], row['vwap']
        
        if trader.position != 0:
            trader.update_trailing_stop(price)
            if not trader.check_stop_loss(price, curr_time):
                if RISK['exit_on_vwap']:
                    if (trader.position > 0 and price < vwap) or (trader.position < 0 and price > vwap):
                        trader.execute_signal("EXIT", price, curr_time)
        
        alignment = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": p15[p15.index <= curr_time], "1h": p1h[p1h.index <= curr_time]}, weights=STRAT['weights'])
        score = alignment['score']
        
        # --- 環境過濾 ---
        can_long, can_short = True, True
        if filter_mode == "macro":
            macro_trend = "BULL" if row_1h['Close'] > row_1h['ema_macro'] else "BEAR"
            is_sideways = abs(row_1h['Close'] - row_1h['ema_macro']) / row_1h['ema_macro'] < 0.005
            can_long, can_short = (macro_trend == "BULL" or is_sideways), (macro_trend == "BEAR" or is_sideways)
        elif filter_mode == "mid":
            mid_trend = "BULL" if row_15m['Close'] > row_15m['ema_filter'] else "BEAR"
            is_sideways = abs(row_15m['Close'] - row_15m['ema_filter']) / row_15m['ema_filter'] < 0.003
            can_long, can_short = (mid_trend == "BULL" or is_sideways), (mid_trend == "BEAR" or is_sideways)

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

        equity_curve.append(trader.balance + ((price - trader.entry_price) * trader.position * 10 if trader.position != 0 else 0))
        
    return equity_curve, trader

def run_triple_pk():
    cfg = load_config()
    console.print(f"[bold cyan]📊 Running Triple Regime Filter PK (None vs Macro vs Mid)...[/bold cyan]")
    
    files = sorted(Path("data/taifex_raw").glob("Daily_*.rpt"))
    all_5m, all_15m, all_1h = [], [], []
    for f in files:
        d5 = load_and_resample(f, "5min", "TMF"); d15 = load_and_resample(f, "15min", "TMF"); d1h = load_and_resample(f, "1h", "TMF")
        if d5 is not None: all_5m.append(d5); all_15m.append(d15); all_1h.append(d1h)
    
    pb_cfg = cfg['strategy']['pullback']
    common_args = {'bb_length': cfg['strategy']['length'], 'ema_fast': pb_cfg['ema_fast'], 'ema_slow': pb_cfg['ema_slow'], 'lookback': pb_cfg['lookback'], 'pb_buffer': pb_cfg['buffer']}
    
    p5 = calculate_futures_squeeze(pd.concat(all_5m).sort_index(), **common_args)
    p15 = calculate_futures_squeeze(pd.concat(all_15m).sort_index(), **common_args)
    p1h = calculate_futures_squeeze(pd.concat(all_1h).sort_index(), **common_args)

    results = []
    for mode in ["none", "macro", "mid"]:
        console.print(f"Testing Filter: {mode}...")
        eq, trader = execute_engine(p5, p15, p1h, cfg, filter_mode=mode)
        results.append((mode, eq, trader))

    table = Table(title="🏆 Triple Regime Filter PK Results")
    table.add_column("Filter Mode", style="cyan"); table.add_column("Net Profit", justify="right", style="bold"); table.add_column("Trades", justify="center")
    for mode, eq, trader in results:
        table.add_row(mode, f"{trader.balance-100000:+.0f}", str(len(trader.trades)))
    console.print(table)

    plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(15, 8))
    colors = {'none': '#FF00FF', 'macro': '#00CCFF', 'mid': '#00FF00'}
    for mode, eq, _ in results:
        ax.plot(p5.index, eq, color=colors[mode], label=f'Filter: {mode}', linewidth=2 if mode == 'mid' else 1.5)
    ax.axhline(100000, color='white', linestyle=':', alpha=0.5); ax.set_title("Equity PK: No Filter vs. Macro (1h) vs. Mid (15m)"); ax.legend(); plt.tight_layout()
    plt.savefig("exports/simulations/triple_filter_pk.png"); os.system("open exports/simulations/triple_filter_pk.png")

if __name__ == "__main__":
    run_triple_pk()
