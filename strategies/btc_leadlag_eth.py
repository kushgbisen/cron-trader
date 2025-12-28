"""
BTC Lead-Lag Strategy - ETH ONLY
=================================
Logic: When BTC breaks out → enter ETH after lag

2025 Backtest Results:
- P&L: $5,900
- Win Rate: 49%
- Profit Factor: 1.31
- Max DD: 6.6%
- Profitable Months: 7/11
"""

import pandas as pd
import numpy as np
import requests
from datetime import datetime, timezone

STRATEGY_NAME = "btc_leadlag_eth"
SYMBOLS = ["ETHUSDT"]  # Only trade ETH based on BTC signals
TIMEFRAME = "4h"

# Parameters
LOOKBACK = 24  # bars for breakout detection
LAG_BARS = 2   # enter ETH 2 bars after BTC signal
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


def fetch_btc_data(limit: int = 100) -> pd.DataFrame:
    """Fetch BTC data to check for breakout signals"""
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            'symbol': 'BTCUSDT',
            'interval': '4h',
            'limit': limit
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        df = pd.DataFrame(data, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        
        df['datetime'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
        df = df.set_index('datetime')
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        
        return df
    except Exception as e:
        print(f"Error fetching BTC data: {e}")
        return pd.DataFrame()


def check_signal(symbol: str, df: pd.DataFrame) -> dict | None:
    """Check for BTC breakout → ETH entry signal"""
    if len(df) < 50:
        return None
    
    # Get BTC data
    btc = fetch_btc_data(100)
    if len(btc) < LOOKBACK + LAG_BARS + 5:
        return None
    
    # Calculate BTC breakout
    btc['high_lb'] = btc['high'].rolling(LOOKBACK).max().shift(1)
    btc['low_lb'] = btc['low'].rolling(LOOKBACK).min().shift(1)
    
    # Check if BTC had breakout LAG_BARS ago
    btc['long_signal'] = btc['close'] > btc['high_lb']
    btc['short_signal'] = btc['close'] < btc['low_lb']
    
    # Get signal from LAG_BARS ago
    if len(btc) < LAG_BARS + 1:
        return None
    
    lagged_long = btc['long_signal'].iloc[-(LAG_BARS + 1)]
    lagged_short = btc['short_signal'].iloc[-(LAG_BARS + 1)]
    
    if not lagged_long and not lagged_short:
        return None
    
    # Calculate ETH ATR for SL/TP
    df = df.copy()
    df['atr'] = calc_atr(df, 14)
    
    curr = df.iloc[-1]
    atr = curr['atr']
    close = curr['close']
    
    if pd.isna(atr) or atr <= 0:
        return None
    
    if lagged_long:
        return {
            'symbol': symbol,
            'direction': 'LONG',
            'entry': close,
            'sl': close - SL_ATR_MULT * atr,
            'tp': close + TP_ATR_MULT * atr,
            'candle_time': str(df.index[-1])
        }
    elif lagged_short:
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
