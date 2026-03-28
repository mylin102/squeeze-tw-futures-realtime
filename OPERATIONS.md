# 📋 Squeeze 期貨實戰操作手冊

本文件導引您如何使用 `squeeze-tw-futures-realtime` 系統進行台灣微台指期 (MXF) 的即時監控與模擬交易。

---

## 1. 認證檢查 (Pre-flight Check)

在開始任何交易前，請確保您的 `.env` 檔案已正確填寫 API 資訊，並執行測試腳本驗證權限。

```bash
# 執行 API 測試腳本
uv run scripts/test_api.py
```
*   **預期結果**：看到 `✓ Login Successful!` 以及您的證券/期貨帳號列表。

---

## 2. 即時看盤監控 (Real-time Monitor)

如果您只想觀察市場指標而不進行模擬交易，請啟動監控看板。

```bash
# 監控台股大盤 (^TWII)
uv run scripts/realtime_monitor.py

# 監控微台指近月全 (MXFR1)
uv run scripts/realtime_monitor.py MXFR1
```

### 看板核心指標說明：
*   **Sqz ON**: 紅色表示市場正在擠壓、蓄勢。
*   **★ FIRED**: 閃爍表示擠壓解除，噴發開始！
*   **vs VWAP %**: 價格相對於法人成本的偏離度（正值為強勢，負值為弱勢）。
*   **MTF Score**: 綜合 5m/15m/1h 的共振分數 (-100 ~ +100)。

---

## 3. 模擬交易實戰 (Daily Simulation)

本腳本會在盤中自動執行策略邏輯，模擬「微台指 (MXF)」的進出場，並在結束後產出績效報告。

```bash
# 啟動微台指模擬交易
uv run scripts/daily_simulation.py MXFR1
```

### 策略進場邏輯 (The Triple Filter)：
1.  **Squeeze 噴發**: 5 分鐘線出現 `Fired` 信號。
2.  **多週期共振**: `MTF Score` 絕對值 > 70（大趨勢與小趨勢方向一致）。
3.  **法人成本過濾**: 價格必須站穩在 VWAP 之上（做多）或之下（做空）。

### 策略出場邏輯：
*   **動能轉弱**: 5 分鐘動能柱顏色轉淡（鮮綠轉深綠，或深紅轉淺紅）。
*   **趨勢反轉**: `MTF Score` 掉回 20 點以下。

---

## 4. 產出與分析報告

當您按下 `Ctrl + C` 結束模擬腳本時，系統會自動生成 Markdown 格式的績效報告。

*   **報告路徑**：`exports/simulations/report_YYYYMMDD_HHMMSS.md`
*   **報告內容**：包含總損益 (PnL)、勝率、最大點數獲利、以及詳細的每筆交易紀錄 (Trade Logs)。

---

## 5. 常見問題與調整

### Q: 週末想測試腳本怎麼辦？
模擬腳本在非開盤時間會自動切換為 `yfinance` 模式，載入最近期的歷史數據進行模擬。

### Q: 如何修改模擬本金或手續費？
請至 `src/squeeze_futures/engine/simulator.py` 修改 `initial_balance` 與 `fee_per_side` 參數。

### Q: 如何調整共振權重？
請至 `src/squeeze_futures/engine/indicators.py` 的 `calculate_mtf_alignment` 函數中修改 `weights` 字典。

---

**⚠️ 警告**：模擬交易不代表實際獲利保證。請在投入真實資金前，確保已在模擬環境中累積足夠的樣本數據。
