import sys
import os
import time
from datetime import datetime
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.live import Console as LiveConsole
from rich.live import Live

# 加入 src 到路徑
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.downloader import download_futures_data
from squeeze_futures.engine.indicators import calculate_futures_squeeze

console = Console()

def generate_status_table(ticker: str, df_5m: pd.DataFrame, df_15m: pd.DataFrame) -> Table:
    table = Table(title=f"Squeeze Real-time Monitor: {ticker} ({datetime.now().strftime('%H:%M:%S')})")
    
    table.add_column("Timeframe", style="cyan")
    table.add_column("Last Price", style="white")
    table.add_column("Squeeze Status", style="magenta")
    table.add_column("Momentum", style="yellow")
    table.add_column("Signal", style="bold")
    
    for tf, df in [("5m", df_5m), ("15m", df_15m)]:
        if df.empty:
            continue
            
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        # Squeeze 狀態
        sqz_text = "[red]ON[/red]" if last_row['sqz_on'] else "[green]OFF[/green]"
        
        # 動能顏色 (Rich 標記)
        mom = last_row['momentum']
        mom_state = last_row['mom_state']
        mom_color = {0: "dark_red", 1: "red", 2: "dark_green", 3: "green"}.get(mom_state, "white")
        mom_text = f"[{mom_color}]{mom:.2f}[/{mom_color}]"
        
        # 信號邏輯
        signal = "Wait"
        if last_row['fired']:
            signal = "[bold green]BUY EXPLOSION[/bold green]" if mom > 0 else "[bold red]SELL BREAKDOWN[/bold red]"
        elif not last_row['sqz_on'] and last_row['mom_state'] == 3:
            signal = "Bullish Trend"
        elif not last_row['sqz_on'] and last_row['mom_state'] == 0:
            signal = "Bearish Trend"
            
        table.add_row(
            tf,
            f"{last_row['Close']:.2f}",
            sqz_text,
            mom_text,
            signal
        )
        
    return table

def main(ticker="^TWII"):
    console.print(f"[bold green]Starting Real-time Squeeze Monitor for {ticker}...[/bold green]")
    
    with Live(auto_refresh=False) as live:
        while True:
            try:
                # 抓取數據
                df_5m = download_futures_data(ticker, interval="5m", period="1d")
                df_15m = download_futures_data(ticker, interval="15m", period="5d")
                
                # 計算指標
                df_5m = calculate_futures_squeeze(df_5m)
                df_15m = calculate_futures_squeeze(df_15m)
                
                # 更新顯示
                live.update(generate_status_table(ticker, df_5m, df_15m), refresh=True)
                
                # 等待下一次輪詢 (期貨交易通常每分鐘檢查一次)
                time.sleep(60)
                
            except KeyboardInterrupt:
                console.print("\n[bold red]Monitor stopped by user.[/bold red]")
                break
            except Exception as e:
                console.print(f"[red]Error: {str(e)}[/red]")
                time.sleep(10)

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "^TWII"
    main(target)
