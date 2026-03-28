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
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def check_funds_for_live(shioaji, lots, min_margin_per_lot=25000):
    available = shioaji.get_available_margin()
    required = lots * min_margin_per_lot
    if available < required:
        msg = f"❌ [FUND ALERT] Insufficient Funds! Available: {available:,.0f}, Required: {required:,.0f}"
        console.print(f"[bold red]{msg}[/bold red]")
        send_email_notification("CRITICAL: Insufficient Funds", msg, f"<h2 style='color:red;'>{msg}</h2>")
        return False
    return True

def get_market_status():
    now = datetime.now()
    weekday = now.weekday()
    current_time = now.hour * 100 + now.minute
    is_day = (0 <= weekday <= 4) and (845 <= current_time < 1345)
    is_night = False
    if (0 <= weekday <= 4) and (current_time >= 1500): is_night = True
    if (1 <= weekday <= 5) and (current_time < 500): is_night = True
    is_near_close = (is_day and current_time >= 1340) or (is_night and current_time >= 455)
    return {"open": is_day or is_night, "near_close": is_near_close}

def run_simulation(ticker="TMF"):
    cfg = load_config()
    LIVE_TRADING, STRATEGY, MGMT, RISK = cfg['live_trading'], cfg['strategy'], cfg['trade_mgmt'], cfg['risk_mgmt']
    PB = STRATEGY.get('pullback', {})
    FILTER_MODE = STRATEGY.get('regime_filter', 'mid')

    trader = PaperTrader(ticker=ticker)
    shioaji = ShioajiClient()
    use_shioaji = shioaji.login()
    contract = shioaji.get_futures_contract(ticker) if use_shioaji else None
    
    console.print(f"🚀 Squeeze Trader Started - Mode: {'LIVE' if LIVE_TRADING else 'PAPER'} | Filter: {FILTER_MODE}")

    try:
        while True:
            market = get_market_status()
            if not market["open"]:
                if trader.position != 0: trader.execute_signal("EXIT", trader.entry_price, datetime.now())
                time.sleep(300); continue

            processed_data = {}
            for tf in ["5m", "15m", "1h"]:
                df = shioaji.get_kline(ticker, interval=tf) if use_shioaji else pd.DataFrame()
                if df.empty: df = download_futures_data("^TWII", interval=tf, period="5d")
                if not df.empty:
                    processed_data[tf] = calculate_futures_squeeze(df, bb_length=STRATEGY["length"], **PB)
            
            if "5m" not in processed_data or "15m" not in processed_data or "1h" not in processed_data: continue
            df_5m, df_15m, df_1h = processed_data["5m"], processed_data["15m"], processed_data["1h"]
            last_5m, last_15m, last_1h = df_5m.iloc[-1], df_15m.iloc[-1], df_1h.iloc[-1]
            
            alignment = calculate_mtf_alignment(processed_data, weights=STRATEGY["weights"])
            score, last_price, vwap = alignment['score'], last_5m['Close'], last_5m['vwap']
            timestamp = last_5m.name if hasattr(last_5m, 'name') else datetime.now()
            
            # --- 🚀 市場環境過濾 (Regime Filter) ---
            can_long, can_short = True, True
            regime_desc = "NONE"
            
            if FILTER_MODE == "macro":
                macro_trend = "BULL" if last_1h['Close'] > last_1h['ema_macro'] else "BEAR"
                is_sideways = abs(last_1h['Close'] - last_1h['ema_macro']) / last_1h['ema_macro'] < 0.005
                can_long, can_short = (macro_trend == "BULL" or is_sideways), (macro_trend == "BEAR" or is_sideways)
                regime_desc = f"MACRO:{macro_trend}"
            elif FILTER_MODE == "mid":
                mid_trend = "BULL" if last_15m['Close'] > last_15m['ema_filter'] else "BEAR"
                is_sideways = abs(last_15m['Close'] - last_15m['ema_filter']) / last_15m['ema_filter'] < 0.003
                can_long, can_short = (mid_trend == "BULL" or is_sideways), (mid_trend == "BEAR" or is_sideways)
                regime_desc = f"MID:{mid_trend}"

            log_msg, real_action = "", None
            
            # --- 2. 風控監控 ---
            if trader.position != 0:
                trader.update_trailing_stop(last_price)
                stop_msg = trader.check_stop_loss(last_price, timestamp)
                if not stop_msg and RISK["exit_on_vwap"]:
                    if (trader.position > 0 and last_price < vwap) or (trader.position < 0 and last_price > vwap):
                        stop_msg = trader.execute_signal("EXIT", last_price, timestamp); stop_msg = "[VWAP] " + stop_msg
                if not stop_msg and market["near_close"] and MGMT["force_close_at_end"]:
                    stop_msg = trader.execute_signal("EXIT", last_price, timestamp); stop_msg = "[EOD] " + stop_msg
                if stop_msg: log_msg, real_action = stop_msg, ("Sell" if trader.position > 0 else "Buy")

            # --- 3. 進場邏輯 ---
            if not log_msg and trader.position == 0:
                sqz_buy = STRATEGY.get('use_squeeze', True) and (not last_5m['sqz_on']) and score >= STRATEGY["entry_score"] and last_price > vwap and last_5m['mom_state'] == 3
                sqz_sell = STRATEGY.get('use_squeeze', True) and (not last_5m['sqz_on']) and score <= -STRATEGY["entry_score"] and last_price < vwap and last_5m['mom_state'] == 0
                pb_buy, pb_sell = False, False
                if STRATEGY.get('use_pullback', False):
                    lb = PB.get('lookback', 60) // 5
                    if df_5m['is_new_high'].tail(lb).any() and last_5m['in_bull_pb_zone'] and last_price > last_5m['Open'] and last_5m['bullish_align']: pb_buy = True
                    if df_5m['is_new_low'].tail(lb).any() and last_5m['in_bear_pb_zone'] and last_price < last_5m['Open'] and last_5m['bearish_align']: pb_sell = True

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
            
            # 即時顯示包含環境狀態
            console.print(f"[{datetime.now().strftime('%H:%M:%S')}] Price: {last_price:.1f} | Score: {score:.1f} | Regime: {regime_desc} | Pos: {trader.position}", end="\r")
            time.sleep(30 if use_shioaji else 60)

    except KeyboardInterrupt: pass
    finally: trader.save_report(); shioaji.logout()

if __name__ == "__main__":
    run_simulation("TMF")
