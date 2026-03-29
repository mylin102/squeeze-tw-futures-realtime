from datetime import datetime

from squeeze_futures.engine.simulator import PaperTrader


def test_paper_trader_uses_configured_point_value_for_pnl():
    trader = PaperTrader(ticker="MXFR1", point_value=50, fee_per_side=20)

    trader.execute_signal("BUY", 100, datetime(2026, 3, 27, 9, 0), lots=1, stop_loss=10)
    trader.execute_signal("EXIT", 110, datetime(2026, 3, 27, 9, 5))

    assert trader.balance == 100000 + (10 * 50) - 40
    assert trader.trades[0]["pnl_cash"] == (10 * 50) - 40


def test_paper_trader_includes_tax_and_exchange_fees():
    trader = PaperTrader(ticker="TMF", point_value=10, fee_per_side=20, exchange_fee_per_side=5, tax_rate=0.00002)

    trader.execute_signal("BUY", 30000, datetime(2026, 3, 27, 9, 0), lots=1, stop_loss=10)
    trader.execute_signal("EXIT", 30010, datetime(2026, 3, 27, 9, 5))

    expected_cost = 40 + 10 + ((30000 + 30010) * 10 * 0.00002)
    assert trader.trades[0]["total_cost"] == expected_cost
    assert trader.trades[0]["pnl_cash"] == (10 * 10) - expected_cost
