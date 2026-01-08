import os
import time
import requests
from typing import Optional

class TelegramBot:
    def __init__(self):
        self.token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage" if self.token else ""
        self.enabled = bool(self.token and self.chat_id)

    def _send(self, message: str, retries: int = 3) -> bool:
        if not self.enabled:
            return False
        
        data = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }
        
        for i in range(retries):
            try:
                resp = requests.post(self.base_url, data=data, timeout=10)
                if resp.status_code == 200:
                    return True
                elif resp.status_code == 429: # Rate limit
                    wait_time = int(resp.headers.get('Retry-After', 5))
                    print(f"[Telegram] Rate limited. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"[Telegram] Failed ({resp.status_code}): {resp.text}")
            except Exception as e:
                print(f"[Telegram] Connection Error: {e}")
            
            if i < retries - 1:
                time.sleep(2)
        
        return False

    def send_signal(self, strategy: str, signal: dict):
        """Send formatted entry signal alert"""
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
        rr = tp_dist / sl_dist if sl_dist > 0 else 0
        
        emoji = "🟢" if direction == "LONG" else "🔴"
        tv_link = f"<a href='https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}'>{symbol}</a>"
        
        # Format prices dynamically (remove trailing zeros)
        def fmt(p): return f"{p:.8g}"
        
        msg = (
            f"{emoji} <b>SIGNAL: {strategy}</b>\n\n"
            f"<b>{direction}</b> {tv_link}\n"
            f"Entry: <code>{fmt(entry)}</code>\n"
            f"SL: <code>{fmt(sl)}</code> ({sl_pct:.2f}%)\n"
            f"TP: <code>{fmt(tp)}</code> ({tp_pct:.2f}%)\n"
            f"RR: 1:{rr:.1f}\n\n"
            f"<i>#{strategy} #{symbol.replace('USDT', '')}</i>"
        )
        self._send(msg)

    def send_exit(self, strategy: str, symbol: str, direction: str, exit_info: dict, pnl_usd: float, pnl_pct: float, entry_price: float):
        """Send formatted exit alert"""
        emoji = "✅" if pnl_usd > 0 else "❌"
        reason = exit_info['reason']
        exit_price = float(exit_info['exit_price'])
        duration = ""
        
        # Format prices
        def fmt(p): return f"{p:.8g}"
        
        msg = (
            f"{emoji} <b>CLOSED: {strategy}</b>\n\n"
            f"{symbol} {direction}\n"
            f"Result: <b>${pnl_usd:+.2f}</b> ({pnl_pct:+.2f}%)\n"
            f"Reason: {reason}\n\n"
            f"Entry: <code>{fmt(entry_price)}</code>\n"
            f"Exit: <code>{fmt(exit_price)}</code>"
        )
        self._send(msg)

    def send_summary(self, summary_text: str):
        """Send portfolio summary"""
        if not summary_text:
            return
            
        msg = (
            f"🤖 <b>CRON TRADER STATUS</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{summary_text}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        self._send(msg)

    def send_error(self, strategy: str, error: str):
        """Send error alert"""
        msg = (
            f"⚠️ <b>ERROR: {strategy}</b>\n\n"
            f"<code>{str(error)[:200]}</code>"
        )
        self._send(msg)
