# 🚀 Squeeze Taiwan Index Futures Real-time System

專為台灣指數期貨 (Taiwan Index Futures) 打造的專業級實戰監控與模擬交易系統。本系統整合了經典的 **TTM Squeeze Momentum** 策略，並透過 **MTF 多週期共振** 與 **VWAP 法人成本線** 進行多重過濾，旨在捕捉高品質的盤中噴發行情。

---

## 🌟 核心功能

### 1. 零延遲數據驅動
- **Shioaji API 整合**: 直接串接永豐金證券，提供毫秒級的盤中即時報價。
- **雙模式自動切換**: 若 API 未登入，自動切換至 `yfinance` 備案模式，確保監控不中斷。

### 2. 專業策略引擎
- **MTF Alignment**: 同時掃描 5m (極短線)、15m (當沖)、1h (趨勢) 週期，計算 -100 到 +100 的共振分數。
- **VWAP 偏離過濾**: 即時分析價格與法人平均成本的關係，避免過熱追價。
- **雙向反手交易**: 支援做多與做空，且能在趨勢轉向時自動執行「平倉並反手」。

### 3. 全自動化通知與報告
- **即時成交警報**: 每一筆成交（買入、賣出、平倉、反手）都會立即發送 **顏色標註的 HTML Email** 到您的手機。
- **每日績效總結**: 收盤後自動產出精美的 **HTML 格式績效報告**，包含損益統計與詳細交易日誌。
- **全自動執行**: 支援 Mac `cron` 排程，實現「日盤+夜盤」全天候無人值守運行。

---

## 🛠️ 快速安裝

本專案使用 `uv` 進行環境管理，安裝極速且穩定。

```bash
# 1. 複製專案
git clone https://github.com/mylin102/squeeze-tw-futures-realtime.git
cd squeeze-tw-futures-realtime

# 2. 安裝 uv (若尚未安裝)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 建立虛擬環境與安裝依賴
uv sync
```

---

## 🔐 認證配置 (.env)

請在專案根目錄建立 `.env` 檔案並填入資訊：

```bash
# 永豐金 Shioaji 帳號資訊
SHIOAJI_API_KEY=您的身份證字號
SHIOAJI_SECRET_KEY=您的密鑰
SHIOAJI_CERT_PATH=/路徑/您的憑證.pfx
SHIOAJI_CERT_PASSWORD=憑證密碼

# Email 通知設定讀取自 ~/.config/squeeze-backtest-email.env
```

---

## 📈 實戰指令

### 啟動即時監控看板
```bash
uv run scripts/realtime_monitor.py MXFR1
```

### 啟動自動模擬交易 (含 Email 通知)
```bash
uv run scripts/daily_simulation.py MXFR1
```

---

## 📁 文件索引
- [📋 詳細操作手冊 (OPERATIONS.md)](OPERATIONS.md): 包含 API 測試、策略邏輯說明與全自動化排程設定。

## ⚠️ 免責聲明
本專案僅供技術研究與模擬交易參考，不構成任何投資建議。金融交易具備高度風險，請投資人審慎評估。

## ⚖️ 授權
MIT License
