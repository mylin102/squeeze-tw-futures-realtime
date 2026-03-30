#!/usr/bin/env python3
"""
MA 動態停損回測比較 - 生成 HTML 報告（含資產變化曲線）
"""
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml
import json

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


def execute_engine(p5, p15, p1h, cfg, stop_mode: str = "fixed", ma_mult: float = 0.0, ma_len: int = 60, ma_ticks: int = 5):
    """執行回測"""
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
    
    ma_type = RISK.get('ma_stop_type', 'below')
    ma_length = ma_len
    ma_tick = ma_ticks
    
    fixed_sl = RISK["stop_loss_pts"]
    lots_entry = 2
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]
        price, vwap = row['Close'], row['vwap']
        
        stop_loss_pts = fixed_sl
        
        # 持倉管理
        if trader.position != 0:
            trader.update_trailing_stop(price)
            
            exited = False  # 標記是否已平倉
            
            # MA 動態停損（最優先）
            if stop_mode == "ma" and ma_mult > 0:
                ma_stop_price_val = calculate_ma_stop_price(
                    p5.iloc[:i+1], trader.position, ma_type, ma_length, ma_tick, ma_mult,
                    use_prev_ma=True  # 使用前一 bar 的 MA，避免未來函數
                )
                if ma_stop_price_val is not None:
                    if trader.position > 0 and price <= ma_stop_price_val:
                        trader.execute_signal("EXIT", ma_stop_price_val, curr_time)
                        has_tp1_hit = False
                        exited = True
                    elif trader.position < 0 and price >= ma_stop_price_val:
                        trader.execute_signal("EXIT", ma_stop_price_val, curr_time)
                        has_tp1_hit = False
                        exited = True
            
            # 分批停利（僅在未平倉時執行）
            if not exited and trader.position != 0 and lots_entry == 2 and abs(trader.position) == 2 and not has_tp1_hit:
                pnl = (price - trader.entry_price) * (1 if trader.position > 0 else -1)
                if pnl >= TP.get('tp1_pts', 40):
                    trader.execute_signal("PARTIAL_EXIT", price, curr_time, lots=1)
                    trader.current_stop_loss = trader.entry_price
                    has_tp1_hit = True
            
            # VWAP 離場（最後檢查，僅在未平倉時執行）
            if not exited and trader.position != 0 and RISK.get('exit_on_vwap', True):
                if (trader.position > 0 and price < vwap and not row.get('opening_bullish', False)) or \
                   (trader.position < 0 and price > vwap and not row.get('opening_bearish', False)):
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
                
                sqz_buy = (not row.get('sqz_on', True)) and score >= STRAT['entry_score'] and price > vwap and row.get('mom_state', 0) == 3
                pb_buy = p5['is_new_high'].iloc[max(0, i-12):i].any() if i > 0 else False
                pb_buy = pb_buy and row.get('in_bull_pb_zone', False) and price > row.get('Open', price) and row.get('bullish_align', False)
                
                sqz_sell = (not row.get('sqz_on', True)) and score <= -STRAT['entry_score'] and price < vwap and row.get('mom_state', 0) == 0
                pb_sell = p5['is_new_low'].iloc[max(0, i-12):i].any() if i > 0 else False
                pb_sell = pb_sell and row.get('in_bear_pb_zone', False) and price < row.get('Open', price) and row.get('bearish_align', False)
                
                if sqz_buy or pb_buy:
                    fill_price = simulate_order_fill("BUY", price, row, execution_model)
                    if fill_price is not None:
                        trader.execute_signal("BUY", fill_price, curr_time, lots=lots_entry, max_lots=lots_entry, stop_loss=stop_loss_pts, break_even_trigger=RISK['break_even_pts'])
                elif sqz_sell or pb_sell:
                    fill_price = simulate_order_fill("SELL", price, row, execution_model)
                    if fill_price is not None:
                        trader.execute_signal("SELL", fill_price, curr_time, lots=lots_entry, max_lots=lots_entry, stop_loss=stop_loss_pts, break_even_trigger=RISK['break_even_pts'])
            
            elif trader.position > 0 and (row.get('mom_state', 0) < 2 or score < 20):
                trader.execute_signal("EXIT", price, curr_time)
                has_tp1_hit = False
            elif trader.position < 0 and (row.get('mom_state', 0) > 1 or score > -20):
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
        return {'net_profit': 0, 'total_trades': 0, 'win_rate': 0, 'max_drawdown': 0, 'profit_factor': 0, 'avg_trade': 0, 'sharpe': 0}
    
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
    
    # Sharpe Ratio (年化)
    returns = eq_series.pct_change().dropna()
    sharpe = (returns.mean() / returns.std()) * (252 * 4.8 * 60) ** 0.5 if len(returns) > 1 else 0
    
    return {
        'net_profit': net_profit,
        'total_trades': len(trades_df),
        'win_rate': win_rate,
        'max_drawdown': max_drawdown,
        'profit_factor': profit_factor,
        'avg_trade': avg_trade,
        'sharpe': sharpe,
        'ending_balance': trader.balance,
    }


def main():
    print("=" * 60)
    print("MA 動態停損回測比較 - 生成 HTML 報告")
    print("=" * 60)
    
    cfg = load_config()
    
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
        ("固定 30 點", "fixed", 0, 60, 5),
        ("MA20-5tick", "ma", 1.0, 20, 5),
        ("MA20-10tick", "ma", 1.0, 20, 10),
        ("MA60-5tick", "ma", 1.0, 60, 5),
    ]
    
    results = []
    equity_curves = {}
    timestamps = [str(ts) for ts in p5.index]
    
    print("\n" + "=" * 60)
    print("執行回測")
    print("=" * 60)
    
    for label, mode, mult, ma_len, ma_tk in test_configs:
        print(f"\n[dim]測試 {label}...[/dim]")
        eq, trader = execute_engine(p5, p15, p1h, cfg, stop_mode=mode, ma_mult=mult, ma_len=ma_len, ma_ticks=ma_tk)
        trades = pd.DataFrame(trader.trades)
        metrics = calculate_metrics(trader, trades, eq)
        
        results.append({
            'strategy': label,
            'label': label,
            **metrics,
        })
        
        equity_curves[label] = eq
        
        print(f"  淨獲利：{metrics['net_profit']:+,.0f} TWD | 交易：{metrics['total_trades']} | 勝率：{metrics['win_rate']:.1f}% | MDD: {metrics['max_drawdown']:,.0f} | PF: {metrics['profit_factor']:.2f}")
    
    # 生成 HTML 報告
    print("\n" + "=" * 60)
    print("生成 HTML 報告...")
    print("=" * 60)
    
    # 準備圖表數據
    chart_data = {
        'timestamps': timestamps,
        'series': []
    }
    
    for r in results:
        chart_data['series'].append({
            'name': r['label'],
            'data': [round(v, 2) for v in equity_curves[r['label']]],
            'color': {
                '固定 30 點': '#888888',
                'MA20-5tick': '#00FF00',
                'MA20-10tick': '#00CCFF',
                'MA60-5tick': '#FF6600',
            }.get(r['label'], '#999999')
        })
    
    # 準備表格數據
    table_data = []
    for r in results:
        table_data.append({
            'strategy': r['label'],
            'net_profit': round(r['net_profit'], 2),
            'total_trades': r['total_trades'],
            'win_rate': round(r['win_rate'], 2),
            'max_drawdown': round(r['max_drawdown'], 2),
            'profit_factor': round(r['profit_factor'], 2),
            'sharpe': round(r['sharpe'], 3),
            'avg_trade': round(r['avg_trade'], 2),
            'ending_balance': round(r['ending_balance'], 2),
        })
    
    # 找出最佳策略
    best = max(results, key=lambda x: x['net_profit'])
    
    # 生成 HTML
    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MA 動態停損回測比較報告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{ 
            text-align: center; 
            margin-bottom: 10px; 
            color: #00d4ff;
            font-size: 2.5em;
            text-shadow: 0 0 20px rgba(0, 212, 255, 0.5);
        }}
        .subtitle {{ 
            text-align: center; 
            color: #888; 
            margin-bottom: 30px;
            font-size: 1.1em;
        }}
        .card {{ 
            background: rgba(255, 255, 255, 0.05);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 25px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }}
        .card h2 {{ 
            color: #00d4ff;
            margin-bottom: 20px;
            font-size: 1.5em;
            border-bottom: 2px solid rgba(0, 212, 255, 0.3);
            padding-bottom: 10px;
        }}
        .metrics-grid {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
            gap: 20px;
            margin-bottom: 20px;
        }}
        .metric-box {{ 
            background: rgba(0, 212, 255, 0.1);
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            border: 1px solid rgba(0, 212, 255, 0.2);
            transition: transform 0.3s ease;
        }}
        .metric-box:hover {{ transform: translateY(-5px); }}
        .metric-box.best {{ 
            background: rgba(0, 255, 100, 0.15);
            border-color: rgba(0, 255, 100, 0.4);
        }}
        .metric-value {{ 
            font-size: 2em; 
            font-weight: bold;
            margin-bottom: 5px;
        }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .positive {{ color: #00ff88; }}
        .negative {{ color: #ff6b6b; }}
        table {{ 
            width: 100%; 
            border-collapse: collapse; 
            margin-top: 20px;
        }}
        th, td {{ 
            padding: 15px; 
            text-align: right; 
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        th {{ 
            background: rgba(0, 212, 255, 0.2);
            color: #00d4ff;
            font-weight: 600;
            text-align: center;
        }}
        tr:hover {{ background: rgba(255, 255, 255, 0.05); }}
        td:first-child {{ text-align: left; font-weight: 500; }}
        .chart-container {{ 
            position: relative; 
            height: 500px; 
            margin-top: 20px;
        }}
        .best-badge {{
            display: inline-block;
            background: linear-gradient(135deg, #00ff88, #00d4ff);
            color: #000;
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 0.9em;
            margin-left: 10px;
        }}
        .highlight {{ 
            background: rgba(0, 255, 100, 0.1);
            font-weight: bold;
        }}
        @media (max-width: 768px) {{
            .metrics-grid {{ grid-template-columns: repeat(2, 1fr); }}
            th, td {{ padding: 10px 5px; font-size: 0.9em; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 MA 動態停損回測比較報告</h1>
        <p class="subtitle">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Data: {len(p5)} 5m bars | Period: {timestamps[0][:10]} ~ {timestamps[-1][:10]}</p>
        
        <div class="card">
            <h2>🏆 最佳策略</h2>
            <div class="metrics-grid">
                <div class="metric-box best">
                    <div class="metric-value positive">{best['label']} <span class="best-badge">BEST</span></div>
                    <div class="metric-label">最佳停損策略</div>
                </div>
                <div class="metric-box best">
                    <div class="metric-value positive">+{best['net_profit']:,.0f}</div>
                    <div class="metric-label">淨獲利 (TWD)</div>
                </div>
                <div class="metric-box best">
                    <div class="metric-value">{best['win_rate']:.1f}%</div>
                    <div class="metric-label">勝率</div>
                </div>
                <div class="metric-box best">
                    <div class="metric-value">{best['profit_factor']:.2f}</div>
                    <div class="metric-label">獲利因子</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>📈 資產變化曲線</h2>
            <div class="chart-container">
                <canvas id="equityChart"></canvas>
            </div>
        </div>
        
        <div class="card">
            <h2>📊 績效指標比較</h2>
            <table>
                <thead>
                    <tr>
                        <th>策略</th>
                        <th>淨獲利 (TWD)</th>
                        <th>交易次數</th>
                        <th>勝率 (%)</th>
                        <th>最大回撤 (TWD)</th>
                        <th>獲利因子</th>
                        <th>Sharpe</th>
                        <th>平均交易 (TWD)</th>
                        <th>期末餘額 (TWD)</th>
                    </tr>
                </thead>
                <tbody>
"""
    
    for i, r in enumerate(table_data):
        is_best = r['strategy'] == best['label']
        row_class = 'class="highlight"' if is_best else ''
        html_content += f"""                    <tr {row_class}>
                        <td>{r['strategy']}{' <span class="best-badge">BEST</span>' if is_best else ''}</td>
                        <td class="{'positive' if r['net_profit'] > 0 else 'negative'}">{r['net_profit']:+,.0f}</td>
                        <td>{r['total_trades']}</td>
                        <td>{r['win_rate']:.1f}%</td>
                        <td class="negative">-{r['max_drawdown']:,.0f}</td>
                        <td>{r['profit_factor']:.2f}</td>
                        <td>{r['sharpe']:.3f}</td>
                        <td class="{'positive' if r['avg_trade'] > 0 else 'negative'}">{r['avg_trade']:+,.0f}</td>
                        <td class="{'positive' if r['ending_balance'] > 100000 else 'negative'}">{r['ending_balance']:,.0f}</td>
                    </tr>
"""
    
    html_content += f"""                </tbody>
            </table>
        </div>
        
        <div class="card">
            <h2>📉 回撤比較</h2>
            <div class="metrics-grid">
"""
    
    for r in results:
        is_best = r['strategy'] == best['label']
        html_content += f"""                <div class="metric-box{' best' if is_best else ''}">
                    <div class="metric-value negative">-{r['max_drawdown']:,.0f}</div>
                    <div class="metric-label">{r['strategy']}</div>
                </div>
"""
    
    html_content += f"""            </div>
        </div>
    </div>
    
    <script>
        const ctx = document.getElementById('equityChart').getContext('2d');
        const chartData = {json.dumps(chart_data)};
        
        const datasets = chartData.series.map((series, idx) => ({{
            label: series.name,
            data: chartData.timestamps.map((t, i) => ({{ x: i, y: series.data[i] }})),
            borderColor: series.color,
            backgroundColor: series.color + '20',
            borderWidth: 2,
            fill: false,
            tension: 0.1,
            pointRadius: 0,
        }}));
        
        new Chart(ctx, {{
            type: 'line',
            data: {{ datasets }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    mode: 'index',
                    intersect: false,
                }},
                plugins: {{
                    legend: {{
                        display: true,
                        position: 'top',
                        labels: {{ color: '#e0e0e0', font: {{ size: 12 }} }}
                    }},
                    tooltip: {{
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleColor: '#00d4ff',
                        bodyColor: '#e0e0e0',
                        borderColor: 'rgba(0, 212, 255, 0.3)',
                        borderWidth: 1,
                        callbacks: {{
                            label: function(context) {{
                                return context.dataset.label + ': ' + context.parsed.y.toLocaleString('en-US', {{minimumFractionDigits: 0, maximumFractionDigits: 0}}) + ' TWD';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        display: true,
                        title: {{ display: true, text: 'Time (5m bars)', color: '#888' }},
                        ticks: {{ color: '#888', maxTicksLimit: 20 }},
                        grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}
                    }},
                    y: {{
                        display: true,
                        title: {{ display: true, text: 'Equity (TWD)', color: '#888' }},
                        ticks: {{ color: '#888', callback: (val) => val.toLocaleString('en-US', {{minimumFractionDigits: 0, maximumFractionDigits: 0}}) + 'K' }},
                        grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    
    # 儲存 HTML 檔案
    output_path = Path(__file__).parent.parent / "exports" / "simulations" / f"ma_stop_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"\n✅ HTML 報告已儲存至：{output_path}")
    print(f"   使用瀏覽器開啟查看互動式圖表")


if __name__ == "__main__":
    main()
