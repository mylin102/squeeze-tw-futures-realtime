import pandas as pd

from squeeze_futures.data.shioaji_client import ShioajiClient


class DummyAPI:
    def kbars(self, contract, start):
        idx = pd.date_range("2026-03-27 08:45", periods=6, freq="1min")
        return {
            "ts": idx,
            "Open": [100, 101, 102, 103, 104, 105],
            "High": [101, 102, 103, 104, 105, 106],
            "Low": [99, 100, 101, 102, 103, 104],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5],
            "Volume": [1, 2, 3, 4, 5, 6],
        }


def test_get_kline_resamples_requested_interval():
    client = ShioajiClient()
    client.api = DummyAPI()
    client.is_logged_in = True
    client.get_futures_contract = lambda ticker: object()

    result = client.get_kline("TMF", interval="5m")

    assert len(result) == 2
    first = result.iloc[0]
    second = result.iloc[1]

    assert first["Open"] == 100
    assert first["High"] == 105
    assert first["Low"] == 99
    assert first["Close"] == 104.5
    assert first["Volume"] == 15
    assert second["Open"] == 105
    assert second["High"] == 106
    assert second["Low"] == 104
    assert second["Close"] == 105.5
    assert second["Volume"] == 6
