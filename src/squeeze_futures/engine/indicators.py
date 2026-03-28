import pandas as pd
import numpy as np
import pandas_ta as ta

def calculate_futures_squeeze(df: pd.DataFrame, bb_length=14, bb_std=2.0, kc_length=14, kc_scalar=1.5, 
                             ema_fast=20, ema_slow=60, lookback=60, pb_buffer=1.002, ema_macro=200) -> pd.DataFrame:
    """
    包含 Squeeze、雙向回測及多週期環境過濾的指標計算。
    """
    if df.empty or len(df) < max(bb_length, ema_slow, lookback, ema_macro):
        return df

    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)
    df.columns = [c.capitalize() for c in df.columns]

    # 1. Squeeze
    sqz = df.ta.squeeze(bb_length=bb_length, bb_std=bb_std, kc_length=kc_length, kc_scalar=kc_scalar, lazy=True)
    sqz_on_col = [c for c in sqz.columns if 'SQZ_ON' in c][0]
    mom_col = [c for c in sqz.columns if c.startswith('SQZ_') and c not in ['SQZ_ON', 'SQZ_OFF', 'SQZ_NO']][0]
    
    # 2. VWAP
    if 'Volume' in df.columns and df['Volume'].sum() > 0:
        vwap_val = (df['Close'] * df['Volume']).cumsum() / df['Volume'].cumsum()
    else:
        vwap_val = df['Close'].rolling(window=bb_length).mean()
    
    # 3. 集成
    res = df.copy()
    res['sqz_on'] = sqz[sqz_on_col].astype(bool)
    res['momentum'] = sqz[mom_col].fillna(0)
    res['vwap'] = vwap_val
    res['fired'] = (~res['sqz_on']) & (res['sqz_on'].shift(1) == True)
    
    # 動能狀態
    res['mom_prev'] = res['momentum'].shift(1).fillna(0)
    def get_mom_state(row):
        m, p = row['momentum'], row['mom_prev']
        if m > 0: return 3 if m >= p else 2
        else: return 0 if m <= p else 1
    res['mom_state'] = res.apply(get_mom_state, axis=1)
    
    # 4. 趨勢排列 (用於 Pullback 進場)
    res['ema_fast'] = df.ta.ema(length=ema_fast)
    res['ema_slow'] = df.ta.ema(length=ema_slow)
    res['bullish_align'] = res['ema_fast'] > res['ema_slow']
    res['bearish_align'] = res['ema_fast'] < res['ema_slow']
    
    # 5. 環境過濾指標 (用於 Regime Filter)
    res['ema_filter'] = df.ta.ema(length=60) # 15m EMA 60 作為中線過濾
    res['ema_macro'] = df.ta.ema(length=ema_macro) # 1h EMA 200 作為長線
    
    # 6. 極值與拉回
    res['recent_high'] = res['Close'].rolling(window=lookback).max()
    res['recent_low'] = res['Close'].rolling(window=lookback).min()
    res['is_new_high'] = res['Close'] >= res['recent_high'].shift(1)
    res['is_new_low'] = res['Close'] <= res['recent_low'].shift(1)
    
    res['in_bull_pb_zone'] = (res['Close'] <= res['ema_fast'] * pb_buffer) & (res['Close'] >= res['ema_slow']) & res['bullish_align']
    res['in_bear_pb_zone'] = (res['Close'] >= res['ema_fast'] * (2 - pb_buffer)) & (res['Close'] <= res['ema_slow']) & res['bearish_align']
    
    return res

def calculate_mtf_alignment(data_dict: dict[str, pd.DataFrame], weights=None) -> dict:
    if not data_dict: return {"score": 0, "is_aligned": False}
    if weights is None: weights = {"1h": 0.2, "15m": 0.4, "5m": 0.4}
    latest_states = {}
    for tf, df in data_dict.items():
        if df.empty: continue
        last = df.iloc[-1]
        direction = 1 if last['momentum'] > 0 else -1
        strength = 1.5 if (last['mom_state'] in [0, 3]) else 1.0
        latest_states[tf] = direction * strength
    total_score = 0
    available_weight = 0
    for tf, val in latest_states.items():
        w = weights.get(tf, 0.1); total_score += val * w; available_weight += w
    norm_score = (total_score / (1.5 * available_weight)) * 100 if available_weight > 0 else 0
    return {"score": norm_score, "states": latest_states, "is_aligned": abs(norm_score) >= 60}
