# 🚀 Squeeze Taiwan Index Futures Hybrid System

專為台灣指數期貨 (TMF/MX) 打造的專業級自動化交易系統。整合了 **Squeeze 爆發**、**雙向趨勢回測 (Pullback)** 與 **動態環境過濾 (Regime Filter)**，在 60 天回測中展現了極佳的獲利延續性。

---

## 🌟 核心進化功能

### 1. 混合進場引擎 (Hybrid Entry)
- **能量爆發 (Squeeze)**: 監控 TTM Squeeze 釋放，捕捉 V 型轉轉或首波噴發。
- **趨勢回測 (Pullback)**: 在強勢多/空頭排列中，尋找價格拉回均線支撐/壓力區的二波上車機會。

### 2. 動態環境感知 (Market Regime)
- **15m EMA 60 過濾**: 系統自動判斷目前處於多頭、空頭或震盪環境。
- **智慧過濾**: 在多頭環境中自動濾除逆勢空單訊號，顯著提升每一筆交易的成功期望值。

### 3. 全面參數化配置 (YAML Config)
所有交易邏輯、部位管理與風險控制皆可透過 `config/trade_config.yaml` 輕鬆調整，無需改動程式碼。

---

## ⚙️ 參數表說明 (config/trade_config.yaml)

```yaml
strategy:
  length: 14           # 指標計算週期
  entry_score: 70      # 進場分數門檻
  use_squeeze: true    # 啟動爆發模式
  use_pullback: true   # 啟動回測模式
  regime_filter: "mid" # 環境過濾 ("mid": 15m EMA 60, "macro": 1h EMA 200, "none")

  pullback:            # 回測策略專用參數
    ema_fast: 20       # 短期支撐線
    ema_slow: 60       # 長期趨勢線
    lookback: 60       # 創高/低判斷根數
    buffer: 1.002      # 支撐區彈性係數

trade_mgmt:
  lots_per_trade: 1    # 交易口數
  max_positions: 3     # 留倉上限
  force_close_at_end: true # 收盤清倉

risk_mgmt:
  stop_loss_pts: 40    # 硬性停損
  break_even_pts: 40   # 獲利保本
  exit_on_vwap: true   # VWAP 結構停損
```

---

## 📊 績效回測報告 (TMF - 60D)
透過 `scripts/advanced_backtest.py` 驗證：
*   **基礎 Squeeze**: +1,820 TWD
*   **雙向 Hybrid (無過濾)**: +10,110 TWD
*   **優化 Hybrid (中線過濾)**: **+12,160 TWD (目前預設)**

---

## 🛠️ 執行與維護
- **即時交易**: `uv run scripts/daily_simulation.py TMF`
- **歷史研究**: `uv run scripts/advanced_backtest.py`
- **資金檢查**: 系統自動實作 **25,000 TWD/口** 的保證金校驗門檻。

---

## ⚠️ 免責聲明
本系統僅供技術研究，不構成投資建議。實戰交易具備高度風險，請投資人務必確認 `live_trading` 設定。

## ⚖️ 授權
MIT License
