"""
Performance Analyzer for trading results.
"""
from typing import List, Dict, Any, Optional
import numpy as np


class PerformanceAnalyzer:
    """Analyze trading performance metrics."""

    def __init__(self, trades: List[Dict[str, Any]], initial_balance: float = 100000):
        self.trades = trades
        self.initial_balance = initial_balance

    def calculate_metrics(self) -> Dict[str, Any]:
        """Calculate performance metrics."""
        if not self.trades:
            return self._empty_metrics()

        pnls = [t.get('pnl_cash', 0) for t in self.trades]
        winning_trades = [p for p in pnls if p > 0]
        losing_trades = [p for p in pnls if p < 0]

        total_pnl = sum(pnls)
        gross_profit = sum(winning_trades) if winning_trades else 0
        gross_loss = abs(sum(losing_trades)) if losing_trades else 0

        return {
            'total_trades': len(self.trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(self.trades) * 100 if self.trades else 0,
            'total_pnl': total_pnl,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'profit_factor': gross_profit / gross_loss if gross_loss > 0 else float('inf'),
            'average_win': np.mean(winning_trades) if winning_trades else 0,
            'average_loss': np.mean(losing_trades) if losing_trades else 0,
            'final_balance': self.initial_balance + total_pnl,
        }

    def _empty_metrics(self) -> Dict[str, Any]:
        """Return empty metrics."""
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0,
            'total_pnl': 0,
            'gross_profit': 0,
            'gross_loss': 0,
            'profit_factor': 0,
            'average_win': 0,
            'average_loss': 0,
            'final_balance': self.initial_balance,
        }
