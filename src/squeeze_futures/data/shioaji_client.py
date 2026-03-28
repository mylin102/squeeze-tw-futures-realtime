import os
import logging
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime, timedelta

# 只有安裝了 shioaji 才匯入
try:
    import shioaji as sj
except ImportError:
    sj = None

load_dotenv()

logger = logging.getLogger(__name__)

class ShioajiClient:
    def __init__(self):
        self.api = None
        self.is_logged_in = False
        if sj is None:
            logger.error("shioaji package not installed.")
            return
            
        self.api = sj.Shioaji()

    def login(self):
        api_key = os.getenv("SHIOAJI_API_KEY")
        secret_key = os.getenv("SHIOAJI_SECRET_KEY")
        cert_path = os.getenv("SHIOAJI_CERT_PATH")
        cert_password = os.getenv("SHIOAJI_CERT_PASSWORD")

        if not all([api_key, secret_key]):
            logger.warning("Shioaji API credentials missing in .env")
            return False

        try:
            self.api.login(
                api_key=api_key,
                secret_key=secret_key,
                fetch_contract=True
            )
            
            # 只有提供憑證路徑才啟動 CA (下單才強制需要，但某些即時報價也需要)
            if cert_path and os.path.exists(cert_path):
                self.api.activate_ca(
                    ca_path=cert_path,
                    ca_passwd=cert_password,
                    person_id=api_key
                )
                logger.info("Shioaji CA activated.")
            
            self.is_logged_in = True
            logger.info("Successfully logged in to Shioaji.")
            return True
        except Exception as e:
            logger.error(f"Shioaji login failed: {str(e)}")
            self.is_logged_in = False
            return False

    def get_kline(self, ticker: str, interval: str = "5m"):
        """
        獲取 K 線數據。
        interval mapping: 
        '1m' -> 1, '5m' -> 5, '15m' -> 15, '1h' -> 60
        """
        if not self.is_logged_in:
            return pd.DataFrame()

        # 簡單的 interval 轉換
        min_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
        itv = min_map.get(interval, 5)

        try:
            # 處理台股格式 (Shioaji 使用純代號)
            clean_ticker = ticker.split('.')[0] if '.' in ticker else ticker
            if clean_ticker.startswith('^'): # yfinance 格式轉換
                if clean_ticker == '^TWII': clean_ticker = "TSE001" # 大盤
            
            # 嘗試抓取合約
            contract = None
            if clean_ticker == "TSE001":
                contract = self.api.Contracts.Indexs.TSE.TSE001
            elif clean_ticker.isalpha(): # 可能是期貨或美股
                # 這裡需要更複雜的期貨合約搜尋，暫以台股為例
                contract = self.api.Contracts.Stocks.get(clean_ticker)
            else:
                contract = self.api.Contracts.Stocks.get(clean_ticker)

            if not contract:
                return pd.DataFrame()

            # 抓取最近兩天的資料
            start_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
            kbars = self.api.kbars(contract, start=start_date)
            
            df = pd.DataFrame({**kbars})
            if df.empty: return df
            
            df.ts = pd.to_datetime(df.ts)
            df.set_index('ts', inplace=True)
            df.index.name = 'Datetime'
            
            # 轉換為標準 OHLCV
            df = df.rename(columns={
                'Open': 'Open', 'High': 'High', 'Low': 'Low', 'Close': 'Close', 'Volume': 'Volume'
            })
            return df
            
        except Exception as e:
            logger.error(f"Shioaji fetch error for {ticker}: {e}")
            return pd.DataFrame()
