import sys
import os
import time
from datetime import datetime
import pandas as pd
from rich.console import Console
from rich.live import Live
from rich.panel import Panel

# 加入 src 到路徑
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.downloader import download_futures_data
from squeeze_futures.data.shioaji_client import ShioajiClient
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from squeeze_futures.engine.simulator import PaperTrader

console = Console()

def is_market_open():
    now = datetime.now()
    # 簡單判斷：週一至週五 08:45 - 13:45 (不含盤後)
    if now.weekday() >= 5: return False
    market_start = now.replace(hour=8, minute=45, second=0)
    market_end = now.replace(hour=13, minute=45, second=0)
    return market_start <= now <= market_end

def run_simulation(ticker="MXFR1"):
    trader = PaperTrader(ticker=ticker)
    shioaji = ShioajiClient()
    use_shioaji = shioaji.login()
    
    console.print(f"[bold green]Starting Daily Simulation for {ticker}...[/bold green]")
    
    try:
        while True:
            # 盤中交易時間檢查 (可手動註解掉以進行非盤中測試)
            # if not is_market_open():
            #     console.print("Market is closed. Waiting...")
            #     time.sleep(300)
            #     continue

            # 1. 抓取多週期數據
            processed_data = {}
            for tf in ["5m", "15m", "1h"]:
                df = shioaji.get_kline(ticker, interval=tf) if use_shioaji else pd.DataFrame()
                if df.empty:
                    df = download_futures_data("^TWII", interval=tf, period="5d") # yfinance 備案
                
                if not df.empty:
                    processed_data[tf] = calculate_futures_squeeze(df)
            
            if "5m" not in processed_data: continue
            
            # 2. 策略邏輯
            last_5m = processed_data["5m"].iloc[-1]
            alignment = calculate_mtf_alignment(processed_data)
            score = alignment['score']
            
            current_price = last_5m['Close']
            timestamp = last_5m.name if hasattr(last_5m, 'name') else datetime.now()
            
            log_msg = ""
            
            # --- 核心交易邏輯 (含反手交易) ---
            
            # 情況 A: 目前空手 (Empty)
            if trader.position == 0:
                if last_5m['fired'] and score > 70 and last_5m['price_vs_vwap'] > 0:
                    log_msg = trader.execute_signal("BUY", current_price, timestamp)
                elif last_5m['fired'] and score < -70 and last_5m['price_vs_vwap'] < 0:
                    log_msg = trader.execute_signal("SELL", current_price, timestamp)
            
            # 情況 B: 持有多單 (Long)
            elif trader.position == 1:
                # 偵測到強勢反向信號 (反手條件)
                if last_5m['fired'] and score < -70:
                    log_msg = trader.execute_signal("EXIT", current_price, timestamp)
                    log_msg += " | " + trader.execute_signal("SELL", current_price, timestamp)
                # 一般出場條件 (動能轉弱或分數轉向)
                elif last_5m['mom_state'] < 3 or score < 20:
                    log_msg = trader.execute_signal("EXIT", current_price, timestamp)
            
            # 情況 C: 持有空單 (Short)
            elif trader.position == -1:
                # 偵測到強勢反向信號 (反手條件)
                if last_5m['fired'] and score > 70:
                    log_msg = trader.execute_signal("EXIT", current_price, timestamp)
                    log_msg += " | " + trader.execute_signal("BUY", current_price, timestamp)
                # 一般出場條件 (動能轉弱或分數轉向)
                elif last_5m['mom_state'] > 0 or score > -20:
                    log_msg = trader.execute_signal("EXIT", current_price, timestamp)

            if log_msg:
                console.print(f"[bold yellow][{timestamp}] {log_msg}[/bold yellow]")
            
            # 顯示進度
            pos_text = "LONG" if trader.position == 1 else "SHORT" if trader.position == -1 else "EMPTY"
            console.print(f"[{datetime.now().strftime('%H:%M:%S')}] Price: {current_price:.1f} | Score: {score:.1f} | Pos: {pos_text}", end="\r")
            
            # 模擬盤中更新頻率
            time.sleep(30 if use_shioaji else 60)

    except KeyboardInterrupt:
        console.print("\n[bold red]Simulation ended by user. Generating report...[/bold red]")
        report_path = trader.save_report()
        console.print(f"[bold green]Report saved to: {report_path}[/bold green]")

if __name__ == "__main__":
    # 使用 ^TWII 代替 MXFR1 進行週末測試 (yfinance 備案)
    run_simulation("^TWII")
