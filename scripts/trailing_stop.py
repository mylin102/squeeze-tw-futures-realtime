#!/usr/bin/env python3
"""
移動停損 (Trailing Stop) 模組
包含冷卻時間機制，避免頻繁改單和 EventEmitter 過載
"""

import time

# ========== 全局狀態變數 ==========
LAST_UPDATE_TIME = 0          # 最後更新時間 (timestamp)
UPDATE_COOLDOWN = 1.0         # 冷卻時間 (秒) - 至少間隔 1 秒才准改單一次
highest_price = 0             # 紀錄進場後最高價
current_stop_price = 0        # 當前停損價
stop_order_trade = None       # 停損委託單物件

# 策略參數
STOP_LOSS_PTS = 60            # 停損 60 點
TAKE_PROFIT_PTS = 50          # 停利 50 點
TRAILING_UPDATE_INTERVAL = 10 # 每 10 點更新一次停損 (避免 API 限流)


def reset_trailing_stop():
    """
    重置移動停損狀態 (新進場時調用)
    """
    global highest_price, current_stop_price, stop_order_trade, LAST_UPDATE_TIME
    highest_price = 0
    current_stop_price = 0
    stop_order_trade = None
    LAST_UPDATE_TIME = 0


def should_update_stop(current_price: float, entry_price: float, is_long: bool) -> bool:
    """
    判斷是否應該更新停損單
    
    Args:
        current_price: 當前價格
        entry_price: 進場價格
        is_long: 是否為多單
    
    Returns:
        bool: True 表示需要更新，False 表示不需要
    """
    global highest_price, current_stop_price, TRAILING_UPDATE_INTERVAL
    
    current_time = time.time()
    
    # 檢查 1: 是否超過冷卻時間 (避免 EventEmitter 過載)
    if current_time - LAST_UPDATE_TIME < UPDATE_COOLDOWN:
        return False
    
    if is_long:
        # 多單：追蹤最高價
        if current_price > highest_price:
            highest_price = current_price
            
            # 計算新的停損價
            new_stop_price = highest_price - STOP_LOSS_PTS
            
            # 檢查 2: 只有當新的停損點比舊的高出 TRAILING_UPDATE_INTERVAL 點以上才更新
            if new_stop_price > (current_stop_price + TRAILING_UPDATE_INTERVAL):
                current_stop_price = new_stop_price
                return True
    else:
        # 空單：追蹤最低價
        if current_price < highest_price or highest_price == 0:
            highest_price = current_price
            
            # 計算新的停損價
            new_stop_price = highest_price + STOP_LOSS_PTS
            
            # 檢查 2: 只有當新的停損點比舊的低出 TRAILING_UPDATE_INTERVAL 點以上才更新
            if new_stop_price < (current_stop_price - TRAILING_UPDATE_INTERVAL):
                current_stop_price = new_stop_price
                return True
    
    return False


def update_trailing_stop(api, contract, is_long: bool) -> bool:
    """
    更新移動停損單
    
    Args:
        api: Shioaji API 物件
        contract: 合約物件
        is_long: 是否為多單
    
    Returns:
        bool: True 表示更新成功，False 表示失敗或不需要更新
    """
    global stop_order_trade, LAST_UPDATE_TIME
    
    if stop_order_trade is None:
        return False
    
    # 獲取當前價格 (需要從外部傳入或在這裡訂閱行情)
    # 這裡假設已經有價格數據
    
    # 執行改單
    try:
        api.update_order(
            stop_order_trade,
            price=current_stop_price,
            qty=1
        )
        
        # 更新最後修改時間
        LAST_UPDATE_TIME = time.time()
        
        print(f"✓ 成功改單，進入 {UPDATE_COOLDOWN} 秒冷卻期...")
        return True
        
    except Exception as e:
        print(f"✗ 改單失敗：{e}")
        return False


def get_trailing_stop_status() -> dict:
    """
    獲取移動停損狀態
    
    Returns:
        dict: 包含當前狀態的字典
    """
    return {
        'highest_price': highest_price,
        'current_stop_price': current_stop_price,
        'last_update_time': LAST_UPDATE_TIME,
        'cooldown_remaining': max(0, UPDATE_COOLDOWN - (time.time() - LAST_UPDATE_TIME))
    }


# 測試用主函數
if __name__ == "__main__":
    # 測試冷卻時間機制
    print("=== 測試移動停損冷卻時間機制 ===\n")
    
    # 模擬進場
    entry_price = 20000
    reset_trailing_stop()
    current_stop_price = entry_price - STOP_LOSS_PTS
    
    print(f"進場價格：{entry_price}")
    print(f"初始停損：{current_stop_price}")
    print(f"冷卻時間：{UPDATE_COOLDOWN} 秒\n")
    
    # 模擬價格上漲
    test_prices = [20010, 20020, 20030, 20040, 20050]
    
    for price in test_prices:
        print(f"當前價格：{price}")
        
        if should_update_stop(price, entry_price, is_long=True):
            print(f"  → 需要更新停損單")
            # 實際使用時會呼叫 update_trailing_stop()
        else:
            cooldown = UPDATE_COOLDOWN - (time.time() - LAST_UPDATE_TIME)
            print(f"  → 不需要更新 (冷卻時間剩餘：{cooldown:.2f}秒)")
        
        time.sleep(0.5)  # 模擬時間流逝
    
    print("\n=== 測試完成 ===")
