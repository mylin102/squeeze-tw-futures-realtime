#!/usr/bin/env python3
"""
Convert TAIFEX Daily_*.rpt tick files → OHLCV K-bar CSV.

Usage:
    uv run python scripts/data/rpt_to_kbars.py [--tf 5m] [--contract TMF] [--out data/taifex_raw]

Columns in .rpt: date, product, delivery_month, time(HHMMSS), price, volume, -, -
"""
import os, sys, argparse
from pathlib import Path
import pandas as pd
from rich.console import Console

console = Console()

RPT_DIR = Path("/Users/mylin/Documents/mylin102/squeeze-tw-futures-realtime/data/taifex_raw")
OUT_DIR = Path(os.path.join(os.path.dirname(__file__), "..", "..", "data", "taifex_raw"))

RESAMPLE_MAP = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h"}

COLS = ["date", "product", "delivery_month", "time", "price", "volume", "x1", "x2"]


def parse_rpt(path: Path, contract: str) -> pd.DataFrame:
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_csv(
            path, header=None, names=COLS, skiprows=1, index_col=False,
            encoding="cp950", skipinitialspace=True,
            on_bad_lines="skip", low_memory=False,
        )
    df = df[df["product"].str.strip() == contract].copy()
    if df.empty:
        return df

    # 只取近月（delivery_month 最小）
    df["delivery_month"] = df["delivery_month"].astype(str).str.strip()
    nearest = df["delivery_month"].min()
    df = df[df["delivery_month"] == nearest]

    # 解析時間
    df["date"] = df["date"].astype(str).str.strip()
    df["time"] = df["time"].astype(str).str.strip().str.zfill(6)
    df["ts"] = pd.to_datetime(df["date"] + df["time"], format="%Y%m%d%H%M%S", errors="coerce")
    df = df.dropna(subset=["ts"])
    df["price"]  = pd.to_numeric(df["price"],  errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.dropna(subset=["price", "volume"])
    df = df.set_index("ts").sort_index()
    return df[["price", "volume"]]


def ticks_to_ohlcv(ticks: pd.DataFrame, rule: str) -> pd.DataFrame:
    ohlcv = ticks["price"].resample(rule).ohlc()
    ohlcv["Volume"] = ticks["volume"].resample(rule).sum()
    ohlcv.columns = ["Open", "High", "Low", "Close", "Volume"]
    return ohlcv.dropna(subset=["Open"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tf",       default="5m",  help="Timeframe: 1m/5m/15m/1h")
    parser.add_argument("--contract", default="TMF", help="Product code e.g. TMF, TXF")
    parser.add_argument("--out",      default=str(OUT_DIR))
    args = parser.parse_args()

    rule = RESAMPLE_MAP.get(args.tf, args.tf)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rpt_files = sorted(RPT_DIR.glob("Daily_*.rpt"))
    console.print(f"[bold cyan]Converting {len(rpt_files)} .rpt files → {args.contract} {args.tf} OHLCV[/bold cyan]")

    all_frames = []
    for f in rpt_files:
        console.print(f"[dim]  {f.name}...[/dim]", end="")
        ticks = parse_rpt(f, args.contract)
        if ticks.empty:
            console.print(" [yellow]no data[/yellow]")
            continue
        bars = ticks_to_ohlcv(ticks, rule)
        all_frames.append(bars)
        console.print(f" [green]{len(bars)} bars[/green]")

    if not all_frames:
        console.print("[red]No data found.[/red]")
        sys.exit(1)

    combined = pd.concat(all_frames)
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()

    out_path = out_dir / f"{args.contract}_{args.tf}_taifex.csv"
    combined.to_csv(out_path)

    console.print(f"\n[green]✓ {len(combined)} bars saved → {out_path}[/green]")
    console.print(f"  Period : {combined.index[0]} ~ {combined.index[-1]}")
    console.print(f"  Close  : {combined['Close'].min():.0f} ~ {combined['Close'].max():.0f}")


if __name__ == "__main__":
    main()
