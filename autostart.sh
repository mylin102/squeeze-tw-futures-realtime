#!/bin/bash
# 🌙☀️ Squeeze Futures Auto-Start Script
# 自動判斷日盤/夜盤並使用對應配置

# 進入專案目錄
cd /Users/mylin/Documents/mylin102/tw-futures-realtime

# 建立日誌目錄
mkdir -p logs

# 獲取當前時間
HOUR=$(date +%H)
DAY_OF_WEEK=$(date +%u)  # 1=週一，7=週日

# 判斷是否為交易日 (週一至週五)
if [ "$DAY_OF_WEEK" -gt 5 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 非交易日，跳过" >> logs/automation.log
    exit 0
fi

# 判斷時段
# 夜盤：15:00-05:00 (包含跨夜)
# 日盤：08:45-13:45
if [ "$HOUR" -ge 15 ] || [ "$HOUR" -lt 5 ]; then
    # 夜盤時段
    SESSION="night"
    SCRIPT="scripts/night_trading_v3.py"
    CONFIG="config/night_config.yaml"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🌙 夜盤時段 (15:00-05:00)" >> logs/automation.log
elif [ "$HOUR" -ge 8 ] && [ "$HOUR" -lt 14 ]; then
    # 日盤時段
    SESSION="day"
    SCRIPT="scripts/daily_simulation_v2.py"
    CONFIG="config/day_config.yaml"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ☀️ 日盤時段 (08:45-13:45)" >> logs/automation.log
else
    # 非交易時段
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 非交易時段，跳过" >> logs/automation.log
    exit 0
fi

# 執行對應的交易腳本
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 啟動 $SESSION 交易系統..." >> logs/automation.log
/Users/mylin/.local/bin/uv run python $SCRIPT >> logs/automation.log 2>&1
