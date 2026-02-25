from __future__ import annotations

import os, json
from pathlib import Path
from datetime import datetime, timezone

import streamlit as st
import plotly.graph_objects as go
from web3 import Web3

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ─────────────────────────────────────────────────────────────────────────────
# Streamlit setup
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="LOTTO", layout="wide", page_icon="🎰")

# ─────────────────────────────────────────────────────────────────────────────
# Global CSS
# ─────────────────────────────────────────────────────────────────────────────
ACCENT = "#62c1e5"
st.markdown(
    f"""
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

.yh    {{ color:{ACCENT} !important; font-size:24px; font-weight:900 !important; }}
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
  font-size:20px;
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

.tx-row {{
  padding:12px 14px;
  border-radius:14px;
  border:1px solid rgba(255,255,255,.08);
  background:rgba(15,19,31,.72);
  margin-bottom:8px;
}}
.tx-amount {{ font-weight:950; color:{ACCENT}; }}
.tx-meta   {{ font-size:12px; color:rgba(233,238,247,.55); margin-top:4px; }}

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
""",
    unsafe_allow_html=True,
)

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


CHAIN_ID       = int(cfg("CHAIN_ID", "56"))
BSC_RPC        = cfg("BSC_RPC", "")
LOTTO_ADDR     = cfg("LOTTO_CONTRACT", "")
USDT_ADDR      = cfg("USDT_ADDRESS", "")
ADMIN_ADDR     = cfg("ADMIN_WALLET", "")
ABI_PATH       = cfg("LOTTO_ABI_PATH", "lotto_abi.json")
DATABASE_URL   = cfg("DATABASE_URL", cfg("NEON_DSN", ""))
BUY_DAPP_URL   = cfg("BUY_DAPP_URL", "https://rugger85.github.io/Lotto85/wallet_buy.html")

ACTIVE_RPC = BSC_RPC  # used in stats area
ADMIN = ADMIN_ADDR    # used in stats area

missing = [k for k, v in {
    "BSC_RPC": BSC_RPC,
    "LOTTO_CONTRACT": LOTTO_ADDR,
    "USDT_ADDRESS": USDT_ADDR,
    "ADMIN_WALLET": ADMIN_ADDR,
}.items() if not v]

if missing:
    st.error("Missing required secrets/env: " + ", ".join(missing))
    st.stop()

LOTTO_ADDR = Web3.to_checksum_address(LOTTO_ADDR)
USDT_ADDR  = Web3.to_checksum_address(USDT_ADDR)
ADMIN_ADDR = Web3.to_checksum_address(ADMIN_ADDR)

# ─────────────────────────────────────────────────────────────────────────────
# Web3 + ABI
# ─────────────────────────────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(BSC_RPC, request_kwargs={"timeout": 20}))
if not w3.is_connected():
    st.error("RPC connection failed. Check BSC_RPC.")
    st.stop()

def load_abi(path: str):
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).parent / path
    raw = json.loads(p.read_text(encoding="utf-8"))
    return raw["abi"] if isinstance(raw, dict) and "abi" in raw else raw

LOTTO_ABI = load_abi(ABI_PATH)
lotto_c = w3.eth.contract(address=LOTTO_ADDR, abi=LOTTO_ABI)

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

def donut(data: dict[str, int]) -> go.Figure:
    labels = list(data.keys())
    values = list(data.values())
    fig = go.Figure(
        data=[go.Pie(labels=labels, values=values, hole=0.62, sort=False)]
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        height=280,
    )
    return fig

def valid_wallet(s: str) -> bool:
    s = (s or "").strip()
    return s.startswith("0x") and len(s) == 42 and Web3.is_address(s)

# ─────────────────────────────────────────────────────────────────────────────
# Cached chain snapshots
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
    try:
        rid = int(lotto_c.functions.roundId().call())
        cr  = lotto_c.functions.currentRound().call()
        state    = int(cr[0]) if len(cr) > 0 else 0
        draw_ts  = int(cr[1]) if len(cr) > 1 else 0
        close_ts = int(cr[2]) if len(cr) > 2 else 0
        sold     = int(cr[3]) if len(cr) > 3 else 0

        dec = int(safe(lambda: usdt_c.functions.decimals().call(), 18))
        sym = safe(lambda: usdt_c.functions.symbol().call(), "USDT")
        tp_units = safe(lambda: int(lotto_c.functions.ticketPrice().call()), 0)
        price_str = f"{(tp_units or 0) / 10**dec:,.4f} {sym}" if tp_units is not None else "N/A"

        return dict(
            round_id=rid, state=state, sold=sold,
            draw_ts=draw_ts, close_ts=close_ts,
            draw_str=ts(draw_ts), close_str=ts(close_ts),
            draw_short=ts_short(draw_ts),
            price_str=price_str
        )
    except Exception:
        return {}

# ─────────────────────────────────────────────────────────────────────────────
# Neon helpers (ONLY used in Dashboard after wallet)
# ─────────────────────────────────────────────────────────────────────────────
def _normalize_db_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url

@st.cache_resource
def get_engine() -> Engine | None:
    url = _normalize_db_url(DATABASE_URL)
    if not url:
        return None
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=3,
        pool_timeout=15,
    )

def db_get_tickets(engine: Engine, buyer: str):
    sql = text("""
        SELECT round_id, qty, first_ticket_id, last_ticket_id, tx_hash, block_number, created_at
        FROM tickets_bought
        WHERE chain_id = :chain_id
          AND contract_addr = :contract
          AND buyer = :buyer
        ORDER BY block_number DESC, created_at DESC
        LIMIT 200
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, dict(
            chain_id=int(CHAIN_ID),
            contract=LOTTO_ADDR.lower(),
            buyer=buyer.lower(),
        )).fetchall()
    return rows

# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
st.session_state.setdefault("wallet", None)
st.session_state.setdefault("active_tab", "landing")  # landing/dashboard

def do_disconnect():
    st.session_state.wallet = None
    st.session_state.active_tab = "landing"
    st.rerun()

def set_wallet_and_go(addr: str):
    st.session_state.wallet = Web3.to_checksum_address(addr.strip())
    st.session_state.active_tab = "dashboard"
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────
snap = get_snap()
rsnap = get_round_snap()

sym = snap["sym"]
pool = snap["c_usdt"]
net_badge = "BSC Mainnet" if CHAIN_ID == 56 else f"Chain {CHAIN_ID}"
stt = state_lbl(rsnap.get("state", 0)) if rsnap else "—"
sold = rsnap.get("sold", "—") if rsnap else "—"
price_str = rsnap.get("price_str", "N/A") if rsnap else "N/A"
close_str = rsnap.get("close_str", "N/A") if rsnap else "N/A"
draw_str  = rsnap.get("draw_str", "N/A") if rsnap else "N/A"

# ─────────────────────────────────────────────────────────────────────────────
# Top bar
# ─────────────────────────────────────────────────────────────────────────────
l, r = st.columns([2, 3], gap="small")
with l:
    st.markdown("### 🎰 LOTTO")
    st.markdown(
        f'<span class="pill">{net_badge}</span> &nbsp; Block: <b>{snap["block"]:,}</b>',
        unsafe_allow_html=True
    )
with r:
    c1, c2 = st.columns([1.3, 1.0], gap="small")
    with c1:
        st.link_button("🦊 Open Buy Page", BUY_DAPP_URL)
    with c2:
        if st.session_state.wallet:
            st.button("Disconnect ✕", on_click=do_disconnect)

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

# Tabs
t1, t2, _ = st.columns([1, 1, 6])
with t1:
    if st.button("🏠 Home"):
        st.session_state.active_tab = "landing"
        st.rerun()
with t2:
    if st.button("📊 Dashboard"):
        st.session_state.active_tab = "dashboard"
        st.rerun()

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Landing (keep same, plus wallet input)
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.active_tab == "landing":
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

        # # Wallet input to unlock dashboard
        # st.markdown('<div class="card">', unsafe_allow_html=True)
        # st.markdown('### <span class="yh">Connect via Address</span>', unsafe_allow_html=True)
        # st.markdown('<div class="muted">Paste your wallet address to view your ticket purchases.</div>', unsafe_allow_html=True)

        # addr = st.text_input(
        #     "Wallet address",
        #     key="manual_wallet",
        #     placeholder="0x1234…abcd",
        #     label_visibility="visible"
        # )
        # b1, b2 = st.columns([1, 1], gap="small")
        # with b1:
        #     if st.button("✅ Use Address", key="use_addr_btn"):
        #         if not valid_wallet(addr):
        #             st.error("Please enter a valid wallet address (0x… 42 chars).")
        #         else:
        #             set_wallet_and_go(addr)
        # with b2:
        #     st.link_button("🦊 Open Buy Page", BUY_DAPP_URL)

        # st.markdown('</div>', unsafe_allow_html=True)

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

# ─────────────────────────────────────────────────────────────────────────────
# Dashboard (ONLY renders analytics when wallet exists)
# ─────────────────────────────────────────────────────────────────────────────
else:
    wallet = st.session_state.wallet
    if not wallet:
        st.info("Paste wallet on Home to view your tickets.")
        st.stop()

    # st.markdown('<div class="card">', unsafe_allow_html=True)
    st.write(f"Wallet: **{fmt_addr(wallet)}**")
    st.write(f"Pool: **{pool:,.2f} {sym}** · Ticket Price: **{price_str}** · Tickets Sold: **{sold}**")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # Neon engine created ONLY here (and cached)
    engine = get_engine()
    if not engine:
        st.warning("DATABASE_URL / NEON_DSN not set. Add it in Streamlit secrets to show tickets from Neon.")
        st.stop()

    st.subheader("🎟️ My Tickets")

    try:
        rows = db_get_tickets(engine, wallet)
    except Exception as e:
        st.error(f"Neon query failed: {e}")
        st.stop()

    if not rows:
        st.warning("No tickets found for this wallet.")
    else:
        st.dataframe(
            [{
                "Round": r[0],
                "Qty": r[1],
                "Ticket Range": f"{r[2]} → {r[3]}",
                "Tx": r[4],
                "Block": r[5],
                "Time": str(r[6]) if r[6] else "",
            } for r in rows],
            use_container_width=True,
            hide_index=True,
        )

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # Analytics section (only in dashboard + wallet connected)
    PRIZE_SPLIT = {
        "1st (40%)":  40,
        "2nd (25%)":  25,
        "3rd (15%)":  15,
        "4th (10%)":  10,
        "5th (5%)":    5,
        "6th (5%)":    5,
        "Admin (20%)": 20,
    }

    c1, c2, c3 = st.columns(3, gap="large")

    with c1:
        st.markdown('#### <span class="yh">🏆 Prize Structure</span>', unsafe_allow_html=True)
        st.plotly_chart(donut(PRIZE_SPLIT), use_container_width=True, config={"displayModeBar": False})
        for lbl, pct in PRIZE_SPLIT.items():
            st.write(f"**{lbl}** — {pool * pct / 100:,.2f} {sym}")

    with c2:
        st.markdown('#### <span class="yh">🧾 Recent Transfers</span>', unsafe_allow_html=True)
        st.caption("Coming soon (optional on-chain transfer scan).")

    with c3:
        st.markdown('#### <span class="yh">📈 Platform Stats</span>', unsafe_allow_html=True)
        st.metric("USDT (Contract)", f"{snap['c_usdt']:,.2f} {sym}")
        st.metric("USDT (Admin)",    f"{snap['a_usdt']:,.2f} {sym}")
        st.metric("BNB (Contract)",  f"{snap['c_bnb']:.6f}")
        st.metric("BNB (Admin)",     f"{snap['a_bnb']:.6f}")
        st.caption(f"RPC: {ACTIVE_RPC}")
        st.caption(f"Admin: {fmt_addr(ADMIN)}")
