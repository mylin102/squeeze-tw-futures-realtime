#!/usr/bin/env python3
"""
MA 動態停損回測比較腳本
基於 atr_backtest_comparison.py 的邏輯，加入 MA 停損支援
"""
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd
import yaml

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from squeeze_futures.engine.simulator import PaperTrader, calculate_ma_stop_price
from squeeze_futures.engine.constants import get_point_value
from squeeze_futures.engine.execution import build_execution_model, simulate_order_fill
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from scripts.backtest.historical_backtest import load_and_resample


def load_config():
    config_path = Path(__file__).parent.parent / "config" / "trade_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def execute_engine(p5, p15, p1h, cfg, use_ma_stop: bool = False, ma_mult: float = 0.0, ma_len: int = 20, ma_ticks: int = 5):
    """
    執行回測 - 完全基於 atr_backtest_comparison.py 的邏輯
    
    Args:
        p5, p15, p1h: 各週期的數據
        cfg: 配置
        use_ma_stop: 是否使用 MA 停損
        ma_mult: MA 停損倍數
        ma_len: MA 週期
        ma_ticks: MA 下方/上方 tick 數
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
    PB, TP = STRAT.get('pullback', {}), STRAT.get('partial_exit', {})
    
    fixed_sl = RISK["stop_loss_pts"]
    lots_entry = 2
    
    # MA 停損參數
    ma_type = "below"
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]
        price, vwap = row['Close'], row['vwap']
        
        # --- 持倉管理 ---
        if trader.position != 0:
            trader.update_trailing_stop(price)
            
            # 分批停利
            if lots_entry == 2 and abs(trader.position) == 2 and not has_tp1_hit:
                pnl = (price - trader.entry_price) * (1 if trader.position > 0 else -1)
                if pnl >= TP.get('tp1_pts', 40):
                    trader.execute_signal("PARTIAL_EXIT", price, curr_time, lots=1)
                    trader.current_stop_loss = trader.entry_price
                    has_tp1_hit = True
            
            # MA 動態停損檢查（最優先）
            if use_ma_stop and ma_mult > 0:
                ma_stop_price_val = calculate_ma_stop_price(
                    p5.iloc[:i+1], trader.position, ma_type, ma_len, ma_ticks, ma_mult,
                    use_prev_ma=True,
                    entry_price=trader.entry_price if trader.position != 0 else None
                )
                if ma_stop_price_val is not None:
                    if trader.position > 0 and price <= ma_stop_price_val:
                        trader.execute_signal("EXIT", ma_stop_price_val, curr_time)
                        has_tp1_hit = False
                    elif trader.position < 0 and price >= ma_stop_price_val:
                        trader.execute_signal("EXIT", ma_stop_price_val, curr_time)
                        has_tp1_hit = False
            
            # 固定停損檢查
            if trader.position != 0 and trader.check_stop_loss(price, curr_time):
                has_tp1_hit = False
            # VWAP 離場
            elif trader.position != 0 and RISK['exit_on_vwap']:
                if (trader.position > 0 and price < vwap and not row['opening_bullish']) or \
                   (trader.position < 0 and price > vwap and not row['opening_bearish']):
                    trader.execute_signal("EXIT", price, curr_time)
                    has_tp1_hit = False
        
        # --- 進場邏輯 ---
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
                        trader.execute_signal("BUY", fill_price, curr_time, lots=lots_entry, max_lots=lots_entry, stop_loss=fixed_sl, break_even_trigger=RISK['break_even_pts'])
                elif sqz_sell or pb_sell:
                    fill_price = simulate_order_fill("SELL", price, row, execution_model)
                    if fill_price is not None:
                        trader.execute_signal("SELL", fill_price, curr_time, lots=lots_entry, max_lots=lots_entry, stop_loss=fixed_sl, break_even_trigger=RISK['break_even_pts'])
            
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
    print("=" * 60)
    print("MA 動態停損回測比較")
    print("=" * 60)
    
    cfg = load_config()
    print(f"\n載入配置完成")
    print(f"  - 策略長度：{cfg['strategy']['length']}")
    print(f"  - 進場分數：{cfg['strategy']['entry_score']}")
    print(f"  - 固定停損：{cfg['risk_mgmt']['stop_loss_pts']} 點")
    
    # 載入數據
    print("\n載入數據中...")
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
    print("計算 Squeeze 指標...")
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
    
    print(f"  - 5m K 棒：{len(p5)} 根")
    
    # 測試不同停損模式
    test_configs = [
        ("固定 30 點", False, 0, 60, 5),
        ("MA20-5tick", True, 1.0, 20, 5),
        ("MA20-10tick", True, 1.0, 20, 10),
        ("MA60-5tick", True, 1.0, 60, 5),
        ("MA60-10tick", True, 1.0, 60, 10),
        ("MA60-15tick", True, 1.0, 60, 15),
        ("MA60-20tick", True, 1.0, 60, 20),
    ]
    
    results = []
    
    print("\n" + "=" * 60)
    print("測試不同停損模式")
    print("=" * 60)
    
    for label, use_ma, mult, ma_len, ma_tk in test_configs:
        print(f"\n[dim]測試 {label}...[/dim]")
        eq, trader = execute_engine(p5, p15, p1h, cfg, use_ma_stop=use_ma, ma_mult=mult, ma_len=ma_len, ma_ticks=ma_tk)
        trades = pd.DataFrame(trader.trades)
        metrics = calculate_metrics(trader, trades, eq)
        
        results.append({
            'label': label,
            **metrics,
        })
        
        print(f"  淨獲利：{metrics['net_profit']:+,.0f} TWD | 交易：{metrics['total_trades']} | 勝率：{metrics['win_rate']:.1f}% | MDD: {metrics['max_drawdown']:,.0f} | PF: {metrics['profit_factor']:.2f}")
    
    # 顯示結果表格
    print("\n" + "=" * 60)
    print("綜合比較")
    print("=" * 60)
    
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    
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
    
    # 找出最佳結果
    best = max(results, key=lambda x: x['net_profit'])
    console.print(f"\n[bold green]✅ 最佳停損策略：{best['label']}[/bold green]")
    console.print(f"  淨獲利：{best['net_profit']:+,.0f} TWD")
    console.print(f"  勝率：{best['win_rate']:.1f}%")
    console.print(f"  獲利因子：{best['profit_factor']:.2f}")
    
    # 儲存報告
    output_path = Path(__file__).parent.parent / "exports" / "simulations" / f"ma_stop_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# MA Dynamic Stop Loss Comparison Report\n\n")
        f.write(f"- Generated at: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"- Data: {len(p5)} 5m bars\n\n")
        
        f.write("## Summary\n\n")
        f.write("| Strategy | Net Profit | Trades | Win Rate | Max DD | Profit Factor | Avg Trade |\n")
        f.write("|:--|--:|--:|--:|--:|--:|--:|\n")
        for r in results:
            f.write(f"| {r['label']} | {r['net_profit']:+,.0f} | {r['total_trades']} | {r['win_rate']:.1f}% | {r['max_drawdown']:,.0f} | {r['profit_factor']:.2f} | {r['avg_trade']:+,.0f} |\n")
        
        f.write(f"\n## Best Configuration\n\n")
        f.write(f"- **Best Strategy**: {best['label']}\n")
        f.write(f"- **Net Profit**: {best['net_profit']:+,.0f} TWD\n")
        f.write(f"- **Win Rate**: {best['win_rate']:.1f}%\n")
        f.write(f"- **Profit Factor**: {best['profit_factor']:.2f}\n")
    
    print(f"\n📄 報告已儲存至：{output_path}")


if __name__ == "__main__":
    main()
