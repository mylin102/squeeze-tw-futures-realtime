#!/usr/bin/env python3
"""
從 Shioaji API 下載 TMF 微型台指期貨 K 棒數據，存為回測用 CSV。
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from squeeze_futures.data.shioaji_client import ShioajiClient
from rich.console import Console

console = Console()


def download_tmf_data(days: int = 60, interval: str = "5m"):
    client = ShioajiClient()
    if not client.login():
        console.print("[red]❌ Shioaji 登入失敗，請確認 .env 設定[/red]")
        return None

    console.print(f"[bold blue]下載 TMF 期貨 {interval} K 棒（近 {days} 天）...[/bold blue]")

    df = client.get_kline("TMF", interval=interval)
    client.logout()

    if df.empty:
        console.print("[red]❌ 未取得資料[/red]")
        return None

    # 只保留近 N 天
    cutoff = datetime.now() - timedelta(days=days)
    df = df[df.index >= cutoff.strftime("%Y-%m-%d")]

    output_dir = Path("data/taifex_raw")
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = output_dir / f"TMF_{interval}_{ts}.csv"
    df.to_csv(out)

    console.print(f"[green]✓ {len(df)} bars，{df.index[0]} ~ {df.index[-1]}[/green]")
    console.print(f"[green]✓ Close 範圍：{df['Close'].min():.0f} ~ {df['Close'].max():.0f}[/green]")
    console.print(f"[green]✓ 儲存至：{out}[/green]")
    return df


if __name__ == "__main__":
    download_tmf_data(days=60, interval="5m")
