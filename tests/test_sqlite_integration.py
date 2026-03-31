#!/usr/bin/env python3
"""
Test script for SQLite persistence integration.

Run this to verify:
1. Database initialization
2. Trade recording
3. Equity snapshots
4. CSV export
5. Performance analysis
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import time

import pandas as pd
import pytest

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.database.db_manager import DatabaseManager
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.export.csv_exporter import CSVExporter
from squeeze_futures.analysis.performance import PerformanceAnalyzer


@pytest.fixture
def integration_workspace(tmp_path):
    return _create_integration_workspace(tmp_path)


def _create_integration_workspace(base_path: Path):
    export_dir = base_path / "exports"
    export_dir.mkdir()
    return {
        "trading_db": base_path / "test_trading.db",
        "paper_db": base_path / "test_papertrader.db",
        "snapshot_db": base_path / "test_snapshot.db",
        "export_dir": export_dir,
        "report_path": export_dir / "test_performance_report.md",
    }


def _record_sample_trade(db: DatabaseManager) -> None:
    entry_time = datetime.now()
    exit_time = entry_time + timedelta(minutes=10)
    db.record_trade({
        'ticker': 'TMF',
        'direction': 'LONG',
        'type': 'ENTRY',
        'entry_time': entry_time,
        'entry_price': 20000,
        'lots': 2,
        'pnl_cash': 0,
        'entry_score': 75,
    })
    db.record_trade({
        'ticker': 'TMF',
        'direction': 'LONG',
        'type': 'EXIT',
        'entry_time': entry_time,
        'exit_time': exit_time,
        'entry_price': 20000,
        'exit_price': 20100,
        'lots': 2,
        'pnl_points': 100,
        'gross_pnl_cash': 2000,
        'broker_fee': 80,
        'exchange_fee': 0,
        'tax_cost': 16,
        'total_cost': 96,
        'pnl_cash': 1904,
        'exit_reason': 'TP1 hit',
    })


def _build_completed_paper_trader(db_path) -> PaperTrader:
    trader = PaperTrader(
        ticker="TMF",
        initial_balance=100000,
        db_path=str(db_path),
        snapshot_interval=60,
    )
    now = datetime.now()
    trader.execute_signal("BUY", 20000, now, lots=2)
    trader.execute_signal("EXIT", 20100, now + timedelta(minutes=10), lots=2)
    return trader


def test_database_initialization(integration_workspace):
    """測試 1: 資料庫初始化"""
    print("\n" + "="*60)
    print("測試 1: 資料庫初始化")
    print("="*60)
    
    db_path = integration_workspace["trading_db"]
    db = DatabaseManager(db_path)
    
    # 驗證表格存在
    with db._get_connection() as conn:
        tables = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name IN ('trades', 'equity_snapshots', 'system_logs')
        """).fetchall()
    
    assert len(tables) == 3, f"Expected 3 tables, got {len(tables)}"
    print(f"✅ 資料庫初始化成功：{db_path}")
    print(f"✅ 表格數量：{len(tables)}")
    
def test_trade_recording(integration_workspace):
    """測試 2: 交易記錄"""
    print("\n" + "="*60)
    print("測試 2: 交易記錄")
    print("="*60)
    
    db_path = integration_workspace["trading_db"]
    db = DatabaseManager(db_path)
    _record_sample_trade(db)
    
    # 驗證記錄
    trades = db.get_trade_history()
    assert len(trades) == 2, f"Expected 2 trades, got {len(trades)}"
    
    summary = db.get_performance_summary()
    assert summary['total_trades'] == 1, f"Expected 1 completed trade, got {summary['total_trades']}"
    assert summary['net_profit'] == 1904, f"Expected net profit 1904, got {summary['net_profit']}"
    
    print(f"✅ 交易記錄成功")
    print(f"✅ 總交易數：{len(trades)}")
    print(f"✅ 淨利：{summary['net_profit']}")
    
def test_papertrader_integration(integration_workspace):
    """測試 3: PaperTrader 整合"""
    print("\n" + "="*60)
    print("測試 3: PaperTrader 整合")
    print("="*60)
    
    db_path = integration_workspace["paper_db"]
    trader = _build_completed_paper_trader(db_path)
    
    # 驗證記憶體記錄
    assert len(trader.trades) == 1, f"Expected 1 trade in memory, got {len(trader.trades)}"
    
    # 驗證資料庫記錄
    db_trades = trader.get_db_trade_history()
    assert len(db_trades) >= 1, f"Expected >= 1 trade in DB, got {len(db_trades)}"
    
    # 驗證績效
    summary = trader.get_db_performance_summary()
    assert summary['total_trades'] >= 1, f"Expected >= 1 completed trade, got {summary['total_trades']}"
    
    print(f"✅ PaperTrader 整合成功")
    print(f"✅ 記憶體交易數：{len(trader.trades)}")
    print(f"✅ 資料庫交易數：{len(db_trades)}")
    print(f"✅ 淨利：{summary.get('net_profit', 0)}")
    
def test_equity_snapshot(integration_workspace):
    """測試 4: 權益快照"""
    print("\n" + "="*60)
    print("測試 4: 權益快照")
    print("="*60)
    
    db_path = integration_workspace["snapshot_db"]
    
    trader = PaperTrader(
        ticker="TMF",
        initial_balance=100000,
        db_path=str(db_path),
        snapshot_interval=1,  # 1 秒快照 (測試用)
    )
    
    now = datetime.now()
    
    # 建倉
    trader.execute_signal("BUY", 20000, now, lots=2)
    
    # 模擬時間流逝，觸發快照
    for i in range(3):
        future_time = now + timedelta(seconds=i+1)
        trader._maybe_save_snapshot(future_time, 20000 + i*10)
        time.sleep(0.1)
    
    # 驗證快照
    equity_curve = trader.db.get_equity_curve()
    assert len(equity_curve) >= 1, f"Expected >= 1 snapshot, got {len(equity_curve)}"
    
    print(f"✅ 權益快照成功")
    print(f"✅ 快照數量：{len(equity_curve)}")
    
def test_csv_export(integration_workspace):
    """測試 5: CSV 匯出"""
    print("\n" + "="*60)
    print("測試 5: CSV 匯出")
    print("="*60)
    
    db_path = integration_workspace["trading_db"]
    db = DatabaseManager(db_path)
    _record_sample_trade(db)
    
    exporter = CSVExporter(str(db_path), str(integration_workspace["export_dir"]))
    
    # 匯出所有交易
    output_path = exporter.export_all_trades()
    assert os.path.exists(output_path), f"CSV file not created: {output_path}"
    
    # 驗證 CSV 內容
    df = pd.read_csv(output_path)
    assert len(df) > 0, f"CSV file is empty: {output_path}"
    
    print(f"✅ CSV 匯出成功")
    print(f"✅ 檔案路徑：{output_path}")
    print(f"✅ 記錄數：{len(df)}")
    
def test_performance_analysis(integration_workspace):
    """測試 6: 績效分析"""
    print("\n" + "="*60)
    print("測試 6: 績效分析")
    print("="*60)
    
    db_path = integration_workspace["paper_db"]
    _build_completed_paper_trader(db_path)
    
    analyzer = PerformanceAnalyzer(str(db_path))
    analyzer.load_trades()
    
    stats = analyzer.get_trade_statistics()
    
    print(f"✅ 績效分析成功")
    print(f"✅ 總交易數：{stats.get('total_trades', 0)}")
    print(f"✅ 勝率：{stats.get('win_rate', 0):.1f}%")
    print(f"✅ 盈虧比：{stats.get('profit_factor', 0):.2f}")
    
    # 產生報告
    report_path = str(integration_workspace["report_path"])
    report = analyzer.generate_report(report_path)
    assert Path(report_path).exists(), f"Report not created: {report_path}"
    
    print(f"✅ 報告已儲存：{report_path}")
    
def main():
    """執行所有測試"""
    print("\n" + "="*60)
    print("🧪 SQLite Persistence Integration Tests")
    print("="*60)

    with TemporaryDirectory() as tmp_dir:
        workspace = _create_integration_workspace(Path(tmp_dir))
        tests = [
            ("資料庫初始化", lambda: test_database_initialization(workspace)),
            ("交易記錄", lambda: test_trade_recording(workspace)),
            ("PaperTrader 整合", lambda: test_papertrader_integration(workspace)),
            ("權益快照", lambda: test_equity_snapshot(workspace)),
            ("CSV 匯出", lambda: test_csv_export(workspace)),
            ("績效分析", lambda: test_performance_analysis(workspace)),
        ]

        passed = 0
        failed = 0
        results = []

        for name, test_func in tests:
            try:
                result = test_func()
                results.append((name, "✅ PASS", result))
                passed += 1
            except AssertionError as e:
                results.append((name, f"❌ FAIL: {str(e)}", None))
                failed += 1
                print(f"❌ {name} 失敗：{str(e)}")
            except Exception as e:
                results.append((name, f"❌ ERROR: {str(e)}", None))
                failed += 1
                print(f"❌ {name} 錯誤：{str(e)}")
    
    # 總結
    print("\n" + "="*60)
    print("📊 測試總結")
    print("="*60)
    
    for name, status, _ in results:
        print(f"  {status} - {name}")
    
    print(f"\n通過：{passed}/{len(tests)}")
    print(f"失敗：{failed}/{len(tests)}")
    
    if failed == 0:
        print("\n🎉 所有測試通過！")
        return 0
    else:
        print(f"\n⚠️  {failed} 個測試失敗")
        return 1


if __name__ == "__main__":
    sys.exit(main())
