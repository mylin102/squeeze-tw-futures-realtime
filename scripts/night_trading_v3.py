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
# 移動停損模組 (包含冷卻時間機制)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from trailing_stop import (
    update_trailing_stop, 
    reset_trailing_stop, 
    should_update_stop,
    get_trailing_stop_status,
    STOP_LOSS_PTS, 
    TAKE_PROFIT_PTS,
    UPDATE_COOLDOWN,
    LAST_UPDATE_TIME
)

print(f"[dim]移動停損冷卻時間：{UPDATE_COOLDOWN} 秒[/dim]")
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment, calculate_atr
from squeeze_futures.report.notifier import send_email_notification


def save_bar_data(row, score, regime_desc, ticker="TMF", live_mode=False):
    """將每一棒的指標狀態存入 CSV (台北時間)"""
    import os
    import pytz
    from datetime import datetime
    
    tw_tz = pytz.timezone('Asia/Taipei')
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(base_dir, "logs", "market_data")
    os.makedirs(log_dir, exist_ok=True)
    date_str = datetime.now(tw_tz).strftime("%Y%m%d")
    # PAPER 和 LIVE 分開儲存
    mode_suffix = '_LIVE' if live_mode else '_PAPER'
    file_path = os.path.join(log_dir, f'{ticker}_{date_str}{mode_suffix}_indicators.csv')
    
    # 轉換時間為台北時間
    ts = row.name
    if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
        ts = ts.astimezone(tw_tz)
    
    data = {
        "timestamp": [ts.strftime('%Y-%m-%d %H:%M:%S')],
        "close": [row['Close']],
        "vwap": [row.get('vwap', row['Close'])],
        "score": [score],
        "sqz_on": [row.get('sqz_on', False)],
        "mom_state": [row.get('mom_state', 0)],
        "regime": [regime_desc],
        "bull_align": [row.get('bull_align', False)],
        "bear_align": [row.get('bear_align', False)],
        "in_pb_zone": [row.get('in_bull_pb_zone', False) or row.get('in_bear_pb_zone', False)]
    }
    df = pd.DataFrame(data)
    header = not os.path.exists(file_path)
    df.to_csv(file_path, mode='a', index=False, header=header)

console = Console()


def load_config(config_file: str = "config/night_config.yaml"):
    """載入配置文件"""
    # 支援絕對路徑和相對路徑
    if os.path.isabs(config_file):
        config_path = config_file
    else:
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
    LIVE_TRADING = cfg.get("live_trading", False)  # 交易模式
    
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
    shioaji.login()  # 使用配置文件中的憑證登入
    contract = shioaji.get_futures_contract(ticker)
    
    # 確認交易模式
    live_mode = cfg.get('live_trading', False)
    if live_mode:
        console.print("[bold red]🚀 LIVE TRADING - Real orders will be placed![/bold red]\n")
    else:
        console.print("[bold yellow]⚠️  PAPER TRADING - Simulated orders only[/bold yellow]\n")
    
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

                # 儲存數據
                save_bar_data(last_5m, score, last_5m.get("regime", "NORMAL"), ticker, live_mode=LIVE_TRADING)
            
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
                # 亞洲時段 (15:00-22:30): 完全禁用 TSM
                use_tsm_now = USE_TSM and STRATEGY.get("tsm_confirmation", False)
                if use_tsm_now and tsm_signal:
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
    """
    執行交易
    - PAPER 模式：使用 PaperTrader.execute_signal()
    - LIVE 模式：使用 shioaji.place_order() + 觸價單 (Stop Order)
    """
    result = None
    
    # 檢查是否為 LIVE 模式
    if LIVE_TRADING and live_ready:
        # LIVE 模式：使用永豐 API 下單
        action = None
        if signal == "BUY":
            action = "Buy"
        elif signal == "SELL":
            action = "Sell"
        elif signal in ["EXIT", "PARTIAL_EXIT"]:
            action = "Sell" if trader.position > 0 else "Buy"
        
        if action:
            console.print(f"[dim]LIVE 下單：{action} {lots} 口 @ {price:.0f}[/dim]")
            
            try:
                # 下達主單 (ROD)
                trade = shioaji.place_order(
                    contract,
                    action=action,
                    quantity=lots,
                    price=price,
                    order_type=sj.OrderType.ROD
                )
                
                if trade:
                    console.print(f"[green]✓ 主單已送出：{action} {lots} @ {price:.0f}[/green]")
                    
                    # 下達停損觸價單 (Stop Order)
                    if stop_loss and signal in ["BUY", "SELL"]:
                        stop_action = "Sell" if action == "Buy" else "Buy"
                        stop_price = stop_loss
                        
                        try:
                            # 建立 Stop Order (觸價單)
                            # 參考：https://shioaji.github.io/Shioaji/api.html#order
                            stop_order = shioaji.Order(
                            price=stop_price,      # 觸發價格
                            quantity=lots,
                            action=stop_action,
                            price_type="LMT",      # 觸發後轉為限價單
                            order_type="STP",      # 指定為 Stop Order
                            order_cond=sj.OrderCond.Futures  # 期貨單
                            )

                            # 送出訂單
                            stop_trade = shioaji.place_order(contract, stop_order)
                            if stop_order:
                                console.print(f"[green]✓ 停損觸價單已設定：{stop_price:.0f}[/green]")
                        except Exception as e:
                            console.print(f"[yellow]⚠️ 停損觸價單設定失敗：{e}[/yellow]")
                            console.print(f"[yellow]  將使用程式監控停損[/yellow]")
                    
                    result = f"Order placed: {action} {lots} @ {price:.0f}"
                    if stop_loss:
                        result += f" (SL: {stop_loss:.0f})"
                else:
                    console.print(f"[red]✗ 下單失敗[/red]")
            except Exception as e:
                console.print(f"[red]✗ 下單錯誤：{e}[/red]")
    else:
        # PAPER 模式：使用 PaperTrader
        result = trader.execute_signal(
            signal, price, ts, lots=lots,
            max_lots=2,
            stop_loss=stop_loss,
            break_even_trigger=break_even_trigger,
        )
    
    # 顯示交易結果
    if result:
        direction = "🟢 BUY" if signal == "BUY" else "🔴 SELL" if signal == "SELL" else "⚪ EXIT"
        pnl_text = ""
        pnl_value = 0
        if "PnL" in result:
            try:
                pnl_value = float(result.split("PnL: ")[-1].replace(",", ""))
                pnl_text = f"PnL: {pnl_value:+,.0f}"
            except:
                pass
        
        # 正確判斷顏色
        if pnl_value > 0:
            color = "green"
        elif pnl_value < 0:
            color = "red"
        else:
            color = "white"
        
        console.print(f"[bold {color}]{direction} @ {price:.0f} | {pnl_text}[/bold {color}]")


def check_force_close(current_time, trader, shioaji, contract):
    """
    13:45 強制平倉檢查
    避免微台指跳空開盤風險
    """
    if current_time.hour == FORCE_CLOSE_HOUR and current_time.minute >= FORCE_CLOSE_MINUTE:
        if trader.position != 0:
            console.print(f"[yellow]⏰ 收盤時間到，強制平倉...[/yellow]")
            action = "Sell" if trader.position > 0 else "Buy"
            
            # 市價平倉
            close_order = sj.Order(
                price=0,  # 市價
                quantity=abs(trader.position),
                action=sj.constant.Action.Sell if action == "Sell" else sj.constant.Action.Buy,
                price_type=sj.constant.FuturesPriceType.MKT,
                order_type=sj.constant.OrderType.ROD,
                account=shioaji.futopt_account
            )
            
            shioaji.place_order(contract, close_order)
            console.print(f"[green]✓ 已強制平倉 {abs(trader.position)} 口[/green]")
            return True
    return False

if __name__ == "__main__":
    run_night_trading("TMF")
