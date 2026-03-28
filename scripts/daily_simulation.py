import sys
import os
import time
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

# ============================================================
# ⚙️ 交易系統配置中心 (User Config)
# ============================================================

# 1. 策略核心參數
STRATEGY_PARAMS = {
    "length": 14,           # Squeeze 計算週期 (14 比 20 更靈敏)
    "entry_score": 60,      # 多週期共振分數門檻 (50~70)
    "weights": {"1h": 0.2, "15m": 0.4, "5m": 0.4} # 加重中短線權重
}

# 2. 部位管理
TRADE_MGMT = {
    "lots_per_trade": 1,    # 一次進場幾口
    "max_positions": 3,     # 總持倉口數上限
    "allow_long": True,     # 允許多頭操作
    "allow_short": True,    # 允許空頭操作
    "force_close_at_end": True # 每日收盤前是否強制平倉 (Day Trading)
}

# 3. 風險控管 (多重停損)
RISK_PARAMS = {
    "stop_loss_pts": 40,    # 【最後防線】固定點數停損
    "break_even_pts": 40,   # 【利潤保護】獲利達此點數後將停損移至成本價
    "exit_on_vwap": True    # 【結構停損】跌破(多)或漲破(空)成本線(VWAP)即出場
}

# ============================================================

def get_market_status():
    """判斷市場狀態"""
    now = datetime.now()
    weekday = now.weekday()
    current_time = now.hour * 100 + now.minute
    
    is_day = (0 <= weekday <= 4) and (845 <= current_time < 1345)
    is_night = False
    if (0 <= weekday <= 4) and (current_time >= 1500): is_night = True
    if (1 <= weekday <= 5) and (current_time < 500): is_night = True
    
    is_near_close = False
    if is_day and current_time >= 1340: is_near_close = True
    if is_night and current_time >= 455: is_near_close = True
    
    return {"open": is_day or is_night, "near_close": is_near_close}

def run_simulation(ticker="MXFR1"):
    trader = PaperTrader(ticker=ticker)
    shioaji = ShioajiClient()
    use_shioaji = shioaji.login()
    
    console.print(f"[bold green]🚀 Squeeze Auto-Trader Started for {ticker}[/bold green]")
    console.print(f"Mode: {'Bi-directional' if TRADE_MGMT['allow_long'] and TRADE_MGMT['allow_short'] else 'Single-side'}")
    
    try:
        while True:
            status = get_market_status()
            
            # --- A. 市場關閉處理 ---
            if not status["open"]:
                if trader.position != 0:
                    trader.execute_signal("EXIT", trader.entry_price, datetime.now())
                console.print(f"[{datetime.now().strftime('%H:%M:%S')}] Market Closed. Sleeping...", end="\r")
                time.sleep(300)
                continue

            # --- B. 抓取數據與指標 ---
            processed_data = {}
            for tf in ["5m", "15m", "1h"]:
                df = shioaji.get_kline(ticker, interval=tf) if use_shioaji else pd.DataFrame()
                if df.empty: df = download_futures_data("^TWII", interval=tf, period="5d")
                if not df.empty:
                    processed_data[tf] = calculate_futures_squeeze(df, bb_length=STRATEGY_PARAMS["length"])
            
            if "5m" not in processed_data: continue
            
            last_5m = processed_data["5m"].iloc[-1]
            alignment = calculate_mtf_alignment(processed_data, weights=STRATEGY_PARAMS["weights"])
            score = alignment['score']
            last_price = last_5m['Close']
            timestamp = last_5m.name if hasattr(last_5m, 'name') else datetime.now()
            
            log_msg = ""
            
            # --- C. 風控監控 ---
            if trader.position != 0:
                # 1. 更新保本停損
                if trader.update_trailing_stop(last_price):
                    console.print(f"[cyan][{timestamp}] Profit reached threshold. Stop set to Break-even.[/cyan]")
                
                # 2. 檢查硬性停損
                stop_msg = trader.check_stop_loss(last_price, timestamp)
                
                # 3. 檢查 VWAP 結構停損
                if not stop_msg and RISK_PARAMS["exit_on_vwap"]:
                    if trader.position > 0 and last_price < last_5m['vwap']:
                        stop_msg = trader.execute_signal("EXIT", last_price, timestamp)
                        if stop_msg: stop_msg = "[VWAP BREAK] " + stop_msg
                    elif trader.position < 0 and last_price > last_5m['vwap']:
                        stop_msg = trader.execute_signal("EXIT", last_price, timestamp)
                        if stop_msg: stop_msg = "[VWAP BREAK] " + stop_msg
                
                # 4. 收盤強制清倉
                if not stop_msg and status["near_close"] and TRADE_MGMT["force_close_at_end"]:
                    stop_msg = trader.execute_signal("EXIT", last_price, timestamp)
                    if stop_msg: stop_msg = "[EOD CLOSE] " + stop_msg
                
                if stop_msg: log_msg = stop_msg

            # --- D. 進場邏輯 ---
            if not log_msg:
                # 判斷多空限制
                can_buy = TRADE_MGMT["allow_long"] and score >= STRATEGY_PARAMS["entry_score"]
                can_sell = TRADE_MGMT["allow_short"] and score <= -STRATEGY_PARAMS["entry_score"]
                is_ready = not last_5m['sqz_on']
                
                # 1. 進場 (目前空手時)
                if trader.position == 0 and is_ready:
                    if can_buy and last_price > last_5m['vwap'] and last_5m['mom_state'] == 3:
                        log_msg = trader.execute_signal("BUY", last_price, timestamp, 
                                                       lots=TRADE_MGMT["lots_per_trade"],
                                                       max_lots=TRADE_MGMT["max_positions"],
                                                       stop_loss=RISK_PARAMS["stop_loss_pts"],
                                                       break_even_trigger=RISK_PARAMS["break_even_pts"])
                    elif can_sell and last_price < last_5m['vwap'] and last_5m['mom_state'] == 0:
                        log_msg = trader.execute_signal("SELL", last_price, timestamp,
                                                       lots=TRADE_MGMT["lots_per_trade"],
                                                       max_lots=TRADE_MGMT["max_positions"],
                                                       stop_loss=RISK_PARAMS["stop_loss_pts"],
                                                       break_even_trigger=RISK_PARAMS["break_even_pts"])
                
                # 2. 反手邏輯 (持倉中若出現反向強勢分數)
                elif trader.position > 0 and can_sell: # 持有多單但共振轉空
                    log_msg = trader.execute_signal("EXIT", last_price, timestamp)
                    log_msg += " | " + trader.execute_signal("SELL", last_price, timestamp, 
                                                           lots=TRADE_MGMT["lots_per_trade"],
                                                           max_lots=TRADE_MGMT["max_positions"],
                                                           stop_loss=RISK_PARAMS["stop_loss_pts"])
                elif trader.position < 0 and can_buy: # 持有空單但共振轉多
                    log_msg = trader.execute_signal("EXIT", last_price, timestamp)
                    log_msg += " | " + trader.execute_signal("BUY", last_price, timestamp,
                                                           lots=TRADE_MGMT["lots_per_trade"],
                                                           max_lots=TRADE_MGMT["max_positions"],
                                                           stop_loss=RISK_PARAMS["stop_loss_pts"])
                
                # 3. 一般趨勢轉弱出場 (當分數轉回盤整區)
                elif trader.position > 0 and (last_5m['mom_state'] < 2 or score < 20):
                    log_msg = trader.execute_signal("EXIT", last_price, timestamp)
                elif trader.position < 0 and (last_5m['mom_state'] > 1 or score > -20):
                    log_msg = trader.execute_signal("EXIT", last_price, timestamp)

            if log_msg:
                console.print(f"[bold yellow][{timestamp}] {log_msg}[/bold yellow]")
                send_email_notification(f"TRADE ALERT: {ticker}", log_msg, f"<h3>{log_msg}</h3>")
            
            # --- E. 即時顯示 ---
            pos_text = f"{trader.position} lots" if trader.position != 0 else "EMPTY"
            sl_text = f"SL: {trader.current_stop_loss:.1f}" if trader.current_stop_loss else "SL: None"
            console.print(f"[{datetime.now().strftime('%H:%M:%S')}] Price: {last_price:.1f} | Score: {score:.1f} | {pos_text} ({sl_text})", end="\r")
            
            time.sleep(30 if use_shioaji else 60)

    except KeyboardInterrupt:
        console.print("\n[bold red]Manual shutdown.[/bold red]")
    finally:
        trader.save_report()

if __name__ == "__main__":
    # 將監控標的從 ^TWII (大盤) 切換至 TMF (微台指) 以符合實戰
    run_simulation("TMF")
