"""
Volatility Squeeze Strategy - SOL ONLY
=======================================
Logic: BB inside Keltner = squeeze → trade release direction

2025 Backtest Results:
- P&L: $9,872
- Win Rate: 61%
- Profit Factor: 2.19
- Max DD: 1.9%
- Profitable Months: 9/11
"""

import pandas as pd
import numpy as np

STRATEGY_NAME = "vol_squeeze_sol"
SYMBOLS = ["SOLUSDT"]  # SOL only - BTC/ETH don't work
TIMEFRAME = "4h"

# Parameters
BB_PERIOD = 20
BB_STD = 2.0
KC_PERIOD = 20
KC_MULT = 1.5
SL_ATR_MULT = 2.0
TP_ATR_MULT = 3.0


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    return tr.rolling(period).mean()


def check_signal(symbol: str, df: pd.DataFrame) -> dict | None:
    """Check for squeeze release signal"""
    if len(df) < 50:
        return None
    
    df = df.copy()
    
    # Calculate indicators
    df['sma'] = df['close'].rolling(BB_PERIOD).mean()
    df['std'] = df['close'].rolling(BB_PERIOD).std()
    df['atr'] = calc_atr(df, 14)
    
    # Bollinger Bands
    df['bb_upper'] = df['sma'] + BB_STD * df['std']
    df['bb_lower'] = df['sma'] - BB_STD * df['std']
    
    # Keltner Channel
    df['kc_upper'] = df['sma'] + KC_MULT * df['atr']
    df['kc_lower'] = df['sma'] - KC_MULT * df['atr']
    
    # Squeeze: BB inside KC
    df['squeeze'] = (df['bb_lower'] > df['kc_lower']) & (df['bb_upper'] < df['kc_upper'])
    
    # Momentum
    df['momentum'] = df['close'] - df['sma']
    
    # Check last two bars for squeeze release
    if len(df) < 2:
        return None
    
    prev_squeeze = df['squeeze'].iloc[-2]
    curr_squeeze = df['squeeze'].iloc[-1]
    
    # Squeeze release: was in squeeze, now not
    if prev_squeeze and not curr_squeeze:
        curr = df.iloc[-1]
        atr = curr['atr']
        close = curr['close']
        momentum = curr['momentum']
        
        if pd.isna(atr) or atr <= 0:
            return None
        
        if momentum > 0:
            # LONG signal
            return {
                'symbol': symbol,
                'direction': 'LONG',
                'entry': close,
                'sl': close - SL_ATR_MULT * atr,
                'tp': close + TP_ATR_MULT * atr,
                'candle_time': str(df.index[-1])
            }
        else:
            # SHORT signal
            return {
                'symbol': symbol,
                'direction': 'SHORT',
                'entry': close,
                'sl': close + SL_ATR_MULT * atr,
                'tp': close - TP_ATR_MULT * atr,
                'candle_time': str(df.index[-1])
            }
    
    return None


def check_exit(position: dict, df: pd.DataFrame) -> dict | None:
    """Check if SL or TP hit"""
    if len(df) < 1:
        return None
    
    curr = df.iloc[-1]
    high = curr['high']
    low = curr['low']
    
    sl = position['sl']
    tp = position['tp']
    direction = position['direction']
    
    if direction == 'LONG':
        if low <= sl:
            return {
                'reason': 'SL',
                'exit_price': sl,
                'candle_time': str(df.index[-1])
            }
        elif high >= tp:
            return {
                'reason': 'TP',
                'exit_price': tp,
                'candle_time': str(df.index[-1])
            }
    else:  # SHORT
        if high >= sl:
            return {
                'reason': 'SL',
                'exit_price': sl,
                'candle_time': str(df.index[-1])
            }
        elif low <= tp:
            return {
                'reason': 'TP',
                'exit_price': tp,
                'candle_time': str(df.index[-1])
            }
    
    return None
