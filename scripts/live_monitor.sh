#!/bin/bash
# 即時監控腳本 - 每 10 秒更新一次

LOG_FILE="/Users/mylin/Documents/mylin102/tw-futures-realtime/logs/automation.log"
DATA_FILE="/Users/mylin/Documents/mylin102/tw-futures-realtime/logs/market_data/TMF_20260331_indicators.csv"

echo "╔════════════════════════════════════════════════════════╗"
echo "║       Squeeze Futures 即時監控 (每 10 秒更新)            ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

while true; do
    clear
    echo "═══════════════════════════════════════════════════════"
    echo "  更新時間：$(date '+%Y-%m-%d %H:%M:%S')"
    echo "═══════════════════════════════════════════════════════"
    echo ""
    
    echo "【最新 K 棒數據】"
    if [ -f "$DATA_FILE" ]; then
        tail -1 "$DATA_FILE" | awk -F',' '{
            printf "  時間：%s\n", $1
            printf "  價格：%s\n", $2
            printf "  Score: %s\n", $4
            printf "  MomState: %s\n", $6
            printf "  Squeeze: %s\n", $5
        }'
    else
        echo "  暫無數據"
    fi
    echo ""
    
    echo "【今日交易記錄】"
    TODAY=$(date '+%Y-%m-%d')
    if [ -f "$LOG_FILE" ]; then
        TRADES=$(grep "$TODAY" "$LOG_FILE" | grep -E "(BUY|SELL|EXIT)" | wc -l | tr -d ' ')
        if [ "$TRADES" -gt 0 ]; then
            grep "$TODAY" "$LOG_FILE" | grep -E "(BUY|SELL|EXIT)" | tail -5
        else
            echo "  暫無交易"
        fi
    else
        echo "  暫無日誌"
    fi
    echo ""
    
    echo "【趨勢突破信號】"
    if [ -f "$LOG_FILE" ]; then
        TREND_SIGNALS=$(grep -i "trend breakout" "$LOG_FILE" | tail -3)
        if [ -n "$TREND_SIGNALS" ]; then
            echo "$TREND_SIGNALS"
        else
            echo "  暫無趨勢突破信號"
        fi
    fi
    echo ""
    
    echo "【系統狀態】"
    TRADING_PROC=$(pgrep -f "daily_simulation" | wc -l | tr -d ' ')
    DASH_PROC=$(pgrep -f "streamlit.*dashboard" | wc -l | tr -d ' ')
    
    if [ "$TRADING_PROC" -gt 0 ]; then
        echo "  ✓ 交易系統運行中 (PID: $(pgrep -f daily_simulation | head -1))"
    else
        echo "  ✗ 交易系統未運行"
    fi
    
    if [ "$DASH_PROC" -gt 0 ]; then
        echo "  ✓ 儀表板運行中 (http://localhost:8501)"
    else
        echo "  ✗ 儀表板未運行"
    fi
    echo ""
    
    echo "═══════════════════════════════════════════════════════"
    echo "  下次更新：10 秒後 (Ctrl+C 停止)"
    echo "═══════════════════════════════════════════════════════"
    
    sleep 10
done
