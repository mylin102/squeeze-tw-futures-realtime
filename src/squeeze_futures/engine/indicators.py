import pandas as pd
import numpy as np
import pandas_ta as ta

def calculate_futures_squeeze(df: pd.DataFrame, bb_length=20, bb_std=2.0, kc_length=20, kc_scalar=1.5) -> pd.DataFrame:
    """
    專為期貨設計的 Squeeze 指標計算。
    增加了更敏感的擠壓偵測與動能顏色邏輯。
    """
    if df.empty:
        return df

    # 1. 基礎 TTM Squeeze 計算
    # 使用 pandas_ta 的 squeeze
    sqz = df.ta.squeeze(bb_length=bb_length, bb_std=bb_std, kc_length=kc_length, kc_scalar=kc_scalar, lazy=True)
    
    sqz_on_col = [c for c in sqz.columns if 'SQZ_ON' in c][0]
    sqz_off_col = [c for c in sqz.columns if 'SQZ_OFF' in c][0]
    mom_col = [c for c in sqz.columns if c.startswith('SQZ_') and c not in ['SQZ_ON', 'SQZ_OFF', 'SQZ_NO']][0]
    
    # 2. 能量等級 (Energy Level) - 期貨交易的核心
    bb = df.ta.bbands(length=bb_length, std=bb_std)
    kc = df.ta.kc(length=kc_length, scalar=kc_scalar)
    
    bb_width = bb.filter(like='BBU').iloc[:, 0] - bb.filter(like='BBL').iloc[:, 0]
    kc_width = kc.filter(like='KCU').iloc[:, 0] - kc.filter(like='KCL').iloc[:, 0]
    
    # 擠壓比率：越高表示擠壓越嚴重
    squeeze_ratio = (kc_width - bb_width) / kc_width
    
    # 3. 集成結果
    res = df.copy()
    res['sqz_on'] = sqz[sqz_on_col].astype(bool)
    res['sqz_off'] = sqz[sqz_off_col].astype(bool)
    res['momentum'] = sqz[mom_col].fillna(0)
    res['sqz_ratio'] = squeeze_ratio.fillna(0)
    
    # 4. 動能狀態辨識 (Momentum State)
    # 0: 負動能增強 (深紅), 1: 負動能減弱 (淺紅), 2: 正動能減弱 (深綠), 3: 正動能增強 (鮮綠)
    res['mom_prev'] = res['momentum'].shift(1).fillna(0)
    
    def get_mom_state(row):
        m = row['momentum']
        p = row['mom_prev']
        if m > 0:
            return 3 if m >= p else 2
        else:
            return 0 if m <= p else 1
            
    res['mom_state'] = res.apply(get_mom_state, axis=1)
    
    # 5. 期貨信號
    # 爆發 (Fired): 剛解除擠壓且動能強勁
    res['fired'] = (~res['sqz_on']) & (res['sqz_on'].shift(1) == True)
    
    return res

def identify_trend_alignment(data_dict: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    多週期共振檢查 (Alignment)。
    例如：15m 擠壓中，5m 剛爆發向上。
    """
    # 實作多週期邏輯...
    pass
