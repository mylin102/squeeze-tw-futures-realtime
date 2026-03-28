# 🚀 Squeeze Taiwan Index Futures Real-time System

專為台灣指數期貨 (Taiwan Index Futures) 打造的專業級實戰監控與自動模擬交易系統。本系統整合了 **TTM Squeeze** 能量引擎、**MTF 多週期共振** 與 **VWAP 法人成本線**，並具備完善的風險控管機制。

---

## 🌟 核心功能

### 1. 專業交易策略 (Squeeze Logic)
系統採用靈敏度優化後的 Squeeze 指標 (Length: 14)，捕捉盤整後的爆發行情：
- **MTF Alignment**: 同時掃描 1h (20%), 15m (40%), 5m (40%) 週期，計算共振分數。
- **進場過濾**: 結合 **VWAP (成交量加權平均價)**，確保只在具備成本優勢的方向進場。
- **動能加速**: 透過動能柱狀態 (Momentum State) 確認趨勢正處於噴發加速階段。

### 2. 進階風險控管 (Multi-layer Risk Mgmt)
- **硬性停損 (SL)**: 進場自動設定 40 點最後防線。
- **保本移動停損 (Break-even)**: 獲利達 40 點後，自動將停損點移至成本價，鎖定不賠。
- **VWAP 結構停損**: 當價格反向穿透 VWAP 線時立即平倉，減少不必要的震盪磨損。
- **收盤自動清倉**: 支援 Day-trading 模式，每日收盤前自動出清部位。

### 3. 部位與配置中心
- **配置中心**: 位於 `scripts/daily_simulation.py` 頂部，可簡易調整交易口數、最大持倉、雙向操作開關。
- **多口數支援**: 自動計算平均成本與累計損益。
- **即時通知**: 透過美化的 HTML Email 發送成交警報與每日績效報表。

---

## 📈 訊號說明

### 🟢 買入訊號 (BUY / 做多)
滿足以下全數條件：
1. **能量釋放**: 擠壓狀態結束 (`sqz_on` 為 False)。
2. **多頭共振**: MTF 分數 >= 60。
3. **成本優勢**: 價格 > VWAP。
4. **動能加速**: 5m 動能柱為淺藍色 (State 3)。

### 🔴 賣出訊號 (SELL / 做空)
滿足以下全數條件：
1. **能量釋放**: 擠壓狀態結束 (`sqz_on` 為 False)。
2. **空頭共振**: MTF 分數 <= -60。
3. **成本弱勢**: 價格 < VWAP。
4. **跌勢加速**: 5m 動能柱為淺紅色 (State 0)。

---

## 🛠️ 快速安裝與設定

```bash
# 1. 複製專案與同步環境
git clone https://github.com/mylin102/squeeze-tw-futures-realtime.git
cd squeeze-tw-futures-realtime
uv sync
```

### ⏰ 自動化排程 (macOS Cron)
在 `crontab -e` 加入，並確保授予 `cron` 「完全磁碟取用權限」：
```cron
45 8 * * 1-5 /path/to/autostart.sh
0 15 * * 1-5 /path/to/autostart.sh
```

---

## 📊 研究與優化工具
- `scripts/historical_backtest.py`: 下載期交所官方資料並執行長達 60 天的回測。
- `scripts/optimize_strategy.py`: 自動掃描多組參數，尋找最佳損益組合。
- `scripts/compare_stop_loss.py`: 專門比較不同停損模式的績效差異。

---

## ⚠️ 免責聲明
本專案僅供技術研究與模擬交易參考，不構成投資建議。金融交易具備高度風險，請審慎評估。

## ⚖️ 授權
MIT License
