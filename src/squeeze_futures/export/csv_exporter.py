"""
CSV Exporter for trade data.
"""
import csv
from pathlib import Path
from typing import List, Dict, Any


class CSVExporter:
    """Export trading data to CSV files."""

    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_trades(self, trades: List[Dict[str, Any]], filename: str = "trades.csv"):
        """Export trades to CSV."""
        filepath = self.output_dir / filename
        if not trades:
            return filepath

        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)

        return filepath

    def export_equity_curve(self, equity_data: List[Dict[str, Any]], filename: str = "equity.csv"):
        """Export equity curve to CSV."""
        filepath = self.output_dir / filename
        if not equity_data:
            return filepath

        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=equity_data[0].keys())
            writer.writeheader()
            writer.writerows(equity_data)

        return filepath
