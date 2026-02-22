# app.py
# ---------------------------------------
# LOTTOLOTTERY (BSC Mainnet) Streamlit UI
# MetaMask connect (if available) + Manual wallet input (read-only)
# On-chain stats via Web3.py + USDT Transfer logs
# ---------------------------------------

# -----------------------------
# LOAD ENV FIRST
# -----------------------------
from dotenv import load_dotenv
import os

load_dotenv()

NETWORK = os.getenv("NETWORK", "bsc")
CHAIN_ID = int(os.getenv("CHAIN_ID", "56"))
BSC_RPC = os.getenv("BSC_RPC", "").strip()
LOTTO_CONTRACT_ADDR = os.getenv("LOTTO_CONTRACT", "").strip()
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "").strip()
ADMIN_WALLET = os.getenv("ADMIN_WALLET", "").strip()
LOTTO_ABI_PATH = os.getenv("LOTTO_ABI_PATH", "lotto_abi.json").strip()

if not BSC_RPC:
    raise ValueError("BSC_RPC not found in .env")
if not LOTTO_CONTRACT_ADDR:
    raise ValueError("LOTTO_CONTRACT not found in .env")
if not USDT_ADDRESS:
    raise ValueError("USDT_ADDRESS not found in .env")
if not ADMIN_WALLET:
    raise ValueError("ADMIN_WALLET not found in .env")

# -----------------------------
# Imports
# -----------------------------
import json
from datetime import datetime, timezone
import streamlit as st
import plotly.graph_objects as go
from web3 import Web3
from web3.exceptions import BadFunctionCallOutput

# Optional MetaMask bridge (browser-side JS). If not installed, app still works with manual wallet.
try:
    from streamlit_javascript import st_javascript
except Exception:
    st_javascript = None

st.set_page_config(page_title="LOTTOLOTTERY", layout="wide")

# -----------------------------
# Web3 setup
# -----------------------------
w3 = Web3(Web3.HTTPProvider(BSC_RPC))
if not w3.is_connected():
    raise RuntimeError("Failed to connect to BSC RPC. Check BSC_RPC in .env.")

LOTTO_CONTRACT = Web3.to_checksum_address(LOTTO_CONTRACT_ADDR)
USDT = Web3.to_checksum_address(USDT_ADDRESS)
ADMIN = Web3.to_checksum_address(ADMIN_WALLET)

# Minimal ERC20 ABI (balances + decimals/symbol)
ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

usdt_contract = w3.eth.contract(address=USDT, abi=ERC20_ABI)

# Load Lotto ABI (full artifact OR abi-array only)
LOTTO_ABI = None
if os.path.exists(LOTTO_ABI_PATH):
    try:
        with open(LOTTO_ABI_PATH, "r", encoding="utf-8") as f:
            abi_json = json.load(f)
            LOTTO_ABI = abi_json.get("abi", abi_json)
    except Exception:
        LOTTO_ABI = None

lotto_contract = w3.eth.contract(address=LOTTO_CONTRACT, abi=LOTTO_ABI) if LOTTO_ABI else None

# -----------------------------
# Helpers
# -----------------------------
def fmt_addr(a: str) -> str:
    a = str(a or "")
    return a[:6] + "..." + a[-4:] if a.startswith("0x") and len(a) > 10 else a

def wei_to_bnb(wei: int) -> float:
    return float(wei) / 1e18

def token_to_float(raw: int, decimals: int) -> float:
    return float(raw) / float(10 ** int(decimals))

def safe_call(fn, default=None):
    try:
        return fn()
    except (BadFunctionCallOutput, ValueError, Exception):
        return default

def padded_topic_address(addr: str) -> str:
    return "0x" + "0" * 24 + addr.lower().replace("0x", "")

def _fmt_dt(ts: int) -> str:
    if not ts or int(ts) <= 0:
        return "N/A"
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        return "N/A"

def _state_text(state: int) -> str:
    mapping = {0: "Pending", 1: "Live", 2: "Sales Closed", 3: "Drawn"}
    return mapping.get(int(state), f"State {int(state)}")

def build_snapshot(w3, lotto_contract):
    """
    Reads Lotto contract round fields + ticketPrice (requires LOTTO_ABI).
    Returns empty dict if ABI missing / call fails.
    """
    snap = {}
    if not lotto_contract:
        return snap

    try:
        cr = lotto_contract.functions.currentRound().call()
        # (state, drawTimestamp, salesCloseTimestamp, ticketsSold, startTicketId, commitHash)
        snap["round_state"] = int(cr[0])
        snap["draw_ts"] = int(cr[1])
        snap["sales_close_ts"] = int(cr[2])
        snap["tickets_sold"] = int(cr[3])
        snap["start_ticket_id"] = int(cr[4])
        snap["draw_human"] = _fmt_dt(snap["draw_ts"])
        snap["sales_close_human"] = _fmt_dt(snap["sales_close_ts"])
        snap["round_state_text"] = _state_text(snap["round_state"])

        try:
            snap["round_id"] = int(lotto_contract.functions.roundId().call())
        except Exception:
            snap["round_id"] = None

        # USDT meta (prefer lotto.usdt() if available)
        usdt_decimals = None
        usdt_symbol = None
        try:
            usdt_addr = lotto_contract.functions.usdt().call()
            _u = w3.eth.contract(address=Web3.to_checksum_address(usdt_addr), abi=[
                {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
            ])
            usdt_decimals = safe_call(lambda: _u.functions.decimals().call(), None)
            usdt_symbol = safe_call(lambda: _u.functions.symbol().call(), None)
        except Exception:
            pass

        if usdt_decimals is None:
            usdt_decimals = safe_call(lambda: usdt_contract.functions.decimals().call(), 18)
        if usdt_symbol is None:
            usdt_symbol = safe_call(lambda: usdt_contract.functions.symbol().call(), "USDT")

        snap["usdt_decimals"] = int(usdt_decimals)
        snap["usdt_symbol"] = str(usdt_symbol)

        # ticketPrice()
        try:
            ticket_units = int(lotto_contract.functions.ticketPrice().call())
            snap["ticket_price_units"] = ticket_units
            denom = 10 ** int(snap["usdt_decimals"])
            snap["ticket_price_human"] = f"{ticket_units / denom:,.6f} {snap['usdt_symbol']}"
        except Exception:
            snap["ticket_price_units"] = None
            snap["ticket_price_human"] = "N/A"

        return snap
    except Exception:
        return snap

# -----------------------------
# Cache on-chain reads
# -----------------------------
@st.cache_data(ttl=15)
def get_chain_snapshot(lookback_blocks: int = 5000, max_logs: int = 15):
    usdt_decimals = safe_call(lambda: usdt_contract.functions.decimals().call(), 18)
    usdt_symbol = safe_call(lambda: usdt_contract.functions.symbol().call(), "USDT")

    contract_usdt_raw = safe_call(lambda: usdt_contract.functions.balanceOf(LOTTO_CONTRACT).call(), 0)
    admin_usdt_raw = safe_call(lambda: usdt_contract.functions.balanceOf(ADMIN).call(), 0)

    contract_bnb_wei = safe_call(lambda: w3.eth.get_balance(LOTTO_CONTRACT), 0)
    admin_bnb_wei = safe_call(lambda: w3.eth.get_balance(ADMIN), 0)

    contract_usdt = token_to_float(contract_usdt_raw, usdt_decimals)
    admin_usdt = token_to_float(admin_usdt_raw, usdt_decimals)

    latest_block = w3.eth.block_number
    from_block = max(0, latest_block - int(lookback_blocks))

    transfer_topic0 = Web3.keccak(text="Transfer(address,address,uint256)").hex()
    to_topic = padded_topic_address(LOTTO_CONTRACT)

    logs = []
    try:
        raw_logs = w3.eth.get_logs({
            "fromBlock": from_block,
            "toBlock": latest_block,
            "address": USDT,
            "topics": [transfer_topic0, None, to_topic],
        })
        raw_logs = list(reversed(raw_logs))[: max_logs]
        for lg in raw_logs:
            txh = lg["transactionHash"].hex()
            blk = lg["blockNumber"]
            from_addr = "0x" + lg["topics"][1].hex()[-40:]
            to_addr = "0x" + lg["topics"][2].hex()[-40:]
            value_raw = int(lg["data"], 16)
            value = token_to_float(value_raw, usdt_decimals)

            logs.append({
                "block": int(blk),
                "tx": txh,
                "from": Web3.to_checksum_address(from_addr),
                "to": Web3.to_checksum_address(to_addr),
                "amount": float(value),
                "symbol": str(usdt_symbol),
            })
    except Exception:
        logs = []

    # Lotto-specific (if ABI exists): use build_snapshot() (more reliable than guessing names)
    lotto_snap = build_snapshot(w3, lotto_contract) if lotto_contract else {}

    return {
        "latest_block": int(latest_block),
        "from_block": int(from_block),
        "usdt_decimals": int(usdt_decimals),
        "usdt_symbol": str(usdt_symbol),
        "contract_usdt": float(contract_usdt),
        "admin_usdt": float(admin_usdt),
        "contract_bnb": float(wei_to_bnb(contract_bnb_wei)),
        "admin_bnb": float(wei_to_bnb(admin_bnb_wei)),
        "logs": logs,
        "lotto": lotto_snap,
    }

def donut_figure(split: dict):
    labels = list(split.keys())
    values = list(split.values())

    fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.72, sort=False, textinfo="none")])
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=240,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig

# -----------------------------
# CSS (fixes: button colors, panel sizing, no overflow)
# -----------------------------
st.markdown(
    """
<style>
/* Background */
.stApp {
  background: radial-gradient(1200px 600px at 20% 20%, rgba(245,196,0,0.10), transparent 55%),
              radial-gradient(900px 500px at 80% 30%, rgba(245,196,0,0.08), transparent 60%),
              linear-gradient(180deg, #05070c 0%, #070a0f 35%, #05070c 100%);
  color: #e9eef7;
}

/* Remove Streamlit chrome */
#MainMenu {visibility: hidden;}
header {visibility: hidden;}
footer {visibility: hidden;}
div.block-container {padding-top: 1.2rem; padding-bottom: 2.2rem;}

/* Width */
.maxw { max-width: 1180px; margin: 0 auto; }

/* Navbar */
.navbar {
  position: sticky; top: 0; z-index: 50;
  backdrop-filter: blur(10px);
  background: rgba(6, 8, 14, 0.55);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 16px;
  padding: 12px 16px;
  margin: 0 auto 18px auto;
}
.navrow { display:flex; align-items:center; justify-content:space-between; gap: 12px; }
.brand { display:flex; align-items:center; gap: 10px; font-weight: 900; letter-spacing: 0.2px; }
.badge {
  display:inline-flex; align-items:center; justify-content:center;
  width: 28px; height: 28px;
  font-size: 12px; color: #0b0f18; background: #f5c400;
  border-radius: 999px; font-weight: 950;
}
.navlinks { display:flex; align-items:center; gap: 14px; color: rgba(233,238,247,0.88); font-size: 13px; flex-wrap: wrap; }

/* Hero */
.heroTag {
  display:inline-flex; align-items:center; gap: 8px;
  background: rgba(245,196,0,0.10);
  color: rgba(245,196,0,0.95);
  border: 1px solid rgba(245,196,0,0.22);
  padding: 6px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 900;
}
.h1 { font-size: 54px; line-height: 1.05; margin: 14px 0 10px 0; font-weight: 950; letter-spacing: 0.6px; }
.h1 .gold { color: #f5c400; text-shadow: 0 10px 45px rgba(245,196,0,0.18); }
.p { color: rgba(233,238,247,0.70); font-size: 14px; line-height: 1.6; max-width: 520px; }

/* Cards */
.glow {
  border-radius: 18px; padding: 18px;
  background: linear-gradient(180deg, rgba(18,22,34,0.75), rgba(12,16,26,0.75));
  border: 1px solid rgba(255,255,255,0.08);
  box-shadow: 0 0 0 1px rgba(255,255,255,0.03) inset,
              0 40px 120px rgba(0,0,0,0.55),
              0 0 80px rgba(245,196,0,0.08);
}
.cardTitle { color: rgba(233,238,247,0.60); font-size: 11px; letter-spacing: 1.2px; text-transform: uppercase; font-weight: 900; }
.bigMoney { font-size: 44px; font-weight: 950; margin-top: 6px; }

.miniGrid { display:grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
.miniBox {
  background: rgba(6,8,14,0.55);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 12px;
  padding: 12px;
}
.miniLabel { font-size: 11px; color: rgba(233,238,247,0.60); }
.miniValue { font-size: 18px; font-weight: 950; margin-top: 4px; }

hr.soft {
  border: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.10), transparent);
  margin: 26px 0;
}

.sectionTitle { text-align:center; font-weight: 950; letter-spacing: 0.6px; margin-top: 8px; }
.sectionSub { text-align:center; color: rgba(233,238,247,0.60); font-size: 12px; max-width: 700px; margin: 6px auto 0 auto; }

/* Make Streamlit buttons match theme (fixes white buttons) */
div.stButton > button {
  width: 100%;
  border-radius: 10px !important;
  font-weight: 900 !important;
  border: 1px solid rgba(255,255,255,0.16) !important;
  background: rgba(6,8,14,0.35) !important;
  color: rgba(233,238,247,0.92) !important;
}
div.stButton > button:hover {
  border-color: rgba(245,196,0,0.65) !important;
  box-shadow: 0 10px 30px rgba(245,196,0,0.10) !important;
}
div.stButton > button:focus { outline: none !important; }

/* Yellow primary button helper */
.primaryBtn div.stButton > button {
  background: #f5c400 !important;
  color: #0b0f18 !important;
  border: 0 !important;
  box-shadow: 0 10px 30px rgba(245,196,0,0.18) !important;
}

/* Fix bordered containers to look like your panels */
div[data-testid="stVerticalBlockBorderWrapper"]{
  border-radius: 16px !important;
  background: linear-gradient(180deg, rgba(18,22,34,0.72), rgba(12,16,26,0.72)) !important;
  border: 1px solid rgba(255,255,255,0.08) !important;
  box-shadow: 0 30px 100px rgba(0,0,0,0.45) !important;
}

/* Prevent plotly overflow */
.js-plotly-plot, .plot-container { max-width: 100% !important; overflow: hidden !important; }

.smallMuted { color: rgba(233,238,247,0.55); font-size: 12px; }
@media (max-width: 1100px) { .h1 { font-size: 44px; } }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------
# Session state (UI + wallet)
# -----------------------------
if "ui_mode" not in st.session_state:
    st.session_state.ui_mode = "home"  # home | buy | my_tickets
if "wallet" not in st.session_state:
    st.session_state.wallet = ""       # active wallet checksum address
if "wallet_mode" not in st.session_state:
    st.session_state.wallet_mode = "manual"  # manual | metamask

def short_addr(a: str) -> str:
    if not a:
        return "Not connected"
    return f"{a[:6]}...{a[-4:]}"

def connect_wallet_metamask():
    """
    Prompts MetaMask and returns:
      - address string
      - "__NO_METAMASK__" if not detected
      - "__REJECTED__" if rejected
      - "__NO_ACCOUNT__" if no account returned
    """
    if not st_javascript:
        return "__NO_METAMASK__"

    res = st_javascript("""
    async () => {
      try {
        if (!window.ethereum) return "__NO_METAMASK__";
        const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
        return (accounts && accounts.length) ? accounts[0] : "__NO_ACCOUNT__";
      } catch (e) {
        return "__REJECTED__";
      }
    }
    """)
    return res

# -----------------------------
# Refresh / pull chain data
# -----------------------------
topbar = st.columns([1, 5])
with topbar[0]:
    if st.button("🔄 Refresh on-chain stats", key="refresh"):
        st.cache_data.clear()

snap = get_chain_snapshot()
lotto_snap = snap.get("lotto", {}) or {}
LOTTO_ABI_LOADED = bool(lotto_contract)

# Prize split
PRIZE_SPLIT = {"1st Prize": 40, "2nd Prize": 25, "3rd Prize": 15, "Admin Fee": 20}

# -----------------------------
# Wrapper start
# -----------------------------
st.markdown('<div class="maxw">', unsafe_allow_html=True)

# -----------------------------
# Navbar (NO duplicate connect buttons)
# -----------------------------
network_badge = "BSC Mainnet" if CHAIN_ID == 56 else f"Chain {CHAIN_ID}"
wallet_display = fmt_addr(st.session_state.wallet) if st.session_state.wallet else "Not connected"

st.markdown(
    f"""
<div class="navbar">
  <div class="navrow">
    <div class="brand">
      <div class="badge">🟡</div>
      <div>LOTTOLOTTERY</div>
    </div>
    <div class="navlinks">
      <span>{network_badge}</span>
      <span style="opacity:0.6;">|</span>
      <span style="opacity:0.9;">Wallet: {wallet_display}</span>
      <span style="opacity:0.6;">|</span>
      <span style="opacity:0.9;">Admin: {fmt_addr(ADMIN)}</span>
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# -----------------------------
# Wallet controls (MetaMask + Manual)  ✅ gives you a field to paste address
# -----------------------------
c1, c2, c3 = st.columns([1.2, 2.4, 1.4], gap="small")

with c1:
    st.session_state.wallet_mode = st.radio(
        "Wallet mode",
        ["manual", "metamask"],
        horizontal=True,
        label_visibility="collapsed",
        index=0 if st.session_state.wallet_mode == "manual" else 1,
        key="wallet_mode_radio",
    )

with c2:
    if st.session_state.wallet_mode == "manual":
        entered = st.text_input(
            "Wallet address",
            value=st.session_state.wallet or "",
            placeholder="Paste wallet address (0x...) for read-only mode",
            label_visibility="collapsed",
            key="manual_wallet_input",
        ).strip()
        if entered:
            if Web3.is_address(entered):
                st.session_state.wallet = Web3.to_checksum_address(entered)
            else:
                st.error("Invalid wallet address. Must start with 0x and be 42 chars.")
    else:
        st.caption("MetaMask must be installed/enabled in THIS browser profile (try http://localhost:8501).")

with c3:
    if st.session_state.wallet_mode == "metamask":
        st.markdown('<div class="primaryBtn">', unsafe_allow_html=True)
        clicked = st.button("🔗 Connect Wallet", key="mm_connect_btn")
        st.markdown("</div>", unsafe_allow_html=True)
        if clicked:
            res = connect_wallet_metamask()
            if res == "__NO_METAMASK__":
                st.warning("MetaMask not detected. Install/enable the extension (try Chrome or Opera profile with MetaMask).")
            elif res == "__REJECTED__":
                st.warning("Connection rejected in MetaMask.")
            elif res == "__NO_ACCOUNT__" or not res:
                st.warning("No account returned from MetaMask.")
            else:
                st.session_state.wallet = Web3.to_checksum_address(res)
    else:
        st.markdown('<div class="smallMuted" style="text-align:right; padding-top:8px;">Read-only mode</div>', unsafe_allow_html=True)

# -----------------------------
# Hero + Stats
# -----------------------------
left, right = st.columns([1.15, 1], gap="large")

with left:
    # Round label
    round_tag = "● ROUND LIVE" if LOTTO_ABI_LOADED else "● ROUND (ABI REQUIRED)"
    st.markdown(f'<div class="heroTag">{round_tag}</div>', unsafe_allow_html=True)

    st.markdown(
        f"""
<div class="h1">
  DECENTRALIZED<br/>
  <span class="gold">WEALTH DISTRIBUTION</span>
</div>
<div class="p">
BSC on-chain prize pool is tracked live via USDT balance of the Lotto contract. All transfers are visible and auditable.
</div>
""",
        unsafe_allow_html=True,
    )

    b1, b2 = st.columns(2, gap="small")
    with b1:
        st.markdown('<div class="primaryBtn">', unsafe_allow_html=True)
        if st.button("🟡 Buy Tickets Now ↗", key="btn_buy"):
            st.session_state.ui_mode = "buy"
        st.markdown("</div>", unsafe_allow_html=True)

    with b2:
        if st.button("🎟️ View My Tickets", key="btn_mytickets"):
            st.session_state.ui_mode = "my_tickets"

    # Contract info
    st.markdown(
        f"""
<div style="margin-top:18px; color: rgba(233,238,247,0.55); font-size: 12px;">
Contract: {fmt_addr(LOTTO_CONTRACT)} &nbsp; • &nbsp; USDT: {fmt_addr(USDT)}
</div>
""",
        unsafe_allow_html=True,
    )

with right:
    total_pool = float(snap.get("contract_usdt", 0.0))
    usdt_symbol = snap.get("usdt_symbol", "USDT")

    contract_bnb = float(snap.get("contract_bnb", 0.0))
    admin_bnb = float(snap.get("admin_bnb", 0.0))

    # From lotto snapshot if ABI loaded
    tickets_sold = lotto_snap.get("tickets_sold", None)
    round_id = lotto_snap.get("round_id", None)
    draw_text = lotto_snap.get("draw_human", "Not available (add Lotto ABI)") if LOTTO_ABI_LOADED else "Not available (add Lotto ABI)"
    ticket_price = lotto_snap.get("ticket_price_human", "N/A") if LOTTO_ABI_LOADED else "N/A"

    st.markdown(
        f"""
<div class="glow">
  <div class="cardTitle">Total Prize Pool (Contract USDT Balance)</div>
  <div class="bigMoney">{total_pool:,.2f} {usdt_symbol}</div>

  <div class="miniGrid">
    <div class="miniBox">
      <div class="miniLabel">Round</div>
      <div class="miniValue">{(round_id if round_id is not None else "—")}</div>
    </div>
    <div class="miniBox">
      <div class="miniLabel">Tickets Sold</div>
      <div class="miniValue">{(tickets_sold if tickets_sold is not None else "—")}</div>
    </div>
  </div>

  <div class="miniGrid" style="margin-top:12px;">
    <div class="miniBox">
      <div class="miniLabel">Contract BNB</div>
      <div class="miniValue">{contract_bnb:.4f}</div>
    </div>
    <div class="miniBox">
      <div class="miniLabel">Admin BNB</div>
      <div class="miniValue">{admin_bnb:.4f}</div>
    </div>
  </div>

  <div style="margin-top:12px; color: rgba(233,238,247,0.55); font-size: 12px;">
    Ticket Price: <span style="color: rgba(233,238,247,0.88); font-weight: 950;">{ticket_price}</span><br/>
    Next Draw: <span style="color: rgba(233,238,247,0.88); font-weight: 950;">{draw_text}</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

st.markdown("<hr class='soft'/>", unsafe_allow_html=True)

# -----------------------------
# Optional sections based on hero buttons
# -----------------------------
if st.session_state.ui_mode == "buy":
    with st.container(border=True):
        st.markdown("### 🟡 Buy Tickets")
        if not st.session_state.wallet:
            st.info("Connect your wallet (MetaMask) or paste a wallet address (manual).")
        st.write("This Streamlit app can show on-chain stats safely. **Sending transactions (approve + buyTickets) must be done in browser-side JS**.")
        st.caption("If you want, I’ll add the full MetaMask approve + buyTickets flow using an embedded JS component (ethers.js) and your ABI.")

elif st.session_state.ui_mode == "my_tickets":
    with st.container(border=True):
        st.markdown("### 🎟️ My Tickets")
        if not st.session_state.wallet:
            st.info("Connect your wallet (MetaMask) or paste a wallet address (manual).")
        else:
            st.write(f"Wallet: `{st.session_state.wallet}`")
            st.caption("Next step: query TicketsBought events for your wallet and list ticket ranges + tx hashes (needs Lotto ABI).")

# -----------------------------
# Mid section title + dynamic subtitle
# -----------------------------
st.markdown('<div class="sectionTitle">TRANSPARENT DISTRIBUTION</div>', unsafe_allow_html=True)

if LOTTO_ABI_LOADED and lotto_snap.get("round_id") is not None:
    sub = (
        f"Live round #{lotto_snap.get('round_id')} • "
        f"State: {lotto_snap.get('round_state_text','-')} • "
        f"Tickets sold: {lotto_snap.get('tickets_sold','-')} • "
        f"Next draw: {lotto_snap.get('draw_human','-')}"
    )
else:
    sub = "Prize pool is computed from on-chain balances and transfers."

if not LOTTO_ABI_LOADED:
    sub += " For full stats, add lotto_abi.json (or set LOTTO_ABI_PATH)."

st.markdown(f'<div class="sectionSub">{sub}</div>', unsafe_allow_html=True)
st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

# -----------------------------
# Bottom panels (ALL inside bordered containers -> no “out of box”)
# -----------------------------
col1, col2, col3 = st.columns(3, gap="large")

with col1:
    with st.container(border=True):
        st.markdown("**🏆 Prize Structure**  \nHow the pool is split")
        fig = donut_figure(PRIZE_SPLIT)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key="donut_main")
        st.caption("• 1st Prize   • 2nd Prize   • 3rd Prize   • Admin Fee")

with col2:
    with st.container(border=True):
        st.markdown("**🧾 Recent USDT Transfers**  \nTransfers to the Lotto contract (on-chain)")
        logs = snap.get("logs", []) or []
        if not logs:
            st.markdown("<div class='smallMuted' style='margin-top:10px;'>No recent USDT transfers found in the lookback window.</div>", unsafe_allow_html=True)
        else:
            for lg in logs[:10]:
                st.markdown(
                    f"""
<div class="smallMuted" style="margin-bottom:10px;">
  <b>{lg["amount"]:.2f} {lg["symbol"]}</b>
  <span style="opacity:0.55;">from</span> {fmt_addr(lg["from"])}
  <span style="opacity:0.55;">(blk {lg["block"]})</span><br/>
  <span style="opacity:0.55;">tx</span> {fmt_addr(lg["tx"])}
</div>
""",
                    unsafe_allow_html=True,
                )

with col3:
    with st.container(border=True):
        st.markdown("**📈 Platform Stats**  \nBalances and configuration")
        st.markdown(
            f"""
<div style="margin-top:10px;">
  <div class="miniLabel">USDT Balance (Admin)</div>
  <div style="font-size:22px; font-weight:950; margin-top:6px;">{snap["admin_usdt"]:,.2f} {snap["usdt_symbol"]}</div>
</div>
<div style="margin-top:14px;">
  <div class="miniLabel">Latest Block</div>
  <div style="font-size:18px; font-weight:950; margin-top:6px;">{snap["latest_block"]:,}</div>
</div>
<div style="margin-top:14px;">
  <div class="miniLabel">RPC</div>
  <div class="smallMuted" style="margin-top:6px;">{BSC_RPC}</div>
</div>
<div style="margin-top:14px;">
  <div class="miniLabel">ABI Status</div>
  <div class="smallMuted" style="margin-top:6px;">
    {"✅ Lotto ABI loaded" if LOTTO_ABI_LOADED else "⚠️ Lotto ABI not loaded (balances-only mode)"}
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

# -----------------------------
# Wrapper end
# -----------------------------
st.markdown("</div>", unsafe_allow_html=True)
