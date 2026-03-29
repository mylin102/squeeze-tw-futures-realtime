from squeeze_futures.engine.execution import ExecutionModel, simulate_order_fill


def test_market_order_applies_slippage():
    bar = {"High": 101, "Low": 99, "Close": 100}
    model = ExecutionModel(order_type="market", market_slippage_pts=1, tick_size=1)
    assert simulate_order_fill("BUY", 100, bar, model) == 101
    assert simulate_order_fill("SELL", 100, bar, model) == 99


def test_limit_order_requires_price_touch():
    bar = {"High": 103, "Low": 99, "Close": 101}
    model = ExecutionModel(order_type="limit", limit_offset_pts=2, tick_size=1)
    assert simulate_order_fill("BUY", 101, bar, model) == 99
    assert simulate_order_fill("SELL", 101, bar, model) == 103


def test_range_market_can_reject_out_of_range_fill():
    bar = {"High": 101, "Low": 99, "Close": 100}
    model = ExecutionModel(order_type="range_market", market_slippage_pts=3, range_protection_pts=2, tick_size=1)
    assert simulate_order_fill("BUY", 100, bar, model) is None
