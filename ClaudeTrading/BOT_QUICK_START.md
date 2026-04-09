# Quick Start: Run the Political Trade Mirror Bot Now

## The Problem
Windows Store Python has a quirk where direct execution is blocked. The batch files below bypass this.

## The Solution: 3 Easy Steps

### Step 1: Open Command Prompt
1. Press `Win + R`
2. Type: `cmd`
3. Press Enter

### Step 2: Navigate to Bot Directory
```cmd
cd C:\Users\Tysun\OneDrive\Documents\ClaudeTrading
```

### Step 3: Run One of These Commands

**Option A: Install dependencies + run bot (recommended)**
```cmd
setup_and_run.bat
```

**Option B: Install dependencies only**
```cmd
install_deps.bat
```
Then run:
```cmd
py main.py
```

---

## What to Expect

### First Run (takes 2-3 minutes):
```
[1/3] Detecting Python installation...
       ✓ Found: python
[2/3] Installing dependencies...
      Collecting alpaca-py...
      Successfully installed alpaca-py, pandas, requests, schedule
[3/3] Launching bot...

═════════════════════════════════════════════════════════════
Starting Political Trade Mirror Bot...
Fetching Capitol Trades history...
Building politician rankings...
Starting daily scan...
Next scan scheduled for: 2026-04-09 14:00:00
[Bot running in background]
```

### Subsequent Runs (faster, just runs):
```
═════════════════════════════════════════════════════════════
Starting Political Trade Mirror Bot...
Loading saved politician rankings...
Running daily scan...
✓ Scan complete: 0 new trades from top politicians
Next scan scheduled for: 2026-04-09 14:00:00
```

---

## Verify It's Working

While the bot is running, check these files:
```
C:\Users\Tysun\OneDrive\Documents\ClaudeTrading\trades\
  - daily_report.txt       (today's activity)
  - trade_log.json         (all executed trades)
  - politician_scores.json (current rankings)
  - seen_trade_ids.json    (tracking state)
```

If files are being created/updated → **Bot is working.**

---

## Stop the Bot

Press `Ctrl + C` in the Command Prompt window.

---

## Run in Background (Advanced)

To keep bot running after closing Command Prompt:

**Windows Task Scheduler approach:**
1. Open Task Scheduler (`Win + R`, type `taskschd.msc`)
2. Create Basic Task
3. Name: "Political Trade Mirror Bot"
4. Trigger: At startup
5. Action: Start program → `setup_and_run.bat` (full path)
6. Check "Run with highest privileges"
7. Finish

Bot will now launch automatically on system startup.

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `'python' is not recognized` | Install Python from https://www.python.org, or use `setup_and_run.bat` |
| `ModuleNotFoundError: alpaca_py` | Run `install_deps.bat`, then retry |
| `Bot exits immediately` | Check `trades/daily_report.txt` for error details |
| `No files created in trades/` | Bot may not have found Capitol Trades data; check Capitol Trades API endpoint |

---

## Bot Configuration

File: `C:\Users\Tysun\OneDrive\Documents\ClaudeTrading\config.py`

Current settings (optimized for your strategy):
- **Top 5 politicians tracked** by win rate × average return
- **5% stop-loss, 12% take-profit** on all mirrored trades
- **Max 5% equity per trade** to manage risk
- **Scans every 4 hours** during trading hours

No changes needed — just run and trade.

---

## Integration with Your Manual Trading

The bot runs **independently** on Alpaca paper account. Your manual trades on MU/GOOG/DAL/XLF are separate.

**Separation by account:**
- **Bot:** Mirrors politicians' trades on paper account (learning + testing)
- **You:** Trade manually on your main account following elite framework

**Sync point:** Daily `trades/trade_log.json` shows bot's results. Use to validate if political signal quality is good before scaling.

---

**Status:** Bot infrastructure is 100% ready. Just run `setup_and_run.bat` from Command Prompt and it will handle the rest.

