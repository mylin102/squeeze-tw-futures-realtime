#!/usr/bin/env python3
import sys
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from scripts.backtest.advanced_backtest import execute_engine
from scripts.backtest.historical_backtest import load_and_resample
from squeeze_futures.engine.indicators import calculate_futures_squeeze


def load_config():
    config_path = Path(__file__).parent.parent / "config" / "trade_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    cfg = load_config()
    files = sorted(Path("data/taifex_raw").glob("Daily_*.rpt"))
    all_d, all_d15, all_d1h = [], [], []
    for f in files:
        d5 = load_and_resample(f, "5min", "TMF")
        d15 = load_and_resample(f, "15min", "TMF")
        d1h = load_and_resample(f, "1h", "TMF")
        if d5 is not None:
            all_d.append(d5)
            all_d15.append(d15)
            all_d1h.append(d1h)

    pb = cfg["strategy"]["pullback"]
    p_args = {
        "bb_length": cfg["strategy"]["length"],
        "ema_fast": pb["ema_fast"],
        "ema_slow": pb["ema_slow"],
        "lookback": pb["lookback"],
        "pb_buffer": pb["buffer"],
    }

    p5 = calculate_futures_squeeze(pd.concat(all_d).sort_index(), **p_args)
    p15 = calculate_futures_squeeze(pd.concat(all_d15).sort_index(), **p_args)
    p1h = calculate_futures_squeeze(pd.concat(all_d1h).sort_index(), **p_args)

    equity_curve, trader = execute_engine(
        p5,
        p15,
        p1h,
        cfg,
        use_partial=cfg["strategy"].get("partial_exit", {}).get("enabled", False),
    )

    trades = pd.DataFrame(trader.trades)
    max_equity = pd.Series(equity_curve).cummax()
    drawdown = pd.Series(equity_curve) - max_equity
    mdd = float(drawdown.min()) if len(drawdown) else 0.0
    profit_factor = None
    if not trades.empty:
        gross_profit = float(trades.loc[trades["pnl_cash"] > 0, "pnl_cash"].sum())
        gross_loss = float(-trades.loc[trades["pnl_cash"] < 0, "pnl_cash"].sum())
        if gross_loss:
            profit_factor = gross_profit / gross_loss

    total_cost = float(trades["total_cost"].sum()) if not trades.empty else 0.0
    broker_fee = float(trades["broker_fee"].sum()) if not trades.empty else 0.0
    exchange_fee = float(trades["exchange_fee"].sum()) if not trades.empty else 0.0
    tax_cost = float(trades["tax_cost"].sum()) if not trades.empty else 0.0

    lines = [
        "# Backtest Performance Report",
        "",
        f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"- Data files: {len(files)}",
        f"- 5m bars: {len(p5)}",
        f"- Strategy length: {cfg['strategy']['length']}",
        f"- Entry score: {cfg['strategy']['entry_score']}",
        f"- Regime filter: {cfg['strategy'].get('regime_filter')}",
        f"- Partial exit enabled: {cfg['strategy'].get('partial_exit', {}).get('enabled', False)}",
        f"- Order type: {cfg.get('execution', {}).get('order_type', 'market')}",
        "",
        "## Metrics",
        "",
        f"- Net Profit: {trader.balance - 100000:+,.0f} TWD",
        f"- Ending Balance: {trader.balance:,.0f} TWD",
        f"- Total Trades: {len(trades)}",
        f"- Win Rate: {(trades['pnl_cash'] > 0).mean() * 100:.1f}%" if not trades.empty else "- Win Rate: 0.0%",
        f"- Average Trade: {trades['pnl_cash'].mean():+,.1f} TWD" if not trades.empty else "- Average Trade: +0.0 TWD",
        f"- Max Drawdown: {mdd:,.0f} TWD",
        f"- Profit Factor: {profit_factor:.2f}" if profit_factor is not None else "- Profit Factor: N/A",
        "",
        "## Cost Breakdown",
        "",
        f"- Total Cost: {total_cost:,.0f} TWD",
        f"- Broker Fee: {broker_fee:,.0f} TWD",
        f"- Exchange Fee: {exchange_fee:,.0f} TWD",
        f"- Tax Cost: {tax_cost:,.0f} TWD",
    ]

    if not trades.empty:
        best = trades.loc[trades["pnl_cash"].idxmax()]
        worst = trades.loc[trades["pnl_cash"].idxmin()]
        lines += [
            "",
            "## Best/Worst Trade",
            "",
            f"- Best Trade: {best['pnl_cash']:+,.0f} TWD ({best['direction']} {best['entry_time']} -> {best['exit_time']})",
            f"- Worst Trade: {worst['pnl_cash']:+,.0f} TWD ({worst['direction']} {worst['entry_time']} -> {worst['exit_time']})",
            "",
            "## Trade Log (tail 10)",
            "",
            trades.tail(10).to_markdown(index=False),
        ]

    out_dir = Path("exports/simulations")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"backtest_performance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
