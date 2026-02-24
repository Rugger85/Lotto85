from __future__ import annotations

import os, json
from pathlib import Path
from datetime import datetime, timezone
import requests
import streamlit as st
import plotly.graph_objects as go
from web3 import Web3

# Optional local dev
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

st.set_page_config(page_title="LOTTO", layout="wide", page_icon="🎰")

# ─────────────────────────────────────────────────────────────────────────────
# Config helpers
# ─────────────────────────────────────────────────────────────────────────────
def cfg(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            v = st.secrets[key]
            return str(v) if v is not None else default
    except Exception:
        pass
    try:
        if "secrets" in st.secrets and key in st.secrets["secrets"]:
            v = st.secrets["secrets"][key]
            return str(v) if v is not None else default
    except Exception:
        pass
    return os.getenv(key, default)

CHAIN_ID            = int(cfg("CHAIN_ID", "56"))
BSC_RPC_PRIMARY     = cfg("BSC_RPC", "")
LOTTO_CONTRACT_ADDR = cfg("LOTTO_CONTRACT", "")
USDT_ADDRESS        = cfg("USDT_ADDRESS", "")
ADMIN_WALLET        = cfg("ADMIN_WALLET", "")
LOTTO_ABI_PATH      = cfg("LOTTO_ABI_PATH", "lotto_abi.json")

BUY_DAPP_URL_DEFAULT = cfg("BUY_DAPP_URL", "https://rugger85.github.io/Lotto85/wallet_buy.html")

missing = [k for k, v in {
    "BSC_RPC": BSC_RPC_PRIMARY,
    "LOTTO_CONTRACT": LOTTO_CONTRACT_ADDR,
    "USDT_ADDRESS": USDT_ADDRESS,
    "ADMIN_WALLET": ADMIN_WALLET,
}.items() if not v]

if missing:
    st.error("Missing required config in secrets/env: " + ", ".join(missing))
    st.stop()

LOTTO_ADDR = Web3.to_checksum_address(LOTTO_CONTRACT_ADDR)
USDT_ADDR  = Web3.to_checksum_address(USDT_ADDRESS)
ADMIN_ADDR = Web3.to_checksum_address(ADMIN_WALLET)

ACCENT = "#62c1e5"
net_badge = "BSC Mainnet" if CHAIN_ID == 56 else f"Chain {CHAIN_ID}"

# ─────────────────────────────────────────────────────────────────────────────
# Web3 connect (try primary + extra + public)
# ─────────────────────────────────────────────────────────────────────────────
RPCS = [BSC_RPC_PRIMARY]
for k in ["BSC_RPC_2", "BSC_RPC_3", "BSC_RPC_4", "BSC_RPC_5"]:
    v = cfg(k, "")
    if v:
        RPCS.append(v)

RPCS += [
    "https://bsc-dataseed.binance.org/",
    "https://bsc-dataseed1.binance.org/",
    "https://bsc-dataseed2.binance.org/",
    "https://bsc-dataseed3.binance.org/",
]

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
# ABI + contracts
# ─────────────────────────────────────────────────────────────────────────────
def load_abi_file(path: str):
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

LOTTO_ABI = load_abi_file(LOTTO_ABI_PATH)
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

def _topic0_from_event_abi(event_abi: dict) -> str:
    name = event_abi["name"]
    types = ",".join([i["type"] for i in event_abi.get("inputs", [])])
    return Web3.keccak(text=f"{name}({types})").hex()

# ─────────────────────────────────────────────────────────────────────────────
# Cached on-chain snapshots
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

    return dict(
        block=blk, dec=dec, sym=sym,
        c_usdt=tok(c_raw, dec), a_usdt=tok(a_raw, dec),
        c_bnb=bnb(c_bnb), a_bnb=bnb(a_bnb),
    )

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
        price_str = f"{(tp_units or 0) / 10**dec:,.4f} {sym}" if tp_units is not None else "N/A"

        return dict(
            round_id=rid, state=state, draw_ts=draw_ts, close_ts=close_ts, sold=sold,
            draw_str=ts(draw_ts), close_str=ts(close_ts),
            draw_short=ts_short(draw_ts),
            price_str=price_str,
        )
    except Exception:
        return {}

# ─────────────────────────────────────────────────────────────────────────────
# Tickets: topic0-only logs, decode, filter buyer in Python
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=120)
def get_tickets_for_wallet(wallet: str, lookback_blocks: int = 200_000):
    if not lotto_c or not LOTTO_ABI:
        return [], {"err": "no_abi_or_contract"}

    api_key = cfg("BSCSCAN_API_KEY", "")
    if not api_key:
        return [], {"err": "missing_bscscan_api_key"}

    wallet = Web3.to_checksum_address(wallet)
    latest = int(w3.eth.block_number)
    frm = max(0, latest - int(lookback_blocks))

    event_name = "TicketsBought"
    ev_abi = next(
        (x for x in LOTTO_ABI if isinstance(x, dict) and x.get("type") == "event" and x.get("name") == event_name),
        None
    )
    if not ev_abi:
        return [], {"err": "event_not_in_abi"}

    topic0 = _topic0_from_event_abi(ev_abi)

    # Pull logs from BscScan (no RPC eth_getLogs)
    j = bscscan_get_logs(LOTTO_ADDR, topic0, frm, latest, api_key)

    if str(j.get("status")) != "1":
        return [], {"err": "bscscan_failed", "message": j.get("message"), "result": j.get("result")}

    logs = j.get("result", [])
    out = []
    decode_errors = 0
    sample_err = None
    decoded_any = 0

    # helper: grab first address-like arg as buyer (ABI-agnostic)
    def find_buyer_addr(args):
        for _, v in dict(args).items():
            if isinstance(v, str) and v.startswith("0x") and len(v) == 42:
                return v
        return None

    def get_int(args, name_candidates, idx_fallback):
        for nm in name_candidates:
            if nm in args:
                return int(args[nm])
        try:
            key = ev_abi["inputs"][idx_fallback]["name"]
            return int(args[key])
        except Exception:
            return 0

    for lg in logs:
        try:
            # Convert BscScan log to web3-like dict
            w3log = {
                "address": Web3.to_checksum_address(lg["address"]),
                "topics": [bytes.fromhex(t[2:]) for t in lg["topics"]],
                "data": lg["data"],
                "blockNumber": int(lg["blockNumber"], 16),
                "transactionHash": bytes.fromhex(lg["transactionHash"][2:]),
                "transactionIndex": int(lg["transactionIndex"], 16),
                "logIndex": int(lg["logIndex"], 16),
            }

            decoded = lotto_c.events.TicketsBought().process_log(w3log)
            decoded_any += 1
            args = decoded["args"]

            buyer = find_buyer_addr(args)
            if not buyer:
                continue
            if Web3.to_checksum_address(buyer) != wallet:
                continue

            out.append({
                "round": get_int(args, ["roundId", "round", "rid"], 1),
                "qty": get_int(args, ["qty", "quantity", "count"], 2),
                "first": get_int(args, ["firstTicketId", "first", "startId", "fromId"], 3),
                "last": get_int(args, ["lastTicketId", "last", "endId", "toId"], 4),
                "tx": "0x" + lg["transactionHash"][2:],
                "block": int(lg["blockNumber"], 16),
            })
        except Exception as e:
            decode_errors += 1
            if sample_err is None:
                sample_err = str(e)

    out.sort(key=lambda x: x["block"], reverse=True)
    dbg = {
        "err": None,
        "fromBlock": frm,
        "toBlock": latest,
        "bscscan_logs": len(logs),
        "decoded_any": decoded_any,
        "decode_errors": decode_errors,
        "sample_error": sample_err,
        "matches": len(out),
        "topic0": topic0,
    }
    return out, dbg
# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
defaults = dict(
    wallet=None,
    show_manual=False,
    manual_input="",
    active_tab="landing",     # landing/dashboard
    ui_mode="home",           # home/my_tickets
    buy_dapp_url=BUY_DAPP_URL_DEFAULT,
    toast=None,
)
for k, v in defaults.items():
    st.session_state.setdefault(k, v)

def toast(msg: str, kind="success"):
    st.session_state.toast = (kind, msg)

def render_toasts():
    t = st.session_state.toast
    if not t:
        return
    kind, msg = t
    (st.success if kind == "success" else st.error if kind == "error" else st.warning)(msg)
    st.session_state.toast = None

def submit_manual():
    raw = (st.session_state.get("manual_input") or "").strip()
    if not raw:
        toast("Please enter a wallet address.", "warning")
        return
    try:
        st.session_state.wallet = Web3.to_checksum_address(raw)
        st.session_state.show_manual = False
        st.session_state.manual_input = ""
        st.session_state.active_tab = "dashboard"
        toast("✅ Address saved. Dashboard unlocked.", "success")
        st.rerun()
    except Exception:
        toast("❌ Invalid address — must be 42 hex chars starting with 0x.", "error")

def do_disconnect():
    st.session_state.wallet = None
    st.session_state.active_tab = "landing"
    st.session_state.ui_mode = "home"
    toast("Disconnected.", "warning")
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# UI visuals (CSS)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
#MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stStatusWidget"] {{ display:none !important; }}

[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(ellipse 1200px 600px at 12% 14%,  rgba(98,193,229,.12)  0%, transparent 56%),
    radial-gradient(ellipse  900px 500px at 88% 18%,  rgba(0,190,255,.08)  0%, transparent 55%),
    radial-gradient(ellipse  900px 500px at 60% 90%,  rgba(190,0,255,.06)  0%, transparent 55%),
    linear-gradient(180deg, #06080d 0%, #07090f 100%) !important;
  color: #e9eef7 !important;
}}
a {{ color:{ACCENT} !important; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.yh {{ color:{ACCENT} !important; font-weight:900 !important; }}
.muted {{ color:rgba(233,238,247,.60); }}
.white {{ color:#e9eef7 !important; }}
.hdiv {{ height:1px; background:linear-gradient(90deg,transparent,rgba(255,255,255,.12),transparent); margin:20px 0; }}

.card {{
  background:rgba(15,19,31,.86);
  border:1px solid rgba(255,255,255,.08);
  border-radius:18px;
  padding:20px;
  box-shadow:0 20px 55px rgba(0,0,0,.35);
}}
.pill {{
  display:inline-block; padding:4px 12px; border-radius:999px;
  background:rgba(98,193,229,.14);
  border:1px solid rgba(98,193,229,.28);
  color:{ACCENT}; font-size:11px; font-weight:900;
  letter-spacing:.6px; text-transform:uppercase;
}}
.kpi {{ border:1px solid rgba(255,255,255,.09); background:rgba(255,255,255,.03); border-radius:16px; padding:16px; }}
.kpi .t {{ font-size:11px; letter-spacing:1px; font-weight:900; color:rgba(233,238,247,.70); text-transform:uppercase; }}
.kpi .v {{ font-size:26px; font-weight:950; color:{ACCENT}; margin-top:4px; line-height:1.1; }}
.kpi .s {{ font-size:12px; color:rgba(233,238,247,.62); margin-top:4px; }}
.big {{ font-size:44px; font-weight:950; color:{ACCENT}; line-height:1; }}

div.stButton > button {{
  border-radius:14px !important; font-weight:800 !important; font-size:13px !important;
  padding:10px 18px !important; color:#e9eef7 !important;
  background: linear-gradient(135deg, rgba(255,255,255,.18) 0%, rgba(255,255,255,.06) 40%, rgba(255,255,255,.10) 100%) !important;
  backdrop-filter:blur(18px) saturate(1.6) !important;
  border:1px solid rgba(255,255,255,.22) !important;
}}
div.stButton > button:hover, div.stButton > button:focus {{
  background: linear-gradient(135deg, rgba(98,193,229,.28) 0%, rgba(98,193,229,.10) 40%, rgba(98,193,229,.18) 100%) !important;
  border:1px solid rgba(98,193,229,.55) !important;
}}
.btnrow div.stButton > button {{ width:100% !important; }}

.stat-chip {{
  display:inline-flex; flex-direction:column; justify-content:center;
  padding:8px 14px; min-height:42px; border-radius:14px;
  background: linear-gradient(135deg, rgba(255,255,255,.16) 0%, rgba(255,255,255,.05) 40%, rgba(255,255,255,.09) 100%);
  border:1px solid rgba(255,255,255,.20);
}}
.stat-chip-label {{ font-size:9px; font-weight:900; letter-spacing:.9px; text-transform:uppercase; color:rgba(233,238,247,.45); }}
.stat-chip-value {{ font-size:13px; font-weight:800; color:#e9eef7; margin-top:1px; }}

.next-draw {{
  display:inline-flex; flex-direction:column; justify-content:center;
  padding:8px 14px; min-height:42px; border-radius:14px;
  border:1px solid rgba(98,193,229,.28); background:rgba(98,193,229,.08);
}}
.next-draw .lbl {{ font-size:9px; font-weight:950; letter-spacing:1px; text-transform:uppercase; color:rgba(233,238,247,.45); }}
.next-draw .dt {{ font-size:18px; font-weight:1000; color:{ACCENT}; margin-top:1px; line-height:1.05; }}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Charts
# ─────────────────────────────────────────────────────────────────────────────
PRIZE_SPLIT = {
    "1st (40%)": 40, "2nd (25%)": 25, "3rd (15%)": 15,
    "4th (10%)": 10, "5th (5%)": 5, "6th (5%)": 5,
    "Admin (20%)": 20,
}

def donut(split: dict[str, float]):
    colors = [ACCENT, "#00beff", "#be00ff", "#ff6b35", "#7ae8b0", "#e87a7a", "#444"]
    fig = go.Figure(go.Pie(
        labels=list(split.keys()),
        values=list(split.values()),
        hole=0.68,
        sort=False,
        textinfo="none",
        marker=dict(colors=colors[:len(split)], line=dict(color="#06080d", width=2)),
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=220,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig

# ─────────────────────────────────────────────────────────────────────────────
# Render blocks
# ─────────────────────────────────────────────────────────────────────────────
snap  = get_snap()
rsnap = get_round_snap()

sym       = snap["sym"]
pool      = snap["c_usdt"]
abi_ok    = "✅ ABI Loaded" if lotto_c else "⚠️ No ABI"
stt       = state_lbl(rsnap.get("state", 0)) if rsnap else "—"
sold      = rsnap.get("sold", "—") if rsnap else "—"
price_str = rsnap.get("price_str", "N/A") if rsnap else "N/A"
draw_str  = rsnap.get("draw_str", "N/A") if rsnap else "N/A"
close_str = rsnap.get("close_str", "N/A") if rsnap else "N/A"
draw_short = rsnap.get("draw_short", "N/A") if rsnap else "N/A"

def render_nav():
    left, right = st.columns([2, 3], gap="small")
    with left:
        st.markdown("### 🎰 LOTTO")
        st.markdown(
            f'<div class="muted" style="font-size:12px;">'
            f'<span class="pill">{net_badge}</span> &nbsp;'
            f'Block: <b style="color:#e9eef7">{snap["block"]:,}</b> &nbsp;·&nbsp; {abi_ok}'
            f'</div>',
            unsafe_allow_html=True,
        )
    with right:
        c1, c2 = st.columns([1.2, 1.0], gap="small")
        with c1:
            st.markdown('<div class="btnrow">', unsafe_allow_html=True)
            st.link_button("🦊 Open Buy Page", st.session_state.buy_dapp_url)
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown('<div class="btnrow">', unsafe_allow_html=True)
            if st.session_state.wallet:
                st.button("Disconnect ✕", on_click=do_disconnect, key="nav_disc")
            else:
                st.button("✏️ Manual Address", on_click=lambda: st.session_state.update(show_manual=True), key="nav_manual")
            st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

def render_tabs():
    t1, t2, t3 = st.columns([0.9, 1.2, 6], gap="small")
    with t1:
        if st.button("🏠 Home", key="tab_home"):
            st.session_state.active_tab = "landing"
            st.rerun()
    with t2:
        if st.button("📊 Dashboard", key="tab_dash"):
            st.session_state.active_tab = "dashboard"
            st.rerun()
    with t3:
        st.markdown(
            f"""
<div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
  <div class="stat-chip">
    <span class="stat-chip-label">Pool</span>
    <span class="stat-chip-value">{pool:,.2f} {sym}</span>
  </div>
  <div class="stat-chip">
    <span class="stat-chip-label">Round</span>
    <span class="stat-chip-value">{stt}</span>
  </div>
  <div class="stat-chip">
    <span class="stat-chip-label">Contract</span>
    <span class="stat-chip-value">{fmt_addr(LOTTO_ADDR)}</span>
  </div>
  <div class="next-draw">
    <div class="lbl">Next Draw</div>
    <div class="dt">{draw_short}</div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

def render_landing():
    render_toasts()

    if st.session_state.show_manual and not st.session_state.wallet:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('#### <span class="yh">Connect Read-Only Wallet</span>', unsafe_allow_html=True)
        st.markdown('<div class="muted">Paste an address to unlock the dashboard.</div>', unsafe_allow_html=True)
        st.text_input("Wallet address", key="manual_input", placeholder="0x1234…abcd", label_visibility="collapsed")
        b1, b2, _ = st.columns([1, 1, 4], gap="small")
        with b1:
            st.button("✅ Use This Address", on_click=submit_manual, key="manual_submit")
        with b2:
            st.button("Cancel", on_click=lambda: st.session_state.update(show_manual=False, manual_input=""), key="manual_cancel")
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    left, right = st.columns([1.3, 0.95], gap="large")
    with left:
        st.markdown('<span class="pill">Transparent · On-Chain · Auditable</span>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="white" style="font-size:46px; font-weight:1000; line-height:1.03;">'
            f'LOTTO<span class="yh">.</span><br/>A verifiable lottery<br/>built on <span class="yh">BSC</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="muted" style="font-size:14px; max-width:60ch;">'
            'Watch the pool live, track ticket purchases on-chain, and verify every draw independently.'
            '</div>',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f"""
<div class="card">
  <h4 style="margin:0 0 14px 0; color:{ACCENT}; font-size:18px;">Get Started</h4>

  <div class="kpi" style="margin-bottom:10px;">
    <div class="t">Total Prize Pool</div>
    <div class="v">{pool:,.2f} {sym}</div>
    <div class="s">Live contract USDT balance</div>
  </div>

  <div class="kpi">
    <div class="t">Round Status</div>
    <div class="v" style="font-size:20px;">{stt}</div>
    <div class="s">
      Tickets sold: <b>{sold}</b> · Price: <b>{price_str}</b><br/>
      Sales close: <b>{close_str}</b><br/>
      Draw: <b>{draw_str}</b>
    </div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

def render_dashboard():
    render_toasts()
    wallet = st.session_state.wallet

    # Debug expander (safe)
    with st.expander("Debug: ABI / Events", expanded=False):
        st.write("RPC:", ACTIVE_RPC)
        st.write("Contract:", LOTTO_ADDR)
        st.write("Wallet:", wallet)
        if not LOTTO_ABI:
            st.warning(f"ABI missing/invalid at: {LOTTO_ABI_PATH}")
        else:
            evs = sorted({x.get("name") for x in LOTTO_ABI if isinstance(x, dict) and x.get("type") == "event"})
            st.write("Events in ABI:", evs)
            st.write("Expecting event name:", "TicketsBought")

    if not wallet:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('### <span class="yh">Connect via Address</span>', unsafe_allow_html=True)
        st.markdown('<div class="muted">Paste your wallet address to view your ticket purchases.</div>', unsafe_allow_html=True)
        st.text_input("Wallet address", key="manual_input", placeholder="0x1234…abcd")
        b1, b2 = st.columns([1, 1], gap="small")
        with b1:
            st.button("✅ Use Address", on_click=submit_manual, key="dash_manual_submit")
        with b2:
            st.link_button("🦊 Open Buy Page", st.session_state.buy_dapp_url)
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # Header KPI strip (if wallet exists)
    if wallet:
        hl, hr = st.columns([1.1, 1], gap="large")
        with hl:
            rid = rsnap.get("round_id") if rsnap else None
            st.markdown(f'<span class="pill">{"ROUND #"+str(rid) if rid else "LIVE"}</span>', unsafe_allow_html=True)
            st.markdown(f'<div class="muted" style="font-size:12px; margin-top:8px;">Wallet: <b style="color:{ACCENT}">✏️ {fmt_addr(wallet)}</b></div>', unsafe_allow_html=True)
            ba, bb, bc = st.columns(3, gap="small")
            with ba:
                st.markdown('<div class="btnrow">', unsafe_allow_html=True)
                st.link_button("🦊 Buy Tickets (MetaMask)", st.session_state.buy_dapp_url)
                st.markdown('</div>', unsafe_allow_html=True)
            with bb:
                st.markdown('<div class="btnrow">', unsafe_allow_html=True)
                st.button("🎟️ My Tickets", on_click=lambda: st.session_state.update(ui_mode="my_tickets"), key="hero_mytickets")
                st.markdown('</div>', unsafe_allow_html=True)
            with bc:
                st.markdown('<div class="btnrow">', unsafe_allow_html=True)
                if st.button("🔄 Refresh", key="hero_refresh"):
                    st.cache_data.clear()
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

        with hr:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown('<div class="muted" style="font-size:11px; font-weight:900; letter-spacing:1px;">TOTAL PRIZE POOL</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="big">{pool:,.2f} <span style="font-size:16px; opacity:.75">{sym}</span></div>', unsafe_allow_html=True)
            ka, kb = st.columns(2, gap="small")
            with ka:
                st.metric("Tickets Sold", sold)
                st.metric("Ticket Price", price_str)
            with kb:
                st.metric("Contract BNB", f"{snap['c_bnb']:.4f}")
                st.metric("Admin BNB", f"{snap['a_bnb']:.4f}")
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # My Tickets panel
    if wallet and st.session_state.ui_mode == "my_tickets":
        st.markdown('<div class="card">', unsafe_allow_html=True)
        h1, h2 = st.columns([10, 1])
        with h1:
            st.markdown('### <span class="yh">🎟️ My Tickets</span>', unsafe_allow_html=True)
        with h2:
            st.button("✕", on_click=lambda: st.session_state.update(ui_mode="home"), key="my_close")

        if not lotto_c:
            st.warning("ABI not loaded — cannot decode ticket events.")
            st.markdown(f"[🔍 View on BscScan](https://bscscan.com/address/{LOTTO_ADDR}#events)")
        else:
            lookback = st.slider("Lookback blocks", 10_000, 2_000_000, 600_000, 10_000, key="my_lookback")
            with st.spinner("Fetching ticket purchases…"):
                purchases, dbg = get_tickets_for_wallet(wallet, int(lookback))
                if dbg.get("err") == "missing_bscscan_api_key":
                    st.error("Add BSCSCAN_API_KEY in Streamlit secrets to fetch ticket events (your RPC blocks eth_getLogs).")
                else:
                    with st.expander("Debug: TicketsBought scan", expanded=False):
                        st.write(dbg)

            if not purchases:
                st.info("No TicketsBought events found for this wallet in the selected lookback range.")
                st.caption("If you bought yesterday and this is empty: your event name may not be 'TicketsBought' OR your buy page is using a different contract.")
                with st.expander("Debug: TicketsBought log scan", expanded=False):
                    st.write(dbg)
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

                if st.checkbox("Expand to individual ticket IDs (can be large)", value=False, key="my_expand"):
                    rows = []
                    total = 0
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

    # Analytics row always
    c1, c2, c3 = st.columns(3, gap="large")
    with c1:
        st.markdown('#### <span class="yh">🏆 Prize Structure</span>', unsafe_allow_html=True)
        st.plotly_chart(donut(PRIZE_SPLIT), use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.markdown('#### <span class="yh">🧾 Info</span>', unsafe_allow_html=True)
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
# Main router
# ─────────────────────────────────────────────────────────────────────────────
render_nav()
render_tabs()

if st.session_state.active_tab == "landing":
    render_landing()
else:
    render_dashboard()
