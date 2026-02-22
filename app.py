from __future__ import annotations
import os
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
# Config
# ─────────────────────────────────────────
def cfg(key: str, default: str = "") -> str:
    if key in st.secrets:
        return str(st.secrets[key])
    return os.getenv(key, default)

CHAIN_ID = int(cfg("CHAIN_ID", "56"))
BSC_RPC  = cfg("BSC_RPC", "")


# ─────────────────────────────────────────
# RPC Connect
# ─────────────────────────────────────────
def connect_web3():
    RPCS = [
        BSC_RPC,
        "https://bsc-dataseed.binance.org/",
        "https://bsc-dataseed1.binance.org/"
    ]
    for rpc in RPCS:
        if not rpc:
            continue
        try:
            w = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
            if w.is_connected():
                return w
        except:
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
# Premium Styling
# ─────────────────────────────────────────
st.markdown("""
<style>
#MainMenu, header, footer {visibility:hidden;}
[data-testid="stAppViewContainer"]{
    background: linear-gradient(180deg,#06080d 0%,#07090f 100%);
    color:#ffffff;
}

.section{
    padding:80px 0px;
}

.hero-title{
    font-size:52px;
    font-weight:900;
    color:#f5c400;
}

.hero-sub{
    font-size:20px;
    color:#ffffff;
    opacity:.85;
}

.card{
    background: linear-gradient(145deg, rgba(20,25,40,.9), rgba(10,12,18,.95));
    border:1px solid rgba(245,196,0,.2);
    border-radius:24px;
    padding:50px;
    margin-top:40px;
    box-shadow: 0 0 60px rgba(245,196,0,.05);
}

.card h2{
    color:#f5c400;
    font-size:30px;
    margin-bottom:20px;
}

.card p, .card li{
    color:#ffffff;
    font-size:17px;
    line-height:1.8;
}

ul{
    padding-left:20px;
}

.cta button{
    background:#f5c400;
    color:black;
    font-weight:900;
    border-radius:14px;
    padding:12px 24px;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────
# Wallet Connect
# ─────────────────────────────────────────
def connect_wallet():
    if not HAS_JS:
        st.error("MetaMask bridge not available.")
        return

    js = """
async()=>{
  try{
    if(!window.ethereum) return {ok:false};
    const accounts = await window.ethereum.request({method:'eth_requestAccounts'});
    return {ok:true, address: accounts[0]};
  }catch(e){
    return {ok:false};
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
left, right = st.columns([6,2])

with left:
    st.markdown("### 🎰 LOTTO")

with right:
    if st.session_state.wallet:
        st.button("Disconnect", on_click=disconnect_wallet, key="btn_disconnect")
    else:
        st.button("Connect Wallet", on_click=connect_wallet, key="btn_connect")


# ─────────────────────────────────────────
# Landing Page (Whitepaper)
# ─────────────────────────────────────────
def landing_page():

    st.markdown("""
    <div class="section">
        <div class="hero-title">Decentralized Lottery</div>
        <div class="hero-sub">
            Fully on-chain. Transparent. Auditable. Trustless.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="card">
        <h2>How It Works</h2>
        <p>
        Replace this text with your full whitepaper explanation of:
        </p>
        <ul>
            <li>Ticket pricing model</li>
            <li>Round lifecycle</li>
            <li>Sales close timing</li>
            <li>Draw timing</li>
            <li>Commit-reveal security</li>
            <li>Prize distribution logic</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="card">
        <h2>Security Model</h2>
        <ul>
            <li>Smart contract transparency</li>
            <li>BSC mainnet deployment</li>
            <li>Admin permissions</li>
            <li>Commit hash mechanism</li>
            <li>On-chain deterministic randomness</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="card">
        <h2>Prize Distribution</h2>
        <ul>
            <li>1st Prize Percentage</li>
            <li>2nd Prize Percentage</li>
            <li>3rd Prize Percentage</li>
            <li>Additional winners</li>
            <li>Administrative fee allocation</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="card">
        <h2>How To Participate</h2>
        <ul>
            <li>Install MetaMask</li>
            <li>Add BSC Network</li>
            <li>Fund wallet with USDT + BNB</li>
            <li>Connect wallet</li>
            <li>Approve USDT</li>
            <li>Buy tickets</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section cta">', unsafe_allow_html=True)
    st.button("🚀 Connect Wallet To Enter Lottery", on_click=connect_wallet, key="cta_connect")
    st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────
def dashboard():
    st.markdown("""
    <div class="section">
        <div class="hero-title">Dashboard</div>
        <div class="hero-sub">
            Wallet Connected
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.write(f"Connected wallet: {st.session_state.wallet}")

    if not w3:
        st.error("Cannot connect to BSC RPC.")
        return

    st.markdown("""
    <div class="card">
        <h2>Lottery Dashboard</h2>
        <p>
        Paste your previous on-chain dashboard UI here.
        </p>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────
# Router
# ─────────────────────────────────────────
if st.session_state.view == "dashboard" and st.session_state.wallet:
    dashboard()
else:
    landing_page()
