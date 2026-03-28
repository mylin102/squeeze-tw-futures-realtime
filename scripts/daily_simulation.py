import sys
import os
import time
import yaml
from datetime import datetime
import pandas as pd
from rich.console import Console

# 加入 src 到路徑
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.downloader import download_futures_data
from squeeze_futures.data.shioaji_client import ShioajiClient
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.report.notifier import send_email_notification

console = Console()

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "trade_config.yaml")
    with open(config_path, 'r', encoding='utf-8') as f: return yaml.safe_load(f)

def check_funds_for_live(shioaji, lots, min_margin_per_lot=25000):
    available = shioaji.get_available_margin()
    required = lots * min_margin_per_lot
    if available < required:
        msg = f"❌ [FUND ALERT] Insufficient Funds! Required: {required:,.0f}"
        console.print(f"[bold red]{msg}[/bold red]")
        send_email_notification("CRITICAL: Insufficient Funds", msg, f"<h2 style='color:red;'>{msg}</h2>")
        return False
    return True

def get_market_status():
    now = datetime.now()
    weekday, current_time = now.weekday(), now.hour * 100 + now.minute
    is_day = (0 <= weekday <= 4) and (845 <= current_time < 1345)
    is_night = ((0 <= weekday <= 4) and (current_time >= 1500)) or ((1 <= weekday <= 5) and (current_time < 500))
    is_near_close = (is_day and current_time >= 1340) or (is_night and current_time >= 455)
    return {"open": is_day or is_night, "near_close": is_near_close}

def run_simulation(ticker="TMF"):
    cfg = load_config()
    LIVE_TRADING, STRATEGY, MGMT, RISK = cfg['live_trading'], cfg['strategy'], cfg['trade_mgmt'], cfg['risk_mgmt']
    PB = STRATEGY.get('pullback', {})
    SCALE = STRATEGY.get('scale_in', {'enabled': False})

    trader = PaperTrader(ticker=ticker)
    shioaji = ShioajiClient()
    shioaji.login()
    contract = shioaji.get_futures_contract(ticker)
    
    console.print(f"🚀 Squeeze Trader Started - Mode: {'LIVE' if LIVE_TRADING else 'PAPER'}")
    
    # 紀錄單次趨勢是否已加碼
    has_scaled_in = False

    try:
        while True:
            market = get_market_status()
            if not market["open"]:
                if trader.position != 0: trader.execute_signal("EXIT", trader.entry_price, datetime.now())
                time.sleep(300); continue

            # 1. 抓取數據
            processed_data = {}
            for tf in ["5m", "15m", "1h"]:
                df = shioaji.get_kline(ticker, interval=tf)
                if df.empty: df = download_futures_data("^TWII", interval=tf, period="5d")
                if not df.empty:
                    processed_data[tf] = calculate_futures_squeeze(df, bb_length=STRATEGY["length"], **PB)
            
            if "5m" not in processed_data: continue
            df_5m = processed_data["5m"]
            last_5m = df_5m.iloc[-1]
            alignment = calculate_mtf_alignment(processed_data, weights=STRATEGY["weights"])
            score, last_price, vwap = alignment['score'], last_5m['Close'], last_5m['vwap']
            timestamp = last_5m.name
            
            log_msg, real_action = "", None
            
            # --- 2. 風控與加碼監控 ---
            if trader.position != 0:
                trader.update_trailing_stop(last_price)
                
                # 🚀 獲利加碼邏輯 (Scale-in)
                if SCALE['enabled'] and abs(trader.position) == 1 and not has_scaled_in:
                    pnl_pts = (last_price - trader.entry_price) * (1 if trader.position > 0 else -1)
                    if pnl_pts >= SCALE['profit_trigger']:
                        # 確認趨勢方向仍正確
                        still_strong = (trader.position > 0 and score > 50) or (trader.position < 0 and score < -50)
                        if still_strong:
                            lots_to_add = MGMT["lots_per_trade"]
                            if not LIVE_TRADING or check_funds_for_live(shioaji, lots_to_add):
                                action = "BUY" if trader.position > 0 else "SELL"
                                msg = trader.execute_signal(action, last_price, timestamp, lots=lots_to_add, max_lots=SCALE['max_lots'])
                                if msg:
                                    log_msg = "[SCALE-IN] " + msg; real_action = action.capitalize()
                                    has_scaled_in = True
                                    # 加碼後自動將停損移至最初進場價 (Break-even for full position)
                                    trader.current_stop_loss = trader.entry_price
                
                # 檢查停損
                stop_msg = trader.check_stop_loss(last_price, timestamp)
                if not stop_msg and RISK["exit_on_vwap"]:
                    if (trader.position > 0 and last_price < vwap and not last_5m['opening_bullish']) or \
                       (trader.position < 0 and last_price > vwap and not last_5m['opening_bearish']):
                        stop_msg = trader.execute_signal("EXIT", last_price, timestamp); stop_msg = "[VWAP] " + stop_msg
                
                if stop_msg: log_msg, real_action = stop_msg, ("Sell" if trader.position > 0 else "Buy"); has_scaled_in = False

            # --- 3. 進場邏輯 ---
            if not log_msg and trader.position == 0:
                has_scaled_in = False # 重設加碼旗標
                sqz_buy = (not last_5m['sqz_on']) and score >= STRATEGY["entry_score"] and last_price > vwap and last_5m['mom_state'] == 3
                pb_buy = df_5m['is_new_high'].tail(12).any() and last_5m['in_bull_pb_zone'] and last_price > last_5m['Open']
                sqz_sell = (not last_5m['sqz_on']) and score <= -STRATEGY["entry_score"] and last_price < vwap and last_5m['mom_state'] == 0
                pb_sell = df_5m['is_new_low'].tail(12).any() and last_5m['in_bear_pb_zone'] and last_price < last_5m['Open']

                # 環境過濾
                can_long = (last_5m['Close'] > processed_data['15m'].iloc[-1]['ema_filter'] or last_5m['opening_bullish'])
                can_short = (last_5m['Close'] < processed_data['15m'].iloc[-1]['ema_filter'] or last_5m['opening_bearish'])

                if (sqz_buy or pb_buy) and can_long and MGMT["allow_long"]:
                    if not LIVE_TRADING or check_funds_for_live(shioaji, MGMT["lots_per_trade"]):
                        log_msg = trader.execute_signal("BUY", last_price, timestamp, lots=MGMT["lots_per_trade"], max_lots=MGMT["max_positions"], stop_loss=RISK["stop_loss_pts"], break_even_trigger=RISK["break_even_pts"])
                        log_msg = f"[{'Sqz' if sqz_buy else 'PB'}] " + log_msg; real_action = "Buy"
                elif (sqz_sell or pb_sell) and can_short and MGMT["allow_short"]:
                    if not LIVE_TRADING or check_funds_for_live(shioaji, MGMT["lots_per_trade"]):
                        log_msg = trader.execute_signal("SELL", last_price, timestamp, lots=MGMT["lots_per_trade"], max_lots=MGMT["max_positions"], stop_loss=RISK["stop_loss_pts"], break_even_trigger=RISK["break_even_pts"])
                        log_msg = f"[{'Sqz' if sqz_sell else 'PB'}] " + log_msg; real_action = "Sell"

            if log_msg:
                console.print(f"[bold yellow][{timestamp}] {log_msg}[/bold yellow]")
                if LIVE_TRADING and real_action and contract: shioaji.place_order(contract, real_action, MGMT["lots_per_trade"])
                send_email_notification(f"TRADE ALERT: {ticker}", log_msg, f"<h3>{log_msg}</h3>")
            
            sl_info = f"SL:{trader.current_stop_loss:.0f}" if trader.current_stop_loss else "None"
            console.print(f"[{datetime.now().strftime('%H:%M:%S')}] Price: {last_price:.1f} | Score: {score:.1f} | Pos: {trader.position} ({sl_info})", end="\r")
            time.sleep(30)

    except KeyboardInterrupt: pass
    finally: trader.save_report(); shioaji.logout()

if __name__ == "__main__":
    run_simulation("TMF")
