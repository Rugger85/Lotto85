from __future__ import annotations

import os, json, time
from pathlib import Path
from datetime import datetime, timezone

import requests
import streamlit as st
import plotly.graph_objects as go
from web3 import Web3

# ─────────────────────────────────────────────────────────────────────────────
# Page
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="LOTTO", layout="wide", page_icon="🎰")

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
def cfg(key: str, default: str = "") -> str:
    try:
        if key in st.secrets and st.secrets[key] is not None:
            return str(st.secrets[key])
    except Exception:
        pass
    try:
        if "secrets" in st.secrets and key in st.secrets["secrets"] and st.secrets["secrets"][key] is not None:
            return str(st.secrets["secrets"][key])
    except Exception:
        pass
    return os.getenv(key, default)

CHAIN_ID       = int(cfg("CHAIN_ID", "56"))
BSC_RPC        = cfg("BSC_RPC", "")
LOTTO_RAW      = cfg("LOTTO_CONTRACT", "")
USDT_RAW       = cfg("USDT_ADDRESS", "")
ADMIN_RAW      = cfg("ADMIN_WALLET", "")
ABI_PATH       = cfg("LOTTO_ABI_PATH", "lotto_abi.json")
BUY_URL        = cfg("BUY_DAPP_URL", "https://rugger85.github.io/Lotto85/wallet_buy.html")
ETHERSCAN_KEY  = cfg("ETHERSCAN_API_KEY", "")

missing = [k for k, v in {
    "BSC_RPC": BSC_RPC,
    "LOTTO_CONTRACT": LOTTO_RAW,
    "USDT_ADDRESS": USDT_RAW,
    "ADMIN_WALLET": ADMIN_RAW,
}.items() if not v]
if missing:
    st.error("Missing required config in Streamlit secrets/env: " + ", ".join(missing))
    st.stop()

LOTTO_ADDR = Web3.to_checksum_address(LOTTO_RAW)
USDT_ADDR  = Web3.to_checksum_address(USDT_RAW)
ADMIN_ADDR = Web3.to_checksum_address(ADMIN_RAW)

ACCENT = "#62c1e5"
NET_BADGE = "BSC Mainnet" if CHAIN_ID == 56 else f"Chain {CHAIN_ID}"

# ─────────────────────────────────────────────────────────────────────────────
# Web3 connect (primary + public fallbacks)
# ─────────────────────────────────────────────────────────────────────────────
RPCS = [BSC_RPC] + [
    cfg("BSC_RPC_2", ""), cfg("BSC_RPC_3", ""), cfg("BSC_RPC_4", ""), cfg("BSC_RPC_5", ""),
    "https://bsc-dataseed.binance.org/",
    "https://bsc-dataseed1.binance.org/",
    "https://bsc-dataseed2.binance.org/",
    "https://bsc-dataseed3.binance.org/",
]
RPCS = [x for x in RPCS if x]

def connect_web3() -> tuple[Web3 | None, str | None]:
    for rpc in RPCS:
        try:
            w = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
            if w.is_connected():
                return w, rpc
        except Exception:
            pass
    return None, None

w3, ACTIVE_RPC = connect_web3()
if not w3:
    st.error("⚠️ Cannot connect to BSC RPC (all endpoints failed).")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# ABI + Contracts
# ─────────────────────────────────────────────────────────────────────────────
def load_abi(path: str):
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).parent / path
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "abi" in raw:
        return raw["abi"]
    if isinstance(raw, list):
        return raw
    return None

LOTTO_ABI = load_abi(ABI_PATH)
lotto_c = w3.eth.contract(address=LOTTO_ADDR, abi=LOTTO_ABI) if LOTTO_ABI else None

ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol",   "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "a", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]
usdt_c = w3.eth.contract(address=USDT_ADDR, abi=ERC20_ABI)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default

def fmt_addr(a: str) -> str:
    a = str(a)
    return a[:6] + "…" + a[-4:] if a.startswith("0x") and len(a) > 10 else a

def tok(raw: int, dec: int) -> float:
    return float(raw) / (10 ** dec)

def bnb(raw: int) -> float:
    return float(raw) / 1e18

def ts(t: int | None) -> str:
    if not t or int(t) <= 0:
        return "N/A"
    return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%b %d, %Y %H:%M UTC")

def ts_short(t: int | None) -> str:
    if not t or int(t) <= 0:
        return "N/A"
    return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%b %d, %Y")

def state_lbl(s: int) -> str:
    return {0: "🟢 Open", 1: "🔒 Sales Closed", 2: "🎉 Drawn"}.get(int(s), f"State {s}")

def topic0_from_event_abi(event_abi: dict) -> str:
    name = event_abi["name"]
    types = ",".join(i["type"] for i in event_abi.get("inputs", []))
    return Web3.keccak(text=f"{name}({types})").hex()

# ─────────────────────────────────────────────────────────────────────────────
# Snapshots
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=15)
def get_snap():
    dec = int(safe(lambda: usdt_c.functions.decimals().call(), 18))
    sym = safe(lambda: usdt_c.functions.symbol().call(), "USDT")
    blk = int(w3.eth.block_number)

    c_raw = int(safe(lambda: usdt_c.functions.balanceOf(LOTTO_ADDR).call(), 0))
    a_raw = int(safe(lambda: usdt_c.functions.balanceOf(ADMIN_ADDR).call(), 0))
    c_bnb = int(safe(lambda: w3.eth.get_balance(LOTTO_ADDR), 0))
    a_bnb = int(safe(lambda: w3.eth.get_balance(ADMIN_ADDR), 0))

    return {
        "block": blk, "dec": dec, "sym": sym,
        "c_usdt": tok(c_raw, dec), "a_usdt": tok(a_raw, dec),
        "c_bnb": bnb(c_bnb), "a_bnb": bnb(a_bnb),
    }

@st.cache_data(ttl=15)
def get_round_snap():
    if not lotto_c:
        return {}
    try:
        rid = int(lotto_c.functions.roundId().call())
        cr  = lotto_c.functions.currentRound().call()
        state    = int(cr[0]) if len(cr) > 0 else 0
        draw_ts  = int(cr[1]) if len(cr) > 1 else 0
        close_ts = int(cr[2]) if len(cr) > 2 else 0
        sold     = int(cr[3]) if len(cr) > 3 else 0

        tp_units = safe(lambda: int(lotto_c.functions.ticketPrice().call()))
        dec = int(safe(lambda: usdt_c.functions.decimals().call(), 18))
        sym = safe(lambda: usdt_c.functions.symbol().call(), "USDT")
        price_str = f"{(tp_units or 0) / (10**dec):,.4f} {sym}" if tp_units is not None else "N/A"

        return {
            "round_id": rid, "state": state, "sold": sold,
            "draw_ts": draw_ts, "close_ts": close_ts,
            "draw_str": ts(draw_ts), "close_str": ts(close_ts),
            "draw_short": ts_short(draw_ts),
            "price_str": price_str,
        }
    except Exception:
        return {}

# ─────────────────────────────────────────────────────────────────────────────
# Etherscan API v2 (BNB Chain) -> logs (avoids RPC eth_getLogs limits)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=120)
def etherscan_v2_get_logs(chainid: int, address: str, topic0: str, from_block: int, to_block: int, api_key: str):
    url = "https://api.etherscan.io/v2/api"
    params = {
        "chainid": str(chainid),
        "module": "logs",
        "action": "getLogs",
        "fromBlock": str(from_block),
        "toBlock": str(to_block),
        "address": address,
        "topic0": topic0,
        "apikey": api_key,
    }
    r = requests.get(url, params=params, timeout=25)
    return r.json()

@st.cache_data(ttl=120)
def get_tickets_for_wallet(wallet: str, lookback_blocks: int):
    if not lotto_c or not LOTTO_ABI:
        return [], {"err": "no_abi_or_contract"}
    if not ETHERSCAN_KEY:
        return [], {"err": "missing_etherscan_api_key"}

    wallet = Web3.to_checksum_address(wallet)
    latest = int(w3.eth.block_number)
    frm = max(0, latest - int(lookback_blocks))

    event_name = "TicketsBought"
    ev_abi = next((x for x in LOTTO_ABI if isinstance(x, dict) and x.get("type") == "event" and x.get("name") == event_name), None)
    if not ev_abi:
        return [], {"err": "event_not_in_abi", "event": event_name}

    topic0 = topic0_from_event_abi(ev_abi)

    # adaptive chunking for API limits
    chunk = 50_000
    min_chunk = 2_000
    out = []
    api_logs_total = 0
    decoded_any = 0
    decode_errors = 0
    sample_err = None

    def find_buyer(args):
        # first address-like argument (works even if param name isn't "buyer")
        for v in dict(args).values():
            if isinstance(v, str) and v.startswith("0x") and len(v) == 42:
                return Web3.to_checksum_address(v)
        return None

    def to_w3_log(lg: dict):
        return {
            "address": Web3.to_checksum_address(lg["address"]),
            "topics": [bytes.fromhex(t[2:]) for t in lg["topics"]],
            "data": lg["data"],
            "blockNumber": int(lg["blockNumber"], 16),
            "transactionHash": bytes.fromhex(lg["transactionHash"][2:]),
            "transactionIndex": int(lg.get("transactionIndex", "0x0"), 16),
            "logIndex": int(lg.get("logIndex", "0x0"), 16),
        }

    start = frm
    while start <= latest:
        end = min(latest, start + chunk)

        j = etherscan_v2_get_logs(CHAIN_ID, LOTTO_ADDR, topic0, start, end, ETHERSCAN_KEY)
        status = str(j.get("status", "0"))
        msg = str(j.get("message", ""))

        if status != "1":
            if "No records found" in msg:
                start = end + 1
                continue
            if chunk > min_chunk:
                chunk = max(min_chunk, chunk // 2)
                continue
            return [], {
                "err": "etherscan_failed",
                "message": msg,
                "result": j.get("result"),
                "fromBlock": start,
                "toBlock": end,
                "final_chunk": chunk,
                "topic0": topic0,
            }

        logs = j.get("result", []) or []
        api_logs_total += len(logs)

        for lg in logs:
            try:
                decoded = lotto_c.events.TicketsBought().process_log(to_w3_log(lg))
                decoded_any += 1
                args = decoded["args"]

                buyer = find_buyer(args)
                if not buyer or buyer != wallet:
                    continue

                # try common arg names; fallback to 0
                def g_int(*names, default=0):
                    for nm in names:
                        if nm in args:
                            try:
                                return int(args[nm])
                            except Exception:
                                pass
                    return default

                out.append({
                    "round": g_int("roundId", "round"),
                    "qty":   g_int("qty", "quantity"),
                    "first": g_int("firstTicketId", "first"),
                    "last":  g_int("lastTicketId", "last"),
                    "tx":    "0x" + lg["transactionHash"][2:],
                    "block": int(lg["blockNumber"], 16),
                })
            except Exception as e:
                decode_errors += 1
                if sample_err is None:
                    sample_err = str(e)

        start = end + 1
        time.sleep(0.15)  # be nice to API

    out.sort(key=lambda x: x["block"], reverse=True)
    return out, {
        "err": None,
        "fromBlock": frm,
        "toBlock": latest,
        "api_logs_total": api_logs_total,
        "decoded_any": decoded_any,
        "decode_errors": decode_errors,
        "sample_error": sample_err,
        "matches": len(out),
        "final_chunk": chunk,
        "topic0": topic0,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Session
# ─────────────────────────────────────────────────────────────────────────────
st.session_state.setdefault("tab", "landing")          # landing/dashboard
st.session_state.setdefault("wallet", None)
st.session_state.setdefault("show_manual", False)
st.session_state.setdefault("manual_input", "")
st.session_state.setdefault("ui_mode", "home")         # home/my_tickets
st.session_state.setdefault("toast", None)

def set_toast(kind: str, msg: str):
    st.session_state.toast = (kind, msg)

def render_toast():
    t = st.session_state.toast
    if not t:
        return
    kind, msg = t
    if kind == "success":
        st.success(msg)
    elif kind == "warning":
        st.warning(msg)
    else:
        st.error(msg)
    st.session_state.toast = None

def submit_manual():
    raw = (st.session_state.manual_input or "").strip()
    if not raw:
        set_toast("warning", "Please enter a wallet address.")
        return
    try:
        st.session_state.wallet = Web3.to_checksum_address(raw)
        st.session_state.show_manual = False
        st.session_state.manual_input = ""
        st.session_state.tab = "dashboard"
        set_toast("success", "✅ Address saved. Dashboard unlocked.")
        st.rerun()
    except Exception:
        set_toast("error", "❌ Invalid address — must be 42 hex chars starting with 0x.")

def disconnect():
    st.session_state.wallet = None
    st.session_state.ui_mode = "home"
    st.session_state.tab = "landing"
    set_toast("warning", "Disconnected.")
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# UI styling (compact)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
#MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stStatusWidget"] {{ display:none !important; }}
[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(ellipse 1200px 600px at 12% 14%, rgba(98,193,229,.12) 0%, transparent 56%),
    radial-gradient(ellipse  900px 500px at 88% 18%, rgba(0,190,255,.08) 0%, transparent 55%),
    radial-gradient(ellipse  900px 500px at 60% 90%, rgba(190,0,255,.06) 0%, transparent 55%),
    linear-gradient(180deg, #06080d 0%, #07090f 100%) !important;
  color:#e9eef7 !important;
}}
a {{ color:{ACCENT} !important; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.yh {{ color:{ACCENT} !important; font-weight:900 !important; }}
.muted {{ color:rgba(233,238,247,.60); }}
.hdiv {{ height:1px; background:linear-gradient(90deg,transparent,rgba(255,255,255,.12),transparent); margin:18px 0; }}
.card {{
  background:rgba(15,19,31,.86);
  border:1px solid rgba(255,255,255,.08);
  border-radius:18px;
  padding:18px;
  box-shadow:0 20px 55px rgba(0,0,0,.35);
}}
.pill {{
  display:inline-block; padding:4px 12px; border-radius:999px;
  background:rgba(98,193,229,.14); border:1px solid rgba(98,193,229,.28);
  color:{ACCENT}; font-size:11px; font-weight:900; letter-spacing:.6px; text-transform:uppercase;
}}
.stat {{
  display:inline-flex; flex-direction:column; justify-content:center;
  padding:8px 14px; border-radius:14px; min-height:42px;
  background:linear-gradient(135deg, rgba(255,255,255,.16) 0%, rgba(255,255,255,.05) 40%, rgba(255,255,255,.09) 100%);
  border:1px solid rgba(255,255,255,.18);
}}
.stat .l {{ font-size:9px; font-weight:900; letter-spacing:1px; text-transform:uppercase; color:rgba(233,238,247,.45); }}
.stat .v {{ font-size:13px; font-weight:800; color:#e9eef7; margin-top:1px; }}
.big {{ font-size:44px; font-weight:950; color:{ACCENT}; line-height:1; }}
div.stButton > button {{
  border-radius:14px !important; font-weight:800 !important; font-size:13px !important;
  padding:10px 18px !important; color:#e9eef7 !important;
  background:linear-gradient(135deg, rgba(255,255,255,.18) 0%, rgba(255,255,255,.06) 40%, rgba(255,255,255,.10) 100%) !important;
  border:1px solid rgba(255,255,255,.22) !important;
}}
div.stButton > button:hover {{
  background:linear-gradient(135deg, rgba(98,193,229,.28) 0%, rgba(98,193,229,.10) 40%, rgba(98,193,229,.18) 100%) !important;
  border:1px solid rgba(98,193,229,.55) !important;
}}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Charts
# ─────────────────────────────────────────────────────────────────────────────
PRIZE_SPLIT = {"1st (40%)": 40, "2nd (25%)": 25, "3rd (15%)": 15, "4th (10%)": 10, "5th (5%)": 5, "6th (5%)": 5, "Admin (20%)": 20}
def donut(split: dict[str, float]):
    fig = go.Figure(go.Pie(labels=list(split.keys()), values=list(split.values()), hole=0.68, sort=False, textinfo="none"))
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=220, showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig

# ─────────────────────────────────────────────────────────────────────────────
# Data for UI
# ─────────────────────────────────────────────────────────────────────────────
snap  = get_snap()
rsnap = get_round_snap()
sym = snap["sym"]
pool = snap["c_usdt"]
abi_ok = "✅ ABI Loaded" if lotto_c else "⚠️ No ABI"
stt = state_lbl(rsnap.get("state", 0)) if rsnap else "—"
sold = rsnap.get("sold", "—") if rsnap else "—"
price_str = rsnap.get("price_str", "N/A") if rsnap else "N/A"
draw_str  = rsnap.get("draw_str", "N/A") if rsnap else "N/A"
close_str = rsnap.get("close_str", "N/A") if rsnap else "N/A"
draw_short = rsnap.get("draw_short", "N/A") if rsnap else "N/A"

# ─────────────────────────────────────────────────────────────────────────────
# UI: Nav + Tabs
# ─────────────────────────────────────────────────────────────────────────────
def render_nav():
    l, r = st.columns([2, 3], gap="small")
    with l:
        st.markdown("### 🎰 LOTTO")
        st.markdown(
            f'<div class="muted" style="font-size:12px;">'
            f'<span class="pill">{NET_BADGE}</span> &nbsp;'
            f'Block: <b style="color:#e9eef7">{snap["block"]:,}</b> &nbsp;·&nbsp; {abi_ok}'
            f"</div>",
            unsafe_allow_html=True,
        )
    with r:
        c1, c2 = st.columns([1.2, 1.0], gap="small")
        with c1:
            st.link_button("🦊 Open Buy Page", BUY_URL)
        with c2:
            if st.session_state.wallet:
                st.button("Disconnect ✕", on_click=disconnect, key="disc")
            else:
                st.button("✏️ Manual Address", on_click=lambda: st.session_state.update(show_manual=True), key="manual_btn")
    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

def render_tabs():
    t1, t2, t3 = st.columns([0.9, 1.2, 6], gap="small")
    with t1:
        if st.button("🏠 Home", key="tab_home"):
            st.session_state.tab = "landing"
            st.rerun()
    with t2:
        if st.button("📊 Dashboard", key="tab_dash"):
            st.session_state.tab = "dashboard"
            st.rerun()
    with t3:
        st.markdown(
            f"""
<div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
  <div class="stat"><div class="l">Pool</div><div class="v">{pool:,.2f} {sym}</div></div>
  <div class="stat"><div class="l">Round</div><div class="v">{stt}</div></div>
  <div class="stat"><div class="l">Contract</div><div class="v">{fmt_addr(LOTTO_ADDR)}</div></div>
  <div class="stat" style="border-color:rgba(98,193,229,.28); background:rgba(98,193,229,.08);">
    <div class="l">Next Draw</div><div class="v" style="color:{ACCENT}; font-weight:950;">{draw_short}</div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Screens
# ─────────────────────────────────────────────────────────────────────────────
def landing():
    render_toast()

    if st.session_state.show_manual and not st.session_state.wallet:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('#### <span class="yh">Connect Read-Only Wallet</span>', unsafe_allow_html=True)
        st.markdown('<div class="muted">Paste an address to unlock the dashboard.</div>', unsafe_allow_html=True)
        st.text_input("Wallet address", key="manual_input", placeholder="0x1234…abcd", label_visibility="collapsed")
        c1, c2, _ = st.columns([1, 1, 4])
        with c1:
            st.button("✅ Use This Address", on_click=submit_manual, key="manual_submit")
        with c2:
            st.button("Cancel", on_click=lambda: st.session_state.update(show_manual=False, manual_input=""), key="manual_cancel")
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    a, b = st.columns([1.35, 1.0], gap="large")
    with a:
        st.markdown('<span class="pill">Transparent · On-Chain · Auditable</span>', unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size:46px; font-weight:1000; line-height:1.03;">'
            f'LOTTO<span class="yh">.</span><br/>A verifiable lottery<br/>built on <span class="yh">BSC</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="muted" style="font-size:14px; max-width:62ch;">'
            'Watch the pool live, track ticket purchases, and verify draws independently.'
            '</div>',
            unsafe_allow_html=True,
        )

    with b:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown(f'<div class="muted" style="font-size:11px; font-weight:900; letter-spacing:1px;">TOTAL PRIZE POOL</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big">{pool:,.2f} <span style="font-size:16px; opacity:.75">{sym}</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="muted">Tickets sold: <b style="color:#e9eef7">{sold}</b> · Price: <b style="color:#e9eef7">{price_str}</b></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="muted">Sales close: <b style="color:#e9eef7">{close_str}</b></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="muted">Draw: <b style="color:#e9eef7">{draw_str}</b></div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

def dashboard():
    render_toast()
    wallet = st.session_state.wallet

    if not wallet:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('### <span class="yh">Connect via Address</span>', unsafe_allow_html=True)
        st.markdown('<div class="muted">Paste your wallet address to view your ticket purchases.</div>', unsafe_allow_html=True)
        st.text_input("Wallet address", key="manual_input", placeholder="0x1234…abcd")
        c1, c2 = st.columns([1, 1])
        with c1:
            st.button("✅ Use Address", on_click=submit_manual, key="dash_use")
        with c2:
            st.link_button("🦊 Open Buy Page", BUY_URL)
        st.markdown("</div>", unsafe_allow_html=True)

    if wallet:
        hl, hr = st.columns([1.15, 1.0], gap="large")
        with hl:
            st.markdown(f'<div class="muted" style="font-size:12px;">Wallet: <b style="color:{ACCENT}">✏️ {fmt_addr(wallet)}</b></div>', unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3, gap="small")
            with c1:
                st.link_button("🦊 Buy Tickets (MetaMask)", BUY_URL)
            with c2:
                st.button("🎟️ My Tickets", on_click=lambda: st.session_state.update(ui_mode="my_tickets"), key="btn_tickets")
            with c3:
                if st.button("🔄 Refresh", key="btn_refresh"):
                    st.cache_data.clear()
                    st.rerun()

            st.markdown(
                f'<div class="muted" style="font-size:11px; margin-top:8px;">'
                f'Contract: <code>{fmt_addr(LOTTO_ADDR)}</code> · USDT: <code>{fmt_addr(USDT_ADDR)}</code> · {abi_ok}'
                f"</div>",
                unsafe_allow_html=True,
            )

        with hr:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown(f'<div class="muted" style="font-size:11px; font-weight:900; letter-spacing:1px;">TOTAL PRIZE POOL</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="big">{pool:,.2f} <span style="font-size:16px; opacity:.75">{sym}</span></div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Tickets Sold", sold)
                st.metric("Ticket Price", price_str)
            with c2:
                st.metric("Contract BNB", f"{snap['c_bnb']:.4f}")
                st.metric("Admin BNB", f"{snap['a_bnb']:.4f}")
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # My Tickets panel
    if wallet and st.session_state.ui_mode == "my_tickets":
        st.markdown('<div class="card">', unsafe_allow_html=True)
        h1, h2 = st.columns([10, 1])
        with h1:
            st.markdown('### <span class="yh">🎟️ My Tickets</span>', unsafe_allow_html=True)
        with h2:
            st.button("✕", on_click=lambda: st.session_state.update(ui_mode="home"), key="close_tickets")

        if not ETHERSCAN_KEY:
            st.error("Missing ETHERSCAN_API_KEY in secrets. Add it, then refresh.")
        elif not lotto_c:
            st.error(f"ABI not loaded. Check LOTTO_ABI_PATH='{ABI_PATH}' exists in repo.")
        else:
            lookback = st.slider("Lookback blocks", 10_000, 2_000_000, 600_000, 10_000, key="lookback")
            with st.spinner("Fetching ticket purchases…"):
                purchases, dbg = get_tickets_for_wallet(wallet, int(lookback))

            with st.expander("Debug (safe)", expanded=False):
                st.write({
                    "rpc": ACTIVE_RPC,
                    "contract": LOTTO_ADDR,
                    "wallet": wallet,
                    "abi_loaded": bool(LOTTO_ABI),
                    "events_in_abi": sorted({x.get("name") for x in LOTTO_ABI if isinstance(x, dict) and x.get("type") == "event"}) if LOTTO_ABI else [],
                    "dbg": dbg,
                })

            if not purchases:
                st.info("No TicketsBought events found for this wallet in the selected lookback range.")
                st.caption("If you bought yesterday and this is empty: confirm the BUY page used THIS same wallet and THIS contract address.")
            else:
                st.markdown("#### Purchases")
                st.dataframe(
                    [{
                        "Round": p["round"],
                        "Qty": p["qty"],
                        "Ticket Range": f'{p["first"]} → {p["last"]}',
                        "Block": p["block"],
                        "Tx": p["tx"],
                        "Tx Link": f"https://bscscan.com/tx/{p['tx']}",
                    } for p in purchases],
                    use_container_width=True,
                    hide_index=True,
                )

                if st.checkbox("Expand to individual ticket IDs (can be large)", value=False, key="expand"):
                    rows, total = [], 0
                    for p in purchases:
                        total += int(p["qty"])
                        for tid in range(int(p["first"]), int(p["last"]) + 1):
                            rows.append({
                                "TicketId": tid,
                                "Round": p["round"],
                                "Block": p["block"],
                                "Tx": p["tx"],
                                "Tx Link": f"https://bscscan.com/tx/{p['tx']}",
                            })
                    st.markdown(f'<div class="muted">Total tickets: <b style="color:{ACCENT}">{total}</b></div>', unsafe_allow_html=True)
                    st.dataframe(rows, use_container_width=True, hide_index=True)

        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # Bottom row (always)
    c1, c2, c3 = st.columns(3, gap="large")
    with c1:
        st.markdown('#### <span class="yh">🏆 Prize Structure</span>', unsafe_allow_html=True)
        st.plotly_chart(donut(PRIZE_SPLIT), use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.markdown('#### <span class="yh">ℹ️ Info</span>', unsafe_allow_html=True)
        st.caption(f"Contract: {LOTTO_ADDR}")
        st.caption(f"USDT: {USDT_ADDR}")
        st.caption(f"Admin: {ADMIN_ADDR}")
        st.caption(f"RPC: {ACTIVE_RPC}")
    with c3:
        st.markdown('#### <span class="yh">📈 Platform Stats</span>', unsafe_allow_html=True)
        st.metric("USDT (Contract)", f"{snap['c_usdt']:,.2f} {sym}")
        st.metric("USDT (Admin)", f"{snap['a_usdt']:,.2f} {sym}")
        st.metric("BNB (Contract)", f"{snap['c_bnb']:.6f}")
        st.metric("BNB (Admin)", f"{snap['a_bnb']:.6f}")

# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────
render_nav()
render_tabs()
if st.session_state.tab == "landing":
    landing()
else:
    dashboard()
