# cron-trader

Strategy-agnostic paper trading engine powered by GitHub Actions.

**Cost: $0** - Runs on GitHub Actions free tier.

---

## 📊 Strategy Leaderboard

<!-- LEADERBOARD_START -->
| Strategy | Trades | Wins | Win% | P&L | Max DD | Status |
|----------|--------|------|------|-----|--------|--------|
| h4_breakout_ensemble | 6 | 2 | 33% | $-314 | 1.5% | 🔴 $-314 |
| weekly_breakout | 5 | 3 | 60% | $+1400 | 0.5% | 🟢 +$1400 |
| vol_squeeze_sol | 0 | 0 | -% | $+0 | 0.0% | 📊 1 open |
| btc_leadlag_eth | 0 | 0 | -% | $0 | 0.0% | 🟡 Waiting |

*Last updated: 2026-01-06 18:38 UTC*
<!-- LEADERBOARD_END -->

---

## How It Works

```
Every hour:
  1. Load enabled strategies
  2. Check open positions for SL/TP exits
  3. Check for new entry signals
  4. Log trades to CSV + signals to JSONL
  5. Update leaderboard
  6. Send Telegram alerts
```

## Structure

```
cron-trader/
├── strategies/           # Drop your strategies here
│   ├── h4_breakout_ensemble.py
│   ├── regime_rsi.py
│   └── weekly_breakout.py
├── logs/                 # Auto-generated trade logs
│   └── {strategy_name}/
│       ├── trades.csv
│       ├── positions.json
│       └── signals.jsonl    # Signal history
├── engine.py             # Core runner
├── config.yaml           # Enable/disable strategies
└── .github/workflows/
    └── run.yml           # Cron scheduler
```

## Adding a Strategy

1. Create `strategies/my_strategy.py`
2. Implement required interface:
   - `STRATEGY_NAME`
   - `SYMBOLS`
   - `TIMEFRAME`
   - `check_signal(symbol, df) -> dict | None`
   - `check_exit(position, df) -> dict | None`
3. Enable in `config.yaml`
4. Push. Done.

## Setup

1. Fork this repo (keep it private)
2. Add secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. Enable GitHub Actions
4. Receive signals on Telegram every hour

## License

MIT - Do whatever you want.
