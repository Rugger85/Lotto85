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
ACCENT         = "#62c1e5"

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

# ─────────────────────────────────────────────────────────────────────────────
# Cached chain snapshots (safe calls only)
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
        tp_units = safe(lambda: int(lotto_c.functions.ticketPrice().call()))
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
# Neon (LAZY) — ONLY used on Dashboard after wallet connect
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

def db_insert_from_tx(engine: Engine, tx_hash: str) -> int:
    tx_hash = tx_hash.strip().lower()
    if not tx_hash.startswith("0x") or len(tx_hash) != 66:
        raise ValueError("Invalid tx hash")

    receipt = w3.eth.get_transaction_receipt(tx_hash)
    if not receipt:
        raise ValueError("Receipt not found")

    inserted = 0
    for lg in receipt["logs"]:
        if Web3.to_checksum_address(lg["address"]) != LOTTO_ADDR:
            continue
        try:
            ev = lotto_c.events.TicketsBought().process_log(lg)
            args = ev["args"]

            payload = dict(
                chain_id=int(CHAIN_ID),
                contract_addr=LOTTO_ADDR.lower(),
                buyer=Web3.to_checksum_address(args["buyer"]).lower(),
                round_id=int(args["roundId"]),
                qty=int(args["qty"]),
                first_ticket_id=int(args["firstTicketId"]),
                last_ticket_id=int(args["lastTicketId"]),
                tx_hash=tx_hash,
                block_number=int(receipt["blockNumber"]),
                log_index=int(lg["logIndex"]),
            )

            upsert = text("""
                INSERT INTO tickets_bought
                (chain_id, contract_addr, buyer, round_id, qty, first_ticket_id, last_ticket_id,
                 tx_hash, block_number, log_index)
                VALUES
                (:chain_id, :contract_addr, :buyer, :round_id, :qty, :first_ticket_id, :last_ticket_id,
                 :tx_hash, :block_number, :log_index)
                ON CONFLICT DO NOTHING
            """)

            with engine.begin() as conn:
                conn.execute(upsert, payload)

            inserted += 1
        except Exception:
            continue

    return inserted

# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
st.session_state.setdefault("wallet", None)
st.session_state.setdefault("active_tab", "landing")  # landing/dashboard

def do_disconnect():
    st.session_state.wallet = None
    st.session_state.active_tab = "landing"
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
#MainMenu, header, footer,[data-testid="stToolbar"],[data-testid="stStatusWidget"]{{display:none!important}}
[data-testid="stAppViewContainer"]{{
  background:
    radial-gradient(ellipse 1200px 600px at 12% 14%,  rgba(98,193,229,.12)  0%, transparent 56%),
    radial-gradient(ellipse  900px 500px at 88% 18%,  rgba(0,190,255,.08)  0%, transparent 55%),
    radial-gradient(ellipse  900px 500px at 60% 90%,  rgba(190,0,255,.06)  0%, transparent 55%),
    linear-gradient(180deg,#06080d 0%,#07090f 100%)!important;
  color:#e9eef7!important
}}
a{{color:{ACCENT}!important;text-decoration:none}} a:hover{{text-decoration:underline}}
.pill{{display:inline-block;padding:4px 12px;border-radius:999px;background:rgba(98,193,229,.14);border:1px solid rgba(98,193,229,.28);color:{ACCENT};font-size:11px;font-weight:900;letter-spacing:.6px;text-transform:uppercase}}
.card{{background:rgba(15,19,31,.86);border:1px solid rgba(255,255,255,.08);border-radius:18px;padding:18px}}
.hdiv{{height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.12),transparent);margin:18px 0}}
.big{{font-size:44px;font-weight:950;color:{ACCENT};line-height:1}}
</style>
""", unsafe_allow_html=True)

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
draw_short = rsnap.get("draw_short", "N/A") if rsnap else "N/A"
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
# Landing (UNCHANGED BEHAVIOR)
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
    # price = lotto_c.functions.ticketPrice().call()
    # st.write(price)
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
# Dashboard (Neon tickets only after wallet)
# ─────────────────────────────────────────────────────────────────────────────
else:
    wallet = st.session_state.wallet
    if not wallet:
        st.info("Paste wallet on Home to view your tickets.")
        st.stop()

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.write(f"Wallet: **{fmt_addr(wallet)}**")
    st.write(f"Pool: **{pool:,.2f} {sym}** · Ticket Price: **{price_str}** · Tickets Sold: **{sold}**")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # Neon engine created ONLY here (and cached)
    engine = get_engine()
    if not engine:
        st.warning("DATABASE_URL / NEON_DSN not set. Add it in Streamlit secrets to show tickets from Neon.")
        st.stop()

    st.subheader("🎟️ My Tickets (from Neon)")

    rows = []
    try:
        rows = db_get_tickets(engine, wallet)
    except Exception as e:
        st.error(f"Neon query failed: {e}")
        st.stop()

    if not rows:
        st.warning("No tickets found in Neon yet.")
        st.caption("If you bought already: use Backfill below with your tx hash to insert that purchase without scanning logs.")
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

    with st.expander("Backfill a past purchase by Tx Hash (no scanning)", expanded=False):
        tx = st.text_input("Tx hash", placeholder="0x...")
        if st.button("Backfill into Neon"):
            try:
                n = db_insert_from_tx(engine, tx)
                st.success(f"Inserted {n} TicketsBought event(s) from receipt.")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(str(e))
