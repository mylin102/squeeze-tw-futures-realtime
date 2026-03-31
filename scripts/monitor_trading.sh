#!/bin/bash
# 📊 實時交易監控腳本
# 使用時間：08:45-13:45 (日盤), 15:00-05:00 (夜盤)

LOG_FILE="/Users/mylin/Documents/mylin102/tw-futures-realtime/logs/automation.log"
MARKET_DIR="/Users/mylin/Documents/mylin102/tw-futures-realtime/logs/market_data"

# 顏色定義
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "╔════════════════════════════════════════════════════════╗"
echo "║          實時交易監控系統                              ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# 1. 檢查進程狀態
echo -e "${BLUE}【1】進程狀態檢查${NC}"
if pgrep -f "daily_simulation" > /dev/null; then
    echo -e "${GREEN}✓ 日盤交易運行中${NC}"
    echo "  PID: $(pgrep -f 'daily_simulation')"
elif pgrep -f "night_trading" > /dev/null; then
    echo -e "${YELLOW}⚠  夜盤交易運行中${NC}"
    echo "  PID: $(pgrep -f 'night_trading')"
else
    echo -e "${RED}✗ 無交易進程${NC}"
    echo "  啟動：bash autostart.sh"
fi
echo ""

# 2. 查看最新交易日誌
echo -e "${BLUE}【2】最新交易記錄${NC}"
if [ -f "$LOG_FILE" ]; then
    # 顯示最近 10 筆交易相關日誌
    tail -50 "$LOG_FILE" | grep -E "(Bar logged|BUY|SELL|EXIT|PnL|Started)" | tail -20
    
    # 統計今日交易
    TODAY=$(date +%Y-%m-%d)
    TRADE_COUNT=$(grep "$TODAY" "$LOG_FILE" | grep -c "EXIT" 2>/dev/null || echo "0")
    echo ""
    echo "  今日交易次數：$TRADE_COUNT"
else
    echo -e "${RED}  日誌檔案不存在${NC}"
fi
echo ""

# 3. 查看市場數據
echo -e "${BLUE}【3】市場數據${NC}"
LATEST_MARKET=$(ls -t "$MARKET_DIR"/TMF_*.csv 2>/dev/null | head -1)
if [ -n "$LATEST_MARKET" ]; then
    echo "  最新檔案：$(basename $LATEST_MARKET)"
    echo "  最後更新：$(stat -f %Sm "$LATEST_MARKET" 2>/dev/null || stat -c %y "$LATEST_MARKET" | cut -d'.' -f1)"
    
    # 顯示最新 5 筆數據
    echo ""
    echo "  最新 K 棒:"
    tail -5 "$LATEST_MARKET" | awk -F',' '{printf "    %s | Close: %s | Score: %s\n", $1, $2, $4}'
else
    echo -e "${RED}  無市場數據${NC}"
fi
echo ""

# 4. 持倉狀態
echo -e "${BLUE}【4】持倉狀態${NC}"
if [ -f "$LOG_FILE" ]; then
    # 查找最新進場和平倉記錄
    LAST_BUY=$(grep "BUY" "$LOG_FILE" | tail -1)
    LAST_EXIT=$(grep "EXIT" "$LOG_FILE" | tail -1)
    
    if [ -n "$LAST_BUY" ] && [ -n "$LAST_EXIT" ]; then
        BUY_TIME=$(echo "$LAST_BUY" | grep -oP '\[\K[^\]]+')
        EXIT_TIME=$(echo "$LAST_EXIT" | grep -oP '\[\K[^\]]+')
        
        if [[ "$EXIT_TIME" > "$BUY_TIME" ]]; then
            echo -e "${GREEN}  目前無持倉${NC}"
        else
            echo -e "${YELLOW}  持有部位${NC}"
            echo "  進場時間：$BUY_TIME"
            echo "$LAST_BUY" | grep -oP 'at \K[\d.]+' | head -1 | xargs -I {} echo "  進場價格：{}"
        fi
    elif [ -n "$LAST_BUY" ]; then
        echo -e "${YELLOW}  持有部位${NC}"
        echo "$LAST_BUY" | grep -oP '\[\K[^\]]+' | head -1 | xargs -I {} echo "  進場時間：{}"
        echo "$LAST_BUY" | grep -oP 'at \K[\d.]+' | head -1 | xargs -I {} echo "  進場價格：{}"
    else
        echo -e "${GREEN}  目前無持倉${NC}"
    fi
fi
echo ""

# 5. 績效統計
echo -e "${BLUE}【5】績效統計${NC}"
if [ -f "$LOG_FILE" ]; then
    TODAY=$(date +%Y-%m-%d)
    
    # 計算今日 PnL
    TOTAL_PNL=$(grep "$TODAY" "$LOG_FILE" | grep "PnL:" | grep -oP 'PnL: \K[\d,-]+' | \
                awk '{sum += $1} END {printf "%.0f", sum}')
    
    # 統計進場次數
    ENTRY_COUNT=$(grep "$TODAY" "$LOG_FILE" | grep -c "BUY\|SELL" 2>/dev/null || echo "0")
    
    # 統計出場次數
    EXIT_COUNT=$(grep "$TODAY" "$LOG_FILE" | grep -c "EXIT" 2>/dev/null || echo "0")
    
    if [ -n "$TOTAL_PNL" ] && [ "$TOTAL_PNL" != "0" ]; then
        if [ "$TOTAL_PNL" -gt 0 ] 2>/dev/null; then
            echo -e "${GREEN}  今日 PnL: +$TOTAL_PNL TWD${NC}"
        else
            echo -e "${RED}  今日 PnL: $TOTAL_PNL TWD${NC}"
        fi
    else
        echo "  今日 PnL: 0 TWD"
    fi
    
    echo "  進場次數：$ENTRY_COUNT"
    echo "  出場次數：$EXIT_COUNT"
fi
echo ""

# 6. 系統資源
echo -e "${BLUE}【6】系統資源${NC}"
# CPU 和記憶體
if command -v top > /dev/null; then
    PYTHON_PROC=$(ps aux | grep "[p]ython.*simulation" | head -1)
    if [ -n "$PYTHON_PROC" ]; then
        PID=$(echo "$PYTHON_PROC" | awk '{print $2}')
        CPU=$(echo "$PYTHON_PROC" | awk '{print $3}')
        MEM=$(echo "$PYTHON_PROC" | awk '{print $4}')
        echo "  Python PID: $PID"
        echo "  CPU: $CPU%"
        echo "  Memory: $MEM%"
    else
        echo "  無 Python 進程"
    fi
fi

# 磁碟空間
DISK=$(df -h . | tail -1 | awk '{print $5}')
echo "  磁碟使用：$DISK"
echo ""

# 7. 快速指令
echo -e "${BLUE}【7】快速指令${NC}"
echo "  查看完整日誌：tail -f $LOG_FILE"
echo "  查看市場數據：cat $MARKET_DIR/TMF_*.csv | tail -20"
echo "  停止交易：pkill -f simulation"
echo "  重啟系統：bash autostart.sh"
echo ""

echo "╔════════════════════════════════════════════════════════╗"
echo "║                    監控完成                            ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "下次更新：60 秒後 (Ctrl+C 停止)"
