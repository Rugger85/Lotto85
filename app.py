from __future__ import annotations
import os, json
from datetime import datetime, timezone

import streamlit as st
from web3 import Web3

# Optional local dev
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# MetaMask bridge
try:
    from streamlit_javascript import st_javascript
    HAS_JS = True
except Exception:
    HAS_JS = False


# ─────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────
st.set_page_config(page_title="LOTTO", layout="wide", page_icon="🎰")


# ─────────────────────────────────────────
# Config Loader
# ─────────────────────────────────────────
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


# ─────────────────────────────────────────
# RPC Connect
# ─────────────────────────────────────────
RPCS = [
    BSC_RPC_PRIMARY,
    "https://bsc-dataseed.binance.org/",
    "https://bsc-dataseed1.binance.org/",
    "https://bsc-dataseed2.binance.org/"
]

def connect_web3():
    for rpc in RPCS:
        if not rpc:
            continue
        try:
            w = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
            if w.is_connected():
                return w
        except Exception:
            pass
    return None

w3 = connect_web3()


# ─────────────────────────────────────────
# Session State
# ─────────────────────────────────────────
if "wallet" not in st.session_state:
    st.session_state.wallet = None
if "view" not in st.session_state:
    st.session_state.view = "landing"


# ─────────────────────────────────────────
# Styles
# ─────────────────────────────────────────
st.markdown("""
<style>
#MainMenu, header, footer {visibility:hidden;}
[data-testid="stAppViewContainer"]{
    background: linear-gradient(180deg,#06080d 0%,#07090f 100%);
    color:#e9eef7;
}
.section{
    padding:60px 0px;
}
.title{
    font-size:42px;
    font-weight:900;
    color:#f5c400;
}
.subtitle{
    font-size:20px;
    opacity:.75;
}
.card{
    background:rgba(15,19,31,.9);
    border:1px solid rgba(255,255,255,.08);
    border-radius:16px;
    padding:24px;
}
.btn-primary button{
    background:#f5c400;
    color:black;
    font-weight:900;
    border-radius:12px;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────
# Wallet Connect
# ─────────────────────────────────────────
def connect_wallet():
    if not HAS_JS:
        st.error("streamlit-javascript not installed.")
        return

    js = """
async()=>{
  try{
    if(!window.ethereum) return {ok:false, err:"no_metamask"};
    const accounts = await window.ethereum.request({method:'eth_requestAccounts'});
    return {ok:true, address: accounts[0]};
  }catch(e){
    return {ok:false, err:e.message};
  }
}
"""
    result = st_javascript(js, key="wallet_connect_js")

    if isinstance(result, dict) and result.get("ok"):
        st.session_state.wallet = result["address"]
        st.session_state.view = "dashboard"
    else:
        st.error("Wallet connection failed.")


def disconnect_wallet():
    st.session_state.wallet = None
    st.session_state.view = "landing"


# ─────────────────────────────────────────
# Navbar
# ─────────────────────────────────────────
col1, col2 = st.columns([6,2])

with col1:
    st.markdown("### 🎰 LOTTO")

with col2:
    if st.session_state.wallet:
        st.button("Disconnect", on_click=disconnect_wallet, key="btn_disconnect")
    else:
        st.button("Connect Wallet", on_click=connect_wallet, key="btn_connect")


# ─────────────────────────────────────────
# Landing Page (Whitepaper Style)
# ─────────────────────────────────────────
def landing_page():

    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown('<div class="title">Decentralized Lottery</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Fully on-chain. Transparent. Auditable.</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # How It Works
    st.markdown('<div class="section card">', unsafe_allow_html=True)
    st.markdown("## How It Works")
    st.write("""
    Explain your full structure here:
    - Ticket price
    - How rounds work
    - Sales close timing
    - Draw timing
    - Commit-reveal security
    - Prize distribution
    """)
    st.markdown("</div>", unsafe_allow_html=True)

    # Security
    st.markdown('<div class="section card">', unsafe_allow_html=True)
    st.markdown("## Security Model")
    st.write("""
    Explain:
    - Smart contract transparency
    - BSC mainnet deployment
    - Admin permissions
    - Commit hash mechanism
    - On-chain randomness model
    """)
    st.markdown("</div>", unsafe_allow_html=True)

    # Prize Structure
    st.markdown('<div class="section card">', unsafe_allow_html=True)
    st.markdown("## Prize Distribution")
    st.write("""
    Describe:
    - 1st Prize %
    - 2nd Prize %
    - 3rd Prize %
    - Admin Fee %
    - Monthly schedule
    """)
    st.markdown("</div>", unsafe_allow_html=True)

    # How To Participate
    st.markdown('<div class="section card">', unsafe_allow_html=True)
    st.markdown("## How To Participate")
    st.write("""
    1. Install MetaMask  
    2. Add BSC network  
    3. Fund wallet with USDT + small BNB  
    4. Click Connect Wallet  
    5. Buy tickets  
    """)
    st.markdown("</div>", unsafe_allow_html=True)

    # CTA
    st.markdown('<div class="section btn-primary">', unsafe_allow_html=True)
    st.button("🚀 Connect Wallet To Enter Lottery", on_click=connect_wallet, key="cta_connect")
    st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────
# Dashboard (After Connect)
# ─────────────────────────────────────────
def dashboard():

    st.markdown("## 📊 Dashboard")

    st.write(f"Connected wallet: {st.session_state.wallet}")

    if not w3:
        st.error("Cannot connect to BSC RPC.")
        return

    # You can paste your full working dashboard here
    st.markdown("### Prize Pool & Round Info")
    st.write("Paste your previous working on-chain dashboard code here.")


# ─────────────────────────────────────────
# Router
# ─────────────────────────────────────────
if st.session_state.view == "dashboard" and st.session_state.wallet:
    dashboard()
else:
    landing_page()
