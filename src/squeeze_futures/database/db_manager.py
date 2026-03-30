"""
Database Manager for SQLite persistence.
Minimal stub implementation.
"""
import sqlite3
from typing import Optional, Dict, Any, List


class DatabaseManager:
    """SQLite database manager for trade persistence."""

    def __init__(self, db_path: str = "data/trading.db"):
        self.db_path = db_path
        self._init_schema()

    def _get_connection(self):
        """Get SQLite connection."""
        return sqlite3.connect(self.db_path)

    def _init_schema(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT,
                    direction TEXT,
                    type TEXT,
                    timestamp TEXT,
                    price REAL,
                    lots INTEGER,
                    pnl_cash REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    balance REAL,
                    position INTEGER,
                    unrealized_pnl REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT,
                    module TEXT,
                    message TEXT,
                    details TEXT,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def record_trade(self, trade: Dict[str, Any]):
        """Record a trade to the database."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO trades (ticker, direction, type, timestamp, price, lots, pnl_cash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.get('ticker', ''),
                trade.get('direction', ''),
                trade.get('type', ''),
                trade.get('timestamp', ''),
                trade.get('price', 0),
                trade.get('lots', 0),
                trade.get('pnl_cash', 0),
            ))
            conn.commit()

    def record_equity_snapshot(self, timestamp: str, balance: float, position: int, unrealized_pnl: float = 0):
        """Record an equity snapshot."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO equity_snapshots (timestamp, balance, position, unrealized_pnl)
                VALUES (?, ?, ?, ?)
            """, (timestamp, balance, position, unrealized_pnl))
            conn.commit()

    def log_system_event(self, level: str, module: str, message: str, details: Optional[str] = None):
        """Log a system event."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO system_logs (level, module, message, details)
                VALUES (?, ?, ?, ?)
            """, (level, module, message, details))
            conn.commit()

    def get_trades(self, ticker: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get trades from the database."""
        with self._get_connection() as conn:
            if ticker:
                cursor = conn.execute(
                    "SELECT * FROM trades WHERE ticker = ? ORDER BY timestamp DESC LIMIT ?",
                    (ticker, limit)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?",
                    (limit,)
                )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_equity_curve(self, limit: int = 1000) -> List[Dict]:
        """Get equity curve data."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM equity_snapshots ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
