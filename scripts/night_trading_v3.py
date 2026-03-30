#!/usr/bin/env python3
"""
夜盤交易系統 v3.0
改進：
1. 使用 TSM (台積電 ADR) 作為進場確認
2. 夜盤專屬參數配置
3. 時間過濾優化
"""

import sys
import os
import time
import yaml
from datetime import datetime
import pandas as pd
from rich.console import Console

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.shioaji_client import ShioajiClient
from squeeze_futures.data.tsm_client import download_tsm_data, calculate_tsm_indicators, get_tsm_signal, print_tsm_report
from squeeze_futures.engine.constants import get_point_value
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment, calculate_atr
from squeeze_futures.report.notifier import send_email_notification

console = Console()


def load_config(config_file: str = "config/night_config.yaml"):
    """載入配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), "..", config_file)
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def is_night_session(timestamp: datetime = None) -> bool:
    """
    判斷是否為夜盤時段
    
    夜盤：15:00-05:00 (台北時間)
    """
    if timestamp is None:
        timestamp = datetime.now()
    
    hour = timestamp.hour
    return hour >= 15 or hour < 5


def should_skip_trading(timestamp: datetime, skip_hours: list) -> bool:
    """時間過濾：跳過指定時段"""
    return timestamp.hour in skip_hours


def run_night_trading(ticker: str = "TMF"):
    """夜盤交易系統"""
    cfg = load_config("config/night_config.yaml")
    
    # 解構配置
    STRATEGY = cfg['strategy']
    MGMT = cfg['trade_mgmt']
    RISK = cfg['risk_mgmt']
    EXEC = cfg['execution']
    MONITOR = cfg['monitoring']
    TSM_CFG = cfg.get('tsm_config', {})
    
    PB, TP = STRATEGY.get('pullback', {}), STRATEGY.get('partial_exit', {})
    
    # 夜盤專屬參數
    ENTRY_SCORE = STRATEGY.get('entry_score', 40)
    STOP_LOSS_PTS = RISK.get('stop_loss_pts', 80)
    BREAK_EVEN_PTS = RISK.get('break_even_pts', 50)
    EXIT_ON_VWAP = RISK.get('exit_on_vwap', False)
    
    # TSM 確認
    USE_TSM = TSM_CFG.get('enabled', True)
    TSM_MIN_CONFIDENCE = TSM_CFG.get('min_confidence', 0.6)
    
    # 移動停損
    TRAILING_STOP = RISK.get('trailing_stop_enabled', True)
    TRAILING_TRIGGER = RISK.get('trailing_stop_trigger_pts', 50)
    TRAILING_DISTANCE = RISK.get('trailing_stop_distance_pts', 25)
    
    # 時間過濾
    TIME_FILTER = RISK.get('time_filter_enabled', True)
    SKIP_HOURS = RISK.get('skip_hours', [])
    MAX_HOLDING_MINS = RISK.get('max_holding_time_mins', 120)
    
    # 成本參數
    INITIAL_BALANCE = EXEC.get('initial_balance', 100000)
    FEE_PER_SIDE = EXEC.get('broker_fee_per_side', 20)
    EXCHANGE_FEE = EXEC.get('exchange_fee_per_side', 0)
    TAX_RATE = EXEC.get('tax_rate', 0.0)
    
    # 監控參數
    POLL_INTERVAL = MONITOR.get('poll_interval_secs', 60)
    PB_CONFIRM_BARS = MONITOR.get('pb_confirmation_bars', 12)
    
    # 初始化
    console.print(f"\n[bold cyan]╔{'═' * 70}╗[/bold cyan]")
    console.print(f"[bold cyan]║[/bold cyan]  [bold white]NIGHT TRADING SYSTEM v3.0[/bold white]  {' ' * 32}[bold cyan]║[/bold cyan]")
    console.print(f"[bold cyan]╚{'═' * 70}╝[/bold cyan]\n")
    
    console.print("[bold]🌙 夜盤專屬配置:[/bold]")
    console.print(f"  • Entry Score: {ENTRY_SCORE}")
    console.print(f"  • Stop Loss: {STOP_LOSS_PTS} pts")
    console.print(f"  • Take Profit: {TP.get('tp1_pts', 60)} pts")
    console.print(f"  • TSM Confirmation: {'✓ Enabled' if USE_TSM else '✗ Disabled'}")
    console.print(f"  • Trailing Stop: {'✓ Enabled' if TRAILING_STOP else '✗ Disabled'}")
    console.print(f"  • Max Holding: {MAX_HOLDING_MINS} mins\n")
    
    # 初始化交易器
    trader = PaperTrader(
        ticker=ticker,
        initial_balance=INITIAL_BALANCE,
        point_value=get_point_value(ticker),
        fee_per_side=FEE_PER_SIDE,
        exchange_fee_per_side=EXCHANGE_FEE,
        tax_rate=TAX_RATE
    )
    
    # 初始化 Shioaji
    shioaji = ShioajiClient()
    shioaji.login()
    contract = shioaji.get_futures_contract(ticker)
    
    console.print(f"[bold green]🚀 Night Trader Started - Mode: PAPER[/bold green]\n")
    
    # 下載 TSM 數據
    tsm_df = None
    tsm_signal = None
    
    if USE_TSM:
        console.print("[dim]下載 TSM 數據...[/dim]")
        tsm_df = download_tsm_data(period=TSM_CFG.get('period', '5d'), interval=TSM_CFG.get('interval', '5m'))
        
        if tsm_df is not None:
            tsm_df = calculate_tsm_indicators(tsm_df)
            tsm_signal = get_tsm_signal(tsm_df)
            
            console.print(f"[dim]TSM Signal: {tsm_signal['signal']} (confidence: {tsm_signal['confidence']:.0%})[/dim]\n")
    
    has_tp1_hit = False
    last_processed_bar = None
    entry_time = None
    
    try:
        while True:
            current_time = datetime.now()
            
            # 檢查是否為夜盤時段
            if not is_night_session(current_time):
                if trader.position != 0:
                    console.print(f"\n[yellow]☀️  Day session started, closing position...[/yellow]")
                    execute_trade("EXIT", trader.entry_price, current_time, abs(trader.position), trader)
                
                console.print(f"\n[{current_time.strftime('%H:%M:%S')}] Night session ended. Shutting down...")
                trader.save_report()
                shioaji.logout()
                console.print("[green]✓ Night trader shutdown complete.[/green]")
                break
            
            # 時間過濾檢查
            if TIME_FILTER and should_skip_trading(current_time, SKIP_HOURS):
                console.print(f"[dim][{current_time.strftime('%H:%M')}] Skipping trading (filtered hour)[/dim]")
                time.sleep(POLL_INTERVAL)
                continue
            
            # 1. 抓取數據
            processed_data = {}
            for tf in ["5m", "15m", "1h"]:
                df = shioaji.get_kline(ticker, interval=tf)
                if df.empty:
                    # Fallback 到 yfinance
                    from squeeze_futures.data.downloader import download_futures_data
                    df = download_futures_data("^TWII", interval=tf, period="5d")
                if not df.empty:
                    processed_data[tf] = calculate_futures_squeeze(
                        df, 
                        bb_length=STRATEGY["length"],
                        **{
                            'ema_fast': PB.get('ema_fast', 20),
                            'ema_slow': PB.get('ema_slow', 60),
                            'lookback': PB.get('lookback', 60),
                            'pb_buffer': PB.get('buffer', 1.002)
                        }
                    )
            
            if "5m" not in processed_data or "15m" not in processed_data:
                time.sleep(POLL_INTERVAL)
                continue
            
            df_5m, df_15m = processed_data["5m"], processed_data["15m"]
            last_5m, last_15m = df_5m.iloc[-1], df_15m.iloc[-1]
            score = calculate_mtf_alignment(processed_data, weights=STRATEGY["weights"])['score']
            last_price = last_5m['Close']
            vwap = last_5m.get('vwap', last_price)
            timestamp = last_5m.name
            
            # 記錄數據
            if last_processed_bar != timestamp:
                last_processed_bar = timestamp
                console.print(f"[dim]Bar logged: {timestamp}[/dim]")
            
            # 2. 風控與分批平倉
            if trader.position != 0:
                # 檢查持倉時間
                if entry_time and MAX_HOLDING_MINS > 0:
                    holding_mins = (current_time - entry_time).total_seconds() / 60
                    if holding_mins >= MAX_HOLDING_MINS:
                        console.print(f"[yellow]⏰ Max holding time reached ({holding_mins:.0f} mins)[/yellow]")
                        execute_trade("EXIT", last_price, timestamp, abs(trader.position), trader)
                        continue
                
                # 移動停損
                if TRAILING_STOP:
                    if trader.position > 0:
                        unrealized_pts = last_price - trader.entry_price
                    else:
                        unrealized_pts = trader.entry_price - last_price
                    
                    if unrealized_pts >= TRAILING_TRIGGER:
                        if trader.position > 0:
                            new_stop = last_price - TRAILING_DISTANCE
                            if trader.current_stop_loss is None or new_stop > trader.current_stop_loss:
                                trader.current_stop_loss = new_stop
                        else:
                            new_stop = last_price + TRAILING_DISTANCE
                            if trader.current_stop_loss is None or new_stop < trader.current_stop_loss:
                                trader.current_stop_loss = new_stop
                
                # 分批停利
                if TP.get('enabled', True) and abs(trader.position) == MGMT.get('lots_per_trade', 1) and not has_tp1_hit:
                    pnl_pts = (last_price - trader.entry_price) * (1 if trader.position > 0 else -1)
                    if pnl_pts >= TP.get('tp1_pts', 60):
                        execute_trade("PARTIAL_EXIT", last_price, timestamp, TP.get('tp1_lots', 1), trader)
                        has_tp1_hit = True
                        trader.current_stop_loss = trader.entry_price
                
                # 停損檢查
                if trader.position > 0 and trader.current_stop_loss and last_price <= trader.current_stop_loss:
                    execute_trade("EXIT", trader.current_stop_loss, timestamp, abs(trader.position), trader)
                elif trader.position < 0 and trader.current_stop_loss and last_price >= trader.current_stop_loss:
                    execute_trade("EXIT", trader.current_stop_loss, timestamp, abs(trader.position), trader)
            
            # 3. 進場邏輯
            if trader.position == 0:
                has_tp1_hit = False
                entry_time = None
                
                # 【關鍵改進】TSM 信號確認
                tsm_confirmed = True
                if USE_TSM and tsm_signal:
                    # 重新獲取最新 TSM 信號
                    tsm_signal = get_tsm_signal(tsm_df)
                    
                    if tsm_signal['confidence'] < TSM_MIN_CONFIDENCE:
                        tsm_confirmed = False
                        console.print(f"[dim]TSM confidence too low: {tsm_signal['confidence']:.0%} < {TSM_MIN_CONFIDENCE:.0%}[/dim]")
                    
                    # 檢查 TSM 趨勢與台指期方向是否一致
                    if tsm_confirmed:
                        tsm_trend = tsm_signal['trend']
                        twii_trend = 1 if score > 0 else -1 if score < 0 else 0
                        
                        if tsm_trend != twii_trend:
                            tsm_confirmed = False
                            console.print(f"[dim]TSM-TWII trend divergence[/dim]")
                
                if not tsm_confirmed:
                    time.sleep(POLL_INTERVAL)
                    continue
                
                # 計算停損點數
                stop_loss_pts = STOP_LOSS_PTS
                
                # 進場條件 (夜盤版)
                sqz_buy = (
                    (not last_5m.get('sqz_on', True)) and
                    score >= ENTRY_SCORE and
                    last_price > vwap and
                    last_5m.get('mom_state', 0) >= 1
                )
                
                pb_buy = (
                    df_5m.get('is_new_high', pd.Series([False])).tail(PB_CONFIRM_BARS).any() and
                    last_5m.get('in_bull_pb_zone', False) and
                    last_price > last_5m.get('Open', last_price)
                )
                
                sqz_sell = (
                    (not last_5m.get('sqz_on', True)) and
                    score <= -ENTRY_SCORE and
                    last_price < vwap and
                    last_5m.get('mom_state', 0) <= 1
                )
                
                pb_sell = (
                    df_5m.get('is_new_low', pd.Series([False])).tail(PB_CONFIRM_BARS).any() and
                    last_5m.get('in_bear_pb_zone', False) and
                    last_price < last_5m.get('Open', last_price)
                )
                
                # 趨勢過濾 (夜盤放寬)
                can_long = True  # 夜盤不強制趨勢過濾
                can_short = True
                
                if (sqz_buy or pb_buy) and can_long and MGMT.get("allow_long", True):
                    entry_time = current_time
                    execute_trade("BUY", last_price, timestamp, MGMT.get("lots_per_trade", 1), trader, stop_loss_pts, BREAK_EVEN_PTS)
                elif (sqz_sell or pb_sell) and can_short and MGMT.get("allow_short", True):
                    entry_time = current_time
                    execute_trade("SELL", last_price, timestamp, MGMT.get("lots_per_trade", 1), trader, stop_loss_pts, BREAK_EVEN_PTS)
            
            time.sleep(POLL_INTERVAL)
    
    except KeyboardInterrupt:
        pass
    finally:
        trader.save_report()
        shioaji.logout()


def execute_trade(signal: str, price: float, ts, lots: int, trader, stop_loss=None, break_even_trigger=None):
    """執行交易"""
    result = trader.execute_signal(
        signal, price, ts, lots=lots,
        max_lots=2,
        stop_loss=stop_loss,
        break_even_trigger=break_even_trigger,
    )
    
    if result:
        direction = "🟢 BUY" if signal == "BUY" else "🔴 SELL" if signal == "SELL" else "⚪ EXIT"
        pnl_text = ""
        if "PnL" in result:
            pnl_text = f"PnL: {result.split('PnL: ')[-1]}"
        
        console.print(f"[bold {'green' if 'PnL' not in result or float(result.split('PnL: ')[-1].replace(',', '')) > 0 else 'red'}]"
                     f"{direction} @ {price:.0f} | {pnl_text}[/bold {'green' if 'PnL' not in result or float(result.split('PnL: ')[-1].replace(',', '')) > 0 else 'red'}]")


if __name__ == "__main__":
    run_night_trading("TMF")
