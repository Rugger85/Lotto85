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
st.set_page_config(page_title="LOTTOLOTTERY", layout="wide", page_icon="🎰")


# ─────────────────────────────────────────────────────────────────────────────
# Config (Streamlit Cloud: st.secrets, Local: .env)
# ─────────────────────────────────────────────────────────────────────────────
def cfg(key: str, default: str = "") -> str:
    if key in st.secrets:
        return str(st.secrets[key])
    return os.getenv(key, default)

CHAIN_ID            = int(cfg("CHAIN_ID", "56"))
BSC_RPC_PRIMARY     = cfg("BSC_RPC", "")
LOTTO_CONTRACT_ADDR = cfg("LOTTO_CONTRACT", "")
USDT_ADDRESS        = cfg("USDT_ADDRESS", "")
ADMIN_WALLET        = cfg("ADMIN_WALLET", "")
LOTTO_ABI_PATH      = cfg("LOTTO_ABI_PATH", "lotto_abi.json")

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
        "Missing required config. Add these in Streamlit Cloud Secrets later:\n\n"
        + ", ".join(missing)
    )
    st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Web3 connect (with RPC fallback)
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
    st.error("Cannot connect to BSC RPC (all endpoints failed). Add a paid RPC in Secrets for stability.")
    st.stop()

LOTTO_CONTRACT = Web3.to_checksum_address(LOTTO_CONTRACT_ADDR)
USDT           = Web3.to_checksum_address(USDT_ADDRESS)
ADMIN          = Web3.to_checksum_address(ADMIN_WALLET)


# ─────────────────────────────────────────────────────────────────────────────
# ABIs
# ─────────────────────────────────────────────────────────────────────────────
ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol",   "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "a", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "name": "allowance",
     "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

usdt_c = w3.eth.contract(address=USDT, abi=ERC20_ABI)

LOTTO_ABI = None
if os.path.exists(LOTTO_ABI_PATH):
    try:
        raw = json.load(open(LOTTO_ABI_PATH, "r", encoding="utf-8"))
        LOTTO_ABI = raw.get("abi", raw)
    except Exception:
        LOTTO_ABI = None

lotto_c = w3.eth.contract(address=LOTTO_CONTRACT, abi=LOTTO_ABI) if LOTTO_ABI else None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def now_ts() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())

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

def fmt_countdown(seconds: int) -> str:
    if seconds <= 0:
        return "0s"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d > 0:
        return f"{d}d {h}h {m}m"
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def state_lbl(s: int) -> str:
    # Contract enum: 0=OPEN, 1=SALES_CLOSED, 2=DRAWN
    return {
        0: "🟢 OPEN",
        1: "🔒 SALES CLOSED",
        2: "🎉 DRAWN",
    }.get(int(s), f"State {s}")

def pad_topic_addr(addr: str) -> str:
    return "0x" + "0" * 24 + addr.lower().replace("0x", "")

def donut(split: dict[str, float]):
    fig = go.Figure(go.Pie(labels=list(split.keys()), values=list(split.values()), hole=0.68, sort=False, textinfo="none"))
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=210, showlegend=False)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Cacheable on-chain snapshots
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

    # Recent inbound USDT transfers to contract (last ~5000 blocks)
    logs = []
    try:
        topic0 = Web3.keccak(text="Transfer(address,address,uint256)").hex()
        rls = list(reversed(w3.eth.get_logs({
            "fromBlock": max(0, blk - 5000),
            "toBlock": blk,
            "address": USDT,
            "topics": [topic0, None, pad_topic_addr(LOTTO_CONTRACT)],
        })))[:10]

        for lg in rls:
            logs.append({
                "block": int(lg["blockNumber"]),
                "tx": lg["transactionHash"].hex(),
                "from": Web3.to_checksum_address("0x" + lg["topics"][1].hex()[-40:]),
                "amount": tok(int(lg["data"], 16), dec),
                "symbol": sym
            })
    except Exception:
        pass

    return dict(
        block=blk,
        dec=dec,
        sym=sym,
        c_usdt=tok(c_raw, dec),
        a_usdt=tok(a_raw, dec),
        c_bnb=bnb(c_bnb),
        a_bnb=bnb(a_bnb),
        logs=logs
    )

@st.cache_data(ttl=15)
def get_round_snap():
    if not lotto_c:
        return {}

    try:
        rid = safe(lambda: int(lotto_c.functions.roundId().call()))
        cr  = lotto_c.functions.currentRound().call()

        # UsdtLottoManual.currentRound():
        # (state, drawTimestamp, salesCloseTimestamp, ticketsSold, startTicketId, commitHash)
        state     = int(cr[0]) if len(cr) > 0 else 0
        draw_ts   = int(cr[1]) if len(cr) > 1 else 0
        close_ts  = int(cr[2]) if len(cr) > 2 else 0
        sold      = int(cr[3]) if len(cr) > 3 else 0
        start_id  = int(cr[4]) if len(cr) > 4 else None

        # Pull USDT metadata from contract USDT address if available
        dec = None
        sym = None
        try:
            uaddr = lotto_c.functions.usdt().call()
            um = w3.eth.contract(address=uaddr, abi=ERC20_ABI)
            dec = int(um.functions.decimals().call())
            sym = str(um.functions.symbol().call())
        except Exception:
            dec = None
            sym = None

        tp_units = safe(lambda: int(lotto_c.functions.ticketPrice().call()))
        price_str = "N/A"
        if tp_units is not None:
            d = dec if dec is not None else get_snap()["dec"]
            s = sym if sym is not None else get_snap()["sym"]
            price_str = f"{tp_units / 10**d:,.4f} {s}"

        # Winner % + admin fee
        admin_bps = safe(lambda: int(lotto_c.functions.adminFeeBps().call()), None)
        wps = []
        try:
            for i in range(6):
                wps.append(int(lotto_c.functions.winnerPct(i).call()))
        except Exception:
            wps = []

        return dict(
            round_id=rid,
            state=state,
            draw_ts=draw_ts,
            close_ts=close_ts,
            sold=sold,
            start_id=start_id,
            draw_str=ts(draw_ts),
            close_str=ts(close_ts),
            price_units=tp_units,
            price_str=price_str,
            dec=dec if dec is not None else get_snap()["dec"],
            sym=sym if sym is not None else get_snap()["sym"],
            admin_bps=admin_bps,
            winner_pcts=wps
        )
    except Exception:
        return {}

@st.cache_data(ttl=60)
def get_tickets_for_wallet(wallet: str, lookback_blocks: int = 120_000):
    """
    Reads TicketsBought events for wallet; returns list of purchases:
    [{round, qty, start, end, tx, block}]
    """
    if not lotto_c:
        return []

    wallet = Web3.to_checksum_address(wallet)
    latest = int(w3.eth.block_number)
    frm = max(0, latest - int(lookback_blocks))

    out = []
    try:
        evs = lotto_c.events.TicketsBought.create_filter(
            from_block=frm,
            to_block="latest",
            argument_filters={"buyer": wallet}
        ).get_all_entries()

        for ev in evs:
            args = ev["args"]
            out.append({
                "round": int(args.get("roundId")),
                "qty": int(args.get("qty")),
                "cost": int(args.get("cost")),
                "start": int(args.get("firstTicketId")),
                "end": int(args.get("lastTicketId")),
                "tx": ev["transactionHash"].hex(),
                "block": int(ev["blockNumber"]),
            })
        out.sort(key=lambda x: x["block"], reverse=True)
        return out
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
for k, v in dict(
    wallet=None,
    wallet_type=None,   # "metamask" / "manual"
    show_manual=False,
    manual_input="",
    ui_mode="home",
    buy_qty=1,
    tx_status=None,
    tx_value=None,
).items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# Wallet connect callbacks
# ─────────────────────────────────────────────────────────────────────────────
def open_manual():
    st.session_state.show_manual = True

def close_manual():
    st.session_state.show_manual = False
    st.session_state.manual_input = ""

def do_disconnect():
    for k in ["wallet", "wallet_type", "tx_status", "tx_value"]:
        st.session_state[k] = None
    close_manual()

def do_connect_metamask():
    if not HAS_JS:
        st.session_state.show_manual = True
        st.session_state.tx_status = "no_js"
        return

    res = st_javascript("""
async () => {
  try {
    if (!window.ethereum) return {ok:false, err:"no_metamask"};
    const a = await window.ethereum.request({method:'eth_requestAccounts'});
    return {ok:true, address: a && a.length ? a[0] : null};
  } catch(e) {
    return {ok:false, err: e && e.message ? e.message : String(e)};
  }
}
""")
    if isinstance(res, dict) and res.get("ok") and res.get("address"):
        st.session_state.wallet = res["address"]
        st.session_state.wallet_type = "metamask"
        st.session_state.show_manual = False
    else:
        st.session_state.tx_status = "mm_fail"
        st.session_state.tx_value = (res.get("err") if isinstance(res, dict) else "Unknown error")

def submit_manual():
    raw = (st.session_state.get("manual_input") or "").strip()
    if not raw:
        st.session_state.tx_status = "manual_empty"
        return
    try:
        st.session_state.wallet = Web3.to_checksum_address(raw)
        st.session_state.wallet_type = "manual"
        st.session_state.show_manual = False
        st.session_state.manual_input = ""
        st.session_state.tx_status = "manual_ok"
    except Exception:
        st.session_state.tx_status = "manual_bad"


# ─────────────────────────────────────────────────────────────────────────────
# UI styling (minimal)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
#MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stStatusWidget"] {display:none!important;}
[data-testid="stAppViewContainer"]{
  background: radial-gradient(ellipse 1100px 550px at 12% 16%,rgba(245,196,0,.06) 0%,transparent 55%),
              linear-gradient(180deg,#06080d 0%,#07090f 100%) !important;
  color: #e9eef7 !important;
}
.card{
  background: rgba(15,19,31,.85);
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 16px;
  padding: 16px;
}
.pill{
  display:inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(245,196,0,.12);
  border: 1px solid rgba(245,196,0,.28);
  color: #f5c400;
  font-size: 11px;
  font-weight: 800;
}
.muted{ color: rgba(233,238,247,.55); }
.big{ font-size: 40px; font-weight: 900; color:#f5c400; line-height:1; }
.hdiv{ height:1px; background:linear-gradient(90deg,transparent,rgba(255,255,255,.10),transparent); margin:18px 0; }
.btnrow div.stButton>button{ width:100%; border-radius:12px; font-weight:800; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────────────────────────────────────
snap  = get_snap()
rsnap = get_round_snap()

sym = snap["sym"]
pool = snap["c_usdt"]
wallet = st.session_state.wallet
is_mm = st.session_state.wallet_type == "metamask"
is_manual = st.session_state.wallet_type == "manual"

net_badge = "BSC Mainnet" if CHAIN_ID == 56 else f"Chain {CHAIN_ID}"
abi_txt = "✅ ABI Loaded" if lotto_c else "⚠️ ABI not loaded (add lotto_abi.json)"

# Time-based sales close (important!)
now = now_ts()
close_ts = int(rsnap.get("close_ts") or 0) if rsnap else 0
draw_ts  = int(rsnap.get("draw_ts") or 0) if rsnap else 0
sales_closed_by_time = (close_ts > 0 and now >= close_ts)
draw_ready_by_time   = (draw_ts > 0 and now >= draw_ts)


# ─────────────────────────────────────────────────────────────────────────────
# Navbar
# ─────────────────────────────────────────────────────────────────────────────
l, m, r = st.columns([1.4, 3.5, 1.7], gap="small")

with l:
    st.markdown(f"### 🎰 LOTTOLOTTERY")
with m:
    st.markdown(
        f'<div class="muted">'
        f'<span class="pill">{net_badge}</span> &nbsp;'
        f'Block: <b>{snap["block"]:,}</b> &nbsp;·&nbsp; '
        f'Admin: <b>{fmt_addr(ADMIN)}</b> &nbsp;·&nbsp; '
        f'Wallet: <b>{"Not connected" if not wallet else fmt_addr(wallet)}</b>'
        f'</div>',
        unsafe_allow_html=True
    )
with r:
    if not wallet:
        c1, c2 = st.columns(2, gap="small")
        with c1:
            st.button("🔗 Connect", on_click=do_connect_metamask)
        with c2:
            st.button("✏️ Manual", on_click=open_manual)
    else:
        st.button(f"{'🦊' if is_mm else '✏️'} {fmt_addr(wallet)} ✕", on_click=do_disconnect)

# Toasts
txs = st.session_state.tx_status
if txs == "manual_ok":
    st.success("✅ Address saved (read-only). Use MetaMask to buy.")
elif txs == "manual_bad":
    st.error("❌ Invalid address — must be 42 chars starting with 0x.")
elif txs == "manual_empty":
    st.warning("Please enter a wallet address.")
elif txs == "no_js":
    st.error("streamlit-javascript not installed. MetaMask actions disabled.")
elif txs == "mm_fail":
    st.warning(f"MetaMask connect failed: {st.session_state.tx_value}")
st.session_state.tx_status = None
st.session_state.tx_value = None


# ─────────────────────────────────────────────────────────────────────────────
# Manual connect panel
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.show_manual and not wallet:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("#### 🔗 Connect Wallet (Read-only)")
    st.markdown('<div class="muted">Paste a wallet address to view tickets/balances. Buying requires MetaMask.</div>', unsafe_allow_html=True)

    st.text_input("Wallet address", key="manual_input", placeholder="0x1234…abcd", label_visibility="collapsed")

    b1, b2 = st.columns(2, gap="small")
    with b1:
        st.button("✅ Use This Address", on_click=submit_manual)
    with b2:
        st.button("Cancel", on_click=close_manual)

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Hero
# ─────────────────────────────────────────────────────────────────────────────
hl, hr = st.columns([1.1, 1], gap="large")

with hl:
    rid = rsnap.get("round_id") if rsnap else None
    st.markdown(f'<span class="pill">{"ROUND #"+str(rid) if rid else "LIVE"}</span>', unsafe_allow_html=True)
    st.markdown("## DECENTRALIZED WEALTH DISTRIBUTION")
    st.markdown('<div class="muted">On-chain lottery with transparent pool and auditable ticket ranges.</div>', unsafe_allow_html=True)

    st.markdown('<div class="btnrow">', unsafe_allow_html=True)
    bA, bB, bC = st.columns(3, gap="small")
    with bA: st.button("🟡 Buy Tickets", on_click=lambda: st.session_state.update(ui_mode="buy"))
    with bB: st.button("🎟️ My Tickets", on_click=lambda: st.session_state.update(ui_mode="my_tickets"))
    with bC:
        if st.button("🔄 Refresh"):
            st.cache_data.clear()
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        f'<div class="muted" style="margin-top:10px">'
        f'Contract: <code>{fmt_addr(LOTTO_CONTRACT)}</code> &nbsp;·&nbsp; '
        f'USDT: <code>{fmt_addr(USDT)}</code> &nbsp;·&nbsp; {abi_txt}'
        f'</div>',
        unsafe_allow_html=True
    )

with hr:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="muted" style="font-size:11px; font-weight:800; letter-spacing:1px;">TOTAL PRIZE POOL</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="big">{pool:,.2f} <span style="font-size:16px; opacity:.75">{sym}</span></div>', unsafe_allow_html=True)

    sold = rsnap.get("sold", "—") if rsnap else "—"
    price = rsnap.get("price_str", "N/A") if rsnap else "N/A"

    # Effective status (time-aware)
    chain_state = int(rsnap.get("state", 0)) if rsnap else 0
    if chain_state == 2:
        stt = "🎉 DRAWN"
    elif sales_closed_by_time:
        stt = "🔒 SALES CLOSED"
    else:
        stt = "🟢 OPEN"

    draw_str = rsnap.get("draw_str", "N/A") if rsnap else "N/A"
    close_str = rsnap.get("close_str", "N/A") if rsnap else "N/A"

    a1, a2 = st.columns(2, gap="small")
    with a1:
        st.metric("Tickets Sold", sold)
        st.metric("Ticket Price", price)
    with a2:
        st.metric("Contract BNB", f"{snap['c_bnb']:.4f}")
        st.metric("Admin BNB", f"{snap['a_bnb']:.4f}")

    st.markdown(f'<div class="muted">State: <b>{stt}</b> &nbsp;·&nbsp; Next Draw: <b>{draw_str}</b></div>', unsafe_allow_html=True)

    if close_ts > 0 and chain_state != 2:
        if sales_closed_by_time:
            st.caption(f"Sales closed at: {close_str} (contract will show OPEN until owner calls closeSales())")
        else:
            st.caption(f"Sales close in: {fmt_countdown(close_ts - now)} · Close time: {close_str}")

    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# BUY PANEL (MetaMask approve + buyTickets)
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.ui_mode == "buy":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    h1, h2 = st.columns([8, 1])
    with h1: st.markdown("### 🟡 Buy Tickets")
    with h2: st.button("✕", on_click=lambda: st.session_state.update(ui_mode="home"))

    if not wallet:
        st.info("Connect MetaMask to buy tickets, or enter a wallet address for read-only mode.")
        c1, c2 = st.columns(2, gap="small")
        with c1: st.button("🦊 Connect MetaMask", on_click=do_connect_metamask)
        with c2: st.button("✏️ Manual", on_click=open_manual)
        st.markdown("</div>", unsafe_allow_html=True)

    elif is_manual:
        st.warning(f"Read-only mode: {fmt_addr(wallet)}. Buying requires MetaMask.")
        st.button("🦊 Switch to MetaMask", on_click=do_connect_metamask)
        st.markdown("</div>", unsafe_allow_html=True)

    else:
        if not lotto_c:
            st.error("ABI not loaded. Add lotto_abi.json to repo root so we can read ticket price & round details.")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            # Enforce time-based close in UI (matches contract rule)
            if sales_closed_by_time:
                st.error(f"Sales are CLOSED (since {ts(close_ts)}). You can’t buy tickets for this round.")
                st.caption("Note: Contract may still show state OPEN until the owner calls closeSales().")
                st.markdown("</div>", unsafe_allow_html=True)
                st.stop()
            else:
                if close_ts > 0:
                    st.info(f"Sales close in: {fmt_countdown(close_ts - now)} · Close time: {ts(close_ts)}")

            max_per_buy = safe(lambda: int(lotto_c.functions.maxTicketsPerBuy().call()), 100)
            qty = st.number_input(
                "Number of tickets",
                min_value=1,
                max_value=int(max_per_buy),
                value=int(st.session_state.buy_qty),
                step=1
            )
            st.session_state.buy_qty = int(qty)

            tp_units = rsnap.get("price_units")
            dec = rsnap.get("dec", snap["dec"])
            sym2 = rsnap.get("sym", snap["sym"])

            total_cost_units = None
            if tp_units is not None:
                total_cost_units = int(tp_units) * int(qty)
                st.success(f"Total cost: {total_cost_units / 10**dec:,.4f} {sym2}")
                st.caption(f"{qty} × {rsnap.get('price_str','N/A')}")

            if not HAS_JS:
                st.error("Install `streamlit-javascript` to enable MetaMask transactions.")
                st.markdown("</div>", unsafe_allow_html=True)
            elif total_cost_units is None:
                st.warning("Ticket price unavailable from contract.")
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                if st.button(f"🟡 Buy {qty} Ticket{'s' if qty > 1 else ''} via MetaMask"):
                    js = f"""
async()=>{{
  try {{
    if(!window.ethereum) return {{ok:false, err:"no_metamask"}};
    const {{ethers}} = await import('https://cdn.ethers.io/lib/ethers-5.7.umd.min.js');
    const provider = new ethers.providers.Web3Provider(window.ethereum);
    await provider.send('eth_requestAccounts', []);
    const signer = provider.getSigner();

    const usdt = new ethers.Contract(
      '{USDT}',
      ['function approve(address,uint256) returns(bool)',
       'function allowance(address,address) view returns(uint256)'],
      signer
    );

    const lotto = new ethers.Contract(
      '{LOTTO_CONTRACT}',
      ['function buyTickets(uint256) external'],
      signer
    );

    const amt = ethers.BigNumber.from('{int(total_cost_units)}');
    const me = await signer.getAddress();
    const alw = await usdt.allowance(me, '{LOTTO_CONTRACT}');
    if (alw.lt(amt)) {{
      const tx1 = await usdt.approve('{LOTTO_CONTRACT}', amt);
      await tx1.wait();
    }}

    const tx2 = await lotto.buyTickets({int(qty)});
    await tx2.wait();

    return {{ok:true, hash: tx2.hash}};
  }} catch(e) {{
    return {{ok:false, err: e && e.message ? e.message : String(e)}};
  }}
}}
"""
                    res = st_javascript(js)
                    if isinstance(res, dict) and res.get("ok"):
                        st.success(f"✅ Purchased! Tx: {res.get('hash')}")
                        st.markdown(f"[🔍 View on BscScan](https://bscscan.com/tx/{res.get('hash')})")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(f"❌ Failed: {(res.get('err') if isinstance(res, dict) else res)}")

                st.caption("Payouts are on-chain (contract stores ticket ownership).")
                st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# MY TICKETS PANEL (from TicketsBought events)
# ─────────────────────────────────────────────────────────────────────────────
elif st.session_state.ui_mode == "my_tickets":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    h1, h2 = st.columns([8, 1])
    with h1: st.markdown("### 🎟️ My Tickets")
    with h2: st.button("✕", on_click=lambda: st.session_state.update(ui_mode="home"))

    if not wallet:
        st.info("Connect or enter a wallet address to view tickets.")
        c1, c2 = st.columns(2, gap="small")
        with c1: st.button("🦊 Connect MetaMask", on_click=do_connect_metamask)
        with c2: st.button("✏️ Manual", on_click=open_manual)
        st.markdown("</div>", unsafe_allow_html=True)

    elif not lotto_c:
        st.warning("ABI not loaded — add lotto_abi.json so we can read TicketsBought events properly.")
        st.markdown(f"[🔍 View contract events on BscScan](https://bscscan.com/address/{LOTTO_CONTRACT}#events)")
        st.markdown("</div>", unsafe_allow_html=True)

    else:
        st.caption(f"Wallet: {wallet} ({'MetaMask' if is_mm else 'Read-only'})")

        lookback = st.slider("Lookback blocks", min_value=10_000, max_value=300_000, value=120_000, step=10_000)
        with st.spinner("Fetching ticket purchases…"):
            purchases = get_tickets_for_wallet(wallet, lookback_blocks=int(lookback))

        if not purchases:
            st.info("No TicketsBought events found in the selected lookback range.")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            rounds = sorted({p["round"] for p in purchases}, reverse=True)
            pick_round = st.selectbox("Round", rounds, index=0)

            subset = [p for p in purchases if p["round"] == pick_round]
            st.markdown(f"**{len(subset)} purchase(s) found in Round #{pick_round}:**")

            expand_small = st.checkbox("Expand into individual ticket numbers (only if qty ≤ 50)", value=False)

            for p in subset:
                qty = int(p["qty"])
                start = int(p["start"])
                end = int(p["end"])
                tx = p["tx"]

                st.markdown(
                    f"""
<div style="padding:14px;border-radius:14px;border:1px solid rgba(245,196,0,.18);background:rgba(245,196,0,.06);margin-bottom:10px;">
  <div style="font-weight:900;">Round #{p["round"]} · Qty: {qty}</div>
  <div class="muted" style="margin-top:6px;">
    Tickets: <b>{start}</b> → <b>{end}</b><br/>
    Tx: <a href="https://bscscan.com/tx/{tx}" target="_blank" style="color:#f5c400;text-decoration:none;">{fmt_addr(tx)} ↗</a>
  </div>
</div>
""",
                    unsafe_allow_html=True
                )

                if expand_small and qty <= 50:
                    ids = list(range(start, end + 1))
                    st.code(", ".join(map(str, ids)))

            st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Bottom analytics (always visible)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

# Dynamic prize split from contract if possible
PRIZE_SPLIT = {}
if rsnap and rsnap.get("winner_pcts") and rsnap.get("admin_bps") is not None:
    wps = rsnap["winner_pcts"]
    admin_pct = float(rsnap["admin_bps"]) / 100.0
    for i, pct in enumerate(wps, start=1):
        PRIZE_SPLIT[f"Winner #{i} ({pct}%)"] = float(pct)
    PRIZE_SPLIT[f"Admin Fee ({admin_pct:.2f}%)"] = float(admin_pct)
else:
    # fallback (avoid wrong numbers if ABI missing)
    PRIZE_SPLIT = {"Winners": 80, "Admin Fee": 20}

c1, c2, c3 = st.columns(3, gap="large")

with c1:
    st.markdown("#### 🏆 Prize Structure")
    st.plotly_chart(donut(PRIZE_SPLIT), use_container_width=True, config={"displayModeBar": False})
    for lbl, pct in PRIZE_SPLIT.items():
        st.write(f"{lbl}: **{pool * pct / 100:,.2f} {sym}**")

with c2:
    st.markdown("#### 🧾 Recent Transfers (USDT → Contract)")
    logs = snap.get("logs", [])
    if not logs:
        st.caption("No recent inbound transfers found in the lookback window.")
    else:
        for lg in logs:
            st.markdown(
                f"""
<div style="padding:12px;border-radius:12px;border:1px solid rgba(255,255,255,.08);background:rgba(15,19,31,.70);margin-bottom:8px;">
  <div style="font-weight:900;color:#f5c400;">+{lg["amount"]:.2f} {lg["symbol"]}</div>
  <div class="muted" style="font-size:12px;margin-top:4px;">
    blk {lg["block"]:,} · from {fmt_addr(lg["from"])} ·
    <a href="https://bscscan.com/tx/{lg["tx"]}" target="_blank" style="color:#f5c400;text-decoration:none;">{fmt_addr(lg["tx"])} ↗</a>
  </div>
</div>
""",
                unsafe_allow_html=True
            )

with c3:
    st.markdown("#### 📈 Platform Stats")
    st.write(f"USDT (Contract): **{snap['c_usdt']:,.2f} {sym}**")
    st.write(f"USDT (Admin): **{snap['a_usdt']:,.2f} {sym}**")
    st.write(f"BNB (Contract): **{snap['c_bnb']:.6f}**")
    st.write(f"BNB (Admin): **{snap['a_bnb']:.6f}**")
    st.write(f"Network: **{net_badge}**")
    st.write(f"ABI: **{'Loaded' if lotto_c else 'Not loaded'}**")
    st.caption(f"RPC: {ACTIVE_RPC}")

st.markdown(
    f'<div class="muted" style="text-align:center; padding:18px 0; font-size:11px;">'
    f'LOTTOLOTTERY · Contract {fmt_addr(LOTTO_CONTRACT)} · Refreshes ~15s</div>',
    unsafe_allow_html=True
)
