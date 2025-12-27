"""
Cron Trader - Strategy Agnostic Paper Trading Engine
=====================================================

Runs all enabled strategies, logs trades, sends Telegram alerts.
"""

import os
import sys
import json
import yaml
import importlib.util
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# =============================================================================
# CONFIG
# =============================================================================

ROOT = Path(__file__).parent
STRATEGIES_DIR = ROOT / "strategies"
LOGS_DIR = ROOT / "logs"
CONFIG_FILE = ROOT / "config.yaml"

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


# =============================================================================
# TELEGRAM
# =============================================================================

def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Not configured, skipping")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[Telegram] Error: {e}")
        return False


# =============================================================================
# DATA FETCHING
# =============================================================================

def fetch_ohlcv(symbol: str, timeframe: str = '4h', limit: int = 500) -> pd.DataFrame:
    """Fetch OHLCV data from Binance"""
    url = "https://api.binance.com/api/v3/klines"
    params = {'symbol': symbol, 'interval': timeframe, 'limit': limit}
    
    response = requests.get(url, params=params, timeout=30)
    data = response.json()
    
    df = pd.DataFrame(data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms', utc=True)
    
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    
    return df


def get_current_price(symbol: str) -> float:
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    r = requests.get(url, timeout=10)
    return float(r.json()['price'])


# =============================================================================
# TRADE LOGGING
# =============================================================================

def get_strategy_log_dir(strategy_name: str) -> Path:
    path = LOGS_DIR / strategy_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_positions(strategy_name: str) -> dict:
    path = get_strategy_log_dir(strategy_name) / "positions.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_positions(strategy_name: str, positions: dict):
    path = get_strategy_log_dir(strategy_name) / "positions.json"
    with open(path, 'w') as f:
        json.dump(positions, f, indent=2)


def load_trades(strategy_name: str) -> pd.DataFrame:
    path = get_strategy_log_dir(strategy_name) / "trades.csv"
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=[
        'candle_time', 'symbol', 'direction', 'entry_price', 'sl', 'tp',
        'exit_price', 'exit_candle_time', 'pnl_pct', 'pnl_usd', 'status', 'exit_reason'
    ])


def save_trades(strategy_name: str, df: pd.DataFrame):
    path = get_strategy_log_dir(strategy_name) / "trades.csv"
    df.to_csv(path, index=False)


def log_entry(strategy_name: str, signal: dict, risk_usd: float):
    """Log new trade entry"""
    trades_df = load_trades(strategy_name)
    
    new_trade = {
        'candle_time': signal['candle_time'],
        'symbol': signal['symbol'],
        'direction': signal['direction'],
        'entry_price': signal['entry'],
        'sl': signal['sl'],
        'tp': signal['tp'],
        'exit_price': None,
        'exit_candle_time': None,
        'pnl_pct': None,
        'pnl_usd': None,
        'status': 'OPEN',
        'exit_reason': None
    }
    
    trades_df = pd.concat([trades_df, pd.DataFrame([new_trade])], ignore_index=True)
    save_trades(strategy_name, trades_df)
    
    # Update positions
    positions = load_positions(strategy_name)
    positions[signal['symbol']] = {
        'direction': signal['direction'],
        'entry': signal['entry'],
        'sl': signal['sl'],
        'tp': signal['tp'],
        'candle_time': signal['candle_time'],
        'risk_usd': risk_usd
    }
    save_positions(strategy_name, positions)


def log_exit(strategy_name: str, symbol: str, exit_info: dict, position: dict):
    """Log trade exit"""
    trades_df = load_trades(strategy_name)
    
    # Calculate P&L
    if position['direction'] == 'LONG':
        pnl_pct = (exit_info['exit_price'] - position['entry']) / position['entry'] * 100
    else:
        pnl_pct = (position['entry'] - exit_info['exit_price']) / position['entry'] * 100
    
    risk_usd = position.get('risk_usd', 500)
    # P&L based on risk: if SL = -1R, TP at 2:1 = +2R, etc.
    sl_distance = abs(position['entry'] - position['sl'])
    actual_distance = abs(exit_info['exit_price'] - position['entry'])
    r_multiple = actual_distance / sl_distance if sl_distance > 0 else 0
    
    if pnl_pct > 0:
        pnl_usd = risk_usd * r_multiple
    else:
        pnl_usd = -risk_usd * r_multiple
    
    # Update CSV
    mask = (trades_df['symbol'] == symbol) & (trades_df['status'] == 'OPEN')
    trades_df.loc[mask, 'exit_price'] = exit_info['exit_price']
    trades_df.loc[mask, 'exit_candle_time'] = exit_info['candle_time']
    trades_df.loc[mask, 'pnl_pct'] = round(pnl_pct, 2)
    trades_df.loc[mask, 'pnl_usd'] = round(pnl_usd, 2)
    trades_df.loc[mask, 'status'] = 'CLOSED'
    trades_df.loc[mask, 'exit_reason'] = exit_info['reason']
    
    save_trades(strategy_name, trades_df)
    
    # Remove from positions
    positions = load_positions(strategy_name)
    if symbol in positions:
        del positions[symbol]
    save_positions(strategy_name, positions)
    
    return pnl_pct, pnl_usd


# =============================================================================
# STRATEGY LOADER
# =============================================================================

def load_strategy(strategy_name: str):
    """Dynamically load a strategy module"""
    path = STRATEGIES_DIR / f"{strategy_name}.py"
    
    if not path.exists():
        raise FileNotFoundError(f"Strategy not found: {path}")
    
    spec = importlib.util.spec_from_file_location(strategy_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    # Validate interface
    required = ['STRATEGY_NAME', 'SYMBOLS', 'TIMEFRAME', 'check_signal', 'check_exit']
    for attr in required:
        if not hasattr(module, attr):
            raise AttributeError(f"Strategy {strategy_name} missing required: {attr}")
    
    return module


# =============================================================================
# MAIN ENGINE
# =============================================================================

def run_strategy(strategy_name: str, config: dict):
    """Run a single strategy"""
    print(f"\n{'='*50}")
    print(f"📊 {strategy_name}")
    print('='*50)
    
    try:
        strat = load_strategy(strategy_name)
    except Exception as e:
        print(f"❌ Failed to load: {e}")
        return
    
    risk_usd = config.get('risk_usd', 500)
    positions = load_positions(strategy_name)
    
    # 1. Check exits for open positions
    for symbol in list(positions.keys()):
        pos = positions[symbol]
        print(f"\n  Checking exit: {symbol} {pos['direction']}")
        
        try:
            df = fetch_ohlcv(symbol, strat.TIMEFRAME, 10)
            exit_info = strat.check_exit(pos, df)
            
            if exit_info:
                pnl_pct, pnl_usd = log_exit(strategy_name, symbol, exit_info, pos)
                emoji = '✅' if pnl_usd > 0 else '❌'
                print(f"    {emoji} EXIT: {exit_info['reason']} → ${pnl_usd:+.0f}")
                
                send_telegram(
                    f"📊 <b>[{strategy_name}] CLOSED</b>\n\n"
                    f"{emoji} {symbol} {pos['direction']}\n"
                    f"Exit: {exit_info['reason']} @ ${exit_info['exit_price']:,.2f}\n"
                    f"P&L: <b>${pnl_usd:+.0f}</b> ({pnl_pct:+.1f}%)"
                )
            else:
                current = get_current_price(symbol)
                if pos['direction'] == 'LONG':
                    unrealized = (current - pos['entry']) / pos['entry'] * 100
                else:
                    unrealized = (pos['entry'] - current) / pos['entry'] * 100
                print(f"    Still open: {unrealized:+.1f}%")
                
        except Exception as e:
            print(f"    ⚠️ Error: {e}")
    
    # Reload positions after exits
    positions = load_positions(strategy_name)
    
    # 2. Check new signals
    for symbol in strat.SYMBOLS:
        if symbol in positions:
            print(f"\n  {symbol}: Already in position")
            continue
        
        print(f"\n  Checking signal: {symbol}")
        
        try:
            df = fetch_ohlcv(symbol, strat.TIMEFRAME, 500)
            signal = strat.check_signal(symbol, df)
            
            if signal:
                log_entry(strategy_name, signal, risk_usd)
                emoji = '🟢' if signal['direction'] == 'LONG' else '🔴'
                print(f"    {emoji} SIGNAL: {signal['direction']} @ ${signal['entry']:,.2f}")
                
                sl_pct = abs(signal['entry'] - signal['sl']) / signal['entry'] * 100
                tp_pct = abs(signal['tp'] - signal['entry']) / signal['entry'] * 100
                
                send_telegram(
                    f"🚨 <b>[{strategy_name}] NEW SIGNAL</b>\n\n"
                    f"{emoji} <b>{signal['direction']} {symbol}</b>\n"
                    f"Entry: <code>${signal['entry']:,.2f}</code>\n"
                    f"SL: <code>${signal['sl']:,.2f}</code> ({sl_pct:.1f}%)\n"
                    f"TP: <code>${signal['tp']:,.2f}</code> ({tp_pct:.1f}%)\n"
                    f"Candle: {signal['candle_time'][:16]}"
                )
            else:
                print(f"    No signal")
                
        except Exception as e:
            print(f"    ⚠️ Error: {e}")


def main():
    now = datetime.now(timezone.utc)
    print("=" * 60)
    print("🤖 CRON TRADER")
    print("=" * 60)
    print(f"Time: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
    
    config = load_config()
    
    # Run each enabled strategy
    strategies = config.get('strategies', {})
    enabled = [name for name, cfg in strategies.items() if cfg.get('enabled', False)]
    
    if not enabled:
        print("⚠️ No strategies enabled in config.yaml")
        return
    
    print(f"Enabled strategies: {', '.join(enabled)}")
    
    for strategy_name in enabled:
        strat_config = strategies[strategy_name]
        run_strategy(strategy_name, strat_config)
    
    print("\n" + "=" * 60)
    print("✅ Done")
    print("=" * 60)


if __name__ == "__main__":
    main()
