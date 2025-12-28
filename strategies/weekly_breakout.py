"""
Weekly Breakout Strategy (H4)
=============================

Entry: Price breaks above/below weekly high/low
Exit: SL/TP or 1 week timeout (42 H4 bars)
"""

import numpy as np
import pandas as pd
from numba import jit

# =============================================================================
# STRATEGY CONFIG
# =============================================================================

STRATEGY_NAME = "weekly_breakout"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEFRAME = "4h"

# =============================================================================
# NUMBA FUNCTIONS
# =============================================================================

@jit(nopython=True)
def calc_atr(highs, lows, closes, period=14):
    n = len(closes)
    atr = np.zeros(n)
    for i in range(period, n):
        sum_tr = 0.0
        for j in range(i - period + 1, i + 1):
            tr = max(highs[j] - lows[j], abs(highs[j] - closes[j-1]), abs(lows[j] - closes[j-1]))
            sum_tr += tr
        atr[i] = sum_tr / period
    return atr


# =============================================================================
# INTERFACE FUNCTIONS
# =============================================================================

def check_signal(symbol: str, df: pd.DataFrame) -> dict | None:
    """Check for weekly breakout signal"""
    
    closes = df['close'].values.astype(np.float64)
    highs = df['high'].values.astype(np.float64)
    lows = df['low'].values.astype(np.float64)
    atr = calc_atr(highs, lows, closes, 14)
    
    lookback = 42  # 1 week in H4 bars
    i = len(closes) - 1
    
    if i < lookback + 10 or atr[i] <= 0:
        return None
    
    week_high = np.max(highs[i-lookback:i])
    week_low = np.min(lows[i-lookback:i])
    
    current_price = closes[i]
    current_atr = atr[i]
    candle_time = df.iloc[i]['close_time'].isoformat()
    
    # SL/TP
    sl_mult = 2.5
    tp_mult = 4.0
    
    if current_price > week_high:
        return {
            'symbol': symbol,
            'direction': 'LONG',
            'entry': current_price,
            'sl': current_price - sl_mult * current_atr,
            'tp': current_price + tp_mult * current_atr,
            'candle_time': candle_time,
        }
    
    elif current_price < week_low:
        return {
            'symbol': symbol,
            'direction': 'SHORT',
            'entry': current_price,
            'sl': current_price + sl_mult * current_atr,
            'tp': current_price - tp_mult * current_atr,
            'candle_time': candle_time,
        }
    
    return None


def check_exit(position: dict, df: pd.DataFrame) -> dict | None:
    """Check if position should exit"""
    
    latest = df.iloc[-1]
    candle_high = latest['high']
    candle_low = latest['low']
    candle_time = latest['close_time'].isoformat()
    
    sl = position['sl']
    tp = position['tp']
    direction = position['direction']
    
    if direction == 'LONG':
        if candle_low <= sl:
            return {'reason': 'SL', 'exit_price': sl, 'candle_time': candle_time}
        elif candle_high >= tp:
            return {'reason': 'TP', 'exit_price': tp, 'candle_time': candle_time}
    else:
        if candle_high >= sl:
            return {'reason': 'SL', 'exit_price': sl, 'candle_time': candle_time}
        elif candle_low <= tp:
            return {'reason': 'TP', 'exit_price': tp, 'candle_time': candle_time}
    
    return None
