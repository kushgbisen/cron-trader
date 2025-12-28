"""
Regime RSI Strategy (H1)
========================

Entry: RSI + ADX regime detection
- Trending (ADX > 25): RSI > 60 = Long, RSI < 40 = Short
- Ranging (ADX < 25): RSI < 30 = Long, RSI > 70 = Short

Exit: SL/TP or 24 bar timeout
"""

import numpy as np
import pandas as pd
from numba import jit

# =============================================================================
# STRATEGY CONFIG
# =============================================================================

STRATEGY_NAME = "regime_rsi"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEFRAME = "1h"

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


@jit(nopython=True)
def calc_rsi(closes, period=14):
    n = len(closes)
    rsi = np.zeros(n)
    gains = np.zeros(n)
    losses = np.zeros(n)
    
    for i in range(1, n):
        diff = closes[i] - closes[i-1]
        if diff > 0:
            gains[i] = diff
        else:
            losses[i] = -diff
    
    for i in range(period + 1, n):
        avg_gain = np.mean(gains[i-period:i])
        avg_loss = np.mean(losses[i-period:i])
        if avg_loss == 0:
            rsi[i] = 100
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100 - (100 / (1 + rs))
    
    return rsi


@jit(nopython=True)
def calc_adx(highs, lows, closes, period=14):
    n = len(closes)
    adx = np.zeros(n)
    
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    
    for i in range(1, n):
        high_diff = highs[i] - highs[i-1]
        low_diff = lows[i-1] - lows[i]
        
        if high_diff > low_diff and high_diff > 0:
            plus_dm[i] = high_diff
        if low_diff > high_diff and low_diff > 0:
            minus_dm[i] = low_diff
        
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    
    for i in range(period * 2, n):
        sum_plus = np.sum(plus_dm[i-period:i])
        sum_minus = np.sum(minus_dm[i-period:i])
        sum_tr = np.sum(tr[i-period:i])
        
        if sum_tr > 0:
            plus_di = sum_plus / sum_tr * 100
            minus_di = sum_minus / sum_tr * 100
            if plus_di + minus_di > 0:
                adx[i] = abs(plus_di - minus_di) / (plus_di + minus_di) * 100
    
    return adx


# =============================================================================
# INTERFACE FUNCTIONS
# =============================================================================

def check_signal(symbol: str, df: pd.DataFrame) -> dict | None:
    """Check for Regime RSI entry signal"""
    
    closes = df['close'].values.astype(np.float64)
    highs = df['high'].values.astype(np.float64)
    lows = df['low'].values.astype(np.float64)
    
    rsi = calc_rsi(closes, 14)
    adx = calc_adx(highs, lows, closes, 14)
    atr = calc_atr(highs, lows, closes, 14)
    
    i = len(closes) - 1
    if i < 50 or atr[i] <= 0:
        return None
    
    current_price = closes[i]
    current_rsi = rsi[i]
    current_adx = adx[i]
    current_atr = atr[i]
    candle_time = df.iloc[i]['close_time'].isoformat()
    
    trending = current_adx > 25
    direction = None
    
    if trending:
        # Trend following
        if current_rsi > 60:
            direction = 'LONG'
        elif current_rsi < 40:
            direction = 'SHORT'
    else:
        # Mean reversion
        if current_rsi < 30:
            direction = 'LONG'
        elif current_rsi > 70:
            direction = 'SHORT'
    
    if direction is None:
        return None
    
    # SL/TP based on ATR
    sl_mult = 2.0
    tp_mult = 3.0
    
    if direction == 'LONG':
        return {
            'symbol': symbol,
            'direction': 'LONG',
            'entry': current_price,
            'sl': current_price - sl_mult * current_atr,
            'tp': current_price + tp_mult * current_atr,
            'candle_time': candle_time,
        }
    else:
        return {
            'symbol': symbol,
            'direction': 'SHORT',
            'entry': current_price,
            'sl': current_price + sl_mult * current_atr,
            'tp': current_price - tp_mult * current_atr,
            'candle_time': candle_time,
        }


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
