import pandas as pd
from datetime import datetime
import os

class PaperTrader:
    def __init__(
        self,
        ticker="TMF",
        initial_balance=100000,
        point_value=10,
        fee_per_side=20,
        exchange_fee_per_side=0,
        tax_rate=0.0,
    ):
        self.ticker = ticker
        self.balance = initial_balance
        self.position = 0  
        self.entry_price = 0
        self.entry_time = None
        self.trades = []
        self.point_value = point_value
        self.fee_per_side = fee_per_side
        self.exchange_fee_per_side = exchange_fee_per_side
        self.tax_rate = tax_rate
        self.current_stop_loss = None
        self.be_triggered = False
        self.be_points = None

    def execute_signal(self, signal: str, price: float, timestamp: datetime, lots=1, max_lots=1, stop_loss=None, break_even_trigger=None):
        if signal == "BUY":
            if self.position < max_lots:
                if self.position < 0: self.execute_signal("EXIT", price, timestamp)
                if self.position == 0:
                    self.entry_price, self.entry_time, self.be_triggered = price, timestamp, False
                    self.current_stop_loss = price - stop_loss if stop_loss else None
                    self.be_points = break_even_trigger
                else:
                    self.entry_price = ((self.entry_price * self.position) + (price * lots)) / (self.position + lots)
                self.position += lots
                return f"Entry LONG {lots} at {price}"
            
        elif signal == "SELL":
            if abs(self.position) < max_lots:
                if self.position > 0: self.execute_signal("EXIT", price, timestamp)
                if self.position == 0:
                    self.entry_price, self.entry_time, self.be_triggered = price, timestamp, False
                    self.current_stop_loss = price + stop_loss if stop_loss else None
                    self.be_points = break_even_trigger
                else:
                    self.entry_price = ((self.entry_price * abs(self.position)) + (price * lots)) / (abs(self.position) + lots)
                self.position -= lots
                return f"Entry SHORT {lots} at {price}"
            
        elif (signal == "EXIT" or signal == "PARTIAL_EXIT") and self.position != 0:
            lots_to_exit = lots if signal == "PARTIAL_EXIT" else abs(self.position)
            lots_to_exit = min(lots_to_exit, abs(self.position))
            
            pnl_pts = (price - self.entry_price) * (1 if self.position > 0 else -1)
            broker_fee = self.fee_per_side * 2 * lots_to_exit
            exchange_fee = self.exchange_fee_per_side * 2 * lots_to_exit
            tax_cost = ((self.entry_price + price) * self.point_value * self.tax_rate) * lots_to_exit
            total_cost = broker_fee + exchange_fee + tax_cost
            pnl_cash = (pnl_pts * self.point_value * lots_to_exit) - total_cost
            
            direction = "LONG" if self.position > 0 else "SHORT"
            self.trades.append({
                "ticker": self.ticker, "entry_time": self.entry_time, "exit_time": timestamp,
                "direction": direction, "entry_price": self.entry_price, "exit_price": price,
                "lots": lots_to_exit, "pnl_points": pnl_pts, "gross_pnl_cash": pnl_pts * self.point_value * lots_to_exit,
                "broker_fee": broker_fee, "exchange_fee": exchange_fee, "tax_cost": tax_cost,
                "total_cost": total_cost, "pnl_cash": pnl_cash, "type": signal
            })
            self.balance += pnl_cash
            
            if signal == "EXIT" or lots_to_exit == abs(self.position):
                self.position, self.entry_price, self.current_stop_loss = 0, 0, None
            else:
                self.position = (abs(self.position) - lots_to_exit) * (1 if self.position > 0 else -1)
            return f"{signal} {lots_to_exit} at {price}, PnL: {pnl_cash:.0f}"
            
        return None

    def update_trailing_stop(self, current_price: float):
        if self.position == 0 or not self.be_points or self.be_triggered: return False
        pnl = (current_price - self.entry_price) * (1 if self.position > 0 else -1)
        if pnl >= self.be_points:
            self.current_stop_loss = self.entry_price + (2 * (1 if self.position > 0 else -1))
            self.be_triggered = True; return True
        return False

    def check_stop_loss(self, price: float, timestamp: datetime):
        if self.position > 0 and self.current_stop_loss and price <= self.current_stop_loss:
            return self.execute_signal("EXIT", self.current_stop_loss, timestamp)
        if self.position < 0 and self.current_stop_loss and price >= self.current_stop_loss:
            return self.execute_signal("EXIT", self.current_stop_loss, timestamp)
        return None

    def get_performance_report(self):
        if not self.trades: return "No trades."
        df = pd.DataFrame(self.trades)
        return (
            f"# 📊 Report\n"
            f"- **PnL**: {df['pnl_cash'].sum():+,.0f} TWD\n"
            f"- **WinRate**: {(df['pnl_cash']>0).mean()*100:.1f}%\n"
            f"- **Total Cost**: {df['total_cost'].sum():,.0f} TWD\n\n"
            f"{df.to_markdown()}"
        )

    def save_report(self):
        os.makedirs("exports/simulations", exist_ok=True)
        path = f"exports/simulations/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(path, "w") as f: f.write(self.get_performance_report())
        return path
