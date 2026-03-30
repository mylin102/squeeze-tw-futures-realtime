import os

import pandas as pd

os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/numba_cache")

from squeeze_futures.engine.indicators import calculate_futures_squeeze


def test_calculate_futures_squeeze_adds_vwap_fields_and_resets_daily_vwap():
    first_day = pd.date_range("2026-03-26 08:45", periods=300, freq="1min")
    second_day = pd.date_range("2026-03-27 08:45", periods=300, freq="1min")
    index = first_day.append(second_day)

    close = pd.Series(range(1, len(index) + 1), index=index)
    df = pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 1,
            "Low": close - 2,
            "Close": close,
            "Volume": 1,
        },
        index=index,
    )

    result = calculate_futures_squeeze(df)

    assert "vwap" in result.columns
    assert "price_vs_vwap" in result.columns
    assert result.loc[second_day[0], "vwap"] == result.loc[second_day[0], "Close"]
    assert result["price_vs_vwap"].notna().all()
