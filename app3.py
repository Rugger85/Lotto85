from __future__ import annotations

import os
import json
import time
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from web3 import Web3
from eth_abi import decode as abi_decode
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ─────────────────────────────────────────────────────────────────────────────
# Page setup
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="LOTTO85", layout="wide", page_icon="⚡")

# Lightweight keep-alive ping: does not reload the full app
components.html(
    """
    <script>
      setInterval(() => {
        fetch(window.location.href, { cache: "no-store" }).catch(() => {});
      }, 60000);
    </script>
    """,
    height=0,
)

ACCENT = "#62c1e5"

st.markdown(
    f"""
<style>
#MainMenu, header, footer,
[data-testid="stToolbar"],
[data-testid="stStatusWidget"] {{ display:none !important; }}

[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(ellipse 1200px 600px at 12% 14%, rgba(98,193,229,.12) 0%, transparent 56%),
    radial-gradient(ellipse 900px 500px at 88% 18%, rgba(0,190,255,.08) 0%, transparent 55%),
    linear-gradient(180deg, #06080d 0%, #07090f 100%) !important;
  color:#e9eef7 !important;
}}

a {{ color:{ACCENT} !important; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}

.hdiv {{ height:1px; background:linear-gradient(90deg,transparent,rgba(255,255,255,.12),transparent); margin:22px 0; }}
.muted {{ color:rgba(233,238,247,.62); }}
.yh {{ color:{ACCENT}; font-weight:950; }}
.card {{
  background:rgba(15,19,31,.88);
  border:1px solid rgba(255,255,255,.09);
  border-radius:20px;
  padding:20px;
  box-shadow:0 20px 55px rgba(0,0,0,.35);
}}
.pill {{
  display:inline-block;
  padding:5px 12px;
  border-radius:999px;
  background:rgba(98,193,229,.14);
  border:1px solid rgba(98,193,229,.28);
  color:{ACCENT};
  font-size:12px;
  font-weight:900;
  letter-spacing:.8px;
  text-transform:uppercase;
}}
.heroTitle {{ font-size:46px; font-weight:1000; line-height:1.05; margin:8px 0; }}
.kpi {{
  border:1px solid rgba(255,255,255,.09);
  background:rgba(255,255,255,.035);
  border-radius:18px;
  padding:16px;
}}
.kpi .t {{ font-size:11px; letter-spacing:1px; font-weight:900; color:rgba(233,238,247,.70); text-transform:uppercase; }}
.kpi .v {{ font-size:28px; font-weight:1000; color:{ACCENT}; margin-top:4px; line-height:1.1; }}
.kpi .s {{ font-size:12px; color:rgba(233,238,247,.64); margin-top:4px; }}

.disclaimer {{
  color:#ff4d4d;
  font-size:18px;
  font-weight:700;
  text-shadow:0 0 8px rgba(255,77,77,.45);
}}

div.stButton > button {{
  border-radius:14px !important;
  font-weight:850 !important;
  color:#e9eef7 !important;
  background:linear-gradient(135deg, rgba(255,255,255,.16), rgba(255,255,255,.06)) !important;
  border:1px solid rgba(255,255,255,.22) !important;
}}
div.stButton > button:hover {{
  border:1px solid rgba(98,193,229,.55) !important;
  background:linear-gradient(135deg, rgba(98,193,229,.28), rgba(98,193,229,.10)) !important;
}}

.odds-hero {{
  border:1px solid rgba(98,193,229,.24);
  background:linear-gradient(135deg, rgba(98,193,229,.13), rgba(255,255,255,.035));
  border-radius:22px;
  padding:18px;
}}
.odds-num {{ font-size:44px; line-height:1; font-weight:1000; color:{ACCENT}; }}

.winner-card {{
  border:1px solid rgba(98,193,229,.20);
  background:rgba(15,19,31,.90);
  border-radius:18px;
  padding:15px 16px;
  margin-bottom:10px;
}}
.winner-rank {{ font-size:12px; letter-spacing:1px; text-transform:uppercase; color:rgba(233,238,247,.60); font-weight:900; }}
.winner-amt {{ font-size:25px; font-weight:1000; color:{ACCENT}; }}
.winner-meta {{ font-size:12px; color:rgba(233,238,247,.64); }}
</style>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Config
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


CHAIN_ID = int(cfg("CHAIN_ID", "56"))
BSC_RPC = cfg("BSC_RPC", "")
LOTTO_ADDR = cfg("LOTTO_CONTRACT", "")
USDT_ADDR = cfg("USDT_ADDRESS", "")
ADMIN_ADDR = cfg("ADMIN_WALLET", "")
ABI_PATH = cfg("LOTTO_ABI_PATH", "lotto_abi.json")
DATABASE_URL = cfg("DATABASE_URL", cfg("NEON_DSN", ""))
BUY_DAPP_URL = cfg("BUY_DAPP_URL", "https://rugger85.github.io/Lotto85/wallet_buy.html")
MAX_TICKETS_PER_WALLET = int(cfg("MAX_TICKETS_PER_WALLET", "50"))

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
USDT_ADDR = Web3.to_checksum_address(USDT_ADDR)
ADMIN_ADDR = Web3.to_checksum_address(ADMIN_ADDR)

# ─────────────────────────────────────────────────────────────────────────────
# Web3 + contracts
# ─────────────────────────────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(BSC_RPC, request_kwargs={"timeout": 25}))
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
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "a", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]
usdt_c = w3.eth.contract(address=USDT_ADDR, abi=ERC20_ABI)

# ─────────────────────────────────────────────────────────────────────────────
# General helpers
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
    return float(raw or 0) / (10 ** int(dec))


def bnb(raw: int) -> float:
    return float(raw or 0) / 1e18


def ts_utc(t: int | None) -> str:
    if not t or int(t) <= 0:
        return "N/A"
    return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%b %d, %Y %H:%M UTC")


def state_lbl(s: int) -> str:
    return {0: "🟢 Open", 1: "🔒 Sales Closed", 2: "🎉 Drawn", 3: "❌ Cancelled"}.get(int(s), f"State {s}")


def valid_wallet(s: str) -> bool:
    return bool(s) and Web3.is_address(s.strip())


def pct(num: float, den: float) -> float:
    return (float(num) / float(den) * 100.0) if float(den or 0) > 0 else 0.0


def topic_uint256(n: int) -> str:
    return "0x" + int(n).to_bytes(32, "big").hex()


def bar_width(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return max(2.0, min(100.0, (float(value) / float(max_value)) * 100.0))


def odds_badge_html(label: str, qty: int, odds: float, max_qty: int) -> str:
    width = bar_width(qty, max_qty)
    return f"""
    <div style="padding:12px 14px; border:1px solid rgba(255,255,255,.08); border-radius:14px; background:rgba(255,255,255,.035); margin-bottom:8px;">
      <div style="display:flex; justify-content:space-between; gap:12px; align-items:center;">
        <div style="font-weight:900; color:#e9eef7;">{label}</div>
        <div style="font-weight:950; color:{ACCENT};">{odds:.2f}%</div>
      </div>
      <div style="font-size:12px; color:rgba(233,238,247,.60); margin:4px 0 8px;">{qty} ticket(s)</div>
      <div style="height:8px; border-radius:999px; overflow:hidden; background:rgba(255,255,255,.08);">
        <div style="width:{width:.2f}%; height:8px; background:linear-gradient(90deg, rgba(98,193,229,.35), rgba(98,193,229,.95)); border-radius:999px;"></div>
      </div>
    </div>
    """


# ─────────────────────────────────────────────────────────────────────────────
# Chain snapshots
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def get_snap():
    dec = int(safe(lambda: usdt_c.functions.decimals().call(), 18))
    sym = safe(lambda: usdt_c.functions.symbol().call(), "USDT")
    block = int(w3.eth.block_number)

    c_raw = int(safe(lambda: usdt_c.functions.balanceOf(LOTTO_ADDR).call(), 0))
    a_raw = int(safe(lambda: usdt_c.functions.balanceOf(ADMIN_ADDR).call(), 0))
    c_bnb = int(safe(lambda: w3.eth.get_balance(LOTTO_ADDR), 0))
    a_bnb = int(safe(lambda: w3.eth.get_balance(ADMIN_ADDR), 0))

    return {
        "block": block,
        "dec": dec,
        "sym": sym,
        "c_usdt": tok(c_raw, dec),
        "a_usdt": tok(a_raw, dec),
        "c_bnb": bnb(c_bnb),
        "a_bnb": bnb(a_bnb),
    }


@st.cache_data(ttl=30)
def get_round_snap():
    rid = int(safe(lambda: lotto_c.functions.roundId().call(), 0))
    cr = safe(lambda: lotto_c.functions.currentRound().call(), None)

    if not cr:
        return {
            "round_id": rid,
            "state": 0,
            "sold": 0,
            "draw_ts": 0,
            "close_ts": 0,
            "ticket_price_units": 0,
            "start_ticket_id": 0,
            "commit_hash": "0x",
            "emergency": False,
            "price_str": "N/A",
            "draw_str": "N/A",
            "close_str": "N/A",
        }

    dec = int(safe(lambda: usdt_c.functions.decimals().call(), 18))
    sym = safe(lambda: usdt_c.functions.symbol().call(), "USDT")

    state = int(cr[0])
    draw_ts = int(cr[1])
    close_ts = int(cr[2])
    ticket_price_units = int(cr[3])
    sold = int(cr[4])
    start_ticket_id = int(cr[5]) if len(cr) > 5 else 0
    commit_hash = cr[6].hex() if hasattr(cr[6], "hex") else str(cr[6])
    if not commit_hash.startswith("0x"):
        commit_hash = "0x" + commit_hash
    emergency = bool(cr[7]) if len(cr) > 7 else False

    return {
        "round_id": rid,
        "state": state,
        "sold": sold,
        "draw_ts": draw_ts,
        "close_ts": close_ts,
        "ticket_price_units": ticket_price_units,
        "start_ticket_id": start_ticket_id,
        "commit_hash": commit_hash,
        "emergency": emergency,
        "price_str": f"{ticket_price_units / 10 ** dec:,.1f} {sym}",
        "draw_str": ts_utc(draw_ts),
        "close_str": ts_utc(close_ts),
    }


@st.cache_data(ttl=60)
def get_prize_config():
    admin_bps = int(safe(lambda: lotto_c.functions.adminFeeBps().call(), 2000))
    winner_pct = [int(safe(lambda i=i: lotto_c.functions.winnerPct(i).call(), 0)) for i in range(6)]
    if sum(winner_pct) != 100:
        winner_pct = [35, 20, 15, 12, 10, 8]
    return admin_bps, winner_pct


# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────
def normalize_db_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@st.cache_resource
def get_engine() -> Engine | None:
    url = normalize_db_url(DATABASE_URL)
    if not url:
        return None
    return create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=3, pool_timeout=15)


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
        return conn.execute(sql, {
            "chain_id": int(CHAIN_ID),
            "contract": LOTTO_ADDR.lower(),
            "buyer": buyer.lower(),
        }).fetchall()


def db_get_current_round_wallet_qty(engine: Engine, buyer: str, round_id: int) -> int:
    sql = text("""
        SELECT COALESCE(SUM(qty), 0)
        FROM tickets_bought
        WHERE chain_id = :chain_id
          AND contract_addr = :contract
          AND buyer = :buyer
          AND round_id = :round_id
    """)
    with engine.connect() as conn:
        return int(conn.execute(sql, {
            "chain_id": int(CHAIN_ID),
            "contract": LOTTO_ADDR.lower(),
            "buyer": buyer.lower(),
            "round_id": int(round_id),
        }).scalar() or 0)


def db_get_round_leaderboard(engine: Engine, round_id: int, limit: int = 100):
    sql = text("""
        SELECT buyer,
               COALESCE(SUM(qty), 0) AS qty,
               MIN(first_ticket_id) AS first_ticket,
               MAX(last_ticket_id) AS last_ticket,
               COUNT(*) AS purchases
        FROM tickets_bought
        WHERE chain_id = :chain_id
          AND contract_addr = :contract
          AND round_id = :round_id
        GROUP BY buyer
        ORDER BY qty DESC, purchases DESC
        LIMIT :limit
    """)
    with engine.connect() as conn:
        return conn.execute(sql, {
            "chain_id": int(CHAIN_ID),
            "contract": LOTTO_ADDR.lower(),
            "round_id": int(round_id),
            "limit": int(limit),
        }).fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Optional tx sync from buy page
# ─────────────────────────────────────────────────────────────────────────────
TOPIC0_TICKETSBOUGHT = "0xd30fc8f419840a5e9cc301144b85f6e0f8dcef82aa3a3fb58cc67c8cb8ae0c48"
NODEREAL_API_KEY = cfg("NODEREAL_API_KEY", "")
NODEREAL_BSC_RPC = cfg("NODEREAL_BSC_RPC", "")


def nodereal_url() -> str:
    if NODEREAL_BSC_RPC:
        return NODEREAL_BSC_RPC
    if NODEREAL_API_KEY:
        return f"https://bsc-mainnet.nodereal.io/v1/{NODEREAL_API_KEY}"
    return ""


def rpc_call(method: str, params: list, _id: int = 1):
    url = nodereal_url() or BSC_RPC
    r = __import__("requests").post(
        url,
        json={"jsonrpc": "2.0", "id": _id, "method": method, "params": params},
        timeout=30,
    )
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["result"]


def hex_to_int(x) -> int:
    if x is None:
        return 0
    if isinstance(x, int):
        return x
    if isinstance(x, str) and x.startswith("0x"):
        return int(x, 16)
    return int(x)


INSERT_SQL = text("""
INSERT INTO tickets_bought
(chain_id, contract_addr, buyer, round_id, qty, first_ticket_id, last_ticket_id,
 tx_hash, log_index, block_number, created_at)
VALUES
(:chain_id, :contract_addr, :buyer, :round_id, :qty, :first_ticket_id, :last_ticket_id,
 :tx_hash, :log_index, :block_number, :created_at)
ON CONFLICT (tx_hash, log_index) DO NOTHING
""")


def sync_tx_to_neon(engine: Engine, tx_hash: str) -> dict:
    txh = (tx_hash or "").strip().lower()
    if not (txh.startswith("0x") and len(txh) == 66):
        return {"ok": False, "error": "Bad tx hash"}

    receipt = rpc_call("eth_getTransactionReceipt", [txh], _id=700)
    if not receipt or not receipt.get("blockNumber"):
        return {"ok": False, "error": "Receipt not found yet"}

    blk_hex = receipt["blockNumber"]
    blk = hex_to_int(blk_hex)
    block = rpc_call("eth_getBlockByNumber", [blk_hex, False], _id=701)
    ts_int = hex_to_int((block or {}).get("timestamp", "0x0"))
    created_at = datetime.fromtimestamp(ts_int, tz=timezone.utc).isoformat() if ts_int else None

    rows = []
    for lg in receipt.get("logs", []) or []:
        if (lg.get("address") or "").lower() != LOTTO_ADDR.lower():
            continue
        topics = lg.get("topics") or []
        if not topics or str(topics[0]).lower() != TOPIC0_TICKETSBOUGHT.lower():
            continue

        round_id = hex_to_int(topics[1])
        buyer = Web3.to_checksum_address("0x" + str(topics[2])[-40:]).lower()
        data_bytes = bytes.fromhex((lg.get("data") or "0x")[2:])
        qty, _cost, first_id, last_id = abi_decode(["uint256", "uint256", "uint256", "uint256"], data_bytes)
        log_index = hex_to_int(lg.get("logIndex", "0x0"))

        rows.append({
            "chain_id": int(CHAIN_ID),
            "contract_addr": LOTTO_ADDR.lower(),
            "buyer": buyer,
            "round_id": int(round_id),
            "qty": int(qty),
            "first_ticket_id": int(first_id),
            "last_ticket_id": int(last_id),
            "tx_hash": txh,
            "log_index": int(log_index),
            "block_number": int(blk),
            "created_at": created_at,
        })

    if not rows:
        return {"ok": False, "error": "No TicketsBought event in this tx"}

    with engine.begin() as conn:
        conn.execute(INSERT_SQL, rows)

    return {"ok": True, "inserted": len(rows), "buyer": rows[0]["buyer"], "round_id": rows[0]["round_id"]}


# ─────────────────────────────────────────────────────────────────────────────
# Winner events from chain
# ─────────────────────────────────────────────────────────────────────────────
TOPIC0_WINNERPAID = "0x4b6eed1faffa83a67a0174fd8fb2cdf6f861ebe370c5123abaaebc2b674e9b12"
TOPIC0_DRAWREVEALED = "0xee0f80d2361182d7637fd4a54c523c037fe13fcbdebf7429d482bd71b1415064"


@st.cache_data(ttl=45)
def get_winner_events_for_round(round_id: int, dec: int, lookback_blocks: int = 120_000):
    latest = int(w3.eth.block_number)
    from_block = max(0, latest - int(lookback_blocks))

    try:
        logs = w3.eth.get_logs({
            "fromBlock": from_block,
            "toBlock": "latest",
            "address": LOTTO_ADDR,
            "topics": [TOPIC0_WINNERPAID, topic_uint256(int(round_id))]
        })
    except Exception:
        return []

    out = []
    for lg in logs:
        try:
            topics = [t.hex() if hasattr(t, "hex") else str(t) for t in lg["topics"]]
            ticket_id = int(topics[2], 16)
            winner = Web3.to_checksum_address("0x" + topics[3][-40:])
            data_hex = lg["data"].hex() if hasattr(lg["data"], "hex") else str(lg["data"])
            data_bytes = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
            amount_raw, pct_or_zero = abi_decode(["uint256", "uint8"], data_bytes)

            out.append({
                "round_id": int(round_id),
                "ticket_id": int(ticket_id),
                "winner": winner,
                "amount": tok(int(amount_raw), int(dec)),
                "pct": int(pct_or_zero),
                "tx_hash": lg["transactionHash"].hex() if hasattr(lg["transactionHash"], "hex") else str(lg["transactionHash"]),
                "block": int(lg["blockNumber"]),
                "log_index": int(lg["logIndex"]),
            })
        except Exception:
            continue

    out.sort(key=lambda x: (x["block"], x["log_index"]))
    return out


@st.cache_data(ttl=45)
def get_draw_revealed_for_round(round_id: int, dec: int, lookback_blocks: int = 120_000):
    latest = int(w3.eth.block_number)
    from_block = max(0, latest - int(lookback_blocks))

    try:
        logs = w3.eth.get_logs({
            "fromBlock": from_block,
            "toBlock": "latest",
            "address": LOTTO_ADDR,
            "topics": [TOPIC0_DRAWREVEALED, topic_uint256(int(round_id))]
        })
    except Exception:
        return None

    if not logs:
        return None

    lg = logs[-1]
    try:
        data_hex = lg["data"].hex() if hasattr(lg["data"], "hex") else str(lg["data"])
        data_bytes = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
        secret_hash, seed, pot_after_fee_raw, admin_fee_raw, emergency = abi_decode(
            ["bytes32", "bytes32", "uint256", "uint256", "bool"],
            data_bytes
        )
        return {
            "secret_hash": "0x" + secret_hash.hex(),
            "seed": "0x" + seed.hex(),
            "pot_after_fee": tok(int(pot_after_fee_raw), int(dec)),
            "admin_fee": tok(int(admin_fee_raw), int(dec)),
            "emergency": bool(emergency),
            "tx_hash": lg["transactionHash"].hex() if hasattr(lg["transactionHash"], "hex") else str(lg["transactionHash"]),
            "block": int(lg["blockNumber"]),
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Session + query params
# ─────────────────────────────────────────────────────────────────────────────
st.session_state.setdefault("wallet", None)
st.session_state.setdefault("active_tab", "landing")


def do_disconnect():
    st.session_state.wallet = None
    st.session_state.active_tab = "landing"
    st.rerun()


def set_wallet_and_go(addr: str):
    st.session_state.wallet = Web3.to_checksum_address(addr.strip())
    st.session_state.active_tab = "dashboard"
    st.rerun()


qp = st.query_params
qp_tx = (qp.get("tx") or "").strip()

if qp_tx:
    engine = get_engine()
    if not engine:
        st.warning("DATABASE_URL / NEON_DSN not set, cannot sync purchase.")
    else:
        with st.spinner("Syncing your purchase from chain…"):
            try:
                res = sync_tx_to_neon(engine, qp_tx)
            except Exception as e:
                res = {"ok": False, "error": str(e)}

        if res.get("ok"):
            st.session_state.wallet = Web3.to_checksum_address(res["buyer"])
            st.session_state.active_tab = "dashboard"
            st.query_params.clear()
            st.success(f"Synced! Round {res.get('round_id')} · inserted {res.get('inserted')} row(s).")
            st.rerun()
        else:
            st.error(f"Sync failed: {res.get('error')}")


# ─────────────────────────────────────────────────────────────────────────────
# Load live data
# ─────────────────────────────────────────────────────────────────────────────
snap = get_snap()
rsnap = get_round_snap()
sym = snap["sym"]
pool = snap["c_usdt"]
net_badge = "BSC Mainnet" if CHAIN_ID == 56 else f"Chain {CHAIN_ID}"
round_id = int(rsnap["round_id"])
state = int(rsnap["state"])
sold = int(rsnap["sold"])

# ─────────────────────────────────────────────────────────────────────────────
# Top bar
# ─────────────────────────────────────────────────────────────────────────────
l, r = st.columns([2, 3], gap="small")
with l:
    st.markdown(f'#### ⚡ LOTTO<b style="color:{ACCENT}; font-size:28px;">85</b>', unsafe_allow_html=True)
    st.markdown(f'<span class="pill">{net_badge}</span> &nbsp; Block: <b>{snap["block"]:,}</b>', unsafe_allow_html=True)
with r:
    c1, c2 = st.columns([1.4, 1.0], gap="small")
    with c1:
        st.link_button("🦊 Open Buy Page", BUY_DAPP_URL)
    with c2:
        if st.session_state.wallet:
            st.button("Disconnect ✕", on_click=do_disconnect)

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

t1, t2, t3 = st.columns([1, 1, 8])
with t1:
    if st.button("🏠 Home"):
        st.session_state.active_tab = "landing"
        st.rerun()
with t2:
    if st.button("📊 Dashboard"):
        st.session_state.active_tab = "dashboard"
        st.rerun()
with t3:
    st.markdown(
        f"""
<span class="disclaimer">
<b>Disclaimer:</b> Tickets are valid for one draw round only. After each draw, all tickets expire and new tickets are issued for the next round.<br>
<span style="color:{ACCENT}; font-weight:700;">Keep a small BNB balance for gas and enough USDT for tickets.</span>
</span>
""",
        unsafe_allow_html=True
    )

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Landing
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.active_tab == "landing":
    left, right = st.columns([1.25, 0.95], gap="large")

    with left:
        st.markdown('<span class="pill">Transparent · On-Chain · Auditable</span>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="heroTitle">LOTTO<b style="color:{ACCENT};">85</b><br>Verifiable lottery on <span class="yh">BSC</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="muted" style="font-size:15px; max-width:65ch;">Live prize pool, on-chain ticket ranges, fair odds, and public winner events — all visible from one dashboard.</div>',
            unsafe_allow_html=True,
        )

    with right:
        st.markdown(
            f"""
<div class="card">
  <h4 style="margin:0 0 14px 0; color:{ACCENT};">Round Status</h4>
  <div class="kpi" style="margin-bottom:10px;">
    <div class="t">Current Round</div>
    <div class="v">#{round_id} · {state_lbl(state)}</div>
    <div class="s">Tickets sold: <b>{sold}</b> · Price: <b>{rsnap["price_str"]}</b></div>
  </div>
  <div class="kpi">
    <div class="t">Schedule</div>
    <div class="s">Sales close: <b>{rsnap["close_str"]}</b><br>Draw: <b>{rsnap["draw_str"]}</b></div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)

    addr = st.text_input("Wallet address", key="manual_wallet", placeholder="0x1234…abcd")
    if st.button("✅ Use Address"):
        if not valid_wallet(addr):
            st.error("Please enter a valid wallet address.")
        else:
            set_wallet_and_go(addr)

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Pool", f"{pool:,.2f} {sym}")
    with c2:
        st.metric("Tickets Sold", f"{sold:,}")
    with c3:
        st.metric("Ticket Price", rsnap["price_str"])
    with c4:
        st.metric("Max Wallet Cap", f"{MAX_TICKETS_PER_WALLET}")

    st.info("Paste a wallet address and open the Dashboard to see ticket history, live odds, winner display, and simulation tools.")
    st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────
wallet = st.session_state.wallet
if not wallet:
    st.info("Paste wallet on Home to view your tickets.")
    st.stop()

engine = get_engine()
if not engine:
    st.warning("DATABASE_URL / NEON_DSN not set. Add it in Streamlit secrets to show tickets, odds and synced purchases.")
    st.stop()

st.write(f"Wallet: **{fmt_addr(wallet)}**")
st.write(f"Round: **#{round_id}** · Status: **{state_lbl(state)}** · Pool: **{pool:,.2f} {sym}** · Ticket Price: **{rsnap['price_str']}**")

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

# My tickets
st.subheader("🎫 My Tickets")
try:
    my_rows = db_get_tickets(engine, wallet)
except Exception as e:
    st.error(f"Neon query failed: {e}")
    st.stop()

if not my_rows:
    st.warning("No tickets found for this wallet.")
else:
    my_df = pd.DataFrame([{
        "Round": r[0],
        "Qty": r[1],
        "Ticket Range": f"{r[2]} → {r[3]}",
        "Tx": f"https://bscscan.com/tx/{r[4]}",
        "Tx Hash": str(r[4])[:10] + "…" + str(r[4])[-8:],
        "Block": r[5],
        "Time": str(r[6]) if r[6] else "",
    } for r in my_rows])
    st.dataframe(
        my_df,
        use_container_width=True,
        hide_index=True,
        column_config={"Tx": st.column_config.LinkColumn("Tx", display_text="🔗")},
    )

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

# Live odds
st.subheader("🎯 Live Odds & Fairness")
try:
    my_current_qty = db_get_current_round_wallet_qty(engine, wallet, round_id)
    leaderboard_rows = db_get_round_leaderboard(engine, round_id, limit=100)
except Exception as e:
    my_current_qty = 0
    leaderboard_rows = []
    st.warning(f"Could not load odds from Neon: {e}")

my_odds = pct(my_current_qty, sold)

oc1, oc2, oc3, oc4 = st.columns([1.35, 1, 1, 1], gap="medium")
with oc1:
    st.markdown(
        f"""
<div class="odds-hero">
  <div style="font-size:11px; letter-spacing:1px; font-weight:900; color:rgba(233,238,247,.70); text-transform:uppercase;">Your Winning Chance</div>
  <div class="odds-num">{my_odds:.2f}%</div>
  <div style="font-size:13px; color:rgba(233,238,247,.70); margin-top:6px;">You own <b>{my_current_qty}</b> of <b>{sold}</b> ticket(s) in Round {round_id}.</div>
</div>
""",
        unsafe_allow_html=True,
    )
with oc2:
    st.metric("Your Round Tickets", f"{my_current_qty:,}")
with oc3:
    st.metric("Total Sold", f"{sold:,}")
with oc4:
    st.metric("Anti-Whale Room", f"{max(0, MAX_TICKETS_PER_WALLET - my_current_qty):,}")

if sold > 0 and leaderboard_rows:
    max_qty = max([int(r[1]) for r in leaderboard_rows] + [1])
    lead_df = pd.DataFrame([{
        "Wallet": fmt_addr(r[0]),
        "Tickets": int(r[1]),
        "Odds %": round(pct(int(r[1]), sold), 4),
        "Ticket Range": f"{int(r[2])} → {int(r[3])}",
        "Purchases": int(r[4]),
    } for r in leaderboard_rows])

    st.dataframe(
        lead_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Odds %": st.column_config.ProgressColumn(
                "Odds %",
                help="Wallet tickets / total tickets sold",
                min_value=0,
                max_value=100,
                format="%.2f%%",
            )
        },
    )

    st.markdown("##### Top wallet odds")
    for r in leaderboard_rows[:5]:
        qty = int(r[1])
        st.markdown(odds_badge_html(fmt_addr(r[0]), qty, pct(qty, sold), max_qty), unsafe_allow_html=True)
else:
    st.caption("Odds leaderboard appears after current-round purchases are synced into Neon.")

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

# Multiple wallet simulation
st.subheader("🧪 Multiple Wallet Simulation")
st.caption("This lets you test fairness perception before public launch. It does not write to blockchain.")

with st.expander("Open simulator", expanded=True):
    sim_text = st.text_area(
        "Enter one wallet per line as: label, tickets",
        value="Wallet A,10\nWallet B,5\nWallet C,2\nWallet D,1",
        height=120,
    )

    sim_rows = []
    for line in sim_text.splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        label, qty_s = line.rsplit(",", 1)
        try:
            qty = max(0, int(qty_s.strip()))
            if qty > 0:
                sim_rows.append((label.strip() or f"Wallet {len(sim_rows) + 1}", qty))
        except Exception:
            pass

    sim_total = sum(q for _, q in sim_rows)
    if sim_total <= 0:
        st.warning("Add at least one wallet with tickets, e.g. Wallet A,10")
    else:
        sim_df = pd.DataFrame([{
            "Wallet": label,
            "Tickets": qty,
            "Odds %": round(pct(qty, sim_total), 4),
            "Over 50 Cap?": "⚠️ Yes" if qty > MAX_TICKETS_PER_WALLET else "No",
        } for label, qty in sim_rows])

        sc1, sc2 = st.columns([1, 1], gap="large")
        with sc1:
            st.dataframe(
                sim_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Odds %": st.column_config.ProgressColumn(
                        "Odds %",
                        min_value=0,
                        max_value=100,
                        format="%.2f%%",
                    )
                },
            )
        with sc2:
            fig = go.Figure(go.Bar(
                x=sim_df["Wallet"],
                y=sim_df["Odds %"],
                text=[f"{v:.2f}%" for v in sim_df["Odds %"]],
                textposition="auto",
                hovertemplate="%{x}: %{y:.2f}%<extra></extra>",
            ))
            fig.update_layout(
                height=310,
                margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e9eef7"),
                yaxis=dict(title="Odds %", range=[0, 100], gridcolor="rgba(255,255,255,.08)"),
                xaxis=dict(title=""),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        max_sim_qty = max(q for _, q in sim_rows)
        for label, qty in sim_rows:
            st.markdown(odds_badge_html(label, qty, pct(qty, sim_total), max_sim_qty), unsafe_allow_html=True)

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

# Winner display
st.subheader("🏆 Frontend Winner Display")
default_result_round = max(1, round_id - 1) if state == 0 else round_id
result_round = st.number_input(
    "Round to show results for",
    min_value=1,
    value=int(default_result_round),
    step=1,
    help="Current round is open, so default is previous completed round.",
)

draw_meta = get_draw_revealed_for_round(int(result_round), int(snap["dec"]))
winner_events = get_winner_events_for_round(int(result_round), int(snap["dec"]))

if not winner_events:
    st.info("No WinnerPaid events found for this round yet. Results will appear after revealAndDraw executes.")
else:
    if draw_meta:
        dm1, dm2, dm3, dm4 = st.columns(4)
        with dm1:
            st.metric("Prize Pool Paid", f"{draw_meta['pot_after_fee']:,.2f} {sym}")
        with dm2:
            st.metric("Admin Fee", f"{draw_meta['admin_fee']:,.2f} {sym}")
        with dm3:
            st.metric("Draw Path", "Emergency" if draw_meta["emergency"] else "Normal")
        with dm4:
            st.link_button("View Draw Tx", f"https://bscscan.com/tx/{draw_meta['tx_hash']}")

    for idx, ev in enumerate(winner_events, start=1):
        st.markdown(
            f"""
<div class="winner-card">
  <div class="winner-rank">Winner #{idx} · Ticket #{ev['ticket_id']} · {ev['pct']}%</div>
  <div class="winner-amt">{ev['amount']:,.4f} {sym}</div>
  <div class="winner-meta">Wallet: <b>{fmt_addr(ev['winner'])}</b> · Block: {ev['block']:,} · <a href="https://bscscan.com/tx/{ev['tx_hash']}" target="_blank">View transaction</a></div>
</div>
""",
            unsafe_allow_html=True,
        )

    win_df = pd.DataFrame([{
        "Rank": i,
        "Ticket": ev["ticket_id"],
        "Winner": fmt_addr(ev["winner"]),
        "Amount": f"{ev['amount']:,.4f} {sym}",
        "Pct": f"{ev['pct']}%",
        "Tx": f"https://bscscan.com/tx/{ev['tx_hash']}",
    } for i, ev in enumerate(winner_events, start=1)])

    st.dataframe(
        win_df,
        use_container_width=True,
        hide_index=True,
        column_config={"Tx": st.column_config.LinkColumn("Tx", display_text="🔗")},
    )

st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

# Prize structure and platform stats
admin_bps, winner_pct = get_prize_config()
admin_pct = admin_bps / 100
prize_pool_pct = 100 - admin_pct
admin_amt = pool * (admin_pct / 100)
pot_after_fee = pool - admin_amt

c1, c2, c3 = st.columns(3, gap="large")

with c1:
    st.markdown('#### <span class="yh">🪙 Prize Structure</span>', unsafe_allow_html=True)
    st.write(f"Admin: **{admin_pct:.0f}%** · Prize pool: **{prize_pool_pct:.0f}%**")
    for i, p in enumerate(winner_pct, start=1):
        st.write(f"Winner {i}: **{p}%** — estimated **{pot_after_fee * p / 100:,.4f} {sym}**")

with c2:
    st.markdown('#### <span class="yh">🧾 Recent Current-Round Transfers</span>', unsafe_allow_html=True)
    try:
        rows = db_get_round_leaderboard(engine, round_id, limit=20)
        if rows:
            recent_df = pd.DataFrame([{
                "Wallet": fmt_addr(r[0]),
                "Tickets": int(r[1]),
                "Odds %": round(pct(int(r[1]), sold), 2),
                "Range": f"{int(r[2])} → {int(r[3])}",
                "Purchases": int(r[4]),
            } for r in rows])
            st.dataframe(recent_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No transfers yet.")
    except Exception as e:
        st.caption(f"Recent transfers unavailable: {e}")

with c3:
    st.markdown('#### <span class="yh">📈 Platform Stats</span>', unsafe_allow_html=True)
    st.metric("USDT Contract", f"{snap['c_usdt']:,.2f} {sym}")
    st.metric("USDT Admin", f"{snap['a_usdt']:,.2f} {sym}")
    st.metric("BNB Contract", f"{snap['c_bnb']:.6f}")
    st.metric("BNB Admin", f"{snap['a_bnb']:.6f}")
    st.caption(f"Contract: {fmt_addr(LOTTO_ADDR)}")
    st.caption(f"Admin: {fmt_addr(ADMIN_ADDR)}")
