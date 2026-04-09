# Political Trade Mirror Bot — Setup Guide

## Status: Ready to Run

The Python environment issue has been resolved. Three launch options are now available.

---

## Option 1: Complete Setup & Run (RECOMMENDED)

Double-click this file from Command Prompt or File Explorer:
```
setup_and_run.bat
```

This script will:
1. ✓ Detect your Python installation
2. ✓ Install all dependencies (alpaca-py, pandas, requests, schedule)
3. ✓ Start the bot daemon

**Expected output:**
```
[1/3] Detecting Python installation...
       ✓ Found: python
[2/3] Installing dependencies...
      Collecting alpaca-py...
[3/3] Launching bot...
      ═════════════════════════════════════════════════════════════
      Starting Political Trade Mirror Bot...
```

---

## Option 2: PowerShell Launch

Run from PowerShell:
```powershell
cd C:\Users\Tysun\OneDrive\Documents\ClaudeTrading
.\run_bot.ps1
```

This is equivalent to Option 1 but gives you more control.

---

## Option 3: Manual Launch (for debugging)

```bash
cd C:\Users\Tysun\OneDrive\Documents\ClaudeTrading
pip install -r requirements.txt
python main.py
```

---

## What the Bot Does

### Every 4 Hours:
1. Fetches recent political trades from Capitol Trades
2. Ranks politicians by trade performance (win rate × return)
3. Mirrors top 5 politicians' trades on Alpaca paper account
4. Applies strict risk controls:
   - 5% stop-loss on every position
   - 12% take-profit target
   - Max 5% of equity per trade
   - Max 10 concurrent positions

### Weekly (Sunday midnight):
- Rebuilds politician ranking from ~15 pages of history

### Continuous Logging:
- All trades logged to: `trades/trade_log.json`
- Political rankings to: `trades/politician_scores.json`
- Daily report to: `trades/daily_report.txt`

---

## Configuration

**File:** `config.py`

Critical settings:
- `ALPACA_API_KEY` — Paper trading account (credentials stored securely)
- `TOP_N_POLITICIANS` — Currently 5; tracks top 5 performers
- `MIRROR_STOP_LOSS_PCT` — 5% stop loss
- `MIRROR_TAKE_PROFIT_PCT` — 12% take profit

**No changes needed** — config is pre-tuned for optimal operation.

---

## Monitoring

Once running, check these files:
```
trades/daily_report.txt        ← Today's scan results
trades/trade_log.json          ← All executed trades
trades/politician_scores.json  ← Current politician rankings
```

---

## Troubleshooting

### "Python was not found"
→ Run `setup_and_run.bat` instead (handles all PATH issues)

### "ModuleNotFoundError: No module named 'alpaca'"
→ Run `setup_and_run.bat` (installs dependencies automatically)

### Bot exits immediately
→ Check `trades/daily_report.txt` for error messages

### No trades being executed
→ This is normal if:
- Capitol Trades hasn't updated yet
- Top politicians haven't made new trades
- Current positions exceed max limit (10)

---

## Next Steps

1. **Run the bot:** `setup_and_run.bat`
2. **Monitor:** Check `trades/daily_report.txt` after 5-10 minutes
3. **Track:** Watch Alpaca paper account for mirrored trades
4. **Analyze:** Review `trades/trade_log.json` for performance

---

## Architecture

```
main.py                    ← Entry point, scheduler
├── capitol_fetcher.py     ← Fetches Capitol Trades data
├── politician_ranker.py   ← Scores & ranks politicians
├── trade_mirror.py        ← Processes & executes trades
├── execution/
│   └── alpaca_broker.py   ← Alpaca API interface
└── utils/
    └── notifier.py        ← Logging & reporting
```

All imports are local and dependencies are in `requirements.txt`.
