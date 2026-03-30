#!/usr/bin/env python3
"""
ATR 倍數優化腳本

測試不同 ATR 倍數，找到最佳停損參數
"""
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd
import yaml
from rich.console import Console
from rich.table import Table

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.engine.constants import get_point_value
from squeeze_futures.engine.execution import build_execution_model, simulate_order_fill
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment, calculate_atr
from scripts.backtest.historical_backtest import load_and_resample

console = Console()


def load_config():
    config_path = Path(__file__).parent.parent / "config" / "trade_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def execute_engine(p5, p15, p1h, cfg, use_atr: bool = False, atr_mult: float = 2.0):
    """
    執行回測
    
    Args:
        p5, p15, p1h: 各週期的數據
        cfg: 配置
        use_atr: 是否使用 ATR（已廢用，改由 atr_mult 控制）
        atr_mult: ATR 倍數
                  - atr_mult = 0    → 使用固定停損
                  - atr_mult > 0    → 使用 ATR 動態停損
    """
    exec_cfg = cfg.get("execution", {})
    execution_model = build_execution_model(exec_cfg)
    
    trader = PaperTrader(
        ticker="TMF",
        initial_balance=100000,
        point_value=get_point_value("TMF"),
        fee_per_side=exec_cfg.get("broker_fee_per_side", 20),
        exchange_fee_per_side=exec_cfg.get("exchange_fee_per_side", 0),
        tax_rate=exec_cfg.get("tax_rate", 0.0),
    )
    
    equity_curve = []
    has_tp1_hit = False
    
    STRAT, MGMT, RISK = cfg['strategy'], cfg['trade_mgmt'], cfg['risk_mgmt']
    TP = STRAT.get('partial_exit', {})
    
    # ATR 參數
    atr_length = RISK.get('atr_length', 14)
    fixed_sl = RISK["stop_loss_pts"]
    
    # 停損模式判定：atr_mult > 0 使用 ATR，否則使用固定停損
    if use_atr and atr_mult > 0:
        atr_5m = calculate_atr(p5, length=atr_length)
    else:
        atr_5m = None
    
    lots_entry = 2
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]
        price, vwap = row['Close'], row['vwap']
        
        # 計算當前停損點數
        if atr_5m is not None and i >= atr_length:
            current_atr = atr_5m.iloc[i]
            if not pd.isna(current_atr):
                stop_loss_pts = current_atr * atr_mult
            else:
                stop_loss_pts = fixed_sl
        else:
            stop_loss_pts = fixed_sl
        
        # 持倉管理
        if trader.position != 0:
            trader.update_trailing_stop(price)
            
            if lots_entry == 2 and abs(trader.position) == 2 and not has_tp1_hit:
                pnl = (price - trader.entry_price) * (1 if trader.position > 0 else -1)
                if pnl >= TP.get('tp1_pts', 40):
                    trader.execute_signal("PARTIAL_EXIT", price, curr_time, lots=1)
                    trader.current_stop_loss = trader.entry_price
                    has_tp1_hit = True
            
            if trader.check_stop_loss(price, curr_time):
                has_tp1_hit = False
            elif RISK['exit_on_vwap']:
                if (trader.position > 0 and price < vwap and not row['opening_bullish']) or \
                   (trader.position < 0 and price > vwap and not row['opening_bearish']):
                    trader.execute_signal("EXIT", price, curr_time)
                    has_tp1_hit = False
        
        # 進場邏輯
        m15 = p15[p15.index <= curr_time]
        if not m15.empty:
            score = calculate_mtf_alignment(
                {"5m": p5.iloc[:i+1], "15m": m15, "1h": p1h[p1h.index <= curr_time]},
                weights=STRAT['weights']
            )['score']
            
            if trader.position == 0:
                has_tp1_hit = False
                
                sqz_buy = (not row['sqz_on']) and score >= STRAT['entry_score'] and price > vwap and row['mom_state'] == 3
                pb_buy = p5['is_new_high'].iloc[max(0, i-12):i].any() and row['in_bull_pb_zone'] and price > row['Open'] and row['bullish_align']
                
                sqz_sell = (not row['sqz_on']) and score <= -STRAT['entry_score'] and price < vwap and row['mom_state'] == 0
                pb_sell = p5['is_new_low'].iloc[max(0, i-12):i].any() and row['in_bear_pb_zone'] and price < row['Open'] and row['bearish_align']
                
                if sqz_buy or pb_buy:
                    fill_price = simulate_order_fill("BUY", price, row, execution_model)
                    if fill_price is not None:
                        trader.execute_signal("BUY", fill_price, curr_time, lots=lots_entry, max_lots=lots_entry, stop_loss=stop_loss_pts, break_even_trigger=RISK['break_even_pts'])
                elif sqz_sell or pb_sell:
                    fill_price = simulate_order_fill("SELL", price, row, execution_model)
                    if fill_price is not None:
                        trader.execute_signal("SELL", fill_price, curr_time, lots=lots_entry, max_lots=lots_entry, stop_loss=stop_loss_pts, break_even_trigger=RISK['break_even_pts'])
            
            elif trader.position > 0 and (row['mom_state'] < 2 or score < 20):
                trader.execute_signal("EXIT", price, curr_time)
                has_tp1_hit = False
            elif trader.position < 0 and (row['mom_state'] > 1 or score > -20):
                trader.execute_signal("EXIT", price, curr_time)
                has_tp1_hit = False
        
        equity_curve.append(
            trader.balance + (
                (price - trader.entry_price) * trader.position * trader.point_value
                if trader.position != 0 else 0
            )
        )
    
    return equity_curve, trader


def calculate_metrics(trader, trades_df: pd.DataFrame, equity_curve: list) -> Dict:
    """計算績效指標"""
    if trades_df.empty:
        return {'net_profit': 0, 'total_trades': 0, 'win_rate': 0, 'max_drawdown': 0, 'profit_factor': 0, 'avg_trade': 0}
    
    net_profit = trader.balance - 100000
    winning_trades = len(trades_df[trades_df['pnl_cash'] > 0])
    win_rate = winning_trades / len(trades_df) * 100
    avg_trade = trades_df['pnl_cash'].mean()
    
    eq_series = pd.Series(equity_curve)
    running_max = eq_series.cummax()
    drawdown = eq_series - running_max
    max_drawdown = abs(drawdown.min())
    
    gross_profit = trades_df[trades_df['pnl_cash'] > 0]['pnl_cash'].sum()
    gross_loss = abs(trades_df[trades_df['pnl_cash'] < 0]['pnl_cash'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    return {
        'net_profit': net_profit,
        'total_trades': len(trades_df),
        'win_rate': win_rate,
        'max_drawdown': max_drawdown,
        'profit_factor': profit_factor,
        'avg_trade': avg_trade,
    }


def main():
    console.print("=" * 60)
    console.print("[bold cyan]ATR 倍數優化測試[/bold cyan]")
    console.print("=" * 60)
    
    cfg = load_config()
    RISK = cfg['risk_mgmt']  # 用於標籤顯示
    
    # 載入數據
    console.print("\n[dim]載入數據中...[/dim]")
    files = sorted(Path("data/taifex_raw").glob("Daily_*.rpt"))
    all_d, all_d15, all_d1h = [], [], []
    for f in files:
        d5 = load_and_resample(f, "5min", "TMF")
        d15 = load_and_resample(f, "15min", "TMF")
        d1h = load_and_resample(f, "1h", "TMF")
        if d5 is not None:
            all_d.append(d5)
            all_d15.append(d15)
            all_d1h.append(d1h)
    
    # 計算 Squeeze 指標
    console.print("[dim]計算 Squeeze 指標...[/dim]")
    pb = cfg["strategy"]["pullback"]
    p_args = {
        "bb_length": cfg["strategy"]["length"],
        "ema_fast": pb["ema_fast"],
        "ema_slow": pb["ema_slow"],
        "lookback": pb["lookback"],
        "pb_buffer": pb["buffer"],
    }
    
    p5 = calculate_futures_squeeze(pd.concat(all_d).sort_index(), **p_args)
    p15 = calculate_futures_squeeze(pd.concat(all_d15).sort_index(), **p_args)
    p1h = calculate_futures_squeeze(pd.concat(all_d1h).sort_index(), **p_args)
    
    console.print(f"[dim]  - 5m K 棒：{len(p5)} 根[/dim]")
    
    # 測試不同 ATR 倍數（包含小數值）
    # atr_multiplier = 0 → 固定停損
    # atr_multiplier > 0 → ATR 動態停損
    atr_multipliers = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 1.0, 1.5, 2.0, 0]  # 0 = 固定停損
    results = []

    console.print("\n" + "=" * 60)
    console.print("[bold]測試不同 ATR 倍數[/bold]")
    console.print("=" * 60)

    for atr_mult in atr_multipliers:
        if atr_mult == 0:
            label = f"固定 {RISK.get('stop_loss_pts', 30)}點"
        else:
            label = f"ATR {atr_mult}x"
        console.print(f"\n[dim]測試 {label}...[/dim]")
        eq, trader = execute_engine(p5, p15, p1h, cfg, use_atr=(atr_mult > 0), atr_mult=atr_mult)
        trades = pd.DataFrame(trader.trades)
        metrics = calculate_metrics(trader, trades, eq)
        
        results.append({
            'atr_mult': atr_mult,
            'label': label,
            'net_profit': metrics['net_profit'],
            'total_trades': metrics['total_trades'],
            'win_rate': metrics['win_rate'],
            'max_drawdown': metrics['max_drawdown'],
            'profit_factor': metrics['profit_factor'],
            'avg_trade': metrics['avg_trade'],
        })
        
        console.print(f"  淨獲利：{metrics['net_profit']:+,.0f} TWD | 交易：{metrics['total_trades']} | 勝率：{metrics['win_rate']:.1f}% | MDD: {metrics['max_drawdown']:,.0f} | PF: {metrics['profit_factor']:.2f}")
    
    # 顯示結果表格
    console.print("\n" + "=" * 60)
    console.print("[bold green]綜合比較[/bold green]")
    console.print("=" * 60)
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Strategy", justify="center")
    table.add_column("Net Profit", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Max DD", justify="right")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Avg Trade", justify="right")
    
    for r in results:
        profit_style = "green" if r['net_profit'] > 0 else "red"
        table.add_row(
            r['label'],
            f"[{profit_style}]{r['net_profit']:+,.0f}[/]",
            f"{r['total_trades']}",
            f"{r['win_rate']:.1f}%",
            f"{r['max_drawdown']:,.0f}",
            f"{r['profit_factor']:.2f}",
            f"{r['avg_trade']:+,.0f}",
        )
    
    console.print(table)
    
    # 找出最佳結果（排除固定停損）
    atr_results = [r for r in results if r['atr_mult'] > 0]
    fixed_results = [r for r in results if r['atr_mult'] == 0]
    
    if atr_results:
        best = max(atr_results, key=lambda x: x['net_profit'])
        console.print(f"\n[bold green]✅ 最佳 ATR 倍數：{best['atr_mult']}x[/bold green]")
        console.print(f"  淨獲利：{best['net_profit']:+,.0f} TWD")
        console.print(f"  勝率：{best['win_rate']:.1f}%")
        console.print(f"  獲利因子：{best['profit_factor']:.2f}")
        
        if fixed_results:
            fixed = fixed_results[0]
            delta = best['net_profit'] - fixed['net_profit']
            if delta > 0:
                console.print(f"\n[bold green]✅ ATR {best['atr_mult']}x 獲利提升 {delta:,.0f} TWD[/bold green]")
            else:
                console.print(f"\n[bold red]❌ 固定停損獲利較佳 {abs(delta):,.0f} TWD[/bold red]")
                console.print(f"  固定停損：{fixed['net_profit']:+,.0f} TWD")
    
    # 儲存報告
    output_path = Path(__file__).parent.parent / "exports" / "simulations" / f"atr_optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# ATR Multiplier Optimization Report\n\n")
        f.write(f"- Generated at: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"- Data: {len(p5)} 5m bars\n\n")
        
        f.write("## Results\n\n")
        f.write("| Strategy | Net Profit | Trades | Win Rate | Max DD | Profit Factor | Avg Trade |\n")
        f.write("|:--|--:|--:|--:|--:|--:|--:|\n")
        for r in results:
            f.write(f"| {r['label']} | {r['net_profit']:+,.0f} | {r['total_trades']} | {r['win_rate']:.1f}% | {r['max_drawdown']:,.0f} | {r['profit_factor']:.2f} | {r['avg_trade']:+,.0f} |\n")
        
        if atr_results:
            best = max(atr_results, key=lambda x: x['net_profit'])
            f.write(f"\n## Best ATR Configuration\n\n")
            f.write(f"- **Best ATR Multiplier**: {best['atr_mult']}x\n")
            f.write(f"- **Net Profit**: {best['net_profit']:+,.0f} TWD\n")
            f.write(f"- **Win Rate**: {best['win_rate']:.1f}%\n")
            f.write(f"- **Profit Factor**: {best['profit_factor']:.2f}\n")
    
    console.print(f"\n[dim]📄 報告已儲存至：{output_path}[/dim]")


if __name__ == "__main__":
    main()
