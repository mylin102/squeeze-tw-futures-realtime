import pandas as pd
from datetime import datetime
import os

class PaperTrader:
    def __init__(self, ticker="MXFR1", initial_balance=100000):
        self.ticker = ticker
        self.balance = initial_balance
        self.position = 0  # 單位為「口」，正數為多單，負數為空單
        self.entry_price = 0
        self.entry_time = None
        self.trades = []
        self.fee_per_side = 20 
        self.current_stop_loss = None
        self.be_triggered = False
        self.be_points = None

    def execute_signal(self, signal: str, price: float, timestamp: datetime, lots=1, max_lots=1, stop_loss=None, break_even_trigger=None):
        """
        執行交易信號
        lots: 本次欲交易口數
        max_lots: 總部位上限
        """
        # --- 進入多單 ---
        if signal == "BUY":
            if self.position < max_lots:
                # 若目前為空單，先全數平倉再進場 (反手邏輯由主程式控制，此處輔助)
                if self.position < 0: self.execute_signal("EXIT", price, timestamp)
                
                if self.position == 0:
                    self.entry_price = price
                    self.entry_time = timestamp
                    self.current_stop_loss = price - stop_loss if stop_loss else None
                    self.be_triggered = False
                    self.be_points = break_even_trigger
                else:
                    # 平均成本
                    total_cost = (self.entry_price * self.position) + (price * lots)
                    self.entry_price = total_cost / (self.position + lots)
                
                self.position += lots
                return f"Entry LONG {lots} lot(s) at {price} (Total: {self.position})"
            
        # --- 進入空單 ---
        elif signal == "SELL":
            if abs(self.position) < max_lots:
                # 若目前為多單，先全數平倉
                if self.position > 0: self.execute_signal("EXIT", price, timestamp)
                
                if self.position == 0:
                    self.entry_price = price
                    self.entry_time = timestamp
                    self.current_stop_loss = price + stop_loss if stop_loss else None
                    self.be_triggered = False
                    self.be_points = break_even_trigger
                else:
                    # 平均成本
                    total_cost = (self.entry_price * abs(self.position)) + (price * lots)
                    self.entry_price = total_cost / (abs(self.position) + lots)
                
                self.position -= lots
                return f"Entry SHORT {lots} lot(s) at {price} (Total: {self.position})"
            
        # --- 全數平倉 ---
        elif signal == "EXIT" and self.position != 0:
            pnl_points = (price - self.entry_price) * (1 if self.position > 0 else -1)
            current_lots = abs(self.position)
            # 假設乘數固定為 10 (微台指)
            pnl_cash = (pnl_points * 10 * current_lots) - (self.fee_per_side * 2 * current_lots)
            
            direction = "LONG" if self.position > 0 else "SHORT"
            trade_record = {
                "ticker": self.ticker,
                "entry_time": self.entry_time,
                "exit_time": timestamp,
                "direction": direction,
                "entry_price": self.entry_price,
                "exit_price": price,
                "lots": current_lots,
                "pnl_points": pnl_points,
                "pnl_cash": pnl_cash
            }
            self.trades.append(trade_record)
            self.balance += pnl_cash
            self.position = 0
            self.entry_price = 0
            self.current_stop_loss = None
            return f"Exit {direction} {current_lots} lot(s) at {price}, PnL: {pnl_cash:.0f}"
            
        return None

    def update_trailing_stop(self, current_price: float):
        """實作保本停損邏輯"""
        if self.position == 0 or not self.be_points or self.be_triggered:
            return False
            
        direction_sign = 1 if self.position > 0 else -1
        pnl = (current_price - self.entry_price) * direction_sign
        if pnl >= self.be_points:
            self.current_stop_loss = self.entry_price + (2 * direction_sign)
            self.be_triggered = True
            return True
        return False

    def check_stop_loss(self, current_price: float, timestamp: datetime):
        """檢查是否觸發停損"""
        if self.position > 0 and self.current_stop_loss and current_price <= self.current_stop_loss:
            return self.execute_signal("EXIT", self.current_stop_loss, timestamp)
        elif self.position < 0 and self.current_stop_loss and current_price >= self.current_stop_loss:
            return self.execute_signal("EXIT", self.current_stop_loss, timestamp)
        return None

    def get_performance_report(self):
        if not self.trades: return "No trades executed."
        df = pd.DataFrame(self.trades)
        total_pnl = df['pnl_cash'].sum()
        win_rate = (df['pnl_cash'] > 0).mean() * 100
        return f"""
# 📊 Backtest/Simulation Report
- **Total Net PnL**: {total_pnl:+.0f} TWD
- **Total Trades**: {len(df)}
- **Win Rate**: {win_rate:.1f}%
- **Max Gain/Loss**: {df['pnl_points'].max():.1f} / {df['pnl_points'].min():.1f} pts
\n{df.to_markdown()}
"""

    def save_report(self):
        report_dir = "exports/simulations"
        os.makedirs(report_dir, exist_ok=True)
        filename = f"{report_dir}/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(self.get_performance_report())
        return filename
