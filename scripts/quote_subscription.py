#!/usr/bin/env python3
"""
行情訂閱管理器
確保只訂閱一次，避免重複訂閱導致監聽器過載
"""

import shioaji as sj
from typing import Optional, Dict
import warnings

warnings.filterwarnings("ignore", category=ResourceWarning)


class QuoteSubscriptionManager:
    """
    行情訂閱管理器 (單例模式)
    
    使用方式:
        manager = QuoteSubscriptionManager.get_instance()
        manager.subscribe(api, contract)
    """
    
    _instance: Optional['QuoteSubscriptionManager'] = None
    _subscribed_contracts: Dict[str, bool] = {}  # 已訂閱的合約
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        # 只初始化一次
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._subscribed_contracts = {}
    
    @classmethod
    def get_instance(cls) -> 'QuoteSubscriptionManager':
        """獲取單例實例"""
        return cls()
    
    def subscribe(self, api, contract, quote_type: str = "Tick") -> bool:
        """
        訂閱行情 (只訂閱一次)
        
        Args:
            api: Shioaji API 物件
            contract: 合約物件
            quote_type: 報價類型 ("Tick", "1m", "5m", etc.)
        
        Returns:
            bool: True 表示訂閱成功，False 表示已訂閱過
        """
        contract_code = contract.code
        
        # 檢查是否已訂閱
        if contract_code in self._subscribed_contracts:
            print(f"[dim]行情已訂閱：{contract_code}[/dim]")
            return False
        
        try:
            # 訂閱行情
            api.quote.subscribe(
                contract,
                quote_type=getattr(sj.constant.QuoteType, quote_type),
                version=sj.constant.QuoteType.v1
            )
            
            # 標記為已訂閱
            self._subscribed_contracts[contract_code] = True
            
            print(f"[green]✓ 已訂閱行情：{contract_code} ({quote_type})[/green]")
            return True
            
        except Exception as e:
            print(f"[red]✗ 訂閱行情失敗：{contract_code} - {e}[/red]")
            return False
    
    def unsubscribe(self, api, contract) -> bool:
        """
        取消訂閱
        
        Args:
            api: Shioaji API 物件
            contract: 合約物件
        
        Returns:
            bool: True 表示取消成功，False 表示未訂閱
        """
        contract_code = contract.code
        
        if contract_code not in self._subscribed_contracts:
            print(f"[dim]未訂閱該合約：{contract_code}[/dim]")
            return False
        
        try:
            api.quote.unsubscribe(contract)
            del self._subscribed_contracts[contract_code]
            print(f"[green]✓ 已取消訂閱：{contract_code}[/green]")
            return True
        except Exception as e:
            print(f"[red]✗ 取消訂閱失敗：{e}[/red]")
            return False
    
    def get_subscribed_contracts(self) -> list:
        """獲取已訂閱的合約列表"""
        return list(self._subscribed_contracts.keys())
    
    def get_subscription_count(self) -> int:
        """獲取訂閱數量"""
        return len(self._subscribed_contracts)
    
    def reset(self):
        """重置所有訂閱 (重新啟動時使用)"""
        self._subscribed_contracts = {}
        print("[dim]已重置訂閱管理器[/dim]")


# 便捷函數
def subscribe_once(api, contract, quote_type: str = "Tick") -> bool:
    """
    訂閱行情 (只訂閱一次)
    
    Args:
        api: Shioaji API 物件
        contract: 合約物件
        quote_type: 報價類型
    
    Returns:
        bool: 訂閱結果
    """
    manager = QuoteSubscriptionManager.get_instance()
    return manager.subscribe(api, contract, quote_type)


def get_subscription_status() -> dict:
    """
    獲取訂閱狀態
    
    Returns:
        dict: 訂閱狀態字典
    """
    manager = QuoteSubscriptionManager.get_instance()
    return {
        'count': manager.get_subscription_count(),
        'contracts': manager.get_subscribed_contracts()
    }


# 測試用
if __name__ == "__main__":
    print("=== 測試行情訂閱管理器 ===\n")
    
    # 獲取單例
    manager1 = QuoteSubscriptionManager.get_instance()
    manager2 = QuoteSubscriptionManager.get_instance()
    
    print(f"manager1 is manager2: {manager1 is manager2}")  # 應該為 True
    print(f"訂閱數量：{manager1.get_subscription_count()}")
    
    # 模擬訂閱
    print("\n=== 模擬訂閱 ===")
    manager1._subscribed_contracts['TXF202604'] = True
    manager1._subscribed_contracts['TMF202604'] = True
    
    print(f"訂閱數量：{manager1.get_subscription_count()}")
    print(f"已訂閱合約：{manager1.get_subscribed_contracts()}")
    
    # 測試重複訂閱
    print("\n=== 測試重複訂閱保護 ===")
    manager2._subscribed_contracts['TXF202604'] = True  # 應該不會重複添加
    
    print(f"訂閱數量：{manager2.get_subscription_count()}")
    print(f"已訂閱合約：{manager2.get_subscribed_contracts()}")
    
    print("\n=== 測試完成 ===")
