import os
import sys
import pytest
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytestmark = [pytest.mark.live, pytest.mark.manual]

sj = pytest.importorskip("shioaji")

console = Console()
load_dotenv()

def test_shioaji():
    if os.getenv("RUN_SHIOAJI_LIVE") != "1":
        pytest.skip("Set RUN_SHIOAJI_LIVE=1 to run manual Shioaji API checks.")

    api = sj.Shioaji()
    
    api_key = os.getenv("SHIOAJI_API_KEY")
    secret_key = os.getenv("SHIOAJI_SECRET_KEY")
    if not api_key or not secret_key:
        pytest.skip("Shioaji credentials are not configured in the environment.")
    
    console.print(f"[bold blue]Testing Shioaji API Login for ID: {api_key}...[/bold blue]")
    
    try:
        # 1. 測試登入
        api.login(
            api_key=api_key,
            secret_key=secret_key,
            fetch_contract=True
        )
        console.print("[green]✓ Login Successful![/green]")
        
        # 2. 測試帳戶列表
        accounts = api.list_accounts()
        table = Table(title="Your Shioaji Accounts")
        table.add_column("Account Type", style="cyan")
        table.add_column("Account No", style="magenta")
        table.add_column("User Name", style="white")
        
        for acc in accounts:
            table.add_row(str(acc.account_type), acc.account_id, acc.username)
        
        console.print(table)
        
        # 3. 測試合約抓取 (以台積電 2330 為例)
        console.print("\n[bold blue]Testing Contract Fetch (2330.TW)...[/bold blue]")
        contract = api.Contracts.Stocks["2330"]
        if contract:
            console.print(f"[green]✓ Contract found: {contract.name} ({contract.symbol})[/green]")
            # 抓取最近一筆快照
            snapshot = api.snapshots([contract])
            if snapshot:
                s = snapshot[0]
                console.print(f"  Last Price: [yellow]{s.close}[/yellow] | High: {s.high} | Low: {s.low}")
        
        # 4. 測試期貨合約 (台指期近月)
        console.print("\n[bold blue]Testing Futures Contract (TXFR1)...[/bold blue]")
        try:
            fut_contract = api.Contracts.Futures.TXF.TXFR1
            console.print(f"[green]✓ Futures found: {fut_contract.name}[/green]")
        except:
            console.print("[yellow]! Could not find TXFR1, maybe your account doesn't have futures permission yet.[/yellow]")

        api.logout()
        console.print("\n[bold green]=== API Test Finished Successfully ===[/bold green]")
        
    except Exception as e:
        console.print(f"\n[bold red]✘ API Test Failed![/bold red]")
        console.print(f"Error Details: {str(e)}")

if __name__ == "__main__":
    test_shioaji()
