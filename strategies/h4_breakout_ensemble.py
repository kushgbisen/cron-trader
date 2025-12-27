"""
H4 Breakout Ensemble Strategy
=============================

Entry: Top 3 params unanimous (3/3 agree)
Exit: SL/TP hit or 30 bar timeout
"""

import numpy as np
import pandas as pd
from numba import jit

# =============================================================================
# STRATEGY CONFIG (required)
# =============================================================================

STRATEGY_NAME = "h4_breakout_ensemble"
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


@jit(nopython=True)
def get_signal_at_bar(closes, highs, lows, atr, lookback, breakout_mult, i):
    if i < lookback + 10 or atr[i] <= 0:
        return 0
    lb_high = np.max(highs[i-lookback:i])
    lb_low = np.min(lows[i-lookback:i])
    thresh = breakout_mult * atr[i]
    if closes[i] > lb_high + thresh:
        return 1
    elif closes[i] < lb_low - thresh:
        return -1
    return 0


@jit(nopython=True)
def backtest_params(closes, highs, lows, atr, lb, bm, sl, tp, start, end):
    pnl = pos = entry = sl_p = tp_p = 0.0
    entry_i = trades = 0
    
    for i in range(start, end):
        if atr[i] <= 0 or i < lb + 10:
            continue
        if pos == 1:
            if lows[i] <= sl_p or highs[i] >= tp_p or i - entry_i >= 30:
                if lows[i] <= sl_p:
                    pnl += (sl_p - entry) / entry
                elif highs[i] >= tp_p:
                    pnl += (tp_p - entry) / entry
                else:
                    pnl += (closes[i] - entry) / entry
                trades += 1
                pos = 0
        elif pos == -1:
            if highs[i] >= sl_p or lows[i] <= tp_p or i - entry_i >= 30:
                if highs[i] >= sl_p:
                    pnl += (entry - sl_p) / entry
                elif lows[i] <= tp_p:
                    pnl += (entry - tp_p) / entry
                else:
                    pnl += (entry - closes[i]) / entry
                trades += 1
                pos = 0
        
        if pos == 0:
            sig = get_signal_at_bar(closes, highs, lows, atr, lb, bm, i)
            if sig != 0:
                pos = float(sig)
                entry = closes[i]
                entry_i = i
                if sig == 1:
                    sl_p = entry - sl * atr[i]
                    tp_p = entry + tp * atr[i]
                else:
                    sl_p = entry + sl * atr[i]
                    tp_p = entry - tp * atr[i]
    
    return pnl, trades


@jit(nopython=True)
def get_top3_params(closes, highs, lows, atr, start, end):
    lookbacks = (12, 24, 48)
    breakout_mults = (0.0, 0.25, 0.5)
    stop_losses = (1.5, 2.0, 2.5)
    take_profits = (2.0, 3.0, 4.0)
    
    results = np.zeros((81, 5))
    idx = 0
    
    for lb in lookbacks:
        for bm in breakout_mults:
            for sl in stop_losses:
                for tp in take_profits:
                    pnl, trades = backtest_params(closes, highs, lows, atr, lb, bm, sl, tp, start, end)
                    results[idx, 0] = pnl if trades >= 3 else -999999.0
                    results[idx, 1] = float(lb)
                    results[idx, 2] = bm
                    results[idx, 3] = sl
                    results[idx, 4] = tp
                    idx += 1
    
    indices = np.argsort(-results[:, 0])
    top3 = np.zeros((3, 5))
    for i in range(3):
        for j in range(5):
            top3[i, j] = results[indices[i], j]
    
    return top3


# =============================================================================
# INTERFACE FUNCTIONS (required)
# =============================================================================

def check_signal(symbol: str, df: pd.DataFrame) -> dict | None:
    """
    Check for entry signal.
    
    Returns dict with: symbol, direction, entry, sl, tp, candle_time
    Or None if no signal.
    """
    closes = df['close'].values.astype(np.float64)
    highs = df['high'].values.astype(np.float64)
    lows = df['low'].values.astype(np.float64)
    atr = calc_atr(highs, lows, closes)
    
    # Train on last ~3 months (540 H4 bars)
    train_end = len(closes) - 1
    train_start = max(0, train_end - 540)
    
    top3 = get_top3_params(closes, highs, lows, atr, train_start, train_end)
    
    # Check signal at last bar
    i = len(closes) - 1
    current_price = closes[i]
    current_atr = atr[i]
    candle_time = df.iloc[i]['close_time'].isoformat()
    
    # Vote
    long_votes = short_votes = 0
    sl_sum = tp_sum = 0.0
    
    for p in range(3):
        lb = int(top3[p, 1])
        bm = top3[p, 2]
        sig = get_signal_at_bar(closes, highs, lows, atr, lb, bm, i)
        if sig == 1:
            long_votes += 1
            sl_sum += top3[p, 3]
            tp_sum += top3[p, 4]
        elif sig == -1:
            short_votes += 1
            sl_sum += top3[p, 3]
            tp_sum += top3[p, 4]
    
    # Need 3/3 unanimous
    if long_votes == 3:
        avg_sl, avg_tp = sl_sum / 3, tp_sum / 3
        return {
            'symbol': symbol,
            'direction': 'LONG',
            'entry': current_price,
            'sl': current_price - avg_sl * current_atr,
            'tp': current_price + avg_tp * current_atr,
            'candle_time': candle_time,
        }
    
    elif short_votes == 3:
        avg_sl, avg_tp = sl_sum / 3, tp_sum / 3
        return {
            'symbol': symbol,
            'direction': 'SHORT',
            'entry': current_price,
            'sl': current_price + avg_sl * current_atr,
            'tp': current_price - avg_tp * current_atr,
            'candle_time': candle_time,
        }
    
    return None


def check_exit(position: dict, df: pd.DataFrame) -> dict | None:
    """
    Check if position should exit.
    
    Returns dict with: reason, exit_price, candle_time
    Or None if still open.
    """
    latest = df.iloc[-1]
    candle_high = latest['high']
    candle_low = latest['low']
    candle_close = latest['close']
    candle_time = latest['close_time'].isoformat()
    
    entry = position['entry']
    sl = position['sl']
    tp = position['tp']
    direction = position['direction']
    
    # Check bars held (optional: time-based exit)
    # For now, just SL/TP
    
    if direction == 'LONG':
        if candle_low <= sl:
            return {'reason': 'SL', 'exit_price': sl, 'candle_time': candle_time}
        elif candle_high >= tp:
            return {'reason': 'TP', 'exit_price': tp, 'candle_time': candle_time}
    
    else:  # SHORT
        if candle_high >= sl:
            return {'reason': 'SL', 'exit_price': sl, 'candle_time': candle_time}
        elif candle_low <= tp:
            return {'reason': 'TP', 'exit_price': tp, 'candle_time': candle_time}
    
    return None
