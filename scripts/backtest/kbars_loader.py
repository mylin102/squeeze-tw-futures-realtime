"""
Shared kbars loader for backtest scripts.
Merges all TMF_5m_*.csv snapshots (price-filtered to TMF range).
Falls back to TWII if no valid TMF data exists yet.
"""
import os
import pandas as pd
from pathlib import Path

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "taifex_raw")

TMF_MIN, TMF_MAX = 20000, 50000   # valid TMF futures price range


def load_all_kbars(verbose=True) -> pd.DataFrame:
    """
    Merge all TMF_5m_*.csv snapshots, deduplicate, sort.
    Filters rows where Close is outside TMF range (rejects TWII/ETF data).
    Falls back to TWII_5m_60d.csv if no valid TMF data found.
    """
    frames = []
    for f in sorted(Path(RAW_DIR).glob("TMF_5m_*.csv")):
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
            df.columns = [c.capitalize() for c in df.columns]
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            df = df[(df["Close"] > TMF_MIN) & (df["Close"] < TMF_MAX)]
            if not df.empty:
                frames.append(df)
        except Exception:
            pass

    if not frames:
        fallback = os.path.join(RAW_DIR, "TWII_5m_60d.csv")
        df = pd.read_csv(fallback, parse_dates=["Datetime"], index_col="Datetime")
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
        if verbose:
            print("⚠️  No valid TMF snapshots yet — using TWII fallback. Run daily_simulation to accumulate TMF data.")
        return df

    combined = pd.concat(frames)
    combined.index = pd.to_datetime(combined.index, utc=True).tz_localize(None)
    combined = combined[~combined.index.duplicated(keep="last")].sort_index().dropna()
    if verbose:
        print(f"✓ Loaded {len(combined)} TMF bars from {len(frames)} snapshot(s)  "
              f"({combined.index[0].date()} ~ {combined.index[-1].date()})")
    return combined
