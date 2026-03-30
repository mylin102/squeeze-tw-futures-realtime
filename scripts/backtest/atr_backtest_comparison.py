#!/usr/bin/env python3
"""
ATR 動態停損回測比較腳本

比較固定停損 vs ATR 動態停損的績效差異
使用與 advanced_backtest.py 相同的邏輯
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

from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.engine.constants import get_point_value
from squeeze_futures.engine.execution import build_execution_model, simulate_order_fill
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment, calculate_atr
from scripts.backtest.historical_backtest import load_and_resample


def load_config():
    config_path = Path(__file__).parent.parent / "config" / "trade_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def execute_engine(p5, p15, p1h, cfg, use_atr: bool = False, atr_mult: float = 2.0):
    """
    執行回測 - 基於 advanced_backtest.py 的邏輯
    
    Args:
        p5, p15, p1h: 各週期的數據（已計算 Squeeze 指標）
        cfg: 配置
        use_atr: 是否使用 ATR 動態停損（已廢用，改由 atr_mult 控制）
        atr_mult: ATR 倍數
                  - atr_mult = 0    → 使用固定停損 (stop_loss_pts)
                  - atr_mult > 0    → 使用 ATR 動態停損 (ATR × atr_mult)
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
    
    # ATR 參數
    atr_length = RISK.get('atr_length', 14)
    fixed_sl = RISK["stop_loss_pts"]
    
    # 停損模式判定
    # atr_mult > 0 → ATR 動態停損
    # atr_mult = 0 → 固定停損
    if use_atr and atr_mult > 0:
        atr_5m = calculate_atr(p5, length=atr_length)
    else:
        atr_5m = None
    
    lots_entry = 2  # 使用 2 口進場
    
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
            
            # 停損檢查
            if trader.check_stop_loss(price, curr_time):
                has_tp1_hit = False
            # VWAP 離場
            elif RISK['exit_on_vwap']:
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
                        trader.execute_signal("BUY", fill_price, curr_time, lots=lots_entry, max_lots=lots_entry, stop_loss=stop_loss_pts, break_even_trigger=RISK['break_even_pts'])
                elif sqz_sell or pb_sell:
                    fill_price = simulate_order_fill("SELL", price, row, execution_model)
                    if fill_price is not None:
                        trader.execute_signal("SELL", fill_price, curr_time, lots=lots_entry, max_lots=lots_entry, stop_loss=stop_loss_pts, break_even_trigger=RISK['break_even_pts'])
            
            # 動能減弱出場
            elif trader.position > 0 and (row['mom_state'] < 2 or score < 20):
                trader.execute_signal("EXIT", price, curr_time)
                has_tp1_hit = False
            elif trader.position < 0 and (row['mom_state'] > 1 or score > -20):
                trader.execute_signal("EXIT", price, curr_time)
                has_tp1_hit = False
        
        # 計算權益
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
        return {
            'net_profit': 0,
            'ending_balance': trader.balance,
            'total_trades': 0,
            'win_rate': 0,
            'avg_trade': 0,
            'max_drawdown': 0,
            'profit_factor': 0,
            'total_cost': 0,
        }
    
    # 淨獲利
    net_profit = trader.balance - 100000
    
    # 勝率
    winning_trades = len(trades_df[trades_df['pnl_cash'] > 0])
    win_rate = winning_trades / len(trades_df) * 100
    
    # 平均交易
    avg_trade = trades_df['pnl_cash'].mean()
    
    # 最大回撤（從權益曲線計算）
    eq_series = pd.Series(equity_curve)
    running_max = eq_series.cummax()
    drawdown = eq_series - running_max
    max_drawdown = abs(drawdown.min())
    
    # 獲利因子
    gross_profit = trades_df[trades_df['pnl_cash'] > 0]['pnl_cash'].sum()
    gross_loss = abs(trades_df[trades_df['pnl_cash'] < 0]['pnl_cash'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # 總成本
    total_cost = trades_df['total_cost'].sum()
    
    return {
        'net_profit': net_profit,
        'ending_balance': trader.balance,
        'total_trades': len(trades_df),
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'max_drawdown': max_drawdown,
        'profit_factor': profit_factor,
        'total_cost': total_cost,
    }


def main():
    print("=" * 60)
    print("ATR 動態停損回測比較")
    print("=" * 60)
    
    # 載入配置
    cfg = load_config()
    print(f"\n載入配置完成")
    print(f"  - 策略長度：{cfg['strategy']['length']}")
    print(f"  - 進場分數：{cfg['strategy']['entry_score']}")
    print(f"  - 固定停損：{cfg['risk_mgmt']['stop_loss_pts']} 點")
    print(f"  - ATR 倍數：{cfg['risk_mgmt'].get('atr_multiplier', 2.0)}x")
    
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
    print(f"  - 15m K 棒：{len(p15)} 根")
    print(f"  - 1h K 棒：{len(p1h)} 根")
    
    # 執行回測 - 固定停損
    print("\n" + "-" * 60)
    print("執行回測 1/2: 固定停損 (30 點)")
    print("-" * 60)
    eq_fixed, trader_fixed = execute_engine(p5, p15, p1h, cfg, use_atr=False, atr_mult=0.0)
    trades_fixed = pd.DataFrame(trader_fixed.trades)
    metrics_fixed = calculate_metrics(trader_fixed, trades_fixed, eq_fixed)
    
    print(f"  淨獲利：{metrics_fixed['net_profit']:+,.0f} TWD")
    print(f"  交易次數：{metrics_fixed['total_trades']}")
    print(f"  勝率：{metrics_fixed['win_rate']:.1f}%")
    print(f"  最大回撤：{metrics_fixed['max_drawdown']:,.0f} TWD")
    print(f"  獲利因子：{metrics_fixed['profit_factor']:.2f}")
    
    # 執行回測 - ATR 動態停損
    print("\n" + "-" * 60)
    print("執行回測 2/2: ATR 動態停損")
    print("-" * 60)
    eq_atr, trader_atr = execute_engine(p5, p15, p1h, cfg, use_atr=True, atr_mult=cfg['risk_mgmt'].get('atr_multiplier', 0.0))
    trades_atr = pd.DataFrame(trader_atr.trades)
    metrics_atr = calculate_metrics(trader_atr, trades_atr, eq_atr)
    
    print(f"  淨獲利：{metrics_atr['net_profit']:+,.0f} TWD")
    print(f"  交易次數：{metrics_atr['total_trades']}")
    print(f"  勝率：{metrics_atr['win_rate']:.1f}%")
    print(f"  最大回撤：{metrics_atr['max_drawdown']:,.0f} TWD")
    print(f"  獲利因子：{metrics_atr['profit_factor']:.2f}")
    
    # 比較結果
    print("\n" + "=" * 60)
    print("比較結果")
    print("=" * 60)
    
    delta_profit = metrics_atr['net_profit'] - metrics_fixed['net_profit']
    delta_trades = metrics_atr['total_trades'] - metrics_fixed['total_trades']
    delta_winrate = metrics_atr['win_rate'] - metrics_fixed['win_rate']
    delta_mdd = metrics_atr['max_drawdown'] - metrics_fixed['max_drawdown']
    delta_pf = metrics_atr['profit_factor'] - metrics_fixed['profit_factor']
    
    print(f"""
┌─────────────────────────────────────────────────────────┐
│  指標          │  固定停損  │  ATR 動態  │   差異      │
├─────────────────────────────────────────────────────────┤
│  淨獲利 (TWD)  │ {metrics_fixed['net_profit']:>10,.0f} │ {metrics_atr['net_profit']:>10,.0f} │ {delta_profit:>+10,.0f} │
│  交易次數      │ {metrics_fixed['total_trades']:>10} │ {metrics_atr['total_trades']:>10} │ {delta_trades:>+10} │
│  勝率 (%)      │ {metrics_fixed['win_rate']:>10.1f} │ {metrics_atr['win_rate']:>10.1f} │ {delta_winrate:>+10.1f} │
│  最大回撤 (TWD)│ {metrics_fixed['max_drawdown']:>10,.0f} │ {metrics_atr['max_drawdown']:>10,.0f} │ {delta_mdd:>+10,.0f} │
│  獲利因子      │ {metrics_fixed['profit_factor']:>10.2f} │ {metrics_atr['profit_factor']:>10.2f} │ {delta_pf:>+10.2f} │
└─────────────────────────────────────────────────────────┘
""")
    
    # 結論
    print("=" * 60)
    print("結論")
    print("=" * 60)
    
    if delta_profit > 0:
        print(f"✅ ATR 動態停損獲利提升 {delta_profit:,.0f} TWD")
    else:
        print(f"❌ ATR 動態停損獲利減少 {abs(delta_profit):,.0f} TWD")
    
    if delta_mdd < 0:
        print(f"✅ ATR 動態停損回撤降低 {abs(delta_mdd):,.0f} TWD")
    else:
        print(f"⚠️  ATR 動態停損回撤增加 {delta_mdd:,.0f} TWD")
    
    if delta_winrate > 0:
        print(f"✅ ATR 動態停損勝率提升 {delta_winrate:.1f}%")
    else:
        print(f"⚠️  ATR 動態停損勝率下降 {abs(delta_winrate):.1f}%")
    
    # 儲存報告
    output_path = Path(__file__).parent.parent / "exports" / "simulations" / f"atr_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# ATR Dynamic Stop Loss Comparison Report\n\n")
        f.write(f"- Generated at: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"- Data: {len(p5)} 5m bars\n")
        f.write(f"- Fixed SL: {cfg['risk_mgmt']['stop_loss_pts']} points\n")
        f.write(f"- ATR Multiplier: {cfg['risk_mgmt'].get('atr_multiplier', 2.0)}x\n\n")
        
        f.write("## Summary\n\n")
        f.write("| Strategy | Net Profit | Trades | Win Rate | Max Drawdown | Profit Factor |\n")
        f.write("|:--|--:|--:|--:|--:|--:|\n")
        f.write(f"| Fixed SL | {metrics_fixed['net_profit']:+,.0f} | {metrics_fixed['total_trades']} | {metrics_fixed['win_rate']:.1f}% | {metrics_fixed['max_drawdown']:,.0f} | {metrics_fixed['profit_factor']:.2f} |\n")
        f.write(f"| ATR Dynamic | {metrics_atr['net_profit']:+,.0f} | {metrics_atr['total_trades']} | {metrics_atr['win_rate']:.1f}% | {metrics_atr['max_drawdown']:,.0f} | {metrics_atr['profit_factor']:.2f} |\n\n")
        
        f.write("## Delta\n\n")
        f.write(f"- Net Profit Delta: {delta_profit:+,.0f} TWD\n")
        f.write(f"- Trades Delta: {delta_trades:+}\n")
        f.write(f"- Win Rate Delta: {delta_winrate:+.1f}%\n")
        f.write(f"- Max Drawdown Delta: {delta_mdd:+,.0f} TWD\n")
        f.write(f"- Profit Factor Delta: {delta_pf:+.2f}\n")
    
    print(f"\n📄 報告已儲存至：{output_path}")


if __name__ == "__main__":
    main()
