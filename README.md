# 🚀 Squeeze Taiwan Index Futures Real-time Monitor

專為台灣指數期貨 (Taiwan Index Futures) 設計的實戰即時監控系統。結合了經典的 **TTM Squeeze Momentum** 指標、**MTF 多週期共振** 與 **VWAP 法人平均成本線**，幫助交易者在盤中快速識別高品質的趨勢噴發點。

## 🌟 功能特色

- **零延遲數據**: 支援 **永豐金 Shioaji API**，提供毫秒級的盤中即時報價。
- **自動備案機制**: 若 Shioaji 未登入，系統自動切換至 `yfinance` 延遲報價模式。
- **MTF 多週期共振 (Alignment)**: 同時監控 5m, 15m, 1h 週期，計算綜合趨勢分數 (-100 ~ +100)。
- **VWAP 偏離度分析**: 即時計算價格相對於當日法人平均成本的位置，有效過濾追高風險。
- **專業監控看板**: 基於 `Rich` 打造的終端機即時 UI，支援動能顏色辨識與爆發信號閃爍。
- **高效能處理**: 整合 `shioaji[speed]` 加速數據解析。

## 🛠️ 安裝說明

本專案使用 `uv` 進行快速、可靠的依賴管理。

```bash
# 1. 複製專案
git clone https://github.com/mylin102/squeeze-tw-futures-realtime.git
cd squeeze-tw-futures-realtime

# 2. 安裝依賴與建立環境
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

## 🔐 配置認證 (.env)

建立 `.env` 檔案並填入您的 API 資訊：

```bash
# Sinopac Shioaji API
SHIOAJI_API_KEY=您的身份證字號
SHIOAJI_SECRET_KEY=您的API密鑰
SHIOAJI_CERT_PATH=/path/to/your/cert.pfx
SHIOAJI_CERT_PASSWORD=您的憑證密碼
```

## 📈 使用教學

### 1. 測試 API 連線
在正式看盤前，先檢查帳號權限與連線是否正常：
```bash
uv run scripts/test_api.py
```

### 2. 啟動即時監控
預設監控台股大盤 (`^TWII`)：
```bash
uv run scripts/realtime_monitor.py
```

監控特定標的（如 0050 或 NQ 期貨）：
```bash
uv run scripts/realtime_monitor.py 0050.TW
uv run scripts/realtime_monitor.py NQ=F
```

## 🕯️ 交易策略參考

| 信號 / 指標 | 解讀與動作 |
| :--- | :--- |
| **Sqz ON (紅色)** | 正在橫盤整理，蓄勢待發。 |
| **★ FIRED (閃爍)** | Squeeze 剛解除，噴發進場點！ |
| **Alignment > 60** | 全週期多頭共振，勝率極高。 |
| **VWAP % > 0** | 價格在法人成本之上，屬於強勢區。 |

## 📁 專案結構

- `src/squeeze_futures/engine/`: 指標計算核心 (Squeeze, MTF, VWAP)。
- `src/squeeze_futures/data/`: 數據抓取模組 (Shioaji, yfinance)。
- `scripts/`: 即時監控與測試工具。

## ⚠️ 免責聲明
本專案僅供技術研究與參考，不構成任何投資建議。金融交易具備高度風險，請投資人審慎評估。

## ⚖️ 授權
MIT License
