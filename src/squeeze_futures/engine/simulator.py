import pandas as pd
from datetime import datetime
import os

class PaperTrader:
    def __init__(self, ticker="MXFR1", initial_balance=100000):
        self.ticker = ticker
        self.balance = initial_balance
        self.position = 0  # 0: 空手, 1: 多單, -1: 空單
        self.entry_price = 0
        self.entry_time = None
        self.trades = []
        self.fee_per_side = 20 # 預估手續費+稅

    def execute_signal(self, signal: str, price: float, timestamp: datetime):
        """
        執行信號：'BUY', 'SELL', 'EXIT'
        """
        if signal == "BUY" and self.position == 0:
            self.position = 1
            self.entry_price = price
            self.entry_time = timestamp
            return f"Entry LONG at {price}"
            
        elif signal == "SELL" and self.position == 0:
            self.position = -1
            self.entry_price = price
            self.entry_time = timestamp
            return f"Entry SHORT at {price}"
            
        elif signal == "EXIT" and self.position != 0:
            pnl_points = (price - self.entry_price) * self.position
            # 微台指 1 點 = 10 元
            pnl_cash = pnl_points * 10 - (self.fee_per_side * 2)
            
            trade_record = {
                "ticker": self.ticker,
                "entry_time": self.entry_time,
                "exit_time": timestamp,
                "direction": "LONG" if self.position == 1 else "SHORT",
                "entry_price": self.entry_price,
                "exit_price": price,
                "pnl_points": pnl_points,
                "pnl_cash": pnl_cash
            }
            self.trades.append(trade_record)
            self.balance += pnl_cash
            self.position = 0
            self.entry_price = 0
            return f"Exit at {price}, PnL: {pnl_cash:.0f}"
            
        return None

    def get_performance_report(self):
        if not self.trades:
            return "No trades executed today."
            
        df = pd.DataFrame(self.trades)
        total_pnl = df['pnl_cash'].sum()
        win_rate = (df['pnl_cash'] > 0).mean() * 100
        
        report = f"""
# 📊 Squeeze Strategy Daily Simulation Report
**Date**: {datetime.now().strftime('%Y-%m-%d')}
**Ticker**: {self.ticker}

## 📈 Performance Summary
- **Total Net PnL**: {total_pnl:+.0f} TWD
- **Total Trades**: {len(df)}
- **Win Rate**: {win_rate:.1f}%
- **Max Gain**: {df['pnl_points'].max():.1f} pts
- **Max Drawdown**: {df['pnl_points'].min():.1f} pts

## 📝 Trade Logs
{df[['entry_time', 'exit_time', 'direction', 'entry_price', 'exit_price', 'pnl_points', 'pnl_cash']].to_markdown()}
"""
        return report

    def save_report(self):
        report_dir = "exports/simulations"
        os.makedirs(report_dir, exist_ok=True)
        filename = f"{report_dir}/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(self.get_performance_report())
        return filename
