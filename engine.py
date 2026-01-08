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
# SIGNAL HISTORY LOGGING
# =============================================================================

def log_signal_check(strategy_name: str, symbol: str, signal_data: dict):
    """Log every signal check to JSONL file"""
    log_dir = get_strategy_log_dir(strategy_name)
    signals_file = log_dir / "signals.jsonl"
    
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'symbol': symbol,
        **signal_data
    }
    
    with open(signals_file, 'a') as f:
        f.write(json.dumps(entry) + '\n')


# =============================================================================
# LEADERBOARD UPDATE
# =============================================================================

def update_leaderboard():
    """Update README.md with current stats"""
    import re
    readme_path = ROOT / "README.md"
    
    if not readme_path.exists():
        return
    
    # Gather stats for each strategy
    rows = []
    now = datetime.now(timezone.utc)
    
    config = load_config()
    strategies = config.get('strategies', {})
    
    for strategy_name, strat_config in strategies.items():
        if not strat_config.get('enabled', False):
            continue
        
        trades_df = load_trades(strategy_name)
        positions = load_positions(strategy_name)
        
        if trades_df.empty:
            rows.append(f"| {strategy_name} | 0 | 0 | -% | $0 | 0.0% | 🟡 Waiting |")
            continue
        
        closed = trades_df[trades_df['status'] == 'CLOSED']
        
        total_trades = len(closed)
        wins = len(closed[closed['pnl_usd'] > 0]) if not closed.empty else 0
        win_pct = f"{wins/total_trades*100:.0f}%" if total_trades > 0 else "-%"
        total_pnl = closed['pnl_usd'].sum() if not closed.empty else 0
        
        # Calculate max DD (simplified)
        if not closed.empty:
            cumsum = closed['pnl_usd'].cumsum()
            peak = cumsum.cummax()
            dd = ((peak - cumsum) / 100000 * 100).max()
        else:
            dd = 0
        
        # Status
        open_count = len(positions)
        if total_pnl > 0:
            status = f"🟢 +${total_pnl:.0f}"
        elif total_pnl < 0:
            status = f"🔴 ${total_pnl:.0f}"
        elif open_count > 0:
            status = f"📊 {open_count} open"
        else:
            status = "🟡 Waiting"
        
        rows.append(f"| {strategy_name} | {total_trades} | {wins} | {win_pct} | ${total_pnl:+.0f} | {dd:.1f}% | {status} |")
    
    # Build new table
    table_header = "| Strategy | Trades | Wins | Win% | P&L | Max DD | Status |\n|----------|--------|------|------|-----|--------|--------|"
    table_rows = "\n".join(rows) if rows else "| No strategies | - | - | - | - | - | - |"
    new_table = f"{table_header}\n{table_rows}\n\n*Last updated: {now.strftime('%Y-%m-%d %H:%M')} UTC*"
    
    # Read and update README
    content = readme_path.read_text()
    pattern = r'<!-- LEADERBOARD_START -->.*?<!-- LEADERBOARD_END -->'
    replacement = f"<!-- LEADERBOARD_START -->\n{new_table}\n<!-- LEADERBOARD_END -->"
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    readme_path.write_text(new_content)
    
    print("\n📊 Leaderboard updated")


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

def format_price(price: float, symbol: str = "") -> str:
    """Format price with appropriate precision"""
    if 'BTC' in symbol or price > 10000:
        return f"{price:.2f}"
    elif 'ETH' in symbol or price > 1000:
        return f"{price:.2f}" 
    elif price > 10:
        return f"{price:.4f}"
    else:
        return f"{price:.6f}"

def format_duration(start_time: str, end_time: str = None) -> str:
    """Format time duration in human readable format"""
    from datetime import datetime, timezone
    
    # Handle non-ISO datetime strings (like candle indices)
    if start_time.isdigit():
        return f"{start_time} bars" if not end_time else f"{end_time} bars"
    
    try:
        start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end = datetime.now(timezone.utc) if not end_time else datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        duration = end - start
        
        days = duration.days
        hours = duration.seconds // 3600
        minutes = (duration.seconds % 3600) // 60
        
        if days > 0:
            return f"{days}d{hours}h{minutes}m"
        elif hours > 0:
            return f"{hours}h{minutes}m"
        else:
            return f"{minutes}m"
    except:
        return "Unknown"

def create_progress_bar(current: float, target: float, length: int = 10) -> str:
    """Create a unicode progress bar"""
    if target <= 0:
        return "░" * length
    progress = min(current / target, 1.0)
    filled = int(progress * length)
    return "█" * filled + "░" * (length - filled)

def get_position_details(strategy_name: str, config: dict) -> str:
    """Get detailed position information with current prices"""
    positions = load_positions(strategy_name)
    if not positions:
        return ""
    
    details = []
    for symbol, pos in positions.items():
        try:
            current = get_current_price(symbol)
            entry = pos['entry']
            direction = pos['direction']
            sl = pos['sl']
            tp = pos['tp']
            
            # Calculate metrics
            if direction == 'LONG':
                pnl_pct = (current - entry) / entry * 100
                sl_dist_pct = (entry - sl) / entry * 100
                tp_dist_pct = (tp - current) / entry * 100
                sl_progress = (entry - current) / (entry - sl) if current < entry else 0
                tp_progress = (current - entry) / (tp - entry) if current > entry else 0
                emoji = "🟢" if pnl_pct >= 0 else "🔴"
            else:  # SHORT
                pnl_pct = (entry - current) / entry * 100
                sl_dist_pct = (sl - entry) / entry * 100
                tp_dist_pct = (current - tp) / entry * 100
                sl_progress = (current - entry) / (sl - entry) if current > entry else 0
                tp_progress = (entry - current) / (entry - tp) if current < entry else 0
                emoji = "🟢" if pnl_pct >= 0 else "🔴"
            
            # Risk multiple
            risk_usd = pos.get('risk_usd', 500)
            r_multiple = abs(pnl_pct / sl_dist_pct) if sl_dist_pct > 0 else 0
            pnl_usd = risk_usd * r_multiple if pnl_pct > 0 else -risk_usd * r_multiple
            
            # Progress bars
            show_progress = config.get('telegram', {}).get('show_progress_bars', True)
            sl_bar = f" {create_progress_bar(sl_progress * 100, 100, 8)} {sl_progress * 100:.0f}%" if show_progress and sl_progress > 0 else ""
            tp_bar = f" {create_progress_bar(tp_progress * 100, 100, 8)} {tp_progress * 100:.0f}%" if show_progress and tp_progress > 0 else ""
            
            # Format details
            detail = (
                f"├─ {symbol} {direction} {emoji} [{pnl_pct:+.1f}%]\n"
                f"│  Entry: ${format_price(entry, symbol)} → ${format_price(current, symbol)}\n"
                f"│  P&L: ${pnl_usd:+.0f} [+R:{r_multiple:.2f}]\n"
                f"│  SL: ${format_price(sl, symbol)} {'▼' if direction == 'LONG' else '▲'}{sl_dist_pct:.1f}%{sl_bar}\n"
                f"│  TP: ${format_price(tp, symbol)} {'▲' if direction == 'LONG' else '▼'}{tp_dist_pct:.1f}%{tp_bar}\n"
                f"│  Age: {format_duration(pos['candle_time'])}"
            )
            details.append(detail)
        except Exception as e:
            details.append(f"├─ {symbol} ❌ Error: {str(e)[:30]}")
    
    return "\n".join(details)

def get_activity_summary(strategy_name: str, recent_signals: dict) -> str:
    """Get recent activity summary for strategy"""
    log_dir = get_strategy_log_dir(strategy_name)
    signals_file = log_dir / "signals.jsonl"
    
    if not signals_file.exists():
        return ""
    
    # Read recent signals (last 20 lines)
    try:
        with open(signals_file, 'r') as f:
            lines = f.readlines()[-20:]
        
        recent_checks = []
        symbols_checked = set()
        signals_found = 0
        
        for line in reversed(lines):
            data = json.loads(line.strip())
            symbols_checked.add(data['symbol'])
            
            if data.get('result') == 'SIGNAL':
                signals_found += 1
                emoji = '🟢' if data['direction'] == 'LONG' else '🔴'
                recent_checks.append(f"{emoji} {data['symbol']} {data['direction']}")
        
        if recent_checks:
            return f"├─ Checked: {', '.join(symbols_checked)}\n├─ Recent: {', '.join(recent_checks[:3])}"
        else:
            return f"├─ Checked: {', '.join(symbols_checked)} | No recent signals"
    
    except:
        return ""

def get_rich_portfolio_summary(config: dict, activity: dict = None) -> str:
    """Get richly formatted portfolio summary"""
    summary_parts = []
    total_pnl = 0
    total_open = 0
    total_closed = 0
    total_wins = 0
    
    # Portfolio overview
    for strategy_dir in LOGS_DIR.iterdir():
        if not strategy_dir.is_dir():
            continue
        
        strategy_name = strategy_dir.name
        positions = load_positions(strategy_name)
        trades_df = load_trades(strategy_name)
        
        if not positions and trades_df.empty:
            continue
        
        closed = trades_df[trades_df['status'] == 'CLOSED'] if not trades_df.empty else pd.DataFrame()
        strategy_pnl = closed['pnl_usd'].sum() if not closed.empty else 0
        wins = len(closed[closed['pnl_usd'] > 0]) if not closed.empty else 0
        total_closed += len(closed)
        total_wins += wins
        total_pnl += strategy_pnl
        total_open += len(positions)
    
    win_rate = f"{total_wins/total_closed*100:.0f}%" if total_closed > 0 else "0%"
    
    # Header
    now = datetime.now(timezone.utc)
    header = (
        f"🤖 CRON TRADER STATUS ────── {now.strftime('%H:%M')} UTC\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    summary_parts.append(header)
    
    # Portfolio overview
    overview = (
        f"\n📊 PORTFOLIO OVERVIEW\n"
        f"├─ Total P&L: ${total_pnl:+.0f}\n"
        f"├─ Open: {total_open} positions | Closed: {total_closed} trades\n"
        f"├─ Win Rate: {win_rate}"
    )
    summary_parts.append(overview)
    
    # Active positions
    if total_open > 0 and config.get('telegram', {}).get('include_positions_detail', True):
        positions_detail = "\n🔥 ACTIVE POSITIONS"
        for strategy_dir in LOGS_DIR.iterdir():
            if not strategy_dir.is_dir():
                continue
            strategy_name = strategy_dir.name
            strategy_positions = get_position_details(strategy_name, config)
            if strategy_positions:
                positions_detail += f"\n{strategy_positions}"
        summary_parts.append(positions_detail)
        positions_detail = "└─"
        summary_parts.append(positions_detail)
    
    # Activity summary
    if activity and config.get('telegram', {}).get('include_activity_summary', True):
        activity_detail = f"\n⚡ RECENT ACTIVITY\n"
        if activity.get('signals', 0) > 0 or activity.get('exits', 0) > 0:
            activity_detail += f"├─ New signals: {activity['signals']}\n"
            activity_detail += f"├─ Exits: {activity['exits']}\n"
        else:
            activity_detail += f"├─ No new activity this run\n"
        summary_parts.append(activity_detail)
    
    return "\n".join(summary_parts)


# =============================================================================
# DATA FETCHING
# =============================================================================

def fetch_ohlcv(symbol: str, timeframe: str = '4h', limit: int = 500) -> pd.DataFrame:
    """Fetch OHLCV data from Binance (tries .com first, falls back to .us)"""
    
    # Try binance.com first, then binance.us (for GitHub Actions US servers)
    urls = [
        "https://api.binance.com/api/v3/klines",
        "https://api.binance.us/api/v3/klines",
    ]
    
    params = {'symbol': symbol, 'interval': timeframe, 'limit': limit}
    data = None
    
    for url in urls:
        try:
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    break
        except:
            continue
    
    if not data or not isinstance(data, list) or len(data) == 0:
        raise Exception(f"Failed to fetch data for {symbol} from all endpoints")
    
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
    urls = [
        f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
        f"https://api.binance.us/api/v3/ticker/price?symbol={symbol}",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return float(r.json()['price'])
        except:
            continue
    raise Exception(f"Failed to get price for {symbol}")


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
    
    if trades_df.empty:
        trades_df = pd.DataFrame([new_trade])
    else:
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
        return 0, 0  # Return signal_count, exit_count
    
    risk_usd = config.get('risk_usd', 500)
    positions = load_positions(strategy_name)
    signal_count = 0
    exit_count = 0
    
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
                exit_count += 1
                
                send_telegram(format_rich_exit(strategy_name, symbol, pos['direction'], exit_info, pnl_usd, pnl_pct, pos['entry']))
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
            log_signal_check(strategy_name, symbol, {'result': 'SKIP_IN_POSITION'})
            continue
        
        print(f"\n  Checking signal: {symbol}")
        
        try:
            df = fetch_ohlcv(symbol, strat.TIMEFRAME, 500)
            signal = strat.check_signal(symbol, df)
            
            if signal:
                log_entry(strategy_name, signal, risk_usd)
                log_signal_check(strategy_name, symbol, {
                    'result': 'SIGNAL',
                    'direction': signal['direction'],
                    'entry': signal['entry'],
                    'sl': signal['sl'],
                    'tp': signal['tp']
                })
                emoji = '🟢' if signal['direction'] == 'LONG' else '🔴'
                print(f"    {emoji} SIGNAL: {signal['direction']} @ ${signal['entry']:,.2f}")
                signal_count += 1
                
                sl_pct = abs(signal['entry'] - signal['sl']) / signal['entry'] * 100
                tp_pct = abs(signal['tp'] - signal['entry']) / signal['entry'] * 100
                
                send_telegram(format_rich_signal(strategy_name, signal))
            else:
                log_signal_check(strategy_name, symbol, {'result': 'NO_SIGNAL'})
                print(f"    No signal")
                
        except Exception as e:
            log_signal_check(strategy_name, symbol, {'result': 'ERROR', 'error': str(e)})
            print(f"    ⚠️ Error: {e}")
    
    return signal_count, exit_count


def get_portfolio_summary() -> str:
    """Get summary of all open positions and stats (legacy - kept for compatibility)"""
    summary_parts = []
    
    for strategy_dir in LOGS_DIR.iterdir():
        if not strategy_dir.is_dir():
            continue
        
        strategy_name = strategy_dir.name
        positions = load_positions(strategy_name)
        trades_df = load_trades(strategy_name)
        
        if not positions and trades_df.empty:
            continue
        
        # Count stats
        closed = trades_df[trades_df['status'] == 'CLOSED'] if not trades_df.empty else pd.DataFrame()
        total_pnl = closed['pnl_usd'].sum() if not closed.empty else 0
        wins = len(closed[closed['pnl_usd'] > 0]) if not closed.empty else 0
        total = len(closed) if not closed.empty else 0
        
        summary_parts.append(f"<b>{strategy_name}</b>")
        summary_parts.append(f"  Open: {len(positions)} | Closed: {total} | W: {wins} | P&L: ${total_pnl:+,.0f}")
    
    return "\n".join(summary_parts) if summary_parts else "No activity yet"

def should_send_notification(config: dict, activity: dict, now: datetime) -> bool:
    """Determine if telegram notification should be sent based on config and activity"""
    telegram_config = config.get('telegram', {})
    
    # Check quiet hours
    quiet_hours = telegram_config.get('quiet_hours', [])
    if now.hour in quiet_hours:
        return False
    
    notification_level = telegram_config.get('notification_level', 'smart')
    
    if notification_level == 'none':
        return False
    elif notification_level == 'all':
        return True
    elif notification_level == 'daily':
        # Only send at 9AM and 9PM UTC
        return now.hour in [9, 21]
    elif notification_level == 'positions':
        # Only send if there are open positions
        total_open = 0
        for strategy_dir in LOGS_DIR.iterdir():
            if strategy_dir.is_dir():
                positions = load_positions(strategy_dir.name)
                total_open += len(positions)
        return total_open > 0
    elif notification_level == 'smart':
        # Only send if there's actual activity
        return activity['signals'] > 0 or activity['exits'] > 0
    
    return True

def format_rich_signal(strategy_name: str, signal: dict) -> str:
    """Format signal with rich layout and TradingView link"""
    symbol = signal['symbol']
    direction = signal['direction']
    entry = float(signal['entry'])
    sl = float(signal['sl'])
    tp = float(signal['tp'])
    
    # Calculate percentages
    sl_dist = abs(entry - sl)
    tp_dist = abs(tp - entry)
    sl_pct = (sl_dist / entry) * 100
    tp_pct = (tp_dist / entry) * 100
    rr_ratio = tp_dist / sl_dist if sl_dist > 0 else 0
    
    emoji = "🟢" if direction == "LONG" else "🔴"
    tv_link = f'<a href="https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}">{symbol}</a>'
    
    # Box layout
    message = (
        f"┌─────────────────────────────────────┐\n"
        f"│  🚨 SIGNAL: {strategy_name}         │\n"
        f"├─────────────────────────────────────┤\n"
        f"│  {emoji} {direction} {tv_link}                 │\n"
        f"│  Entry: <code>${format_price(entry, symbol)}</code>        │\n"
        f"│  SL: <code>${format_price(sl, symbol)}</code> {'▼' if direction == 'LONG' else '▲'}{sl_pct:.1f}%           │\n"
        f"│  TP: <code>${format_price(tp, symbol)}</code> {'▲' if direction == 'LONG' else '▼'}{tp_pct:.1f}%           │\n"
        f"│  Risk: $500 | RR: 1:{rr_ratio:.1f}      │\n"
        f"│  Candle: {signal['candle_time'][:16].replace('T', ' ')}     │\n"
        f"└─────────────────────────────────────┘"
    )
    
    return message

def format_rich_exit(strategy_name: str, symbol: str, direction: str, exit_info: dict, 
                    pnl_usd: float, pnl_pct: float, entry_price: float) -> str:
    """Format exit with rich layout"""
    emoji = "✅" if pnl_usd > 0 else "❌"
    reason = exit_info['reason']
    exit_price = float(exit_info['exit_price'])
    
    # Duration calculation
    entry_time = exit_info.get('entry_time', '')
    if entry_time:
        duration = format_duration(entry_time, exit_info['candle_time'])
    else:
        duration = "Unknown"
    
    # Box layout
    message = (
        f"┌─────────────────────────────────────┐\n"
        f"│  📊 CLOSED: {strategy_name}           │\n"
        f"├─────────────────────────────────────┤\n"
        f"│  {emoji} {symbol} {direction}                  │\n"
        f"│  Exit: {reason}                       │\n"
        f"│  Result: <b>${pnl_usd:+.0f}</b> ({pnl_pct:+.1f}%)  │\n"
        f"│  Entry: ${format_price(entry_price, symbol)}            │\n"
        f"│  Exit: <code>${format_price(exit_price, symbol)}</code>              │\n"
        f"│  Duration: {duration}                  │\n"
        f"└─────────────────────────────────────┘"
    )
    
    return message


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
    
    # Track if any signals or exits for smart notifications
    activity = {'signals': 0, 'exits': 0}
    
    # Store signal counts per strategy
    strategy_activity = {}
    
    for strategy_name in enabled:
        strat_config = strategies[strategy_name]
        
        # Run strategy and get activity counts
        signal_count, exit_count = run_strategy(strategy_name, strat_config)
        
        strategy_activity[strategy_name] = {
            'signals': signal_count,
            'exits': exit_count
        }
        activity['signals'] += signal_count
        activity['exits'] += exit_count
    
    # Update leaderboard in README
    update_leaderboard()
    
    # Smart notification logic
    if should_send_notification(config, activity, now):
        # Use rich formatting for portfolio summary
        rich_summary = get_rich_portfolio_summary(config, activity)
        send_telegram(rich_summary)
        print("\n📱 Telegram notification sent")
    else:
        print("\n📱 Telegram notification skipped (no activity or quiet hours)")
    
    print("\n" + "=" * 60)
    print("✅ Done")
    print("=" * 60)


if __name__ == "__main__":
    main()
