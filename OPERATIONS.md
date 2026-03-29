# 📋 Squeeze 期貨實戰操作手冊

本手冊提供從零開始配置、執行與維護 `squeeze-tw-futures-realtime` 系統的完整指南。

---

## 1. 環境準備與安全性

### A. API 權限
- 本系統使用 **永豐金 Shioaji API**。請確保您已完成「API 電子交易風險預告書」簽署。
- 建議在 `.env` 中設定 `SHIOAJI_SIMULATION=True` 進行初步測試。

### B. Email 配置
系統會讀取 `~/.config/squeeze-backtest-email.env` 發送通知。
格式如下：
```bash
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=您的發信帳號
SMTP_PASSWORD=您的Google應用程式密碼
SMTP_RECIPIENT=您的收信帳號
```

---

## 2. 實戰監控與交易腳本

### A. 即時看板 (`realtime_monitor.py`)
用於盤中視覺化監控指標：
- **Sqz**: `ON` 表示目前處於擠壓盤整期。
- **Mom Color**: 反映動能強弱（鮮綠 > 深綠 > 淺紅 > 深紅）。
- **vs VWAP %**: 判斷目前價格是否過度偏離法人成本。

### B. 模擬交易 (`daily_simulation.py`)
這是自動化核心，負責執行以下邏輯：
1.  **進場**: 5m `Fired` 信號 + `MTF Score > 70` + 符合 VWAP 趨勢。
2.  **反手**: 持有部位時若偵測到強勢反向噴發信號，會「秒平並反手」。
3.  **出場**: 動能柱顏色轉淡或共振分數掉下 20。

---

## 3. 自動化成交通知

系統配置了 **雙重 Email 通知機制**：

1.  **即時警報 (Trade Alerts)**:
    - 成交當下立即發信。
    - **綠色主題**: 做多進場。
    - **紅色主題**: 做空進場。
    - **藍色主題**: 平倉結算。
2.  **每日報告 (Daily Report)**:
    - 收盤時發送 HTML 格式總結報告。
    - 包含 PnL 計算、勝率統計與完整的交易 Log。

---

## 4. Mac 全自動排程設定 (Cron Job)

為了實現無人值守交易，請按照以下步驟設定 Mac 的 Crontab：

1.  開啟終端機輸入 `crontab -e`。
2.  加入以下兩行（請根據您的實際路徑修改）：

```bash
# 每日日盤自動啟動 (08:45)
45 8 * * 1-5 /Users/mylin/Documents/mylin102/tw-futures-realtime/autostart.sh

# 每日夜盤自動啟動 (15:00)
0 15 * * 1-5 /Users/mylin/Documents/mylin102/tw-futures-realtime/autostart.sh
```

**提示**：`autostart.sh` 會將執行日誌記錄在 `logs/automation.log`，方便出問題時追蹤。

---

## 5. 策略維護建議

- **定期檢查 Log**: 若發現 Shioaji 登入頻繁失敗，請檢查憑證是否過期。
- **微調參數**: 如果覺得進場次數太少，可將 `MTF Score` 門檻從 70 降至 60。
- **成本更新**: 若要調整微台指 `TMF` 的手續費、期交稅或成交模型，請優先更新 `config/trade_config.yaml` 的 `execution` 區塊。

---

**Happy Trading!** 🚀
