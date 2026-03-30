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

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.database.db_manager import DatabaseManager
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.export.csv_exporter import CSVExporter
from squeeze_futures.analysis.performance import PerformanceAnalyzer


def test_database_initialization():
    """測試 1: 資料庫初始化"""
    print("\n" + "="*60)
    print("測試 1: 資料庫初始化")
    print("="*60)
    
    db_path = "data/test_trading.db"
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
    
    return db


def test_trade_recording():
    """測試 2: 交易記錄"""
    print("\n" + "="*60)
    print("測試 2: 交易記錄")
    print("="*60)
    
    db_path = "data/test_trading.db"
    db = DatabaseManager(db_path)
    
    # 記錄一筆完整交易
    entry_time = datetime.now()
    exit_time = entry_time + timedelta(minutes=10)
    
    # ENTRY 記錄
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
    
    # EXIT 記錄
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
    
    # 驗證記錄
    trades = db.get_trade_history()
    assert len(trades) == 2, f"Expected 2 trades, got {len(trades)}"
    
    summary = db.get_performance_summary()
    assert summary['total_trades'] == 1, f"Expected 1 completed trade, got {summary['total_trades']}"
    assert summary['net_profit'] == 1904, f"Expected net profit 1904, got {summary['net_profit']}"
    
    print(f"✅ 交易記錄成功")
    print(f"✅ 總交易數：{len(trades)}")
    print(f"✅ 淨利：{summary['net_profit']}")
    
    return db


def test_papertrader_integration():
    """測試 3: PaperTrader 整合"""
    print("\n" + "="*60)
    print("測試 3: PaperTrader 整合")
    print("="*60)
    
    db_path = "data/test_papertrader.db"
    
    # 建立 PaperTrader (帶 SQLite)
    trader = PaperTrader(
        ticker="TMF",
        initial_balance=100000,
        db_path=db_path,
        snapshot_interval=60,  # 1 分鐘快照
    )
    
    now = datetime.now()
    
    # 執行交易
    print("執行交易：BUY 2 @ 20000")
    trader.execute_signal("BUY", 20000, now, lots=2)
    
    print("執行交易：EXIT 2 @ 20100")
    trader.execute_signal("EXIT", 20100, now + timedelta(minutes=10), lots=2)
    
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
    
    return trader


def test_equity_snapshot():
    """測試 4: 權益快照"""
    print("\n" + "="*60)
    print("測試 4: 權益快照")
    print("="*60)
    
    db_path = "data/test_snapshot.db"
    
    trader = PaperTrader(
        ticker="TMF",
        initial_balance=100000,
        db_path=db_path,
        snapshot_interval=1,  # 1 秒快照 (測試用)
    )
    
    now = datetime.now()
    
    # 建倉
    trader.execute_signal("BUY", 20000, now, lots=2)
    
    # 模擬時間流逝，觸發快照
    import time
    for i in range(3):
        future_time = now + timedelta(seconds=i+1)
        trader._maybe_save_snapshot(future_time, 20000 + i*10)
        time.sleep(0.1)
    
    # 驗證快照
    equity_curve = trader.db.get_equity_curve()
    assert len(equity_curve) >= 1, f"Expected >= 1 snapshot, got {len(equity_curve)}"
    
    print(f"✅ 權益快照成功")
    print(f"✅ 快照數量：{len(equity_curve)}")
    
    return trader


def test_csv_export():
    """測試 5: CSV 匯出"""
    print("\n" + "="*60)
    print("測試 5: CSV 匯出")
    print("="*60)
    
    db_path = "data/test_trading.db"
    
    exporter = CSVExporter(db_path, "exports/test_trades")
    
    # 匯出所有交易
    output_path = exporter.export_all_trades()
    assert os.path.exists(output_path), f"CSV file not created: {output_path}"
    
    # 驗證 CSV 內容
    import pandas as pd
    df = pd.read_csv(output_path)
    assert len(df) > 0, f"CSV file is empty: {output_path}"
    
    print(f"✅ CSV 匯出成功")
    print(f"✅ 檔案路徑：{output_path}")
    print(f"✅ 記錄數：{len(df)}")
    
    return output_path


def test_performance_analysis():
    """測試 6: 績效分析"""
    print("\n" + "="*60)
    print("測試 6: 績效分析")
    print("="*60)
    
    db_path = "data/test_papertrader.db"
    
    analyzer = PerformanceAnalyzer(db_path)
    analyzer.load_trades()
    
    stats = analyzer.get_trade_statistics()
    
    print(f"✅ 績效分析成功")
    print(f"✅ 總交易數：{stats.get('total_trades', 0)}")
    print(f"✅ 勝率：{stats.get('win_rate', 0):.1f}%")
    print(f"✅ 盈虧比：{stats.get('profit_factor', 0):.2f}")
    
    # 產生報告
    report_path = "exports/test_performance_report.md"
    report = analyzer.generate_report(report_path)
    
    print(f"✅ 報告已儲存：{report_path}")
    
    return report


def main():
    """執行所有測試"""
    print("\n" + "="*60)
    print("🧪 SQLite Persistence Integration Tests")
    print("="*60)
    
    tests = [
        ("資料庫初始化", test_database_initialization),
        ("交易記錄", test_trade_recording),
        ("PaperTrader 整合", test_papertrader_integration),
        ("權益快照", test_equity_snapshot),
        ("CSV 匯出", test_csv_export),
        ("績效分析", test_performance_analysis),
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
