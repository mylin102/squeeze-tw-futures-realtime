# 🚀 Squeeze Taiwan Index Futures Ultimate System

專為微型臺指期貨 `TMF` 打造的專業級自動化交易系統。本系統採用最新的 **Hybrid 進場引擎**、**Opening Regime (開盤強弱判定)** 與 **Partial Exit (分批停利)** 策略，在歷史回測中展現出明確的趨勢追蹤能力。

---

## 🌟 核心戰力：分批停利策略 (Partial Exit)

這是本系統目前最強大的獲利引擎，透過 2 口進場的精細管理，實現「低風險、大波段」：
- **TP1 (落袋為安)**: 當獲利達 **+50 點** 時，自動平倉 **1 口** 鎖定基本利潤。
- **Runner (趨勢追蹤)**: 剩下的 **1 口** 自動移至 **保本停損**，零風險參與大波段。
- **回測驗證**: 此策略相較於單口操作，總獲利提升了約 **3.5 倍**。

---

## 🛡️ 安全與風控
- **智慧環境過濾**: 15m EMA 60 與每日開盤強弱判定雙重疊加，只做勝率最高的趨勢。
- **保證金檢查**: 實戰下單前校驗 **25,000 TWD/口**，資金不足自動發送告警。
- **多重平倉邏輯**: 包含 60 點硬性 SL、保本停損、VWAP 結構停損以及趨勢轉弱平倉。
- **Exit Reason 追蹤**: 每筆平倉自動記錄原因 (`STOP_LOSS` / `TP1` / `VWAP`)，方便事後分析。

---

## ⚙️ 系統設定 (config/trade_config.yaml)

```yaml
strategy:
  length: 20           # 最佳化計算週期
  entry_score: 20      # 進場門檻
  use_squeeze: true
  use_pullback: true
  regime_filter: "mid"

  partial_exit:        # 🚀 分批停利設定
    enabled: true
    tp1_pts: 50        # 獲利 50 點平 1 口
    tp1_lots: 1

trade_mgmt:
  lots_per_trade: 2    # 進場直接 2 口
  max_positions: 2
  force_close_at_end: false # 🌙 允許留倉 (Swing Mode)

risk_mgmt:
  stop_loss_pts: 60    # 初始停損 (2 口同步)
  break_even_pts: 50   # 保本觸發點數
```

---

## 📊 績效回測 (TMF)
- 最新成本化回測請參考 `exports/simulations/backtest_performance_*.md`
- 目前預設商品與模擬標的是 `TMF`

---

## 🛠️ 快速啟動

```bash
# 即時交易/模擬
uv run scripts/daily_simulation.py TMF

# 夜盤交易
uv run scripts/night_trading_v3.py

# Dry Run 健康檢查
WEEKEND_TEST=1 uv run scripts/daily_simulation.py TMF

# 執行測試
uv run pytest tests/

# 查看優化報告
open STRATEGY_REPORT.html
```

---

## ⚠️ 免責聲明
本系統僅供技術研究，不構成投資建議。實戰具備高度風險，請投資人務必確認實戰開關 (`live_trading`)。

## ⚖️ 授權
MIT License
