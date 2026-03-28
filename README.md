# 🚀 Squeeze Taiwan Index Futures Ultimate System

專為台灣指數期貨 (TMF/MX) 打造的專業級自動化交易系統。本系統採用最新的 **Hybrid 進場引擎** 與 **Opening Regime (開盤強弱判定)** 邏輯，經 81 組參數交叉掃描優化，在 60 天回測中展現了極高的獲利穩定性。

---

## 🌟 核心戰力

### 1. 智慧環境感知 (Regime Filtering)
- **15m EMA 60 中線過濾**: 動態判斷波段方向，減少逆勢損耗。
- **Opening Regime**: 自動偵測每日開盤走勢。強勢日鎖定多單，弱勢日鎖定空單，具備「盤感」的智慧過濾。

### 2. 混合進場引擎 (Hybrid Entry)
- **Squeeze 爆發**: 捕捉能量釋放後的首波行情。
- **Trend Pullback**: 在確立趨勢中尋找二波回測支撐/壓力的進場點。

### 3. 科學優化參數
- **Length 20 / Score 70 / SL 30**: 經大數據測試出的獲利黃金組合。
- **Swing Mode**: 預設允許留倉（隔日沖），以捕捉最大幅度的跨日噴發行情。

---

## ⚙️ 終極版設定 (config/trade_config.yaml)

```yaml
strategy:
  length: 20           # 最佳化計算週期
  entry_score: 70      # 嚴格進場門檻
  use_squeeze: true    # 啟動爆發模式
  use_pullback: true   # 啟動趨勢回測
  regime_filter: "mid" # 使用 15m 中線過濾

trade_mgmt:
  lots_per_trade: 1
  max_positions: 3
  force_close_at_end: false # 🚀 允許留倉 (Swing Mode)

risk_mgmt:
  stop_loss_pts: 30    # 最佳化停損點數
  break_even_pts: 30   # 1:1 保本觸發
  exit_on_vwap: true   # VWAP 結構停損 (強勢日自動寬限)
```

---

## 📊 研究工具箱
- `scripts/advanced_backtest.py`: 執行三方策略 PK 並產出資產對比圖。
- `scripts/run_plan_backtest.py`: 產出專業 **HTML 績效分析報告**。
- `STRATEGY_REPORT.html`: 包含 81 種參數組合的詳細掃描報告。

---

## 🛠️ 執行
- **啟動交易**: `uv run scripts/daily_simulation.py TMF`
- **資金檢查**: 下單前自動校驗 **25,000 TWD/口**。

---

## ⚠️ 免責聲明
本系統僅供技術研究，不構成投資建議。實戰具備高度風險，請投資人務必確認實戰開關 (`live_trading`)。

## ⚖️ 授權
MIT License
