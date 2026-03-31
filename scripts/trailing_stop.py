# 📋 策略參數
STOP_LOSS_PTS = 60       # 停損 60 點
TAKE_PROFIT_PTS = 50     # 停利 50 點
TRAILING_UPDATE_INTERVAL = 10  # 每 10 點更新一次停損 (避免 API 限流)

# 移動停損狀態
highest_price = 0        # 紀錄進場後最高價
current_stop_price = 0   # 動態停損價
stop_order_trade = None  # 紀錄停損委託單物件

def update_trailing_stop(current_price: float, entry_price: float, is_long: bool):
    """
    移動停損 (Trailing Stop) 更新邏輯
    
    Args:
        current_price: 當前價格
        entry_price: 進場價格
        is_long: 是否為多單
    """
    global highest_price, current_stop_price, TRAILING_UPDATE_INTERVAL
    
    if is_long:
        # 多單：追蹤最高價
        if current_price > highest_price:
            highest_price = current_price
            
            # 計算新的停損價
            new_stop_price = highest_price - STOP_LOSS_PTS
            
            # 只有當新的停損點比舊的高出 TRAILING_UPDATE_INTERVAL 點以上才改單
            if new_stop_price > (current_stop_price + TRAILING_UPDATE_INTERVAL):
                current_stop_price = new_stop_price
                return True  # 需要更新停損單
    else:
        # 空單：追蹤最低價
        if current_price < highest_price or highest_price == 0:
            highest_price = current_price
            
            # 計算新的停損價
            new_stop_price = highest_price + STOP_LOSS_PTS
            
            # 只有當新的停損點比舊的低出 TRAILING_UPDATE_INTERVAL 點以上才改單
            if new_stop_price < (current_stop_price - TRAILING_UPDATE_INTERVAL):
                current_stop_price = new_stop_price
                return True  # 需要更新停損單
    
    return False  # 不需要更新

def reset_trailing_stop():
    """重置移動停損狀態 (新進場時調用)"""
    global highest_price, current_stop_price, stop_order_trade
    highest_price = 0
    current_stop_price = 0
    stop_order_trade = None
