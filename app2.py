from __future__ import annotations

import os, json
from datetime import datetime, timezone

import streamlit as st
import plotly.graph_objects as go
from web3 import Web3

# Optional local dev
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# MetaMask JS bridge
try:
    from streamlit_javascript import st_javascript
    HAS_JS = True
except Exception:
    HAS_JS = False


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit setup
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="LOTTO", layout="wide", page_icon="🎰")


# ─────────────────────────────────────────────────────────────────────────────
# Config (Streamlit Cloud: st.secrets, Local: .env)
# ─────────────────────────────────────────────────────────────────────────────
def cfg(key: str, default: str = "") -> str:
    # 1) direct root keys: st.secrets["LOTTO_CONTRACT"]
    try:
        if key in st.secrets:
            v = st.secrets[key]
            return str(v) if v is not None else default
    except Exception:
        pass

    # 2) common nested section: st.secrets["secrets"]["LOTTO_CONTRACT"]
    try:
        if "secrets" in st.secrets and key in st.secrets["secrets"]:
            v = st.secrets["secrets"][key]
            return str(v) if v is not None else default
    except Exception:
        pass

    # 3) env vars (local .env or Streamlit Cloud "Environment variables")
    return os.getenv(key, default)

# st.write("Secrets keys:", list(st.secrets.keys()))
# if "secrets" in st.secrets:
#     st.write("Nested secrets keys:", list(st.secrets["secrets"].keys()))

CHAIN_ID            = int(cfg("CHAIN_ID", "56"))
BSC_RPC_PRIMARY     = cfg("BSC_RPC", "")
LOTTO_CONTRACT_ADDR = cfg("LOTTO_CONTRACT", "")
USDT_ADDRESS        = cfg("USDT_ADDRESS", "")
ADMIN_WALLET        = cfg("ADMIN_WALLET", "")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOTTO_ABI_PATH = cfg("LOTTO_ABI_PATH", "lotto_abi.json")

# Optional: add extra RPCs in secrets as BSC_RPC_2, BSC_RPC_3...
RPCS = [BSC_RPC_PRIMARY]
for k in ["BSC_RPC_2", "BSC_RPC_3", "BSC_RPC_4", "BSC_RPC_5"]:
    v = cfg(k, "")
    if v:
        RPCS.append(v)

# Public fallbacks (helpful on Streamlit Cloud)
RPCS += [
    "https://bsc-dataseed.binance.org/",
    "https://bsc-dataseed1.binance.org/",
    "https://bsc-dataseed2.binance.org/",
    "https://bsc-dataseed3.binance.org/",
]

missing = [k for k, v in {
    "LOTTO_CONTRACT": LOTTO_CONTRACT_ADDR,
    "USDT_ADDRESS": USDT_ADDRESS,
    "ADMIN_WALLET": ADMIN_WALLET,
}.items() if not v]

if missing:
    st.error(
        "Missing required config. Add these in Streamlit Cloud Secrets:\n\n"
        + ", ".join(missing)
    )
    st.stop()

ACCENT = "#62c1e5"

# Mini dApp URL (served by python http.server)
BUY_DAPP_URL_DEFAULT = "https://rugger85.github.io/Lotto85/wallet_buy.html"

# ─────────────────────────────────────────────────────────────────────────────
# Web3 connect
# ─────────────────────────────────────────────────────────────────────────────
def connect_web3() -> tuple[Web3 | None, str | None]:
    for rpc in RPCS:
        if not rpc:
            continue
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

LOTTO_CONTRACT = Web3.to_checksum_address(LOTTO_CONTRACT_ADDR)
USDT           = Web3.to_checksum_address(USDT_ADDRESS)
ADMIN          = Web3.to_checksum_address(ADMIN_WALLET)


# ─────────────────────────────────────────────────────────────────────────────
# ABIs
# ─────────────────────────────────────────────────────────────────────────────
ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol",
     "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "a", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True,
     "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

usdt_c = w3.eth.contract(address=USDT, abi=ERC20_ABI)

from pathlib import Path

LOTTO_ABI = None
abi_path = Path(__file__).parent / LOTTO_ABI_PATH  # LOTTO_ABI_PATH like "lotto_abi.json"

if abi_path.exists():
    try:
        raw = json.loads(abi_path.read_text(encoding="utf-8"))
        LOTTO_ABI = raw.get("abi", raw)
    except Exception:
        LOTTO_ABI = None

lotto_c = w3.eth.contract(address=LOTTO_CONTRACT, abi=LOTTO_ABI) if LOTTO_ABI else None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def fmt_addr(a: str) -> str:
    a = str(a)
    return a[:6] + "…" + a[-4:] if a.startswith("0x") and len(a) > 10 else a

def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default

def tok(raw: int, dec: int) -> float:
    return float(raw) / (10 ** dec)

def bnb(raw: int) -> float:
    return float(raw) / 1e18

def ts(t: int | None) -> str:
    if not t or int(t) <= 0:
        return "N/A"
    try:
        return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        return "N/A"

def ts_short(t: int | None) -> str:
    if not t or int(t) <= 0:
        return "N/A"
    try:
        return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%b %d, %Y")
    except Exception:
        return "N/A"

def state_lbl(s: int) -> str:
    return {0: "🟢 Open", 1: "🔒 Sales Closed", 2: "🎉 Drawn"}.get(int(s), f"State {s}")

def pad_topic_addr(addr: str) -> str:
    return "0x" + "0" * 24 + addr.lower().replace("0x", "")

def countdown_label(target_ts: int) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    if target_ts <= 0:
        return "N/A"
    d = target_ts - now
    if d <= 0:
        return "Now"
    days = d // 86400
    hrs  = (d % 86400) // 3600
    mins = (d % 3600) // 60
    return f"{days}d {hrs}h {mins}m"

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
# On-chain data (cached)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=15)
def get_snap():
    dec   = int(safe(lambda: usdt_c.functions.decimals().call(), 18))
    sym   = safe(lambda: usdt_c.functions.symbol().call(), "USDT")
    c_raw = int(safe(lambda: usdt_c.functions.balanceOf(LOTTO_CONTRACT).call(), 0))
    a_raw = int(safe(lambda: usdt_c.functions.balanceOf(ADMIN).call(), 0))
    c_bnb = int(safe(lambda: w3.eth.get_balance(LOTTO_CONTRACT), 0))
    a_bnb = int(safe(lambda: w3.eth.get_balance(ADMIN), 0))
    blk   = int(w3.eth.block_number)

    logs = []
    try:
        topic0 = Web3.keccak(text="Transfer(address,address,uint256)").hex()

        def fetch_to(to_addr: str):
            return w3.eth.get_logs({
                "fromBlock": max(0, blk - 50_000),
                "toBlock": blk,
                "address": USDT,
                "topics": [topic0, None, pad_topic_addr(to_addr)],
            })

        all_logs = []
        all_logs += list(fetch_to(LOTTO_CONTRACT))
        all_logs += list(fetch_to(ADMIN))

        # newest first
        all_logs = sorted(all_logs, key=lambda x: int(x["blockNumber"]), reverse=True)[:12]

        for lg in all_logs:
            to_addr = Web3.to_checksum_address("0x" + lg["topics"][2].hex()[-40:])
            logs.append({
                "block": int(lg["blockNumber"]),
                "tx": lg["transactionHash"].hex(),
                "from": Web3.to_checksum_address("0x" + lg["topics"][1].hex()[-40:]),
                "to": to_addr,
                "amount": tok(int(lg["data"], 16), dec),
                "symbol": sym,
            })
    except Exception:
        pass

    return dict(block=blk, dec=dec, sym=sym,
                c_usdt=tok(c_raw, dec), a_usdt=tok(a_raw, dec),
                c_bnb=bnb(c_bnb), a_bnb=bnb(a_bnb), logs=logs)

@st.cache_data(ttl=15)
def get_round_snap():
    if not lotto_c:
        return {}
    try:
        rid = safe(lambda: int(lotto_c.functions.roundId().call()))
        cr  = lotto_c.functions.currentRound().call()
        state    = int(cr[0]) if len(cr) > 0 else 0
        draw_ts  = int(cr[1]) if len(cr) > 1 else 0
        close_ts = int(cr[2]) if len(cr) > 2 else 0
        sold     = int(cr[3]) if len(cr) > 3 else 0

        dec, sym = None, None
        try:
            uaddr = lotto_c.functions.usdt().call()
            um = w3.eth.contract(address=uaddr, abi=ERC20_ABI)
            dec = int(um.functions.decimals().call())
            sym = str(um.functions.symbol().call())
        except Exception:
            pass

        tp_units = safe(lambda: int(lotto_c.functions.ticketPrice().call()))
        snap_dec = dec if dec is not None else 18
        snap_sym = sym if sym is not None else "USDT"
        price_str = f"{tp_units / 10**snap_dec:,.4f} {snap_sym}" if tp_units is not None else "N/A"

        return dict(round_id=rid, state=state, draw_ts=draw_ts, close_ts=close_ts,
                    sold=sold, draw_str=ts(draw_ts), close_str=ts(close_ts),
                    draw_short=ts_short(draw_ts),
                    price_units=tp_units, price_str=price_str,
                    dec=snap_dec, sym=snap_sym)
    except Exception:
        return {}

@st.cache_data(ttl=60)
def get_tickets_for_wallet(wallet: str, lookback_blocks: int = 120_000):
    if not lotto_c:
        return []

    wallet = Web3.to_checksum_address(wallet)
    latest = int(w3.eth.block_number)
    frm = max(0, latest - int(lookback_blocks))

    out = []
    ev = lotto_c.events.TicketsBought

    try:
        flt = ev.create_filter(
            fromBlock=frm,
            toBlock="latest",
            argument_filters={"buyer": wallet},
        )
        entries = flt.get_all_entries()
    except Exception:
        # RPC fallback: fetch all, filter locally
        try:
            flt = ev.create_filter(fromBlock=frm, toBlock="latest")
            entries = flt.get_all_entries()
            entries = [e for e in entries if Web3.to_checksum_address(e["args"]["buyer"]) == wallet]
        except Exception:
            return []

    for e in entries:
        args = e["args"]
        out.append({
            "event": "TicketsBought",
            "round": int(args["roundId"]),
            "qty": int(args["qty"]),
            "first": int(args["firstTicketId"]),
            "last": int(args["lastTicketId"]),
            "tx": e["transactionHash"].hex(),
            "block": int(e["blockNumber"]),
        })

    out.sort(key=lambda x: x["block"], reverse=True)
    return out

# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
for k, v in dict(
    wallet=None,
    wallet_type=None,       # "manual"
    show_manual=False,
    manual_input="",
    ui_mode="home",
    buy_qty=1,
    tx_status=None,
    tx_value=None,
    active_tab="landing",   # "landing" | "dashboard"
    buy_dapp_url=BUY_DAPP_URL_DEFAULT,
).items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# Global CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
#MainMenu, header, footer,
[data-testid="stToolbar"],
[data-testid="stStatusWidget"] {{ display:none !important; }}

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

.yh    {{ color:{ACCENT} !important; font-weight:900 !important; }}
.muted {{ color:rgba(233,238,247,.60); }}
.white {{ color:#e9eef7 !important; }}
.hdiv  {{ height:1px; background:linear-gradient(90deg,transparent,rgba(255,255,255,.12),transparent); margin:20px 0; }}

.card {{
  background:rgba(15,19,31,.86);
  border:1px solid rgba(255,255,255,.08);
  border-radius:18px;
  padding:20px;
  box-shadow:0 20px 55px rgba(0,0,0,.35);
}}

.pill {{
  display:inline-block;
  padding:4px 12px;
  border-radius:999px;
  background:rgba(98,193,229,.14);
  border:1px solid rgba(98,193,229,.28);
  color:{ACCENT};
  font-size:11px;
  font-weight:900;
  letter-spacing:.6px;
  text-transform:uppercase;
}}

.kpi {{ border:1px solid rgba(255,255,255,.09); background:rgba(255,255,255,.03); border-radius:16px; padding:16px; }}
.kpi .t {{ font-size:11px; letter-spacing:1px; font-weight:900; color:rgba(233,238,247,.70); text-transform:uppercase; }}
.kpi .v {{ font-size:26px; font-weight:950; color:{ACCENT}; margin-top:4px; line-height:1.1; }}
.kpi .s {{ font-size:12px; color:rgba(233,238,247,.62); margin-top:4px; }}

.big {{ font-size:44px; font-weight:950; color:{ACCENT}; line-height:1; }}

.heroTitle {{ font-size:46px; font-weight:1000; line-height:1.03; margin:6px 0 8px; }}
.heroSub   {{ font-size:14px; color:rgba(233,238,247,.64); max-width:58ch; }}

div.stButton > button {{
  border-radius:14px !important;
  font-weight:800 !important;
  font-size:13px !important;
  letter-spacing:.2px !important;
  padding:10px 18px !important;
  color:#e9eef7 !important;
  cursor:pointer !important;
  transition:all .22s ease !important;
  background:
    linear-gradient(135deg,
      rgba(255,255,255,.18) 0%,
      rgba(255,255,255,.06) 40%,
      rgba(255,255,255,.10) 100%
    ) !important;
  backdrop-filter:blur(18px) saturate(1.6) !important;
  -webkit-backdrop-filter:blur(18px) saturate(1.6) !important;
  border:1px solid rgba(255,255,255,.22) !important;
}}

div.stButton > button:hover,
div.stButton > button:focus {{
  background:
    linear-gradient(135deg,
      rgba(98,193,229,.28) 0%,
      rgba(98,193,229,.10) 40%,
      rgba(98,193,229,.18) 100%
    ) !important;
  border:1px solid rgba(98,193,229,.55) !important;
  color:#fff !important;
}}

.btnrow div.stButton > button {{ width:100% !important; }}

.tab-active div.stButton > button {{
  background:
    linear-gradient(135deg,
      rgba(98,193,229,.35) 0%,
      rgba(98,193,229,.12) 45%,
      rgba(98,193,229,.24) 100%
    ) !important;
  border:1px solid rgba(98,193,229,.60) !important;
  color:{ACCENT} !important;
  font-weight:950 !important;
}}
.tab-inactive div.stButton > button {{
  background:
    linear-gradient(135deg,
      rgba(255,255,255,.10) 0%,
      rgba(255,255,255,.04) 50%,
      rgba(255,255,255,.08) 100%
    ) !important;
  border:1px solid rgba(255,255,255,.16) !important;
  color:rgba(233,238,247,.65) !important;
}}

.stat-chip {{
  display:inline-flex;
  flex-direction:column;
  justify-content:center;
  padding:8px 14px;
  min-height:42px;
  background:
    linear-gradient(135deg,
      rgba(255,255,255,.16) 0%,
      rgba(255,255,255,.05) 40%,
      rgba(255,255,255,.09) 100%
    );
  backdrop-filter:blur(18px) saturate(1.6);
  -webkit-backdrop-filter:blur(18px) saturate(1.6);
  border:1px solid rgba(255,255,255,.20);
  border-radius:14px;
  line-height:1.25;
  cursor:default;
}}
.stat-chip-label {{
  font-size:9px;
  font-weight:900;
  letter-spacing:.9px;
  text-transform:uppercase;
  color:rgba(233,238,247,.45);
}}
.stat-chip-value {{
  font-size:13px;
  font-weight:800;
  color:#e9eef7;
  margin-top:1px;
}}

.next-draw {{
  display:inline-flex;
  flex-direction:column;
  justify-content:center;
  padding:8px 14px;
  min-height:42px;
  border-radius:14px;
  border:1px solid rgba(98,193,229,.28);
  background:rgba(98,193,229,.08);
}}
.next-draw .lbl {{
  font-size:9px;
  font-weight:950;
  letter-spacing:1px;
  text-transform:uppercase;
  color:rgba(233,238,247,.45);
}}
.next-draw .dt {{
  font-size:18px;
  font-weight:1000;
  color:{ACCENT};
  margin-top:1px;
  line-height:1.05;
}}
.next-draw .cd {{
  font-size:11px;
  font-weight:800;
  color:rgba(233,238,247,.70);
  margin-top:2px;
}}

.tx-row {{
  padding:12px 14px;
  border-radius:14px;
  border:1px solid rgba(255,255,255,.08);
  background:rgba(15,19,31,.72);
  margin-bottom:8px;
}}
.tx-amount {{ font-weight:950; color:{ACCENT}; }}
.tx-meta   {{ font-size:12px; color:rgba(233,238,247,.55); margin-top:4px; }}

.ticket-row {{
  padding:14px;
  border-radius:16px;
  border:1px solid rgba(98,193,229,.18);
  background:rgba(98,193,229,.06);
  margin-bottom:10px;
}}

.info-card {{
  background:rgba(15,19,31,.86);
  border:1px solid rgba(255,255,255,.10);
  border-radius:18px;
  padding:26px 22px;
  height:100%;
  box-sizing:border-box;
}}
.info-card-icon {{ font-size:28px; margin-bottom:10px; }}
.info-card-title {{ font-size:16px; font-weight:900; color:{ACCENT}; margin-bottom:10px; letter-spacing:.2px; }}
.info-card-body {{ font-size:13.5px; color:rgba(233,238,247,.82); line-height:1.7; }}
.step {{
  display:inline-block; width:20px; height:20px;
  background:rgba(98,193,229,.20);
  border:1px solid rgba(98,193,229,.40);
  border-radius:50%;
  text-align:center; line-height:20px;
  font-size:11px; font-weight:900; color:{ACCENT};
  margin-right:6px; vertical-align:middle;
}}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Session actions
# ─────────────────────────────────────────────────────────────────────────────
def open_manual():
    st.session_state.show_manual = True

def close_manual():
    st.session_state.show_manual = False
    st.session_state.manual_input = ""

def do_disconnect():
    for kk in ["wallet", "wallet_type", "tx_status", "tx_value"]:
        st.session_state[kk] = None
    st.session_state.ui_mode = "home"
    st.session_state.active_tab = "landing"
    close_manual()

def submit_manual():
    raw = (st.session_state.get("manual_input") or "").strip()
    if not raw:
        st.session_state.tx_status = "manual_empty"
        return
    try:
        st.session_state.wallet      = Web3.to_checksum_address(raw)
        st.session_state.wallet_type = "manual"
        st.session_state.show_manual = False
        st.session_state.manual_input = ""
        st.session_state.active_tab  = "dashboard"
        st.session_state.tx_status   = "manual_ok"
        st.rerun()
    except Exception:
        st.session_state.tx_status = "manual_bad"


# ─────────────────────────────────────────────────────────────────────────────
# Toast notifications
# ─────────────────────────────────────────────────────────────────────────────
def render_toasts():
    txs = st.session_state.tx_status
    if txs == "manual_ok":
        st.success("✅ Address saved. Dashboard unlocked.")
    elif txs == "manual_bad":
        st.error("❌ Invalid address — must be 42 hex chars starting with 0x.")
    elif txs == "manual_empty":
        st.warning("Please enter a wallet address.")
    st.session_state.tx_status = None
    st.session_state.tx_value  = None


# ─────────────────────────────────────────────────────────────────────────────
# Fetch data
# ─────────────────────────────────────────────────────────────────────────────
snap  = get_snap()
rsnap = get_round_snap()

sym       = snap["sym"]
pool      = snap["c_usdt"]
net_badge = "BSC Mainnet" if int(CHAIN_ID) == 56 else f"Chain {CHAIN_ID}"
abi_ok    = "✅ ABI Loaded" if lotto_c else "⚠️ No ABI"
stt       = state_lbl(rsnap.get("state", 0)) if rsnap else "🟢 Open"
sold      = rsnap.get("sold", "—") if rsnap else "—"
price_str = rsnap.get("price_str", "N/A") if rsnap else "N/A"
draw_str  = rsnap.get("draw_str", "N/A") if rsnap else "N/A"
close_str = rsnap.get("close_str", "N/A") if rsnap else "N/A"
draw_cd   = countdown_label(int(rsnap.get("draw_ts", 0))) if rsnap else "N/A"
draw_short = rsnap.get("draw_short", "N/A") if rsnap else "N/A"


# ─────────────────────────────────────────────────────────────────────────────
# Top nav
# ─────────────────────────────────────────────────────────────────────────────
def render_nav():
    wallet = st.session_state.wallet

    nav_left, nav_right = st.columns([2, 3], gap="small")

    with nav_left:
        st.markdown("### 🎰 LOTTO")
        st.markdown(
            f'<div class="muted" style="font-size:12px;">'
            f'<span class="pill">{net_badge}</span> &nbsp;'
            f'Block: <b style="color:#e9eef7">{snap["block"]:,}</b> &nbsp;·&nbsp; {abi_ok}'
            f'</div>',
            unsafe_allow_html=True,
        )

    with nav_right:
        c1, c2 = st.columns([1.2, 1.0], gap="small")

        with c1:
            st.markdown('<div class="btnrow">', unsafe_allow_html=True)
            st.link_button("🦊 Open Buy Page", st.session_state.buy_dapp_url)
            st.markdown("</div>", unsafe_allow_html=True)

        with c2:
            if wallet:
                st.markdown('<div class="btnrow">', unsafe_allow_html=True)
                st.button("Disconnect ✕", on_click=do_disconnect, key="nav_disconnect")
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.markdown('<div class="btnrow">', unsafe_allow_html=True)
                st.button("✏️ Manual Address", on_click=open_manual, key="nav_manual")
                st.markdown("</div>", unsafe_allow_html=True)

        # Optional: hidden settings for the buy URL
        # with st.expander("⚙️ Settings", expanded=False):
        #     st.text_input("Buy page URL", key="buy_dapp_url")

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tab strip + stats
# ─────────────────────────────────────────────────────────────────────────────
def render_tab_strip():
    wallet = st.session_state.wallet
    active = st.session_state.active_tab

    t1, t2, t3 = st.columns([0.9, 1.2, 6], gap="small")

    with t1:
        cls = "tab-active" if active == "landing" else "tab-inactive"
        st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
        if st.button("🏠 Home", key="tab_landing"):
            st.session_state.active_tab = "landing"
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    with t2:
        cls = "tab-active" if active == "dashboard" else "tab-inactive"
        st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
        if st.button("📊 Dashboard", key="tab_dashboard"):
            st.session_state.active_tab = "dashboard"
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    with t3:
        st.markdown(
            f"""
<div style="display:flex; align-items:center; gap:10px; height:100%; padding-top:2px; flex-wrap:wrap;">
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
    <span class="stat-chip-value">{fmt_addr(LOTTO_CONTRACT)}</span>
  </div>
  <div class="next-draw">
    <div class="lbl">Next Draw</div>
    <div class="dt">{draw_short}</div>
    <div class="cd">{draw_cd}</div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Landing
# ─────────────────────────────────────────────────────────────────────────────
def render_landing():
    render_toasts()

    if st.session_state.show_manual and not st.session_state.wallet:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('#### <span class="yh">Connect Read-Only Wallet</span>', unsafe_allow_html=True)
        st.markdown('<div class="muted">Paste an address to unlock the dashboard. Buying tickets requires MetaMask.</div>', unsafe_allow_html=True)
        st.text_input("Wallet address", key="manual_input",
                      placeholder="0x1234…abcd", label_visibility="collapsed")
        b1, b2, _ = st.columns([1, 1, 4], gap="small")
        with b1:
            st.button("✅ Use This Address", on_click=submit_manual, key="manual_submit")
        with b2:
            st.button("Cancel", on_click=close_manual, key="manual_cancel")
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    left, right = st.columns([1.3, 0.95], gap="large")

    with left:
        st.markdown('<span class="pill">Transparent · On-Chain · Auditable</span>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="heroTitle white">LOTTO<span class="yh">.</span><br/>'
            f'A verifiable lottery<br/>built on <span class="yh">BSC</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="heroSub">Watch the pool live, track ticket ranges on-chain, '
            'and verify every purchase with public events. Connect your wallet to unlock the dashboard.</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="muted" style="margin-top:10px; font-size:12px;">'
            f'Network: <b style="color:#e9eef7">{net_badge}</b> &nbsp;·&nbsp; '
            f'Pool: <b style="color:{ACCENT}">{pool:,.2f} {sym}</b> &nbsp;·&nbsp; '
            f'Block: <b style="color:#e9eef7">{snap["block"]:,}</b></div>',
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

  <div class="kpi" style="margin-bottom:14px;">
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

        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)

    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1:
        st.markdown(
            f"""
<div class="info-card">
  <div class="info-card-icon">💡</div>
  <div class="info-card-title">The Idea</div>
  <div class="info-card-body">
    A lottery should be <b>provable</b> — not just "trust us".
    LOTTO surfaces live on-chain pool data, ticket purchases, and
    round states so anyone can verify every draw independently.
  </div>
</div>""",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            """
<div class="info-card">
  <div class="info-card-icon">⚙️</div>
  <div class="info-card-title">How It Works</div>
  <div class="info-card-body">
    <span class="step">1</span> Connect your wallet<br/>
    <span class="step">2</span> Approve USDT spend<br/>
    <span class="step">3</span> Buy tickets &amp; receive a range<br/>
    <span class="step">4</span> Draw happens on-chain automatically
  </div>
</div>""",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            """
<div class="info-card">
  <div class="info-card-icon">🦊</div>
  <div class="info-card-title">Wallets</div>
  <div class="info-card-body">
    Use <b>MetaMask</b> to buy tickets and sign transactions.<br/><br/>
    Use <b>Manual Address</b> to view the dashboard in read-only
    mode without connecting a wallet.
  </div>
</div>""",
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)

    st.markdown(
        f'<div class="muted" style="text-align:center; padding:18px 0; font-size:11px;">'
        f'LOTTO · Contract: {fmt_addr(LOTTO_CONTRACT)} · '
        f'<a href="https://bscscan.com/address/{LOTTO_CONTRACT}" target="_blank">View on BscScan ↗</a></div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────
PRIZE_SPLIT = {
    "1st (40%)":  40,
    "2nd (25%)":  25,
    "3rd (15%)":  15,
    "4th (10%)":  10,
    "5th (5%)":    5,
    "6th (5%)":    5,
    "Admin (20%)": 20,
}

def render_dashboard():
    render_toasts()

    wallet = st.session_state.wallet

    # Show connect card if no wallet — but DO NOT return (so stats still show)
    if not wallet:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('### <span class="yh">Connect via Address</span>', unsafe_allow_html=True)
        st.markdown('<div class="muted">Paste your wallet address to view your ticket purchases.</div>', unsafe_allow_html=True)
        st.text_input("Wallet address", key="manual_input",
                      placeholder="0x1234…abcd", label_visibility="visible")
        b1, b2 = st.columns([1, 1], gap="small")
        with b1:
            st.button("✅ Use Address", on_click=submit_manual, key="dash_manual_submit")
        with b2:
            st.link_button("🦊 Open Buy Page", st.session_state.buy_dapp_url)
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # If wallet exists, show the dashboard hero strip
    if wallet:
        hl, hr = st.columns([1.1, 1], gap="large")
        with hl:
            rid = rsnap.get("round_id") if rsnap else None
            st.markdown(f'<span class="pill">{"ROUND #"+str(rid) if rid else "LIVE"}</span>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="muted" style="font-size:12px; margin-top:8px;">'
                f'Wallet: <b style="color:{ACCENT}">✏️ {fmt_addr(wallet)}</b>'
                f'</div>',
                unsafe_allow_html=True,
            )

            st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
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

            st.markdown(
                f'<div class="muted" style="font-size:11px; margin-top:10px;">'
                f'Contract: <code>{fmt_addr(LOTTO_CONTRACT)}</code> · '
                f'USDT: <code>{fmt_addr(USDT)}</code> · {abi_ok}'
                f'</div>',
                unsafe_allow_html=True,
            )

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
                st.metric("Admin BNB",    f"{snap['a_bnb']:.4f}")
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

        # My Tickets panel only if wallet exists and they clicked it
        if st.session_state.ui_mode == "my_tickets":
            st.markdown('<div class="card">', unsafe_allow_html=True)
            h1, h2 = st.columns([10, 1])
            with h1:
                st.markdown('### <span class="yh">🎟️ My Tickets</span>', unsafe_allow_html=True)
            with h2:
                st.button("✕", on_click=lambda: st.session_state.update(ui_mode="home"), key="my_close")

            if not lotto_c:
                st.warning("ABI not loaded — add `lotto_abi.json` to read TicketsBought events.")
                st.markdown(f"[🔍 View events on BscScan](https://bscscan.com/address/{LOTTO_CONTRACT}#events)")
            else:
                lookback = st.slider("Lookback blocks", 10_000, 300_000, 120_000, 10_000, key="my_lookback")
                with st.spinner("Fetching ticket purchases…"):
                    purchases = get_tickets_for_wallet(wallet, lookback_blocks=int(lookback))

                if not purchases:
                    st.info("No TicketsBought events found in the selected lookback range.")
                else:
                    rounds = sorted({p["round"] for p in purchases}, reverse=True)
                    pick_round = st.selectbox("Round", rounds, index=0, key="my_round_select")
                    subset = [p for p in purchases if p["round"] == pick_round]
                    expand = st.checkbox("Expand ticket numbers (qty ≤ 50)", value=False, key="my_expand")

                    for p in subset:
                        qty2  = int(p["qty"])
                        start = int(p["first"])
                        end   = int(p["last"])
                        tx    = p["tx"]
                        st.markdown(
                            f'<div class="ticket-row">'
                            f'<div style="font-weight:950;">Round #{p["round"]} · Qty: {qty2}</div>'
                            f'<div class="muted" style="font-size:12px; margin-top:6px;">'
                            f'Tickets: <b>{start}</b> → <b>{end}</b><br/>'
                            f'Tx: <a href="https://bscscan.com/tx/{tx}" target="_blank">{fmt_addr(tx)} ↗</a>'
                            f'</div></div>',
                            unsafe_allow_html=True,
                        )
                        if expand and qty2 <= 50:
                            st.code(", ".join(map(str, range(start, end + 1))), language="text")

            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # ✅ Analytics row ALWAYS (wallet or not)
    c1, c2, c3 = st.columns(3, gap="large")

    with c1:
        st.markdown('#### <span class="yh">🏆 Prize Structure</span>', unsafe_allow_html=True)
        st.plotly_chart(donut(PRIZE_SPLIT), use_container_width=True, config={"displayModeBar": False})
        for lbl, pct in PRIZE_SPLIT.items():
            st.write(f"**{lbl}** — {pool * pct / 100:,.2f} {sym}")

    with c2:
        st.markdown('#### <span class="yh">🧾 Recent Transfers</span>', unsafe_allow_html=True)
        logs = snap.get("logs", []) or []
    
        if not logs:
            st.caption("No inbound USDT transfers found in the last 5,000 blocks.")
        else:
            for lg in logs:
                amt = float(lg.get("amount", 0.0))
                sym2 = lg.get("symbol", sym)
                blk2 = int(lg.get("block", 0))
                frm2 = lg.get("from", "0x0")
                tx2  = lg.get("tx", "")
    
                # show tiny transfers properly
                pretty = f"{amt:,.6f}" if amt >= 0.01 else f"{amt:.12f}".rstrip("0").rstrip(".")
    
                st.markdown(
                    f'<div class="tx-row">'
                    f'<div class="tx-amount">+{pretty} {sym2}</div>'
                    f'<div class="tx-meta">'
                    f'Block {blk2:,} · from {fmt_addr(frm2)} · '
                    f'<a href="https://bscscan.com/tx/{tx2}" target="_blank">{fmt_addr(tx2)} ↗</a>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

    with c3:
        st.markdown('#### <span class="yh">📈 Platform Stats</span>', unsafe_allow_html=True)
        st.metric("USDT (Contract)", f"{snap['c_usdt']:,.2f} {sym}")
        st.metric("USDT (Admin)",    f"{snap['a_usdt']:,.2f} {sym}")
        st.metric("BNB (Contract)",  f"{snap['c_bnb']:.6f}")
        st.metric("BNB (Admin)",     f"{snap['a_bnb']:.6f}")
        st.caption(f"RPC: {ACTIVE_RPC}")
        st.caption(f"Admin: {fmt_addr(ADMIN)}")


# ─────────────────────────────────────────────────────────────────────────────
# Main router
# ─────────────────────────────────────────────────────────────────────────────
render_nav()
render_tab_strip()

if st.session_state.active_tab == "landing":
    render_landing()
else:
    render_dashboard()
