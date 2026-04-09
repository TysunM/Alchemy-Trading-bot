# Alchemical Trading Command Center

## Overview

Autonomous trading system with Claude as the "Brain" and Python backend as the "Body."
Full transparency via Reasoning Ledger. Production-ready with healthcheck endpoint and robust error handling.
Claude has 9 tools including portfolio rebalancing, sector rotation analysis, news sentiment, multi-timeframe confluence, and memory recall from past decisions.

## Architecture

### Python Trading Backend (`/trading/`)
- **`run.py`** — Launcher script: starts healthcheck server, then launches Streamlit
- **`app.py`** — Main Streamlit dashboard (port 5000), 9 tabs, auth gate, emergency stop
- **`healthcheck.py`** — HTTP healthcheck server on port 8099 (agent status, DB connectivity, heartbeat tracking) for Replit Deployments
- **`trading/services/broker.py`** — Alpaca Markets broker client (paper/live trading) & exports `get_active_annotations()` module-level function for annotation retrieval
- **`trading/services/claude_brain.py`** — Claude tool-use agent with 10 tools (execute_trade, get_market_analysis, log_alchemical_reasoning, rebalance_portfolio, analyze_sector_rotation, get_news_sentiment, get_multi_timeframe_analysis, recall_past_decisions, get_active_annotations)
- **`trading/services/agent_loop.py`** — Autonomous background worker with configurable intervals, thread-safe state
- **`trading/services/bot_manager.py`** — Multi-bot management (create/start/stop/delete bots with independent strategies/watchlists/risk params, persisted to SQLite)
- **`trading/services/agent_memory.py`** — Agent memory system (recall past decisions, trade outcomes, per-symbol track record, auto-derived lessons)
- **`trading/services/backtester.py`** — Strategy backtester (5 strategies, equity curve, Sharpe ratio, drawdown, win rate, profit factor, trade log)
- **`trading/services/notifications.py`** — NTFY push notification service for emergency alerts
- **`trading/services/capitol_fetcher.py`** — Capitol Trades scraper (RSC endpoint, no API key needed, public STOCK Act data)
- **`trading/services/politician_ranker.py`** — Politician performance ranking engine (win rate + avg return scoring, Alpaca historical data)
- **`trading/services/political_mirror.py`** — Political Trade Mirror service (auto-mirror top politicians' trades, SQLite persistence, idempotency safeguards)
- **`trading/services/indicators.py`** — Technical indicators (Bollinger Bands, Fibonacci, Triple EMA, RSI, MACD, ATR)
- **`trading/services/managed_agent.py`** — Managed Agent class with session lifecycle (start/heartbeat/terminate), runtime budget, 1M-token context ledger, tool call logging, session token auth
- **`trading/services/context_compiler.py`** — ContextCompiler service for snapshot checkpoints, daily summaries, context payload compilation, tool call logging
- **`trading/services/tool_server.py`** — HTTP tool server (port 8098) with API key + session token auth, endpoints for broker_trade, fetch_alchemical_context, heartbeat, terminate
- **`trading/services/risk_manager.py`** — ATR-based position sizing, kill switch, risk controls
- **`trading/ui/charts.py`** — Interactive Plotly charting module (yfinance data, indicator overlays, drawing tools)
- **`trading/utils/database.py`** — SQLite via SQLAlchemy (trade logs, reasoning ledger, system events, snapshot checkpoints, daily summaries, tool call logs, annotations, P&L stats)
- **`trading/utils/config.py`** — Environment variable handler

### Mobile App (`/artifacts/trading-command/`)
- Expo React Native mobile command center

### TypeScript Monorepo
- **`artifacts/api-server/`** — Express 5 API server (Node.js)
- **`lib/api-spec/`** — OpenAPI spec + Orval codegen
- **`lib/db/`** — PostgreSQL + Drizzle ORM

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM (Node), SQLite + SQLAlchemy (Python)
- **Python**: Streamlit, alpaca-trade-api, anthropic, pandas, numpy, plotly, yfinance
- **Broker**: Alpaca Markets (paper trading mode)
- **AI Brain**: Claude (Anthropic tool-use / function calling) with 10 tools

## Secrets Required

- `ANTHROPIC_API_KEY` — Anthropic API key for Claude
- `ALPACA_API_KEY` — Alpaca Markets API key
- `ALPACA_SECRET_KEY` — Alpaca Markets secret key
- `DASH_USER` — Dashboard login username (optional, skips auth if empty)
- `DASH_PASS` — Dashboard login password (optional, skips auth if empty)
- `NTFY_TOPIC` — NTFY.sh topic for push notifications (optional)
- `SESSION_SECRET` — Session secret for API server

## Claude's 10 Tools

1. **execute_trade** — Submit orders through Alpaca broker (thread-safe with global trade lock)
2. **get_market_analysis** — Single-timeframe indicator data for any symbol
3. **log_alchemical_reasoning** — Record thought process to the Reasoning Ledger
4. **rebalance_portfolio** — Analyze current positions vs target allocations, suggest rebalancing trades
5. **analyze_sector_rotation** — Compare 11 sector ETF performance to identify rotation patterns
6. **get_news_sentiment** — Fetch yfinance headlines, company info, analyst recommendations
7. **get_multi_timeframe_analysis** — Cross-reference 15m/1h/daily signals, returns confluence score
8. **recall_past_decisions** — Search past reasoning entries and trade outcomes, per-symbol track record with auto-derived lessons
9. **get_active_annotations** — Retrieve operator-drawn price levels and annotations from database

## Dashboard Tabs (9 tabs)

1. **Chart & Analysis** — Interactive Plotly candlestick chart with toggleable BB, Triple EMA, Fibonacci, RSI, MACD, Volume, Plotly drawing tools. One-click Claude analysis.
2. **ATR Monitor** — Live ATR readings across watchlist, calculated stop-loss levels, position sizing calculator, risk dollar readout.
3. **Bots** — Multi-bot management center. Create, configure, deploy, and monitor multiple autonomous trading bots — each with its own name, strategy preset (Alchemical Default, Momentum Rider, Mean Reversion, Scalper, Political Mirror, Custom), watchlist, risk parameters, cycle interval. Start/stop/delete bots independently. Per-bot cycle history and tool call inspector. Bots persisted to SQLite.
4. **Managed Agent** — Long-running autonomous trading session command deck with:
   - **Live Session Monitor** — Active session status, cycle count, tool calls, trade count, errors
   - **Token Usage Gauge** — Real-time 1M-token budget visualization with used/remaining/total
   - **The Pulse** — Heartbeat indicator with last-seen timestamp, latency, green/yellow/red status
   - **Kill Switch** — Graceful stop and force kill buttons for instant session termination
   - **Real-Time Tool Call Log** — Scrolling log of recent tool invocations with timestamps
   - **Session Launch** — Configure runtime window, cycle interval, and watchlist for new sessions
5. **Political Mirror** — Political trade mirroring service dashboard:
   - **Service Control** — Start/stop the mirror service, manual scan and ranking rebuild buttons
   - **Politician Rankings** — Ranked table of politicians by trade performance (score, win rate, avg return)
   - **Mirrored Trades** — Log of all executed mirror trades with politician, ticker, qty, price, SL/TP, status
   - **Configuration** — View current mirror settings (position size, SL/TP %, scan interval)
   - **Trading Framework** — Embedded reference to the Tysun Elite Trading Framework
6. **Positions & Orders** — Live positions, open orders, manual order entry form.
7. **Reasoning Ledger** — Enhanced: gold highlights for high-conviction (≥80%), red highlights for risk-off/sell, stats bar (total entries, high conviction count, risk-off count, avg confidence). Every Claude decision with full internal monologue.
8. **Performance Ledger** — Trade history with P&L tracking, win/loss stats, system event stream.
9. **Backtester** — Test 5 strategies (EMA Crossover, Mean Reversion, Momentum, Triple EMA Trend, BB Squeeze) against historical data. Configurable risk/ATR/position sizing. Shows equity curve, Sharpe ratio, max drawdown, profit factor, win rate, strategy vs buy & hold comparison, full trade log.

## Production Features

### Dashboard Authentication
- `DASH_USER` + `DASH_PASS` environment variables enable login gate
- If both are empty, dashboard is open (dev mode)
- Session-based auth via Streamlit session_state

### Emergency Stop Protocol
- Single red "EMERGENCY STOP" button replaces separate kill/liquidate buttons
- On press: activates kill switch, stops all bots, cancels all orders, liquidates all positions
- Sends NTFY push notification to operator's phone (requires `NTFY_TOPIC`)
- Resume button to re-enable trading

### Enhanced Healthcheck
- Port 8099 `/health` endpoint with JSON payload
- Reports: database connectivity, agent alive status, heartbeat age, uptime, cycle count, running bot count
- Degraded status if heartbeat stale >10 minutes
- Started by `run.py` launcher (independent of Streamlit sessions)

### Mobile-Responsive Layout
- CSS media queries for ≤768px screens
- Tab list wraps, metrics shrink, columns stack vertically
- Emergency stop button enlarged for touch targets

### Bot Manager Architecture (`trading/services/bot_manager.py`)
- **BotConfig** dataclass: name, strategy, custom_prompt, watchlist, interval, risk params — persisted to SQLite `bot_configs` table
- **BotState**: Thread-safe state per bot (cycles, trades, errors, history)
- **BotManager**: Process-global singleton that creates/updates/deletes/starts/stops bots. Each bot runs its own background thread with independent agent loop.
- **Strategy Presets**: alchemical_default, momentum_rider, mean_reversion, scalper, political_mirror, custom
- Emergency stop halts ALL bots atomically

### Political Trade Mirror (`trading/services/political_mirror.py`)
- **Capitol Trades Scraper** — Fetches STOCK Act disclosures via public RSC endpoint (no API key needed)
- **Politician Ranker** — Scores politicians by 30-day trade performance: `0.6 × win_rate + 0.4 × normalized_avg_return`
- **Trade Mirroring** — Auto-mirrors top 5 politicians' trades on Alpaca with bracket orders (5% SL, 12% TP)
- **Idempotency** — Every txId is locked in SQLite BEFORE order placement to prevent duplicates across crashes/restarts
- **SQLite Persistence** — `politician_scores`, `seen_political_trades`, `mirrored_trades` tables
- **PoliticalMirrorService** — Process-global singleton, background thread, 4-hour scan interval, weekly ranking rebuild
- **Safety** — Respects kill switch, max 10 open positions, skips stale disclosures (>7 days), validates tickers, checks market hours
- **Trading Framework** — Tysun Elite Trading Framework stored in `trading/data/trading_framework.md` as reference

### Agent Memory (`trading/services/agent_memory.py`)
- **recall_decisions()** — Query past reasoning entries filtered by symbol and time
- **recall_trades()** — Query trade history with P&L summary
- **get_symbol_track_record()** — Per-symbol win rate, total P&L, recent reasoning, auto-derived lesson
- **build_memory_context()** — Generates memory block injected into every agent cycle prompt

### Backtester (`trading/services/backtester.py`)
- 5 strategies: ema_crossover, mean_reversion, momentum, triple_ema_trend, bb_squeeze
- ATR-based position sizing identical to live system
- Metrics: total return, win rate, Sharpe ratio, max drawdown, profit factor, avg win/loss, avg hold duration
- Equity curve visualization with Plotly
- Strategy vs buy & hold comparison

### Managed Agent Architecture (`trading/services/managed_agent.py`)
- **ManagedAgent** class wraps AgentState + agent loop with session lifecycle management
- **Session lifecycle**: start_session (generates session_id + session_token), heartbeat, terminate (graceful/force)
- **Runtime budget**: Configurable window (1-12h), auto-terminates when expired
- **Token budget**: 1M-token limit with usage tracking, auto-terminates when exhausted
- **Tool schema**: `broker_trade(symbol, side, qty)` and `fetch_alchemical_context()` callback tools
- **ContextCompiler**: Periodic snapshot checkpoints (every 5 cycles), daily summary generation, context payload compilation
- **Tool server** (`trading/services/tool_server.py`): HTTP server on port 8098 with API key + session token auth
  - `POST /tool/session/start` — Start a managed agent session
  - `POST /tool/broker_trade` — Execute a trade via broker
  - `POST /tool/fetch_alchemical_context` — Get 24h context payload
  - `GET /tool/heartbeat` — Session heartbeat
  - `POST /tool/terminate` — Kill session
  - `GET /tool/session/info` — Session status
  - `GET /tool/health` — Tool server health
- **Security**: API key header (`X-API-Key`) + session token header (`X-Session-Token`) validated on every request
- **Database models**: SnapshotCheckpoint, DailySummary, ToolCallLog in SQLAlchemy

### Thread Safety
- **Trade execution lock** (`_trade_lock`) serializes all trade approvals across bots
- **Thread-local context** (`_thread_local`) isolates per-bot risk settings during execution
- **Fresh position/equity refresh** inside trade lock ensures no stale data
- **BotManager singleton** prevents duplicate bot instances across Streamlit sessions

## Safety & Ops

- **Emergency Stop**: Immediately cancels all orders, liquidates positions, stops all bots + agent loop, sends NTFY alert. Single button.
- **Error handling**: All API calls wrapped in try/except with alerts surfaced to the UI header.
- **Healthcheck**: HTTP endpoint at port 8099 (`/health`) — agent status, DB connectivity, heartbeat tracking. Reserved VM for Replit Deployments.
- **Tool Server**: HTTP endpoint at port 8098 (`/tool/*`) for managed agent callbacks, secured with API key + session token headers.
- **Risk Manager**: ATR-based position sizing, max risk %, max position size %, exposure limits.

## Workflows

- `Alchemical Trading Dashboard` — `python run.py` (launcher: healthcheck + Streamlit on port 5000)
- `artifacts/api-server: API Server` — Node.js Express API on port 8080
- `artifacts/trading-command: expo` — Expo mobile app
- `artifacts/mockup-sandbox: Component Preview Server` — Vite dev server for canvas previews
