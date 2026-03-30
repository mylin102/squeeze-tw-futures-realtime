import os
import sys
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.shioaji_client import ShioajiClient

console = Console()
load_dotenv()

def test_live_preparation():
    client = ShioajiClient()
    
    console.print("[bold cyan]=== Shioaji Live Trading Preparation Test ===[/bold cyan]\n")
    
    # 1. 測試登入與憑證
    console.print("[bold blue]1. Testing Login & CA Activation...[/bold blue]")
    if client.login():
        console.print("[green]✓ Login & CA Activation Successful![/green]")
    else:
        console.print("[red]✘ Login Failed. Please check your .env and Cert path.[/red]")
        return

    # 2. 顯示可用帳號
    accounts = client.api.list_accounts()
    table = Table(title="Available Accounts")
    table.add_column("Type")
    table.add_column("Account ID")
    table.add_column("Username")
    for acc in accounts:
        table.add_row(str(acc.account_type), acc.account_id, acc.username)
    console.print(table)

    # 3. 測試微台指 (TMF) 合約抓取
    console.print("\n[bold blue]2. Testing Micro-TAIEX (TMF) Contract Fetch...[/bold blue]")
    tmf_contract = client.get_futures_contract("TMF")
    if tmf_contract:
        console.print(f"[green]✓ Found TMF Contract: {tmf_contract.name} ({tmf_contract.symbol})[/green]")
        console.print(f"  Delivery Month: {tmf_contract.delivery_month}")
        
        # 4. 測試即時報價抓取
        console.print("\n[bold blue]3. Testing Real-time Snapshot...[/bold blue]")
        snapshot = client.api.snapshots([tmf_contract])
        if snapshot:
            s = snapshot[0]
            console.print(f"  Last Price: [yellow]{s.close}[/yellow] | High: {s.high} | Low: {s.low}")
        
        # 5. 測試 K 線抓取 (5m)
        console.print("\n[bold blue]4. Testing 5m K-Bar Fetch...[/bold blue]")
        df = client.get_kline("TMF", interval="5m")
        if not df.empty:
            console.print(f"[green]✓ Successfully fetched {len(df)} K-bars.[/green]")
            console.print(df.tail(3))
        else:
            console.print("[yellow]! No K-bars returned. (Market might be closed)[/yellow]")
    else:
        console.print("[red]✘ Could not find TMF contract. Check if your account has permission.[/red]")

    client.logout()
    console.print("\n[bold green]=== Live Preparation Test Finished ===[/bold green]")

if __name__ == "__main__":
    test_live_preparation()
