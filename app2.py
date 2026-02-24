from __future__ import annotations

import os, json
from pathlib import Path
from datetime import datetime, timezone

import psycopg2
import streamlit as st
import plotly.graph_objects as go
from web3 import Web3


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="LOTTO", layout="wide", page_icon="🎰")

def cfg(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            v = st.secrets[key]
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
NEON_DSN       = cfg("NEON_DSN", "")
BUY_DAPP_URL   = cfg("BUY_DAPP_URL", "https://rugger85.github.io/Lotto85/wallet_buy.html")
ACCENT         = "#62c1e5"

missing = [k for k, v in {
    "BSC_RPC": BSC_RPC,
    "LOTTO_CONTRACT": LOTTO_ADDR,
    "USDT_ADDRESS": USDT_ADDR,
    "ADMIN_WALLET": ADMIN_ADDR,
    "NEON_DSN": NEON_DSN,
}.items() if not v]

if missing:
    st.error("Missing secrets/env: " + ", ".join(missing))
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
# Neon helpers
# ─────────────────────────────────────────────────────────────────────────────
def db():
    return psycopg2.connect(NEON_DSN)

def q_all(sql: str, params=()):
    with db() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
        return cols, rows

def exec_sql(sql: str, params=()):
    with db() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# UI helpers
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

def ts_short(t: int | None) -> str:
    if not t or int(t) <= 0:
        return "N/A"
    return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%b %d, %Y")

def state_lbl(s: int) -> str:
    return {0: "🟢 Open", 1: "🔒 Sales Closed", 2: "🎉 Drawn"}.get(int(s), f"State {s}")

def donut(split: dict[str, float]):
    fig = go.Figure(go.Pie(labels=list(split.keys()), values=list(split.values()), hole=0.68, sort=False, textinfo="none"))
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=220, showlegend=False, paper_bgcolor="rgba(0,0,0,0)")
    return fig


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

        return dict(round_id=rid, state=state, sold=sold, draw_short=ts_short(draw_ts), price_str=price_str)
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Neon tickets (THIS is how you show TicketIDs without scanning chain)
# ─────────────────────────────────────────────────────────────────────────────
def db_get_tickets(buyer: str):
    buyer = buyer.lower()
    sql = """
    SELECT round_id, qty, first_ticket_id, last_ticket_id, tx_hash, block_number, created_at
    FROM tickets_bought
    WHERE chain_id = %s AND contract_addr = %s AND buyer = %s
    ORDER BY block_number DESC, created_at DESC
    LIMIT 200;
    """
    _, rows = q_all(sql, (CHAIN_ID, LOTTO_ADDR.lower(), buyer))
    return rows

def db_insert_from_tx(tx_hash: str):
    """
    One-time backfill: fetch receipt, decode TicketsBought log, insert into Neon.
    Works without getLogs scanning.
    """
    tx_hash = tx_hash.strip()
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
            buyer = Web3.to_checksum_address(args["buyer"]).lower()
            exec_sql(
                """
                INSERT INTO tickets_bought
                (chain_id, contract_addr, buyer, round_id, qty, first_ticket_id, last_ticket_id, tx_hash, block_number, log_index)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING;
                """,
                (
                    CHAIN_ID,
                    LOTTO_ADDR.lower(),
                    buyer,
                    int(args["roundId"]),
                    int(args["qty"]),
                    int(args["firstTicketId"]),
                    int(args["lastTicketId"]),
                    tx_hash.lower(),
                    int(receipt["blockNumber"]),
                    int(lg["logIndex"]),
                )
            )
            inserted += 1
        except Exception:
            continue

    return inserted


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
st.session_state.setdefault("wallet", None)
st.session_state.setdefault("active_tab", "landing")
st.session_state.setdefault("ui_mode", "home")


# ─────────────────────────────────────────────────────────────────────────────
# CSS (kept minimal)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
#MainMenu, header, footer,[data-testid="stToolbar"],[data-testid="stStatusWidget"]{{display:none!important}}
[data-testid="stAppViewContainer"]{{
  background:linear-gradient(180deg,#06080d 0%,#07090f 100%)!important;color:#e9eef7!important
}}
a{{color:{ACCENT}!important;text-decoration:none}} a:hover{{text-decoration:underline}}
.pill{{display:inline-block;padding:4px 12px;border-radius:999px;background:rgba(98,193,229,.14);border:1px solid rgba(98,193,229,.28);color:{ACCENT};font-size:11px;font-weight:900;letter-spacing:.6px;text-transform:uppercase}}
.card{{background:rgba(15,19,31,.86);border:1px solid rgba(255,255,255,.08);border-radius:18px;padding:18px}}
.hdiv{{height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.12),transparent);margin:18px 0}}
.big{{font-size:44px;font-weight:950;color:{ACCENT};line-height:1}}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Render
# ─────────────────────────────────────────────────────────────────────────────
snap = get_snap()
rsnap = get_round_snap()
sym = snap["sym"]
pool = snap["c_usdt"]
net_badge = "BSC Mainnet" if CHAIN_ID == 56 else f"Chain {CHAIN_ID}"
abi_ok = "✅ ABI Loaded"

PRIZE_SPLIT = {"1st (40%)":40,"2nd (25%)":25,"3rd (15%)":15,"4th (10%)":10,"5th (5%)":5,"6th (5%)":5,"Admin (20%)":20}

# Top bar
l, r = st.columns([2,3], gap="small")
with l:
    st.markdown("### 🎰 LOTTO")
    st.markdown(f'<span class="pill">{net_badge}</span> &nbsp; Block: <b>{snap["block"]:,}</b> · {abi_ok}', unsafe_allow_html=True)
with r:
    c1, c2 = st.columns([1.3,1.0], gap="small")
    with c1:
        st.link_button("🦊 Open Buy Page", BUY_DAPP_URL)
    with c2:
        if st.session_state.wallet:
            if st.button("Disconnect ✕"):
                st.session_state.wallet = None
                st.session_state.active_tab = "landing"
                st.session_state.ui_mode = "home"
                st.rerun()

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

# Tabs
t1, t2, _ = st.columns([1,1,6])
with t1:
    if st.button("🏠 Home"):
        st.session_state.active_tab = "landing"; st.rerun()
with t2:
    if st.button("📊 Dashboard"):
        st.session_state.active_tab = "dashboard"; st.rerun()

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

if st.session_state.active_tab == "landing":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(f"<span class='pill'>Transparent · On-Chain · Auditable</span>", unsafe_allow_html=True)
    st.markdown(f"<div class='big'>LOTTO</div>", unsafe_allow_html=True)
    st.write(f"Pool: **{pool:,.2f} {sym}**")
    st.write(f"Round: **{state_lbl(rsnap.get('state',0))}** · Tickets sold: **{rsnap.get('sold','—')}** · Price: **{rsnap.get('price_str','—')}**")
    st.write("Enter wallet to view tickets (read-only):")
    w = st.text_input("Wallet address", placeholder="0x...", label_visibility="collapsed")
    if st.button("✅ Use Address"):
        try:
            st.session_state.wallet = Web3.to_checksum_address(w)
            st.session_state.active_tab = "dashboard"
            st.rerun()
        except Exception:
            st.error("Invalid address.")
    st.markdown('</div>', unsafe_allow_html=True)

else:
    wallet = st.session_state.wallet

    if not wallet:
        st.info("Paste wallet on Home to view your tickets.")
        st.stop()

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.write(f"Wallet: **{fmt_addr(wallet)}**")
    st.write(f"Pool: **{pool:,.2f} {sym}** · Ticket Price: **{rsnap.get('price_str','—')}** · Tickets Sold: **{rsnap.get('sold','—')}**")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # Backfill by tx hash (optional)
    with st.expander("Backfill a past purchase by Tx Hash (no scanning)", expanded=False):
        tx = st.text_input("Tx hash", placeholder="0x...")
        if st.button("Backfill into Neon"):
            try:
                n = db_insert_from_tx(tx)
                st.success(f"Inserted {n} TicketsBought event(s) from receipt.")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(str(e))

    # My Tickets from Neon
    st.subheader("🎟️ My Tickets (from Neon)")
    rows = db_get_tickets(wallet)

    if not rows:
        st.warning("No tickets found in Neon yet. (Indexer may not have run, or you need backfill).")
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
            hide_index=True
        )

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    c1, c2 = st.columns([1,1])
    with c1:
        st.subheader("🏆 Prize Structure")
        st.plotly_chart(donut(PRIZE_SPLIT), use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.subheader("📈 Platform Stats")
        st.metric("USDT (Contract)", f"{snap['c_usdt']:,.2f} {sym}")
        st.metric("USDT (Admin)", f"{snap['a_usdt']:,.2f} {sym}")
        st.metric("BNB (Contract)", f"{snap['c_bnb']:.6f}")
        st.metric("BNB (Admin)", f"{snap['a_bnb']:.6f}")
