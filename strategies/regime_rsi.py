"""
Regime RSI Strategy
===================

Trend-following mean reversion.
1. Determine Regime: Price vs SMA 200
2. Enter on Pullbacks: RSI Oversold in Bull / Overbought in Bear
"""

import numpy as np
import pandas as pd

# =============================================================================
# STRATEGY CONFIG
# =============================================================================

STRATEGY_NAME = "regime_rsi"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
TIMEFRAME = "4h"  # 4-hour candles

# Params
SMA_PERIOD = 200
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
ATR_PERIOD = 14
SL_ATR_MULT = 2.0
RISK_REWARD = 2.0  # Just for fixed TP calculation backup

# =============================================================================
# INDICATORS (Pandas Implementation)
# =============================================================================

def calc_sma(series, period):
    return series.rolling(window=period).mean()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

# =============================================================================
# INTERFACE FUNCTIONS
# =============================================================================

def check_signal(symbol: str, df: pd.DataFrame) -> dict | None:
    """
    Check for entry signal.
    """
    # sufficient data check
    if len(df) < SMA_PERIOD + 5:
        return None

    # Calculate Indicators
    close = df['close']
    high = df['high']
    low = df['low']
    
    sma = calc_sma(close, SMA_PERIOD)
    rsi = calc_rsi(close, RSI_PERIOD)
    atr = calc_atr(high, low, close, ATR_PERIOD)
    
    # Get latest values
    current_price = close.iloc[-1]
    current_sma = sma.iloc[-1]
    current_rsi = rsi.iloc[-1]
    current_atr = atr.iloc[-1]
    candle_time = df.iloc[-1]['close_time'].isoformat()
    
    # Logic
    # 1. Bullish Regime
    if current_price > current_sma:
        # Buy Dip
        if current_rsi < RSI_OVERSOLD:
            sl_price = current_price - (current_atr * SL_ATR_MULT)
            # TP is dynamic (RSI 50), but we set a hard TP for safety
            tp_price = current_price + (current_atr * SL_ATR_MULT * RISK_REWARD)
            
            return {
                'symbol': symbol,
                'direction': 'LONG',
                'entry': current_price,
                'sl': sl_price,
                'tp': tp_price,
                'candle_time': candle_time
            }
            
    # 2. Bearish Regime
    elif current_price < current_sma:
        # Sell Rally
        if current_rsi > RSI_OVERBOUGHT:
            sl_price = current_price + (current_atr * SL_ATR_MULT)
            tp_price = current_price - (current_atr * SL_ATR_MULT * RISK_REWARD)
            
            return {
                'symbol': symbol,
                'direction': 'SHORT',
                'entry': current_price,
                'sl': sl_price,
                'tp': tp_price,
                'candle_time': candle_time
            }
            
    return None


def check_exit(position: dict, df: pd.DataFrame) -> dict | None:
    """
    Check for exit (RSI mean reversion or SL/TP).
    """
    latest = df.iloc[-1]
    close = df['close']
    
    current_price = latest['close']
    candle_high = latest['high']
    candle_low = latest['low']
    candle_time = latest['close_time'].isoformat()
    
    # Calculate RSI dynamically for exit check
    rsi = calc_rsi(close, RSI_PERIOD)
    current_rsi = rsi.iloc[-1]
    
    direction = position['direction']
    sl = position['sl']
    tp = position['tp']
    
    # 1. Hard SL/TP Check
    if direction == 'LONG':
        if candle_low <= sl:
            return {'reason': 'SL', 'exit_price': sl, 'candle_time': candle_time}
        if candle_high >= tp:
            return {'reason': 'TP_HARD', 'exit_price': tp, 'candle_time': candle_time}
            
        # 2. Dynamic Exit: RSI returns to 50
        if current_rsi >= 50:
             return {'reason': 'RSI_NEUTRAL', 'exit_price': current_price, 'candle_time': candle_time}
             
    elif direction == 'SHORT':
        if candle_high >= sl:
            return {'reason': 'SL', 'exit_price': sl, 'candle_time': candle_time}
        if candle_low <= tp:
            return {'reason': 'TP_HARD', 'exit_price': tp, 'candle_time': candle_time}
            
        # 2. Dynamic Exit: RSI returns to 50
        if current_rsi <= 50:
             return {'reason': 'RSI_NEUTRAL', 'exit_price': current_price, 'candle_time': candle_time}
    
    # 3. Time Limit (48 hours = 12 bars of 4h)
    entry_time = pd.Timestamp(position['candle_time'])
    current_ts = pd.Timestamp(candle_time)
    duration = current_ts - entry_time
    
    if duration.total_seconds() >= 48 * 3600:
        return {'reason': 'TIME', 'exit_price': current_price, 'candle_time': candle_time}
        
    return None
