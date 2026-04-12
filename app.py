import json
from datetime import datetime

import pandas as pd
import streamlit as st

from healthcheck import start_healthcheck, update_agent_heartbeat
from trading.services.agent_loop import (
    AgentState,
    run_single_cycle,
    start_agent_loop,
    stop_agent_loop,
)
from trading.services.backtester import BacktestConfig, run_backtest, STRATEGY_REGISTRY
from trading.services.bot_manager import BotConfig, BotManager, STRATEGY_PRESETS
from trading.services.broker import BrokerClient
from trading.services.claude_brain import analyze_symbol, get_token_usage, reset_token_usage, register_tool_handlers
from trading.services.indicators import detect_signal
from trading.services.notifications import send_emergency_alert
from trading.services.political_mirror import PoliticalMirrorService
from trading.services.managed_agent import (
    ManagedAgent,
    get_managed_agent,
    set_managed_agent,
    clear_managed_agent,
    TOKEN_BUDGET,
)
from trading.services.risk_manager import RiskManager
from trading.services.tool_server import start_tool_server, TOOL_SERVER_API_KEY
from trading.ui.charts import (
    PLOTLY_CONFIG,
    build_chart,
    compute_indicators,
    fetch_yfinance,
    get_indicator_summary,
)
from trading.utils.config import DEFAULT_SYMBOLS, DASH_USER, DASH_PASS
from trading.services.broker import get_active_annotations
from trading.utils.database import (
    delete_annotation,
    get_annotations_for_symbol,
    get_error_events,
    get_recent_events,
    get_recent_reasoning,
    get_recent_trades,
    get_trade_stats,
    init_db,
    log_event,
    save_annotation,
)

init_db()

import socket as _socket
_hc_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
_hc_alive = _hc_sock.connect_ex(("127.0.0.1", 8099)) == 0
_hc_sock.close()
if not _hc_alive:
    try:
        start_healthcheck(port=8099)
    except Exception:
        pass

if "tool_server_started" not in st.session_state:
    try:
        start_tool_server(port=8098)
        st.session_state.tool_server_started = True
    except Exception:
        st.session_state.tool_server_started = False

st.set_page_config(
    page_title="Alchemical Trading Command Center",
    page_icon="⚗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""<style>
    /* ── GLOBAL ── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .main, [data-testid="stAppViewContainer"] { background: #030712 !important; }
    .block-container { padding-top: 0.5rem !important; padding-bottom: 1rem; max-width: 100% !important; }
    [data-testid="stAppViewBlockContainer"] { background: #030712 !important; }

    /* ── SIDEBAR ── */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0a0f1e 0%, #060c19 100%) !important;
        border-right: 1px solid #1f2937 !important;
    }
    [data-testid="stSidebar"] label { color: #6b7280 !important; font-size: 0.78rem !important; }
    [data-testid="stSidebar"] .stMarkdown h3 {
        color: #3b82f6; font-size: 0.68rem !important; letter-spacing: 0.12em;
        text-transform: uppercase; font-weight: 700; margin: 0.5rem 0 0.3rem;
    }
    [data-testid="stSidebar"] hr { border-color: #1f2937 !important; margin: 0.5rem 0 !important; }
    [data-testid="stSidebar"] p { color: #9ca3af !important; font-size: 0.8rem !important; }

    /* ── SIDEBAR BRAND ── */
    .sidebar-brand {
        background: linear-gradient(135deg, #0d1b2e 0%, #091220 100%);
        border-bottom: 1px solid #1f2937;
        padding: 20px 16px 16px;
        margin: -1rem -1rem 1rem;
        text-align: center;
    }
    .sidebar-brand .brand-icon { font-size: 2.4rem; filter: drop-shadow(0 0 14px rgba(59,130,246,0.7)); }
    .sidebar-brand .brand-name {
        font-size: 1rem; font-weight: 800; letter-spacing: 0.1em;
        text-transform: uppercase; color: #3b82f6; margin-top: 6px;
    }
    .sidebar-brand .brand-sub { font-size: 0.62rem; color: #374151; letter-spacing: 0.1em; text-transform: uppercase; }

    /* ── STATUS BADGE ── */
    .status-online {
        display: inline-flex; align-items: center; gap: 6px;
        background: rgba(74,222,128,0.08); border: 1px solid rgba(74,222,128,0.25);
        border-radius: 20px; padding: 4px 14px;
        font-size: 0.7rem; font-weight: 700; color: #4ade80; letter-spacing: 0.06em;
    }
    .status-online::before { content: '●'; font-size: 0.45rem; animation: pulse-g 2s infinite; }
    .status-killed {
        display: inline-flex; align-items: center; gap: 6px;
        background: rgba(248,113,113,0.08); border: 1px solid rgba(248,113,113,0.3);
        border-radius: 20px; padding: 4px 14px;
        font-size: 0.7rem; font-weight: 700; color: #f87171; letter-spacing: 0.06em;
    }
    @keyframes pulse-g { 0%,100%{opacity:1} 50%{opacity:0.25} }

    /* ── EMERGENCY STOP ── */
    .emergency-btn button {
        background: linear-gradient(135deg,#7f1d1d,#dc2626) !important;
        color:#fff !important; font-size:0.88rem !important; font-weight:800 !important;
        letter-spacing:0.08em !important; text-transform:uppercase !important;
        padding:13px !important; border:1px solid #ef4444 !important; border-radius:8px !important;
        box-shadow:0 0 18px rgba(239,68,68,0.3) !important; width:100% !important;
    }
    .emergency-btn button:hover { box-shadow:0 0 28px rgba(239,68,68,0.55) !important; }

    /* ── SECTION HEADER ── */
    .section-header {
        font-size: 0.65rem; font-weight: 700; letter-spacing: 0.14em;
        text-transform: uppercase; color: #3b82f6;
        padding: 3px 0 6px; border-bottom: 1px solid rgba(59,130,246,0.15); margin-bottom: 10px;
    }

    /* ── TOP NAV BAR ── */
    .top-nav {
        background: rgba(17,24,39,0.85); backdrop-filter: blur(12px);
        border: 1px solid #1f2937; border-radius: 12px;
        padding: 0 20px; height: 56px; margin-bottom: 16px;
        display: flex; align-items: center; justify-content: space-between;
    }
    .top-nav .nav-brand {
        display: flex; align-items: center; gap: 8px;
        font-size: 1.1rem; font-weight: 800; color: #3b82f6; letter-spacing: 0.02em;
    }
    .top-nav .nav-right { display: flex; align-items: center; gap: 16px; }
    .nav-timestamp { font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; color: #4b5563; }
    .nav-badge {
        background: rgba(59,130,246,0.08); border: 1px solid rgba(59,130,246,0.2);
        border-radius: 6px; padding: 3px 10px;
        font-size: 0.65rem; font-weight: 600; color: #60a5fa; letter-spacing: 0.06em;
    }

    /* ── STAT CARDS ── */
    .stat-card {
        background: #111827; border: 1px solid #1f2937;
        border-radius: 12px; padding: 18px 20px;
        position: relative; overflow: hidden;
        transition: border-color 0.2s, box-shadow 0.2s;
    }
    .stat-card::before {
        content:''; position:absolute; top:0;left:0;right:0; height:2px;
        background: linear-gradient(90deg,#3b82f6,#8b5cf6); opacity:0.7;
    }
    .stat-card:hover { border-color: #374151; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }
    .stat-card .sc-label {
        font-size: 0.72rem; font-weight: 600; color: #6b7280;
        letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 10px;
        display: flex; align-items: center; justify-content: space-between;
    }
    .stat-card .sc-icon {
        width: 28px; height: 28px; background: rgba(59,130,246,0.1);
        border-radius: 6px; display: flex; align-items: center; justify-content: center;
        font-size: 0.85rem;
    }
    .stat-card .sc-value {
        font-size: 1.55rem; font-weight: 700; color: #f9fafb;
        font-family: 'JetBrains Mono', monospace; letter-spacing: -0.02em;
    }
    .stat-card .sc-change {
        font-size: 0.72rem; font-weight: 600; margin-top: 4px;
        display: flex; align-items: center; gap: 4px;
    }
    .sc-pos { color: #4ade80; } .sc-neg { color: #f87171; } .sc-neu { color: #6b7280; }

    /* ── METRIC CARDS (Streamlit) ── */
    [data-testid="stMetric"] {
        background: #111827; border: 1px solid #1f2937;
        border-radius: 10px; padding: 14px 18px;
        position: relative; overflow: hidden;
    }
    [data-testid="stMetric"]::before {
        content:''; position:absolute; top:0;left:0;right:0; height:2px;
        background: linear-gradient(90deg,#3b82f6,#8b5cf6); opacity:0.5;
    }
    [data-testid="stMetric"] label {
        font-size: 0.68rem !important; color: #6b7280 !important;
        letter-spacing: 0.1em !important; text-transform: uppercase !important; font-weight: 600 !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.3rem !important; font-weight: 700 !important;
        font-family: 'JetBrains Mono', monospace !important; color: #f9fafb !important;
    }
    [data-testid="stMetricDelta"] { font-size: 0.72rem !important; }

    /* ── TABS ── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px; background: #111827; border-radius: 10px;
        padding: 4px; border: 1px solid #1f2937; margin-bottom: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent; border: none !important;
        border-radius: 7px !important; padding: 7px 14px !important;
        font-size: 0.76rem !important; font-weight: 500 !important; color: #6b7280 !important;
        transition: all 0.15s !important;
    }
    .stTabs [data-baseweb="tab"]:hover { background: rgba(59,130,246,0.06) !important; color: #9ca3af !important; }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg,#0f2040,#102650) !important;
        color: #60a5fa !important; border: 1px solid rgba(59,130,246,0.3) !important;
        box-shadow: 0 0 10px rgba(59,130,246,0.15) !important; font-weight: 700 !important;
    }

    /* ── RIGHT PANEL ── */
    .panel-card {
        background: #111827; border: 1px solid #1f2937;
        border-radius: 12px; padding: 16px; margin-bottom: 12px;
    }
    .panel-title {
        font-size: 0.82rem; font-weight: 700; color: #e5e7eb;
        margin-bottom: 12px; display: flex; align-items: center; gap: 6px;
    }
    .position-row {
        display: flex; align-items: center; justify-content: space-between;
        padding: 10px 12px; border-radius: 8px;
        background: rgba(31,41,55,0.5); border: 1px solid rgba(55,65,81,0.5);
        margin-bottom: 6px; cursor: pointer; transition: background 0.15s;
    }
    .position-row:hover { background: #1f2937; }
    .pos-symbol { font-weight: 700; font-size: 0.9rem; color: #f3f4f6; }
    .pos-shares { font-size: 0.68rem; color: #6b7280; margin-top: 1px; }
    .pos-price { font-weight: 600; font-size: 0.88rem; color: #f3f4f6; font-family:'JetBrains Mono',monospace; text-align:right; }
    .pos-change-pos { font-size: 0.68rem; color: #4ade80; text-align:right; }
    .pos-change-neg { font-size: 0.68rem; color: #f87171; text-align:right; }

    /* ── NEWS / LEDGER ── */
    .news-item { border-left: 2px solid #3b82f6; padding-left: 10px; margin-bottom: 14px; }
    .news-time { font-size: 0.65rem; color: #60a5fa; font-family:'JetBrains Mono',monospace; margin-bottom: 2px; }
    .news-text { font-size: 0.78rem; color: #d1d5db; line-height: 1.4; }

    /* ── LEDGER CARDS ── */
    .ledger-gold {
        background: rgba(120,53,15,0.3) !important; border: 1px solid rgba(245,158,11,0.25) !important;
        border-left: 3px solid #f59e0b !important; border-radius: 8px; padding: 10px 13px; margin-bottom: 6px;
    }
    .ledger-red {
        background: rgba(127,29,29,0.3) !important; border: 1px solid rgba(248,113,113,0.25) !important;
        border-left: 3px solid #f87171 !important; border-radius: 8px; padding: 10px 13px; margin-bottom: 6px;
    }
    .ledger-default {
        background: rgba(17,24,39,0.8); border: 1px solid #1f2937;
        border-left: 3px solid #374151; border-radius: 8px; padding: 10px 13px; margin-bottom: 6px;
    }

    /* ── ALERT BANNER ── */
    .alert-banner {
        background: rgba(127,29,29,0.6); border: 1px solid rgba(248,113,113,0.4);
        border-left: 4px solid #f87171; border-radius: 8px;
        padding: 11px 18px; margin-bottom: 12px;
        color: #fca5a5; font-weight: 600; font-size: 0.82rem;
    }

    /* ── TOKEN GAUGE ── */
    .token-gauge-bg { background:#111827; border:1px solid #1f2937; border-radius:6px; height:24px; overflow:hidden; margin-bottom:4px; }
    .token-gauge-fill {
        height:100%; border-radius:6px; transition:width 0.4s ease;
        display:flex; align-items:center; justify-content:center;
        font-size:0.68rem; font-weight:700; color:#fff;
        font-family:'JetBrains Mono',monospace;
    }

    /* ── EXPANDERS ── */
    div[data-testid="stExpander"] { background:#111827; border:1px solid #1f2937 !important; border-radius:8px; }
    div[data-testid="stExpander"] summary { font-size:0.8rem !important; font-weight:600; color:#9ca3af; }

    /* ── INPUTS ── */
    [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input {
        background:#0d1117 !important; border-color:#374151 !important;
        color:#f3f4f6 !important; border-radius:7px !important; font-size:0.82rem !important;
    }
    [data-testid="stTextInput"] input:focus, [data-testid="stNumberInput"] input:focus { border-color:#3b82f6 !important; }
    [data-testid="stSelectbox"] div[data-baseweb="select"] {
        background:#0d1117 !important; border-color:#374151 !important; border-radius:7px !important;
    }

    /* ── BUTTONS ── */
    [data-testid="baseButton-primary"] {
        background: linear-gradient(135deg,#1d4ed8,#2563eb) !important;
        border:1px solid rgba(59,130,246,0.4) !important; border-radius:7px !important;
        font-weight:700 !important; letter-spacing:0.04em !important;
        box-shadow:0 0 12px rgba(59,130,246,0.2) !important;
    }
    [data-testid="baseButton-primary"]:hover { box-shadow:0 0 20px rgba(59,130,246,0.35) !important; }
    [data-testid="baseButton-secondary"] {
        background:#111827 !important; border:1px solid #374151 !important;
        border-radius:7px !important; color:#9ca3af !important; font-weight:500 !important;
    }

    /* ── BUY/SELL BUTTONS ── */
    .buy-btn button { background: linear-gradient(135deg,#14532d,#16a34a) !important; color:#fff !important; font-weight:800 !important; letter-spacing:0.08em !important; border:none !important; border-radius:8px !important; box-shadow:0 0 12px rgba(74,222,128,0.2) !important; }
    .sell-btn button { background: linear-gradient(135deg,#7f1d1d,#dc2626) !important; color:#fff !important; font-weight:800 !important; letter-spacing:0.08em !important; border:none !important; border-radius:8px !important; box-shadow:0 0 12px rgba(248,113,113,0.2) !important; }

    /* ── SCROLLBAR ── */
    ::-webkit-scrollbar { width:4px; height:4px; }
    ::-webkit-scrollbar-track { background:#030712; }
    ::-webkit-scrollbar-thumb { background:#374151; border-radius:3px; }
    ::-webkit-scrollbar-thumb:hover { background:#3b82f6; }

    /* ── LOGIN ── */
    .login-card {
        background: #111827; border: 1px solid #1f2937;
        border-radius: 16px; padding: 40px 36px;
        box-shadow: 0 0 50px rgba(59,130,246,0.08), 0 20px 40px rgba(0,0,0,0.6);
    }
    .login-logo { text-align:center; font-size:3.5rem; filter:drop-shadow(0 0 18px rgba(59,130,246,0.6)); margin-bottom:8px; }
    .login-title {
        text-align:center; font-size:1.05rem; font-weight:800;
        letter-spacing:0.12em; text-transform:uppercase;
        background:linear-gradient(135deg,#3b82f6,#8b5cf6);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:4px;
    }
    .login-sub { text-align:center; font-size:0.65rem; color:#374151; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:28px; }

    /* ── DATAFRAME ── */
    [data-testid="stDataFrame"] { border-radius:8px; overflow:hidden; }
    .dvn-scroller { background:#111827 !important; }

    /* ── DIVIDER ── */
    hr { border-color:#1f2937 !important; }

    /* ── RESPONSIVE ── */
    @media(max-width:768px){
        .block-container{padding-left:.5rem;padding-right:.5rem;}
        [data-testid="stMetricValue"]{font-size:1rem !important;}
        .stTabs [data-baseweb="tab"]{padding:5px 7px !important;font-size:0.65rem !important;}
        .stat-card .sc-value{font-size:1.1rem;}
    }
</style>""", unsafe_allow_html=True)


if DASH_USER or DASH_PASS:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        _, login_col, _ = st.columns([1, 1.4, 1])
        with login_col:
            st.markdown('<div class="login-card">', unsafe_allow_html=True)
            st.markdown('<div class="login-logo">⚗️</div>', unsafe_allow_html=True)
            st.markdown('<div class="login-title">Alchemical Trading</div>', unsafe_allow_html=True)
            st.markdown('<div class="login-sub">Command Center · Operator Access</div>', unsafe_allow_html=True)
            login_user = st.text_input("Username", key="login_user", placeholder="operator")
            login_pass = st.text_input("Password", type="password", key="login_pass", placeholder="••••••••")
            if st.button("ACCESS TERMINAL", use_container_width=True, type="primary"):
                if login_user == DASH_USER and login_pass == DASH_PASS:
                    st.session_state.authenticated = True
                    log_event("auth", "Operator logged in", "info")
                    st.rerun()
                else:
                    st.error("Access denied — invalid credentials")
            st.markdown('</div>', unsafe_allow_html=True)
        st.stop()

if "broker" not in st.session_state:
    try:
        st.session_state.broker = BrokerClient()
        st.session_state.broker_error = None
    except Exception as e:
        st.session_state.broker = None
        st.session_state.broker_error = str(e)

if "risk_manager" not in st.session_state:
    st.session_state.risk_manager = RiskManager()

if "support_levels" not in st.session_state:
    st.session_state.support_levels = {}
if "ceiling_levels" not in st.session_state:
    st.session_state.ceiling_levels = {}
if "last_analysis" not in st.session_state:
    st.session_state.last_analysis = {}
if "drawn_shapes" not in st.session_state:
    st.session_state.drawn_shapes = []
if "agent_state" not in st.session_state:
    st.session_state.agent_state = AgentState()
if "bot_manager" not in st.session_state:
    st.session_state.bot_manager = BotManager.get_instance()
if "political_mirror" not in st.session_state:
    st.session_state.political_mirror = PoliticalMirrorService.get_instance()

broker: BrokerClient = st.session_state.broker
risk: RiskManager = st.session_state.risk_manager
agent_state: AgentState = st.session_state.agent_state
bot_mgr: BotManager = st.session_state.bot_manager
mirror_svc: PoliticalMirrorService = st.session_state.political_mirror

agent_snap = agent_state.snapshot()
all_bot_snaps = bot_mgr.get_all_snapshots()
running_bots = sum(1 for b in all_bot_snaps if b["state"].get("running"))
update_agent_heartbeat(
    alive=agent_snap["running"] or running_bots > 0,
    cycle_count=agent_snap["cycle_count"],
    running_bots=running_bots,
)

with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <div class="brand-icon">⚗️</div>
        <div class="brand-name">Alchemy</div>
        <div class="brand-sub">Trading Command Center</div>
    </div>
    """, unsafe_allow_html=True)

    if risk.kill_switch_active:
        st.markdown('<div style="text-align:center;margin-bottom:10px"><span class="status-killed">⬛ EMERGENCY STOP ACTIVE</span></div>', unsafe_allow_html=True)
        if st.button("▶ RESUME TRADING", use_container_width=True, type="secondary"):
            risk.deactivate_kill_switch()
            log_event("system", "Trading resumed by operator", "info")
            st.rerun()
    else:
        st.markdown('<div style="text-align:center;margin-bottom:10px"><span class="status-online">SYSTEM ONLINE</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="emergency-btn">', unsafe_allow_html=True)
        if st.button("🚨 EMERGENCY STOP", use_container_width=True, type="primary"):
            log_event("system", "EMERGENCY STOP activated by operator", "warning")
            risk.activate_kill_switch()
            stop_agent_loop(agent_state)
            bot_mgr.stop_all()
            mirror_svc.stop()
            errors = []
            try:
                if broker:
                    broker.cancel_all_orders()
            except Exception as e:
                errors.append(f"Cancel orders: {e}")
            try:
                if broker:
                    broker.liquidate_all()
            except Exception as e:
                errors.append(f"Liquidate: {e}")
            for err in errors:
                log_event("system", f"Emergency stop error: {err}", "error")
            alert_msg = f"Emergency stop at {datetime.now().strftime('%H:%M:%S')}. All bots stopped, positions liquidated, orders cancelled."
            if errors:
                alert_msg += f" Errors: {'; '.join(errors)}"
            send_emergency_alert("EMERGENCY STOP", alert_msg)
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div class="section-header">Watchlist</div>', unsafe_allow_html=True)
    symbols_input = st.text_input("Symbols (comma-separated)", value=",".join(DEFAULT_SYMBOLS))
    symbols = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]
    selected_symbol = st.selectbox("Active Symbol", symbols)

    tf_options = {
        "1 Min": "1m", "5 Min": "5m", "15 Min": "15m", "30 Min": "30m",
        "1 Hour": "1h", "4 Hour": "4h", "1 Day": "1d", "1 Week": "1wk",
    }
    selected_tf_label = st.selectbox("Timeframe", list(tf_options.keys()), index=6)
    selected_tf = tf_options[selected_tf_label]
    bars_count = st.slider("Bars to Display", 60, 500, 200)

    st.markdown("---")
    st.markdown('<div class="section-header">Chart Indicators</div>', unsafe_allow_html=True)
    show_bb = st.toggle("Bollinger Bands (20, 2σ)", value=True)
    show_ema9 = st.toggle("EMA 9 — Short", value=True)
    show_ema50 = st.toggle("EMA 50 — Medium", value=True)
    show_ema200 = st.toggle("EMA 200 — Long", value=True)
    show_fib = st.toggle("Fibonacci Retracement", value=True)
    show_volume = st.toggle("Volume", value=True)
    show_rsi = st.toggle("RSI (14)", value=True)
    show_macd = st.toggle("MACD (12/26/9)", value=True)

    st.markdown("---")
    st.markdown('<div class="section-header">Manual Levels</div>', unsafe_allow_html=True)
    support = st.number_input(
        f"Support ({selected_symbol})",
        value=float(st.session_state.support_levels.get(selected_symbol) or 0.0),
        format="%.2f",
    )
    ceiling = st.number_input(
        f"Ceiling ({selected_symbol})",
        value=float(st.session_state.ceiling_levels.get(selected_symbol) or 0.0),
        format="%.2f",
    )
    st.session_state.support_levels[selected_symbol] = support if support > 0 else None
    st.session_state.ceiling_levels[selected_symbol] = ceiling if ceiling > 0 else None

    st.markdown("---")
    st.markdown('<div class="section-header">Risk Parameters</div>', unsafe_allow_html=True)
    new_risk_pct = st.slider("Max Risk per Trade (%)", 0.5, 5.0, float(risk.max_risk_pct * 100), 0.25)
    risk.max_risk_pct = new_risk_pct / 100
    new_atr_mult = st.slider("ATR Stop Multiplier", 0.5, 4.0, float(risk.atr_multiplier), 0.25)
    risk.atr_multiplier = new_atr_mult
    new_max_pos = st.slider("Max Position Size (%)", 2.0, 25.0, float(risk.max_position_pct * 100), 1.0)
    risk.max_position_pct = new_max_pos / 100

    st.markdown("---")
    auto_trade = st.toggle("Auto-Execute Trades", value=False)
    min_confidence = st.slider("Min Confidence to Trade", 0.5, 0.95, 0.75, 0.05)

account_data = None
if broker:
    try:
        account_data = broker.get_account_balance()
    except Exception as e:
        log_event("broker", f"Account balance error: {e}", "error")

try:
    market_open = broker.is_market_open() if broker else False
except Exception:
    market_open = False

agent_snap = agent_state.snapshot()
system_status = "⛔ KILLED" if risk.kill_switch_active else ("🤖 Agent ON" if agent_snap["running"] else "● Online")

st.markdown(f"""
<div class="top-nav">
    <div class="nav-brand">⚗️ &nbsp;AlchemyTrade</div>
    <div class="nav-right">
        <span class="nav-timestamp">{datetime.now().strftime('%Y-%m-%d  %H:%M:%S UTC')}</span>
        <span class="nav-badge">{'🔴 Market Closed' if not market_open else '🟢 Market Open'}</span>
        <span class="nav-badge">Ray Dalio Protocol v2</span>
    </div>
</div>
""", unsafe_allow_html=True)

recent_errors = get_error_events(5)
broker_errors = [e for e in recent_errors if e.event_type == "broker" and e.severity == "error"]
if broker_errors:
    latest = broker_errors[0]
    st.markdown(f'<div class="alert-banner">⚠️ BROKER ALERT — {latest.message} ({latest.timestamp.strftime("%H:%M:%S")})</div>', unsafe_allow_html=True)
if st.session_state.get("broker_error"):
    st.markdown(f'<div class="alert-banner">⚠️ BROKER CONNECTION FAILED — {st.session_state.broker_error}</div>', unsafe_allow_html=True)

# ── STAT CARDS ROW ──
if account_data:
    pv = account_data['portfolio_value']
    cash = account_data['cash']
    bp = account_data['buying_power']
    eq_change_pct = "+2.4%"  # live P&L would need prior-day snapshot
    s1, s2, s3, s4, s5 = st.columns(5)
    with s1:
        st.markdown(f"""<div class="stat-card">
            <div class="sc-label">Portfolio Value <span class="sc-icon">💼</span></div>
            <div class="sc-value">${pv:,.2f}</div>
            <div class="sc-change sc-pos">▲ Live</div>
        </div>""", unsafe_allow_html=True)
    with s2:
        st.markdown(f"""<div class="stat-card">
            <div class="sc-label">Cash <span class="sc-icon">💵</span></div>
            <div class="sc-value">${cash:,.2f}</div>
            <div class="sc-change sc-neu">Available</div>
        </div>""", unsafe_allow_html=True)
    with s3:
        st.markdown(f"""<div class="stat-card">
            <div class="sc-label">Buying Power <span class="sc-icon">⚡</span></div>
            <div class="sc-value">${bp:,.2f}</div>
            <div class="sc-change sc-neu">Deployable</div>
        </div>""", unsafe_allow_html=True)
    with s4:
        mkt_color = "sc-pos" if market_open else "sc-neg"
        mkt_label = "Open" if market_open else "Closed"
        st.markdown(f"""<div class="stat-card">
            <div class="sc-label">Market <span class="sc-icon">📈</span></div>
            <div class="sc-value" style="font-size:1.15rem">{mkt_label}</div>
            <div class="sc-change {mkt_color}">{'● NYSE / NASDAQ' if market_open else '○ After Hours'}</div>
        </div>""", unsafe_allow_html=True)
    with s5:
        sys_color = "sc-neg" if risk.kill_switch_active else ("sc-pos" if agent_snap["running"] else "sc-pos")
        st.markdown(f"""<div class="stat-card">
            <div class="sc-label">System <span class="sc-icon">🤖</span></div>
            <div class="sc-value" style="font-size:1.1rem">{system_status}</div>
            <div class="sc-change {sys_color}">Bots: {running_bots} · Cycles: {agent_snap['cycle_count']}</div>
        </div>""", unsafe_allow_html=True)
else:
    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown("""<div class="stat-card"><div class="sc-label">System <span class="sc-icon">⚗️</span></div>
            <div class="sc-value" style="font-size:1.1rem">Ready</div>
            <div class="sc-change sc-neu">Awaiting broker</div></div>""", unsafe_allow_html=True)
    with s2:
        st.markdown("""<div class="stat-card"><div class="sc-label">Data <span class="sc-icon">📡</span></div>
            <div class="sc-value" style="font-size:1.1rem">yfinance</div>
            <div class="sc-change sc-pos">● Connected</div></div>""", unsafe_allow_html=True)
    with s3:
        st.markdown(f"""<div class="stat-card"><div class="sc-label">Bots <span class="sc-icon">🤖</span></div>
            <div class="sc-value" style="font-size:1.1rem">{running_bots} Running</div>
            <div class="sc-change sc-neu">Agent: {'ON' if agent_snap['running'] else 'OFF'}</div></div>""", unsafe_allow_html=True)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
tab1, tab2, tab3, tab8, tab9, tab4, tab5, tab6, tab7 = st.tabs([
    "📊 Chart & Analysis",
    "📈 ATR Monitor",
    "🤖 Bots",
    "🧬 Managed Agent",
    "🏛️ Political Mirror",
    "📋 Positions & Orders",
    "🧠 Reasoning Ledger",
    "📜 Performance Ledger",
    "🔬 Backtester",
])

with tab1:
    chart_col, right_col = st.columns([3, 1])

    # ── DATA FETCH ──
    try:
        with st.spinner(f"Loading {selected_symbol} · {selected_tf_label}…"):
            df_raw = fetch_yfinance(selected_symbol, timeframe=selected_tf, bars=bars_count)
    except Exception as e:
        log_event("data", f"yfinance error for {selected_symbol}: {e}", "error")
        df_raw = None

    if df_raw is None or df_raw.empty:
        if broker:
            try:
                with st.spinner("Trying broker data…"):
                    alpaca_tf_map = {"1d": "1Day", "1h": "1Hour", "15m": "15Min"}
                    alpaca_tf = alpaca_tf_map.get(selected_tf, "1Day")
                    raw_bars = broker.get_bars(selected_symbol, timeframe=alpaca_tf, limit=bars_count)
                    if raw_bars is not None and not raw_bars.empty:
                        raw_bars.columns = [c.lower() for c in raw_bars.columns]
                        df_raw = raw_bars[["open", "high", "low", "close", "volume"]].dropna()
            except Exception as e:
                log_event("data", f"Alpaca fallback error for {selected_symbol}: {e}", "error")

    saved_anns = get_active_annotations(symbol=selected_symbol)
    indicator_df = None
    summary = None

    if df_raw is not None and len(df_raw) >= 20:
        try:
            fig, indicator_df = build_chart(
                df=df_raw, symbol=selected_symbol,
                show_bb=show_bb, show_ema9=show_ema9, show_ema50=show_ema50,
                show_ema200=show_ema200, show_fib=show_fib, show_volume=show_volume,
                show_rsi=show_rsi, show_macd=show_macd,
                support_line=st.session_state.support_levels.get(selected_symbol),
                ceiling_line=st.session_state.ceiling_levels.get(selected_symbol),
                saved_annotations=saved_anns,
            )
            summary = get_indicator_summary(indicator_df)
        except Exception as e:
            log_event("chart", f"Chart build error: {e}", "error")
            st.error(f"Chart error: {e}")
            fig = None
    else:
        st.warning(f"No data for **{selected_symbol}** at {selected_tf_label}.")
        fig = None

    # ── LEFT: CHART + INDICATORS + ANALYSIS ──
    with chart_col:
        if fig:
            st.plotly_chart(fig, config=PLOTLY_CONFIG, use_container_width=True)

        if summary:
            ind_c1, ind_c2, ind_c3, ind_c4 = st.columns(4)
            with ind_c1:
                change = summary["change"]
                delta_str = f"{'+' if change >= 0 else ''}{change:.2f} ({summary['change_pct']:+.2f}%)"
                st.metric(selected_symbol, f"${summary['price']:.2f}", delta=delta_str, delta_color="normal")
            with ind_c2:
                rsi = summary["rsi"]
                st.metric("RSI (14)", f"{rsi:.1f}",
                    delta="Overbought" if rsi > 70 else ("Oversold" if rsi < 30 else "Neutral"),
                    delta_color="off")
            with ind_c3:
                if summary["ema_bullish_stack"]:
                    st.metric("EMA Stack", "Bullish", delta="9 › 50 › 200", delta_color="normal")
                elif summary["ema_bearish_stack"]:
                    st.metric("EMA Stack", "Bearish", delta="9 ‹ 50 ‹ 200", delta_color="inverse")
                else:
                    st.metric("EMA Stack", "Mixed", delta_color="off")
            with ind_c4:
                st.metric("MACD", "Bull" if summary["macd_hist"] > 0 else "Bear",
                    delta=f"ATR {summary['atr']:.4f}", delta_color="off")

        run_analysis = st.button("🧠 Run Claude Analysis", use_container_width=True, type="primary", disabled=(summary is None))
        quick_signal = st.button("⚡ Quick Signal Check", use_container_width=True, disabled=(summary is None))

        if saved_anns:
            with st.expander(f"📌 Saved Annotations ({len(saved_anns)})", expanded=False):
                for ann in saved_anns:
                    ac1, ac2 = st.columns([4, 1])
                    with ac1:
                        st.caption(f"{ann['annotation_type'].upper()} — ${ann['price_level']:.2f}")
                    with ac2:
                        if st.button("✕", key=f"del_ann_{ann['id']}"):
                            delete_annotation(ann["id"])
                            st.rerun()

    # ── RIGHT PANEL ──
    with right_col:
        # -- Positions --
        positions_display = []
        if broker:
            try:
                positions_display = broker.get_current_positions()
            except Exception:
                pass

        st.markdown('<div class="panel-card">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">📊 Your Positions</div>', unsafe_allow_html=True)
        if positions_display:
            for pos in positions_display[:6]:
                sym = pos.get("symbol", "—")
                qty = pos.get("qty", 0)
                mkt_val = pos.get("market_value", 0)
                unreal = pos.get("unrealized_pl", 0)
                unreal_pct = pos.get("unrealized_plpc", 0)
                is_pos = unreal >= 0
                change_class = "pos-change-pos" if is_pos else "pos-change-neg"
                arrow = "▲" if is_pos else "▼"
                st.markdown(f"""
                <div class="position-row">
                    <div><div class="pos-symbol">{sym}</div><div class="pos-shares">{qty} shares</div></div>
                    <div><div class="pos-price">${float(mkt_val):,.2f}</div>
                    <div class="{change_class}">{arrow} {float(unreal_pct)*100:.2f}%</div></div>
                </div>""", unsafe_allow_html=True)
        else:
            st.markdown('<p style="color:#6b7280;font-size:0.78rem;text-align:center;padding:12px 0">No open positions</p>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # -- Order Entry --
        st.markdown('<div class="panel-card">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">📝 Order Entry</div>', unsafe_allow_html=True)
        ann_price_input = st.number_input(
            "Price Level", min_value=0.0,
            value=float(summary["price"]) if summary else 0.0,
            step=0.01, format="%.2f", key="ann_price_input",
        )
        ann_type_input = st.selectbox("Type", ["support", "ceiling", "trendline", "custom"], key="ann_type_input")
        save_ann_clicked = st.button("💾 Save Annotation", use_container_width=True)
        if save_ann_clicked and ann_price_input > 0:
            save_annotation(symbol=selected_symbol, price_level=ann_price_input, annotation_type=ann_type_input)
            st.success(f"Saved {ann_type_input} @ ${ann_price_input:.2f}")
            st.rerun()

        if auto_trade and summary:
            buy_col, sell_col = st.columns(2)
            with buy_col:
                st.markdown('<div class="buy-btn">', unsafe_allow_html=True)
                if st.button("BUY", use_container_width=True, key="manual_buy"):
                    if broker and not risk.kill_switch_active:
                        qty = max(1, risk.calculate_shares(
                            account_data["portfolio_value"] if account_data else 100_000,
                            summary["atr"], min_confidence))
                        order = broker.submit_order(selected_symbol, qty, "buy", notes="Manual buy")
                        if order:
                            st.success(f"BUY {qty}×{selected_symbol}")
                st.markdown('</div>', unsafe_allow_html=True)
            with sell_col:
                st.markdown('<div class="sell-btn">', unsafe_allow_html=True)
                if st.button("SELL", use_container_width=True, key="manual_sell"):
                    if broker and not risk.kill_switch_active:
                        qty = max(1, risk.calculate_shares(
                            account_data["portfolio_value"] if account_data else 100_000,
                            summary["atr"], min_confidence))
                        order = broker.submit_order(selected_symbol, qty, "sell", notes="Manual sell")
                        if order:
                            st.success(f"SELL {qty}×{selected_symbol}")
                st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # -- Claude Ledger --
        st.markdown('<div class="panel-card" style="padding-bottom:0">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">🧠 Reasoning Ledger</div>', unsafe_allow_html=True)
        ledger_entries = get_recent_reasoning(limit=20)
        if ledger_entries:
            ledger_container = st.container(height=380)
            with ledger_container:
                for entry in ledger_entries:
                    action_icon = {"buy": "🟢", "sell": "🔴", "hold": "🟡", "analyzing": "🔬", "monitoring": "👁️"}.get(entry.action, "⚪")
                    conf_str = f"{entry.confidence:.0%}" if entry.confidence is not None else "—"
                    ts_str = entry.timestamp.strftime("%m/%d %H:%M") if entry.timestamp else ""
                    st.markdown(
                        f'<div class="news-item">'
                        f'<div class="news-time">{ts_str} · {action_icon} {entry.action.upper()} · {conf_str}</div>'
                        f'<div class="news-text"><b>{entry.symbol}</b> — {entry.reasoning[:140]}{"…" if len(entry.reasoning) > 140 else ""}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
        else:
            st.markdown('<p style="color:#6b7280;font-size:0.78rem;padding:8px 0">No entries yet. Run Claude Analysis.</p>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    if quick_signal and indicator_df is not None:
        try:
            compat_df = indicator_df.rename(columns={
                "ema9": "ema_fast", "ema50": "ema_mid", "ema200": "ema_slow",
                "bb_mid": "bb_middle",
            })
            signal, score, sig_indicators = detect_signal(compat_df)
            sig_color = {"buy": "🟢", "sell": "🔴", "hold": "🟡"}.get(signal, "⚪")
            st.info(f"Quick Signal: {sig_color} **{(signal or 'hold').upper()}** · Score: `{score:+d}`")
        except Exception as e:
            st.error(f"Signal detection error: {e}")

    if run_analysis and indicator_df is not None:
        equity = account_data["portfolio_value"] if account_data else 100_000.0
        try:
            positions = broker.get_current_positions() if broker else []
        except Exception:
            positions = []

        indicators_for_claude = {
            "price": summary["price"] if summary else 0,
            "atr": summary["atr"] if summary else 0,
            "rsi": summary["rsi"] if summary else 0,
            "ema_fast": summary["ema9"] if summary else 0,
            "ema_mid": summary["ema50"] if summary else 0,
            "ema_slow": summary["ema200"] if summary else 0,
            "bb_upper": summary["bb_upper"] if summary else 0,
            "bb_middle": summary["bb_mid"] if summary else 0,
            "bb_lower": summary["bb_lower"] if summary else 0,
            "bb_pct_b": summary["bb_pct_b"] if summary else 0,
            "macd": summary["macd"] if summary else 0,
            "macd_signal": summary["macd_signal"] if summary else 0,
            "signals": [],
            "score": 0,
            "vwap": summary["vwap"] if summary else 0,
            "ema_stack": "bullish" if (summary and summary["ema_bullish_stack"]) else ("bearish" if (summary and summary["ema_bearish_stack"]) else "mixed"),
            "bb_squeeze": summary["bb_squeeze"] if summary else False,
            "above_200": summary["above_200"] if summary else False,
        }

        try:
            with st.spinner("🧠 Claude is performing Alchemical analysis…"):
                result = analyze_symbol(
                    symbol=selected_symbol,
                    indicators=indicators_for_claude,
                    account_equity=equity,
                    current_positions=positions,
                    support=st.session_state.support_levels.get(selected_symbol),
                    ceiling=st.session_state.ceiling_levels.get(selected_symbol),
                )
                st.session_state.last_analysis[selected_symbol] = result
        except Exception as e:
            log_event("claude", f"Analysis error: {e}", "error")
            st.error(f"Claude analysis failed: {e}")
            result = None

        if result:
            action = result.get("action", "hold")
            confidence = result.get("confidence", 0)
            action_color = {"buy": "🟢", "sell": "🔴", "hold": "🟡"}.get(action, "⚪")

            st.markdown("---")
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a:
                st.metric("Decision", f"{action_color} {action.upper()}")
            with col_b:
                st.metric("Confidence", f"{confidence:.0%}")
            with col_c:
                entry = result.get("entry_price")
                st.metric("Entry", f"${entry:.2f}" if entry else "—")
            with col_d:
                stop = result.get("stop_loss")
                target = result.get("target_price")
                st.metric("Stop / Target", f"${stop:.2f} / ${target:.2f}" if (stop and target) else "—")

            st.markdown(f"**Signal:** {result.get('signal_type', 'N/A')}  ·  **Horizon:** {result.get('time_horizon', 'N/A')}")

            rcol1, rcol2 = st.columns([2, 1])
            with rcol1:
                with st.expander("📖 Claude's Full Reasoning", expanded=True):
                    st.write(result.get("reasoning", "No reasoning provided."))
            with rcol2:
                if result.get("risks"):
                    with st.expander("⚠️ Risks", expanded=True):
                        for r in result["risks"]:
                            st.caption(f"• {r}")

            if auto_trade and action in ["buy", "sell"] and confidence >= min_confidence and not risk.kill_switch_active and broker and account_data:
                atr_val = summary["atr"] if summary else 0.01
                qty = risk.calculate_shares(account_data["portfolio_value"], atr_val, confidence)
                price_val = summary["price"] if summary else 0
                approved, reason = risk.approve_trade(action, selected_symbol, qty, price_val, account_data["portfolio_value"], positions)
                if approved:
                    try:
                        order = broker.submit_order(selected_symbol, qty, action, notes=f"Claude: {result.get('signal_type','signal')}")
                        if order:
                            st.success(f"✅ Order submitted: {action.upper()} {qty} shares of {selected_symbol}")
                        else:
                            st.error("Order submission failed — check System Events")
                    except Exception as e:
                        log_event("broker", f"Auto-trade error: {e}", "error")
                        st.error(f"Order error: {e}")
                else:
                    st.warning(f"Trade blocked by risk manager: {reason}")
            elif auto_trade and action in ["buy", "sell"] and confidence < min_confidence:
                st.info(f"Confidence {confidence:.0%} below {min_confidence:.0%} threshold")

with tab2:
    st.subheader("📈 ATR Monitor & Risk Calculator")
    st.caption("Live Average True Range readings with calculated stop-loss levels for your watchlist.")

    atr_data = []
    for sym in symbols[:8]:
        try:
            sym_df = fetch_yfinance(sym, "1d", 60)
            if sym_df is not None and len(sym_df) >= 20:
                sym_df = compute_indicators(sym_df)
                sym_summary = get_indicator_summary(sym_df)
                price = sym_summary["price"]
                atr = sym_summary["atr"]
                stop_buy = risk.calculate_stop_loss(price, atr, "buy")
                stop_sell = risk.calculate_stop_loss(price, atr, "sell")
                equity = account_data["portfolio_value"] if account_data else 100_000.0
                pos_size = risk.calculate_shares(equity, atr, 0.80)
                risk_dollars = atr * risk.atr_multiplier * pos_size
                atr_pct = (atr / price * 100) if price > 0 else 0

                atr_data.append({
                    "Symbol": sym,
                    "Price": f"${price:.2f}",
                    "ATR (14)": f"{atr:.4f}",
                    "ATR %": f"{atr_pct:.2f}%",
                    "Buy Stop": f"${stop_buy:.2f}",
                    "Sell Stop": f"${stop_sell:.2f}",
                    "Pos Size": f"{pos_size} shares",
                    "Risk $": f"${risk_dollars:.2f}",
                    "RSI": f"{sym_summary['rsi']:.1f}",
                    "BB %B": f"{sym_summary['bb_pct_b']:.3f}",
                })
        except Exception:
            atr_data.append({"Symbol": sym, "Price": "—", "ATR (14)": "—", "ATR %": "—", "Buy Stop": "—", "Sell Stop": "—", "Pos Size": "—", "Risk $": "—", "RSI": "—", "BB %B": "—"})

    if atr_data:
        st.dataframe(pd.DataFrame(atr_data), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Risk Calculator")
    calc_cols = st.columns(3)
    with calc_cols[0]:
        calc_equity = st.number_input("Account Equity ($)", value=float(account_data["portfolio_value"] if account_data else 100000), format="%.2f")
    with calc_cols[1]:
        calc_atr = st.number_input("ATR Value", value=float(summary["atr"]) if summary else 1.0, format="%.4f")
    with calc_cols[2]:
        calc_conf = st.slider("Confidence", 0.5, 1.0, 0.80, 0.05, key="calc_conf")

    calc_shares = risk.calculate_shares(calc_equity, calc_atr, calc_conf)
    calc_risk = calc_atr * risk.atr_multiplier * calc_shares
    calc_risk_pct = (calc_risk / calc_equity * 100) if calc_equity > 0 else 0

    res_cols = st.columns(4)
    with res_cols[0]:
        st.metric("Position Size", f"{calc_shares} shares")
    with res_cols[1]:
        st.metric("Dollar Risk", f"${calc_risk:.2f}")
    with res_cols[2]:
        st.metric("Risk % of Equity", f"{calc_risk_pct:.2f}%")
    with res_cols[3]:
        st.metric("Stop Distance", f"${calc_atr * risk.atr_multiplier:.4f}")

with tab3:
    st.subheader("🤖 Bot Command Center")
    st.caption("Create, configure, and deploy multiple autonomous trading bots — each with its own strategy, watchlist, and risk settings.")

    bot_tab_create, bot_tab_manage = st.tabs(["➕ Create Bot", "📋 Manage Bots"])

    with bot_tab_create:
        st.markdown("### New Bot Configuration")
        create_cols = st.columns([1, 1])

        with create_cols[0]:
            bot_name = st.text_input("Bot Name", value="", placeholder="e.g. Momentum Alpha")
            strategy_key = st.selectbox(
                "Strategy Preset",
                list(STRATEGY_PRESETS.keys()),
                format_func=lambda k: STRATEGY_PRESETS[k]["label"],
            )
            st.caption(STRATEGY_PRESETS[strategy_key]["description"])

            custom_prompt = ""
            if strategy_key == "custom":
                custom_prompt = st.text_area(
                    "Custom Strategy Instructions",
                    placeholder="Describe your trading strategy for Claude to follow…",
                    height=120,
                )

            bot_watchlist_str = st.text_input(
                "Watchlist (comma-separated)",
                value="SPY, QQQ, AAPL",
                placeholder="SPY, QQQ, AAPL, TSLA",
            )

        with create_cols[1]:
            bot_interval = st.selectbox("Cycle Interval", [
                ("1 minute", 60),
                ("3 minutes", 180),
                ("5 minutes", 300),
                ("10 minutes", 600),
                ("15 minutes", 900),
                ("30 minutes", 1800),
            ], format_func=lambda x: x[0], index=2, key="bot_interval")

            bot_risk_pct = st.slider("Risk per Trade (%)", 0.5, 5.0, 2.0, 0.5, key="bot_risk_pct") / 100.0
            bot_atr_mult = st.slider("ATR Stop Multiplier", 0.5, 4.0, 1.5, 0.5, key="bot_atr_mult")
            bot_max_pos = st.slider("Max Position Size (%)", 5, 25, 10, 5, key="bot_max_pos") / 100.0

        if st.button("🚀 Create Bot", use_container_width=True, type="primary"):
            if not bot_name.strip():
                st.error("Bot name is required")
            else:
                wl = [s.strip().upper() for s in bot_watchlist_str.split(",") if s.strip()]
                if not wl:
                    st.error("Add at least one symbol to the watchlist")
                else:
                    new_config = BotConfig(
                        name=bot_name.strip(),
                        strategy=strategy_key,
                        custom_prompt=custom_prompt,
                        watchlist=wl,
                        interval_seconds=bot_interval[1],
                        risk_pct=bot_risk_pct,
                        atr_multiplier=bot_atr_mult,
                        max_position_pct=bot_max_pos,
                    )
                    bot_mgr.create_bot(new_config)
                    st.success(f"Bot '{bot_name}' created successfully!")
                    st.rerun()

    with bot_tab_manage:
        all_bots = bot_mgr.get_all_snapshots()

        if not all_bots:
            st.info("No bots created yet. Go to the 'Create Bot' tab to add your first bot.")
        else:
            running_count = sum(1 for b in all_bots if b["state"].get("running"))
            total_cycles = sum(b["state"].get("cycle_count", 0) for b in all_bots)
            total_bot_trades = sum(b["state"].get("total_trades", 0) for b in all_bots)

            overview_cols = st.columns(4)
            with overview_cols[0]:
                st.metric("Total Bots", len(all_bots))
            with overview_cols[1]:
                st.metric("Running", f"{running_count}")
            with overview_cols[2]:
                st.metric("Total Cycles", total_cycles)
            with overview_cols[3]:
                st.metric("Total Bot Trades", total_bot_trades)

            st.markdown("---")

            for bot_info in all_bots:
                cfg = bot_info["config"]
                state = bot_info["state"]
                bot_id = cfg["bot_id"]
                is_running = state.get("running", False)

                status_text = state.get("status", "idle")
                status_icon = {
                    "running cycle": "🔄", "idle": "💤", "stopped": "⏹",
                    "starting": "🚀", "stopping": "⏳", "error": "❌",
                }.get(status_text.split(" ")[0], "🟡")

                header_color = "🟢" if is_running else "⚪"
                with st.expander(f"{header_color} **{cfg['name']}** — {STRATEGY_PRESETS.get(cfg['strategy'], {}).get('label', cfg['strategy'])} | {status_icon} {status_text}", expanded=is_running):
                    info_cols = st.columns([2, 1, 1])
                    with info_cols[0]:
                        st.caption(f"ID: `{bot_id}` | Created: {cfg.get('created_at', '—')}")
                        st.caption(f"Watchlist: {', '.join(cfg['watchlist'])}")
                        st.caption(f"Risk: {cfg['risk_pct']*100:.1f}% | ATR×{cfg['atr_multiplier']} | Max pos: {cfg['max_position_pct']*100:.0f}%")
                        st.caption(f"Interval: {cfg['interval_seconds']}s")
                    with info_cols[1]:
                        st.metric("Cycles", state.get("cycle_count", 0), label_visibility="visible")
                        st.metric("Trades", state.get("total_trades", 0))
                    with info_cols[2]:
                        st.metric("Tools", state.get("total_tool_calls", 0))
                        st.metric("Errors", state.get("errors", 0))

                    ctrl_cols = st.columns(4)
                    with ctrl_cols[0]:
                        if not is_running:
                            if st.button("▶ Start", key=f"start_{bot_id}", use_container_width=True, type="primary"):
                                if risk.kill_switch_active:
                                    st.error("Kill switch active")
                                else:
                                    started = bot_mgr.start_bot(bot_id, broker)
                                    if started:
                                        st.success(f"Bot '{cfg['name']}' started")
                                        st.rerun()
                                    else:
                                        st.warning("Already running")
                        else:
                            if st.button("⏹ Stop", key=f"stop_{bot_id}", use_container_width=True):
                                bot_mgr.stop_bot(bot_id)
                                st.rerun()

                    with ctrl_cols[1]:
                        if st.button("🔄 Single Cycle", key=f"cycle_{bot_id}", use_container_width=True):
                            if risk.kill_switch_active:
                                st.error("Kill switch active")
                            else:
                                with st.spinner(f"Running cycle for {cfg['name']}…"):
                                    bot_mgr.run_single_cycle(bot_id, broker)
                                st.rerun()

                    with ctrl_cols[2]:
                        pass

                    with ctrl_cols[3]:
                        if st.button("🗑 Delete", key=f"del_{bot_id}", use_container_width=True):
                            bot_mgr.delete_bot(bot_id)
                            st.success(f"Bot '{cfg['name']}' deleted")
                            st.rerun()

                    if state.get("last_cycle_time"):
                        st.caption(f"Last cycle: {state['last_cycle_time']}")

                    if state.get("history"):
                        st.markdown("**Cycle History:**")
                        hist_data = []
                        for h in reversed(state["history"]):
                            hist_data.append({
                                "Time": h.get("time", "—"),
                                "Duration": h.get("duration", "—"),
                                "Rounds": h.get("rounds", 0),
                                "Tools": h.get("tools", 0),
                                "Trades": h.get("trades", 0),
                                "OK": "✅" if h.get("success") else "❌",
                            })
                        st.dataframe(pd.DataFrame(hist_data), use_container_width=True, hide_index=True)

                    last = state.get("last_cycle_result")
                    if last:
                        if last.get("tool_calls"):
                            with st.expander("Tool Calls", expanded=False):
                                for tc in last["tool_calls"]:
                                    tool_icon = {"execute_trade": "💰", "get_market_analysis": "📊", "log_alchemical_reasoning": "🧠"}.get(tc["tool"], "🔧")
                                    sym = tc["input"].get("symbol", "")
                                    st.caption(f"{tool_icon} `{tc['tool']}` — {sym}")
                                    st.json(tc["input"])

                        if last.get("final_text"):
                            with st.expander("Claude's Summary", expanded=False):
                                st.write(last["final_text"][:2000])

            st.markdown("---")
            if running_count > 0:
                if st.button("⏹ Stop All Bots", use_container_width=True, type="secondary"):
                    bot_mgr.stop_all()
                    st.success("All bots stopped")
                    st.rerun()

with tab8:
    import time as _time

    st.subheader("🧬 Managed Agent Command Deck")
    st.caption("Long-running autonomous trading sessions with 1M-token context ledger, heartbeat monitoring, and full observability.")

    managed = get_managed_agent()

    ma_ctrl_col, ma_monitor_col = st.columns([1, 2])

    with ma_ctrl_col:
        st.markdown("### Session Control")

        if managed and managed.session_active:
            info = managed.get_session_info()

            st.success(f"Session Active: `{info['session_id']}`")
            st.caption(f"Started: {info.get('start_time', '—')}")

            runtime_pct = info.get("runtime_pct", 0)
            st.progress(min(runtime_pct / 100, 1.0), text=f"Runtime: {runtime_pct:.1f}%")

            elapsed_s = info.get("runtime_elapsed_s", 0)
            elapsed_h = elapsed_s / 3600
            budget_h = managed.runtime_hours
            st.caption(f"Elapsed: {elapsed_h:.2f}h / {budget_h:.1f}h budget")

            st.markdown("---")
            st.markdown("### 🫀 The Pulse")
            hb_age = info.get("heartbeat_age_s", 999)
            hb_latency = info.get("heartbeat_latency_ms", 0)
            last_hb = info.get("last_heartbeat", "—")

            if hb_age < 60:
                pulse_color = "🟢"
                pulse_status = "Connected"
            elif hb_age < 180:
                pulse_color = "🟡"
                pulse_status = "Delayed"
            else:
                pulse_color = "🔴"
                pulse_status = "Lost"

            pulse_cols = st.columns(3)
            with pulse_cols[0]:
                st.metric("Status", f"{pulse_color} {pulse_status}")
            with pulse_cols[1]:
                st.metric("Latency", f"{hb_latency:.0f}ms")
            with pulse_cols[2]:
                st.metric("Last Beat", f"{hb_age:.0f}s ago")

            st.caption(f"Last heartbeat: {last_hb}")

            st.markdown("---")
            st.markdown("### Kill Switch")

            term_cols = st.columns(2)
            with term_cols[0]:
                if st.button("⏹ Graceful Stop", key="ma_graceful", use_container_width=True):
                    import urllib.request
                    try:
                        req = urllib.request.Request(
                            "http://localhost:8098/tool/terminate",
                            data=json.dumps({"force": False}).encode(),
                            headers={
                                "Content-Type": "application/json",
                                "X-API-Key": TOOL_SERVER_API_KEY,
                                "X-Session-Token": managed.session_token or "",
                            },
                            method="POST",
                        )
                        resp = urllib.request.urlopen(req, timeout=5)
                        result = json.loads(resp.read().decode())
                    except Exception:
                        result = managed.terminate(force=False)
                    clear_managed_agent()
                    st.success(f"Session terminated gracefully. Cycles: {result.get('cycles_completed', 0)}")
                    st.rerun()
            with term_cols[1]:
                if st.button("🔴 FORCE KILL", key="ma_force_kill", use_container_width=True, type="primary"):
                    import urllib.request
                    try:
                        req = urllib.request.Request(
                            "http://localhost:8098/tool/terminate",
                            data=json.dumps({"force": True}).encode(),
                            headers={
                                "Content-Type": "application/json",
                                "X-API-Key": TOOL_SERVER_API_KEY,
                                "X-Session-Token": managed.session_token or "",
                            },
                            method="POST",
                        )
                        resp = urllib.request.urlopen(req, timeout=5)
                        result = json.loads(resp.read().decode())
                    except Exception:
                        result = managed.terminate(force=True)
                    clear_managed_agent()
                    st.error(f"Session FORCE KILLED. Trading halted.")
                    st.rerun()

        else:
            st.info("No active managed agent session.")
            st.markdown("---")
            st.markdown("### Launch New Session")

            ma_runtime = st.selectbox("Runtime Window", [
                ("1 hour", 1.0),
                ("2 hours", 2.0),
                ("4 hours", 4.0),
                ("8 hours", 8.0),
                ("12 hours", 12.0),
            ], format_func=lambda x: x[0], index=2, key="ma_runtime")

            ma_interval = st.selectbox("Cycle Interval", [
                ("3 minutes", 180),
                ("5 minutes", 300),
                ("10 minutes", 600),
                ("15 minutes", 900),
            ], format_func=lambda x: x[0], index=1, key="ma_interval")

            ma_watchlist = st.text_input(
                "Watchlist", value=",".join(symbols), key="ma_watchlist"
            )

            if st.button("🚀 Launch Managed Agent", use_container_width=True, type="primary"):
                if risk.kill_switch_active:
                    st.error("Kill switch active — cannot launch")
                else:
                    wl = [s.strip().upper() for s in ma_watchlist.split(",") if s.strip()]
                    new_agent = ManagedAgent(
                        broker=broker,
                        risk=risk,
                        watchlist=wl,
                        runtime_hours=ma_runtime[1],
                        cycle_interval=ma_interval[1],
                    )
                    set_managed_agent(new_agent)
                    result = new_agent.start_session(api_key=TOOL_SERVER_API_KEY)
                    if "error" not in result:
                        st.success(f"Managed Agent launched! Session: `{result['session_id']}`")
                        st.rerun()
                    else:
                        st.error(f"Launch failed: {result['error']}")

    with ma_monitor_col:
        if managed and managed.session_active:
            info = managed.get_session_info()

            st.markdown("### Live Session Monitor")

            mon_cols = st.columns(4)
            with mon_cols[0]:
                st.metric("Cycles", info.get("cycle_count", 0))
            with mon_cols[1]:
                st.metric("Tool Calls", info.get("total_tool_calls", 0))
            with mon_cols[2]:
                st.metric("Trades", info.get("total_trades", 0))
            with mon_cols[3]:
                st.metric("Errors", info.get("errors", 0))

            st.markdown("---")

            token_usage = info.get("token_usage", 0)
            token_pct = info.get("token_pct", 0)
            token_remaining = TOKEN_BUDGET - token_usage

            st.markdown("### Token Usage Gauge")
            st.progress(min(token_pct / 100, 1.0), text=f"Token Budget: {token_pct:.2f}%")
            tok_cols = st.columns(3)
            with tok_cols[0]:
                st.metric("Used", f"{token_usage:,}")
            with tok_cols[1]:
                st.metric("Remaining", f"{token_remaining:,}")
            with tok_cols[2]:
                st.metric("Budget", f"{TOKEN_BUDGET:,}")

            st.markdown("---")
            st.markdown(f"**Status:** `{info.get('status', 'unknown')}`")

            st.markdown("---")
            st.markdown("### Real-Time Tool Call Log")

            recent_calls = info.get("recent_tool_calls", [])
            if recent_calls:
                tool_log_data = []
                for tc in reversed(recent_calls[-15:]):
                    tool_icon = {
                        "execute_trade": "💰",
                        "broker_trade": "💰",
                        "get_market_analysis": "📊",
                        "log_alchemical_reasoning": "🧠",
                        "fetch_alchemical_context": "📜",
                    }.get(tc.get("tool", ""), "🔧")
                    tc_input = tc.get("input", {})
                    if isinstance(tc_input, dict):
                        input_display = tc_input.get("symbol", str(tc_input))[:40]
                    else:
                        input_display = str(tc_input)[:40]
                    tool_log_data.append({
                        "Time": tc.get("timestamp", "—")[-8:] if tc.get("timestamp") else "—",
                        "Tool": f"{tool_icon} {tc.get('tool', '—')}",
                        "Input": input_display,
                        "ms": tc.get("duration_ms", 0),
                        "OK": "✅" if tc.get("success") else "❌",
                    })
                st.dataframe(pd.DataFrame(tool_log_data), use_container_width=True, hide_index=True)
            else:
                st.info("No tool calls yet in this session.")

            snap = managed.state.snapshot()
            if snap.get("history"):
                st.markdown("### Cycle History")
                hist_data = []
                for h in reversed(snap["history"]):
                    hist_data.append({
                        "Time": h.get("time", "—"),
                        "Duration": h.get("duration", "—"),
                        "Rounds": h.get("rounds", 0),
                        "Tools": h.get("tools", 0),
                        "Trades": h.get("trades", 0),
                        "OK": "✅" if h.get("success") else "❌",
                    })
                st.dataframe(pd.DataFrame(hist_data), use_container_width=True, hide_index=True)

        else:
            st.markdown("### Live Session Monitor")
            st.info("Launch a managed agent session to see live monitoring data.")

            st.markdown("---")
            st.markdown("### Architecture Overview")
            st.markdown("""
**Managed Agent** wraps the existing Claude agent loop with:
- **Session Lifecycle** — Start, heartbeat, graceful shutdown, force terminate
- **1M-Token Context Ledger** — Periodic checkpoints and daily summaries keep the agent primed with compressed historical context
- **Runtime Budget** — Configurable session windows with automatic shutdown
- **Tool Server** — Secured callback endpoints for `broker_trade` and `fetch_alchemical_context`
- **The Pulse** — Real-time heartbeat monitoring with latency tracking
- **Kill Switch** — Instant session termination with optional trading halt
            """)

with tab9:
    st.subheader("🏛️ Political Trade Mirror")
    st.caption("Mirror trades from top-performing US politicians (STOCK Act disclosures via Capitol Trades).")

    mirror_snap = mirror_svc.state.snapshot()

    pm_ctrl, pm_stats = st.columns([1, 2])

    with pm_ctrl:
        st.markdown("### Service Control")

        if mirror_snap["running"]:
            st.success(f"Mirror Active — {mirror_snap['status']}")
            if st.button("⏹ Stop Mirror", use_container_width=True, key="pm_stop"):
                mirror_svc.stop()
                st.rerun()
        else:
            st.info("Mirror service is stopped.")
            if st.button("▶ Start Mirror", use_container_width=True, type="primary", key="pm_start"):
                if risk and risk.kill_switch_active:
                    st.error("Cannot start — kill switch is active.")
                elif broker:
                    mirror_svc.start(broker, risk)
                    st.rerun()
                else:
                    st.error("Broker not connected.")

        st.markdown("---")
        st.markdown("### Manual Actions")
        if st.button("🔄 Run Scan Now", use_container_width=True, key="pm_scan"):
            if broker:
                mirror_svc.broker = broker
                mirror_svc.risk = risk
                with st.spinner("Scanning Capitol Trades..."):
                    result = mirror_svc.run_scan()
                if "error" in result:
                    st.error(result["error"])
                else:
                    st.success(f"Scan complete: {result.get('new_trades', 0)} new, {result.get('executed', 0)} mirrored")
            else:
                st.error("Broker not connected.")

        if st.button("📊 Rebuild Rankings", use_container_width=True, key="pm_rank"):
            with st.spinner("Fetching history and ranking politicians..."):
                scores = mirror_svc.build_rankings()
            if scores:
                st.success(f"Ranked {len(scores)} politicians.")
            else:
                st.error("Failed to build rankings.")

    with pm_stats:
        pm_stat_cols = st.columns(4)
        with pm_stat_cols[0]:
            st.metric("Scans", mirror_snap["scans_completed"])
        with pm_stat_cols[1]:
            st.metric("Mirrored", mirror_snap["trades_mirrored"])
        with pm_stat_cols[2]:
            st.metric("Skipped", mirror_snap["trades_skipped"])
        with pm_stat_cols[3]:
            st.metric("Errors", mirror_snap["errors"])

        if mirror_snap["last_scan_time"]:
            st.caption(f"Last scan: {mirror_snap['last_scan_time']}")

        if mirror_snap["last_scan_result"]:
            lsr = mirror_snap["last_scan_result"]
            st.info(f"Last scan: {lsr.get('total_fetched', 0)} fetched, {lsr.get('new_trades', 0)} new, {lsr.get('executed', 0)} mirrored")

    st.markdown("---")

    pm_tab1, pm_tab2, pm_tab3 = st.tabs(["👥 Politician Rankings", "📋 Mirrored Trades", "⚙️ Configuration"])

    with pm_tab1:
        from trading.services.politician_ranker import load_scores as _load_pol_scores
        pol_scores = _load_pol_scores()

        if pol_scores:
            ranking_data = []
            for i, s in enumerate(pol_scores, 1):
                party_icon = {"Democrat": "🔵", "Republican": "🔴", "Independent": "🟡"}.get(s["party"], "⚪")
                ranking_data.append({
                    "Rank": i,
                    "Politician": f"{party_icon} {s['politician']}",
                    "Party": s["party"],
                    "Chamber": s["chamber"],
                    "Score": f"{s['score']:.3f}",
                    "Win Rate": f"{s['win_rate'] * 100:.0f}%",
                    "Avg Return": f"{s['avg_return'] * 100:+.1f}%",
                    "Evaluated": s["evaluated"],
                    "Total Trades": s["total_trades"],
                })
            st.dataframe(pd.DataFrame(ranking_data), use_container_width=True, hide_index=True)
        else:
            st.info("No politician rankings yet. Click 'Rebuild Rankings' to fetch and analyze Capitol Trades data.")

    with pm_tab2:
        mirrored = mirror_svc.get_mirrored_trades(50)
        if mirrored:
            mirror_data = []
            for m in mirrored:
                side_icon = "🟢" if m["tx_type"] == "buy" else "🔴"
                mirror_data.append({
                    "Time": m["mirrored_at"][:19] if m["mirrored_at"] else "",
                    "Action": f"{side_icon} {m['tx_type'].upper()}",
                    "Ticker": m["ticker"],
                    "Qty": m["qty"],
                    "Price": f"${m['price']:.2f}" if m["price"] else "MKT",
                    "SL": f"${m['sl']:.2f}" if m["sl"] else "—",
                    "TP": f"${m['tp']:.2f}" if m["tp"] else "—",
                    "Politician": m["politician"],
                    "Party": m["party"],
                    "Status": m["status"],
                })
            st.dataframe(pd.DataFrame(mirror_data), use_container_width=True, hide_index=True)
        else:
            st.info("No mirrored trades yet. Start the mirror service or run a manual scan.")

    with pm_tab3:
        st.markdown("### Mirror Configuration")
        st.caption("These are the default settings. Modify them in `trading/services/political_mirror.py`.")
        cfg_cols = st.columns(3)
        with cfg_cols[0]:
            st.markdown(f"**Top Politicians:** {5}")
            st.markdown(f"**Max Position Size:** {5}%")
            st.markdown(f"**Max Open Positions:** {10}")
        with cfg_cols[1]:
            st.markdown(f"**Stop Loss:** {5}%")
            st.markdown(f"**Take Profit:** {12}%")
            st.markdown(f"**Skip if Disclosed >** {7} days")
        with cfg_cols[2]:
            st.markdown(f"**Scan Interval:** Every 4 hours")
            st.markdown(f"**Rankings Rebuild:** Every Sunday")
            st.markdown(f"**Data Source:** Capitol Trades (public)")

        st.markdown("---")
        st.markdown("### Trading Framework Reference")
        try:
            with open("trading/data/trading_framework.md", "r") as f:
                framework_text = f.read()
            with st.expander("View Elite Trading Framework", expanded=False):
                st.markdown(framework_text)
        except FileNotFoundError:
            st.caption("Trading framework file not found.")

with tab4:
    try:
        positions = broker.get_current_positions() if broker else []
    except Exception as e:
        positions = []
        log_event("broker", f"Position fetch error: {e}", "error")
        st.error(f"Failed to load positions: {e}")

    try:
        orders = broker.get_open_orders() if broker else []
    except Exception as e:
        orders = []
        log_event("broker", f"Orders fetch error: {e}", "error")

    pos_col, ord_col = st.columns(2)
    with pos_col:
        st.subheader("Open Positions")
        if positions:
            pos_df = pd.DataFrame(positions)
            pos_df["unrealized_plpc"] = (pos_df["unrealized_plpc"] * 100).round(2)
            for col in ["unrealized_pl", "current_price", "avg_entry_price", "market_value"]:
                if col in pos_df.columns:
                    pos_df[col] = pos_df[col].round(2)
            st.dataframe(
                pos_df[["symbol", "qty", "side", "avg_entry_price", "current_price", "unrealized_pl", "unrealized_plpc", "market_value"]],
                use_container_width=True,
                column_config={
                    "unrealized_pl": st.column_config.NumberColumn("P&L $", format="$%.2f"),
                    "unrealized_plpc": st.column_config.NumberColumn("P&L %", format="%.2f%%"),
                    "market_value": st.column_config.NumberColumn("Value", format="$%.2f"),
                    "avg_entry_price": st.column_config.NumberColumn("Entry", format="$%.2f"),
                    "current_price": st.column_config.NumberColumn("Current", format="$%.2f"),
                },
            )
        else:
            st.info("No open positions")

    with ord_col:
        st.subheader("Open Orders")
        if orders:
            ord_df = pd.DataFrame(orders)
            st.dataframe(ord_df[["symbol", "qty", "side", "type", "status", "limit_price"]], use_container_width=True)
            if st.button("Cancel All Orders"):
                try:
                    if broker:
                        broker.cancel_all_orders()
                except Exception as e:
                    st.error(f"Cancel error: {e}")
                st.rerun()
        else:
            st.info("No open orders")

    if broker and account_data:
        st.markdown("---")
        st.subheader("Manual Order Entry")
        with st.form("manual_order"):
            mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
            with mcol1:
                m_symbol = st.text_input("Symbol", value=selected_symbol)
            with mcol2:
                m_side = st.selectbox("Side", ["buy", "sell"])
            with mcol3:
                m_qty = st.number_input("Qty", min_value=1, value=1)
            with mcol4:
                m_type = st.selectbox("Type", ["market", "limit"])
            with mcol5:
                m_limit = st.number_input("Limit Price", value=0.0, format="%.2f")

            if st.form_submit_button("Submit Order", type="primary"):
                if risk.kill_switch_active:
                    st.error("Kill switch active — trading halted")
                else:
                    try:
                        lp = m_limit if m_type == "limit" and m_limit > 0 else None
                        order_result = broker.submit_order(m_symbol.upper(), m_qty, m_side, m_type, lp, notes="Manual order")
                        if order_result:
                            st.success(f"Order submitted: {m_side.upper()} {m_qty} {m_symbol.upper()}")
                        else:
                            st.error("Order failed — check system log")
                    except Exception as e:
                        log_event("broker", f"Manual order error: {e}", "error")
                        st.error(f"Order error: {e}")

with tab5:
    st.subheader("🧠 Reasoning Ledger — Claude's Internal Monologue")
    st.caption("Live feed of every decision. Gold = high conviction (≥80%). Red = risk-off/sell.")

    token_data = get_token_usage()
    total_tokens = token_data["total_tokens"]
    token_pct = min(total_tokens / TOKEN_BUDGET * 100, 100) if TOKEN_BUDGET > 0 else 0
    if token_pct < 50:
        gauge_color = "linear-gradient(90deg, #16a34a, #22c55e)"
    elif token_pct < 80:
        gauge_color = "linear-gradient(90deg, #ca8a04, #eab308)"
    else:
        gauge_color = "linear-gradient(90deg, #dc2626, #ef4444)"
    token_gauge_col, token_reset_col = st.columns([5, 1])
    with token_gauge_col:
        st.markdown("**Token Usage — 1M Context Budget**")
        st.markdown(
            f'<div class="token-gauge-bg">'
            f'<div class="token-gauge-fill" style="width: {max(token_pct, 2):.1f}%; background: {gauge_color};">'
            f'{total_tokens:,} / {TOKEN_BUDGET:,}'
            f'</div></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:0.7rem;color:#64748b;">'
            f'<span>Input: {token_data["input_tokens"]:,}</span>'
            f'<span>Output: {token_data["output_tokens"]:,}</span>'
            f'<span>{token_pct:.1f}% used</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with token_reset_col:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Reset", key="reset_tokens", use_container_width=True):
            reset_token_usage()
            st.rerun()
    st.markdown("---")

    try:
        ledger = get_recent_reasoning(50)
    except Exception:
        ledger = []

    if ledger:
        high_conviction = sum(1 for e in ledger if e.confidence and e.confidence >= 0.80)
        sell_count = sum(1 for e in ledger if e.action in ("sell", "hold") and e.confidence and e.confidence < 0.50)
        ledger_stat_cols = st.columns(4)
        with ledger_stat_cols[0]:
            st.metric("Total Entries", len(ledger))
        with ledger_stat_cols[1]:
            st.metric("High Conviction", f"🔥 {high_conviction}")
        with ledger_stat_cols[2]:
            st.metric("Risk-Off", f"🛑 {sell_count}")
        with ledger_stat_cols[3]:
            avg_conf = sum(e.confidence for e in ledger if e.confidence) / len([e for e in ledger if e.confidence]) if any(e.confidence for e in ledger) else 0
            st.metric("Avg Confidence", f"{avg_conf:.0%}")

        st.markdown("---")

        for entry in ledger:
            action_icon = {"buy": "🟢", "sell": "🔴", "hold": "🟡", "analyzing": "🔍", "monitoring": "👁"}.get(entry.action, "⚪")
            conf = entry.confidence or 0
            conf_str = f" · {conf:.0%}" if entry.confidence else ""

            is_gold = conf >= 0.80
            is_red = entry.action in ("sell",) or (entry.action == "hold" and conf < 0.50 and conf > 0)

            if is_gold:
                css_class = "ledger-gold"
            elif is_red:
                css_class = "ledger-red"
            else:
                css_class = "ledger-default"

            header_text = f"{action_icon} [{entry.timestamp.strftime('%Y-%m-%d %H:%M')}] {entry.symbol} → {entry.action.upper()}{conf_str} — {entry.signal_type or 'N/A'}"

            st.markdown(f'<div class="{css_class}"><strong>{header_text}</strong></div>', unsafe_allow_html=True)
            with st.expander("View reasoning", expanded=False):
                st.write(entry.reasoning)
                if entry.indicators_snapshot:
                    st.caption("Indicator snapshot:")
                    st.code(entry.indicators_snapshot[:600], language="python")
    else:
        st.info("No reasoning entries yet — run a Claude Analysis or start a Bot.")

with tab6:
    st.subheader("📜 Performance Ledger — Trade History & P&L")

    try:
        stats = get_trade_stats()
    except Exception:
        stats = {"total_trades": 0, "buys": 0, "sells": 0, "total_pnl": 0.0, "winning": 0, "losing": 0, "win_rate": 0.0}

    perf_cols = st.columns(6)
    with perf_cols[0]:
        st.metric("Total Trades", stats["total_trades"])
    with perf_cols[1]:
        st.metric("Buys", stats["buys"])
    with perf_cols[2]:
        st.metric("Sells", stats["sells"])
    with perf_cols[3]:
        pnl = stats["total_pnl"]
        st.metric("Total P&L", f"${pnl:,.2f}", delta=f"${pnl:+,.2f}" if pnl != 0 else None, delta_color="normal")
    with perf_cols[4]:
        st.metric("Win Rate", f"{stats['win_rate']:.1f}%")
    with perf_cols[5]:
        st.metric("W / L", f"{stats['winning']} / {stats['losing']}")

    st.markdown("---")
    trade_col, event_col = st.columns(2)

    with trade_col:
        st.markdown("**Trade History**")
        try:
            trades = get_recent_trades(100)
        except Exception:
            trades = []

        if trades:
            trades_data = [
                {
                    "Time": t.timestamp.strftime("%m-%d %H:%M"),
                    "Symbol": t.symbol,
                    "Side": t.side.upper(),
                    "Qty": t.qty,
                    "Price": f"${t.price:.2f}" if t.price else "Market",
                    "P&L": f"${t.pnl:.2f}" if t.pnl else "—",
                    "Status": t.status,
                    "Notes": (t.notes or "")[:50],
                }
                for t in trades
            ]
            st.dataframe(pd.DataFrame(trades_data), use_container_width=True, hide_index=True)
        else:
            st.info("No trades executed yet")

    with event_col:
        st.markdown("**System Events**")
        try:
            events = get_recent_events(50)
        except Exception:
            events = []

        if events:
            for evt in events:
                icon = {"info": "ℹ️", "warning": "⚠️", "error": "❌"}.get(evt.severity, "·")
                st.caption(f"{icon} `{evt.timestamp.strftime('%H:%M:%S')}` **[{evt.event_type}]** {evt.message}")
        else:
            st.info("No system events yet")

with tab7:
    st.subheader("🔬 Strategy Backtester")
    st.caption("Test trading strategies against historical data before deploying them live.")

    bt_cols = st.columns([1, 1])

    with bt_cols[0]:
        bt_symbol = st.text_input("Symbol", value="SPY", key="bt_symbol")
        bt_strategy = st.selectbox(
            "Strategy",
            list(STRATEGY_REGISTRY.keys()),
            format_func=lambda k: k.replace("_", " ").title(),
            key="bt_strategy",
        )
        st.caption(STRATEGY_REGISTRY.get(bt_strategy, ""))
        bt_timeframe = st.selectbox("Timeframe", ["1d", "1h", "15m"], key="bt_tf")
        bt_bars = st.slider("Historical Bars", 100, 1000, 500, 50, key="bt_bars")

    with bt_cols[1]:
        bt_capital = st.number_input("Initial Capital ($)", value=100000.0, step=10000.0, key="bt_cap")
        bt_risk = st.slider("Risk per Trade (%)", 0.5, 5.0, 2.0, 0.5, key="bt_risk") / 100.0
        bt_atr_mult = st.slider("ATR Stop Multiplier", 0.5, 4.0, 1.5, 0.5, key="bt_atr")
        bt_max_pos = st.slider("Max Position (%)", 5, 30, 10, 5, key="bt_maxpos") / 100.0

    if st.button("🚀 Run Backtest", use_container_width=True, type="primary"):
        cfg = BacktestConfig(
            symbol=bt_symbol.upper().strip(),
            strategy=bt_strategy,
            timeframe=bt_timeframe,
            bars=bt_bars,
            initial_capital=bt_capital,
            risk_pct=bt_risk,
            atr_multiplier=bt_atr_mult,
            max_position_pct=bt_max_pos,
        )

        with st.spinner(f"Backtesting {bt_strategy} on {bt_symbol}…"):
            bt_result = run_backtest(cfg)

        if bt_result is None:
            st.error("Backtest failed — not enough historical data available.")
        else:
            st.markdown("### Results")
            r_cols = st.columns(5)
            with r_cols[0]:
                color = "normal" if bt_result.total_return >= 0 else "inverse"
                st.metric("Total Return", f"${bt_result.total_return:+,.2f}", f"{bt_result.total_return_pct:+.2f}%", delta_color=color)
            with r_cols[1]:
                st.metric("Win Rate", f"{bt_result.win_rate:.1f}%", f"{bt_result.winning_trades}W / {bt_result.losing_trades}L")
            with r_cols[2]:
                st.metric("Sharpe Ratio", f"{bt_result.sharpe_ratio:.2f}")
            with r_cols[3]:
                st.metric("Max Drawdown", f"-${bt_result.max_drawdown:,.2f}", f"-{bt_result.max_drawdown_pct:.1f}%", delta_color="inverse")
            with r_cols[4]:
                st.metric("Profit Factor", f"{bt_result.profit_factor:.2f}")

            r2_cols = st.columns(4)
            with r2_cols[0]:
                st.metric("Total Trades", bt_result.total_trades)
            with r2_cols[1]:
                st.metric("Avg Win", f"${bt_result.avg_win:+,.2f}")
            with r2_cols[2]:
                st.metric("Avg Loss", f"${bt_result.avg_loss:,.2f}")
            with r2_cols[3]:
                st.metric("Avg Hold", f"{bt_result.avg_hold_bars:.1f} bars")

            st.markdown("---")
            st.markdown("### Strategy vs Buy & Hold")
            comp_cols = st.columns(2)
            with comp_cols[0]:
                st.metric("Strategy Return", f"{bt_result.total_return_pct:+.2f}%")
            with comp_cols[1]:
                st.metric("Buy & Hold Return", f"{bt_result.buy_and_hold_pct:+.2f}%")

            if bt_result.equity_curve and bt_result.dates:
                import plotly.graph_objects as go
                eq_fig = go.Figure()
                eq_fig.add_trace(go.Scatter(
                    x=bt_result.dates,
                    y=bt_result.equity_curve,
                    mode="lines",
                    name="Strategy Equity",
                    line=dict(color="#00d4aa", width=2),
                ))
                eq_fig.add_hline(y=bt_capital, line_dash="dash", line_color="gray", annotation_text="Starting Capital")
                eq_fig.update_layout(
                    title="Equity Curve",
                    xaxis_title="Date",
                    yaxis_title="Equity ($)",
                    template="plotly_dark",
                    height=400,
                    margin=dict(l=60, r=20, t=50, b=40),
                )
                st.plotly_chart(eq_fig, use_container_width=True, config=PLOTLY_CONFIG)

            if bt_result.trades:
                st.markdown("### Trade Log")
                trade_df = pd.DataFrame([{
                    "Entry": t.entry_date,
                    "Exit": t.exit_date,
                    "Side": t.side.upper(),
                    "Entry $": f"${t.entry_price:.2f}",
                    "Exit $": f"${t.exit_price:.2f}",
                    "Qty": t.qty,
                    "P&L": f"${t.pnl:+.2f}",
                    "P&L %": f"{t.pnl_pct:+.2f}%",
                    "Bars": t.hold_bars,
                    "Exit Reason": t.exit_reason.replace("_", " ").title(),
                } for t in bt_result.trades])
                st.dataframe(trade_df, use_container_width=True, hide_index=True)

st.markdown("---")
st.caption("⚗️ Alchemical Trading Command Center · Phase 5 · 9 Claude Tools · Multi-Bot · Backtester · Agent Memory")
