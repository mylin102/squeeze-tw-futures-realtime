"""
Shared kbars loader for backtest scripts.
Priority: TMF_5m_taifex.csv (from .rpt) > TMF_5m_<timestamp>.csv snapshots > TWII fallback.
"""
import os
import pandas as pd
from pathlib import Path

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "taifex_raw")
TMF_MIN, TMF_MAX = 30000, 50000  # TMF futures realistic range (TWII ~28000 excluded)


def load_all_kbars(verbose=True) -> pd.DataFrame:
    frames = []

    # 1. Best source: converted from TAIFEX .rpt files
    taifex_file = Path(RAW_DIR) / "TMF_5m_taifex.csv"
    if taifex_file.exists():
        try:
            df = pd.read_csv(taifex_file, index_col=0, parse_dates=True)
            df.columns = [c.capitalize() for c in df.columns]
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            df = df[(df["Close"] > TMF_MIN) & (df["Close"] < TMF_MAX)]
            if not df.empty:
                frames.append(df)
                if verbose:
                    print(f"✓ taifex.csv: {len(df)} bars  ({df.index[0].date()} ~ {df.index[-1].date()})")
        except Exception as e:
            if verbose:
                print(f"⚠ taifex.csv error: {e}")

    # 2. Daily snapshots from daily_simulation (TMF price range only)
    for f in sorted(Path(RAW_DIR).glob("TMF_5m_2*.csv")):
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
            print("⚠️  No valid TMF data — using TWII fallback.")
        return df

    combined = pd.concat(frames)
    combined.index = pd.to_datetime(combined.index, utc=True).tz_localize(None)
    combined = combined[~combined.index.duplicated(keep="last")].sort_index().dropna()
    if verbose:
        print(f"✓ Total: {len(combined)} TMF bars  ({combined.index[0].date()} ~ {combined.index[-1].date()})")
    return combined
