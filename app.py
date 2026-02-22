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
# Config
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

missing = [k for k, v in {
    "LOTTO_CONTRACT": LOTTO_CONTRACT_ADDR,
    "USDT_ADDRESS": USDT_ADDRESS,
    "ADMIN_WALLET": ADMIN_WALLET,
}.items() if not v]


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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def fmt_addr(a: str) -> str:
    a = str(a or "")
    return a[:6] + "…" + a[-4:] if a.startswith("0x") and len(a) > 10 else (a or "N/A")

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

def state_lbl_contract(s: int) -> str:
    return {0: "&#x1F7E2; Open", 1: "&#x1F512; Sales Closed", 2: "&#x1F389; Drawn"}.get(int(s), f"State {s}")

def pad_topic_addr(addr: str) -> str:
    return "0x" + "0" * 24 + addr.lower().replace("0x", "")

def glass_card(title: str, body_html: str, id_: str):
    st.markdown(
        f"""
<div class="glass" id="{id_}">
  <div class="glass-head">{title}</div>
  <div class="glass-body">{body_html}</div>
</div>
""",
        unsafe_allow_html=True
    )

def do_refresh():
    st.cache_data.clear()
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
for k, v in dict(
    wallet=None,
    wallet_type=None,
    show_manual=False,
    manual_input="",
    ui_mode="landing",
    toast=None,
    toast_val=None,
).items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# Wallet callbacks
# ─────────────────────────────────────────────────────────────────────────────
def open_manual():
    st.session_state.show_manual = True

def close_manual():
    st.session_state.show_manual = False
    st.session_state.manual_input = ""

def do_disconnect():
    st.session_state.wallet = None
    st.session_state.wallet_type = None
    st.session_state.ui_mode = "landing"
    close_manual()

def do_connect_metamask():
    if not HAS_JS:
        st.session_state.show_manual = True
        st.session_state.toast = "no_js"
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
        st.session_state.ui_mode = "buy"
        st.session_state.toast = "mm_ok"
    else:
        st.session_state.toast = "mm_fail"
        st.session_state.toast_val = (res.get("err") if isinstance(res, dict) else "Unknown error")

def submit_manual():
    raw = (st.session_state.get("manual_input") or "").strip()
    if not raw:
        st.session_state.toast = "manual_empty"
        return
    try:
        st.session_state.wallet = Web3.to_checksum_address(raw)
        st.session_state.wallet_type = "manual"
        st.session_state.show_manual = False
        st.session_state.manual_input = ""
        st.session_state.ui_mode = "my_tickets"
        st.session_state.toast = "manual_ok"
    except Exception:
        st.session_state.toast = "manual_bad"


# ─────────────────────────────────────────────────────────────────────────────
# CSS + Particles — FIXED:
#  1. particles canvas uses pointer-events:none and z-index:-1 (behind content)
#  2. glass cards are visible by default (no opacity:0 animation that breaks)
#  3. All emoji use HTML entities to avoid browser rendering issues
#  4. Buttons have proper styling without emoji artifacts
#  5. Glass head font-size reduced for better hierarchy
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800;900&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;1,9..40,300&display=swap');

#MainMenu, header, footer,
[data-testid="stToolbar"],
[data-testid="stStatusWidget"] { display:none!important; }

.block-container {
  padding-top: 0 !important;
  padding-bottom: 3rem;
  max-width: 1200px;
}

*, *::before, *::after { box-sizing: border-box; }

:root {
  --gold: #f5c400;
  --gold-dim: rgba(245,196,0,.70);
  --text: #e9eef7;
  --muted: rgba(233,238,247,.55);
  --glass: rgba(16, 20, 36, 0.55);
  --glass-hover: rgba(22, 28, 48, 0.70);
  --border: rgba(255,255,255,.10);
  --border-gold: rgba(245,196,0,.22);
  --shadow: 0 8px 40px rgba(0,0,0,.50);
  --radius: 20px;
}

/* ── Background ── */
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(ellipse 80% 50% at 10% 10%, rgba(245,196,0,.06), transparent 60%),
    radial-gradient(ellipse 60% 40% at 90% 80%, rgba(0,120,255,.05), transparent 55%),
    linear-gradient(160deg, #04060c 0%, #070a14 60%, #050810 100%) !important;
  color: var(--text) !important;
  font-family: 'DM Sans', sans-serif;
}

/* ── Particles — BEHIND everything ── */
#particles-wrap {
  position: fixed;
  inset: 0;
  z-index: -1;          /* FIX: was 0, now -1 so it never intercepts clicks */
  pointer-events: none;
  overflow: hidden;
}
#particles-wrap canvas {
  width: 100%;
  height: 100%;
  opacity: .65;
}

/* ── Main content always above ── */
[data-testid="stAppViewContainer"] > .main {
  position: relative;
  z-index: 1;
}
[data-testid="block-container"] {
  position: relative;
  z-index: 1;
}

/* ── Navbar ── */
.nav {
  position: sticky;
  top: 0;
  z-index: 100;
  margin: 0 0 24px 0;
  padding: 14px 20px;
  background: rgba(8, 11, 20, 0.80);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border-bottom: 1px solid var(--border);
  box-shadow: 0 2px 32px rgba(0,0,0,.40);
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: rgba(245,196,0,.12);
  border: 1px solid var(--border-gold);
  display: grid;
  place-items: center;
  font-size: 20px;
  box-shadow: 0 0 20px rgba(245,196,0,.15);
}
.brand-name {
  font-family: 'Syne', sans-serif;
  font-weight: 900;
  font-size: 18px;
  letter-spacing: 1.5px;
  color: var(--gold);
}
.pill {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(245,196,0,.10);
  border: 1px solid var(--border-gold);
  color: var(--gold);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .6px;
  text-transform: uppercase;
}
.nav-info {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.8;
  margin-top: 2px;
}
.nav-info b { color: var(--text); }

/* ── Streamlit button overrides ── */
div.stButton > button {
  width: 100% !important;
  height: 40px !important;
  border-radius: 12px !important;
  font-family: 'DM Sans', sans-serif !important;
  font-weight: 600 !important;
  font-size: 13px !important;
  border: 1px solid var(--border) !important;
  background: rgba(255,255,255,.05) !important;
  color: var(--text) !important;
  box-shadow: none !important;
  transition: all .2s ease !important;
  padding: 0 14px !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
}
div.stButton > button:hover {
  border-color: var(--border-gold) !important;
  background: rgba(245,196,0,.08) !important;
  color: var(--gold) !important;
  transform: translateY(-1px) !important;
}
div.stButton > button:active {
  transform: translateY(0) !important;
}

/* Gold primary button */
.btn-primary div.stButton > button {
  background: linear-gradient(135deg, rgba(245,196,0,.20), rgba(245,150,0,.12)) !important;
  border: 1px solid rgba(245,196,0,.40) !important;
  color: var(--gold) !important;
  font-weight: 700 !important;
}
.btn-primary div.stButton > button:hover {
  background: linear-gradient(135deg, rgba(245,196,0,.28), rgba(245,150,0,.18)) !important;
  box-shadow: 0 0 30px rgba(245,196,0,.15) !important;
}

/* ── Separator ── */
.sep {
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.08), transparent);
  margin: 28px 0;
}

/* ── Hero ── */
.hero {
  padding: 8px 0 20px 0;
}
.hero h1 {
  font-family: 'Syne', sans-serif;
  font-weight: 900;
  font-size: 52px;
  color: var(--gold);
  margin: 0 0 8px 0;
  letter-spacing: -.5px;
  text-shadow: 0 0 60px rgba(245,196,0,.25);
}
.hero .sub {
  color: var(--text);
  font-size: 16px;
  margin: 0 0 4px 0;
  opacity: .85;
}
.hero .note {
  color: var(--muted);
  font-size: 13px;
}

/* ── Glass cards — ALWAYS VISIBLE (no animation that hides them) ── */
.glass {
  position: relative;
  background: var(--glass);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px 26px;
  box-shadow: var(--shadow);
  overflow: hidden;
  margin-bottom: 14px;
  transition: border-color .3s ease, box-shadow .3s ease;
}
.glass:hover {
  border-color: rgba(245,196,0,.18);
  box-shadow: 0 12px 50px rgba(0,0,0,.55), 0 0 60px rgba(245,196,0,.04);
}
.glass::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: var(--radius);
  background:
    radial-gradient(500px 180px at 0% 0%, rgba(245,196,0,.07), transparent 70%),
    radial-gradient(400px 200px at 100% 100%, rgba(0,140,255,.05), transparent 70%);
  pointer-events: none;
  z-index: 0;
}
.glass > * { position: relative; z-index: 1; }

.glass-head {
  font-family: 'Syne', sans-serif;
  font-size: 20px;
  font-weight: 800;
  color: var(--gold);
  letter-spacing: .3px;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.glass-head::before {
  content: "";
  display: inline-block;
  width: 3px;
  height: 18px;
  background: var(--gold);
  border-radius: 2px;
  opacity: .7;
}

.glass-body {
  color: var(--text);
  font-size: 14px;
  line-height: 1.7;
}
.glass-body .muted { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
.glass-body ul { margin: 8px 0 0 16px; padding: 0; }
.glass-body li { margin: 6px 0; color: var(--text); }
.glass-body b { color: var(--gold-dim); font-weight: 600; }

/* ── Dashboard stat rows ── */
.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 6px 0;
  border-bottom: 1px solid rgba(255,255,255,.04);
}
.stat-row:last-child { border-bottom: none; }
.stat-label { color: var(--muted); font-size: 12px; }
.stat-value { font-weight: 600; font-size: 14px; color: var(--text); }

/* Pool number */
.pool-amount {
  font-family: 'Syne', sans-serif;
  font-size: 48px;
  font-weight: 900;
  color: var(--gold);
  line-height: 1;
  letter-spacing: -1px;
  margin: 8px 0 4px 0;
  text-shadow: 0 0 40px rgba(245,196,0,.30);
}
.pool-sym {
  font-size: 16px;
  color: var(--muted);
  font-weight: 400;
  margin-left: 4px;
}

/* ── Ticket purchase card ── */
.ticket-entry {
  margin-top: 12px;
  padding: 16px 18px;
  border-radius: 16px;
  border: 1px solid rgba(245,196,0,.15);
  background: rgba(245,196,0,.04);
  transition: border-color .2s;
}
.ticket-entry:hover {
  border-color: rgba(245,196,0,.30);
}
.ticket-round {
  font-family: 'Syne', sans-serif;
  font-weight: 800;
  color: var(--gold);
  font-size: 15px;
}
.ticket-meta {
  color: var(--muted);
  font-size: 12px;
  margin-top: 6px;
  line-height: 1.7;
}
.ticket-meta a { color: var(--gold); text-decoration: none; }
.ticket-meta a:hover { text-decoration: underline; }

/* ── Footer ── */
.footer {
  text-align: center;
  padding: 24px 0 8px 0;
  color: var(--muted);
  font-size: 11px;
  letter-spacing: .3px;
}
.footer span { color: var(--gold); }

/* ── Streamlit input ── */
[data-testid="stTextInput"] input {
  background: rgba(255,255,255,.05) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
  color: var(--text) !important;
  font-family: 'DM Sans', sans-serif !important;
}
[data-testid="stTextInput"] input:focus {
  border-color: var(--border-gold) !important;
  box-shadow: 0 0 0 2px rgba(245,196,0,.10) !important;
}

/* ── Number input ── */
[data-testid="stNumberInput"] input {
  background: rgba(255,255,255,.05) !important;
  border: 1px solid var(--border) !important;
  color: var(--text) !important;
  border-radius: 10px !important;
}

/* ── Selectbox ── */
[data-testid="stSelectbox"] > div > div {
  background: rgba(255,255,255,.05) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
  color: var(--text) !important;
}

/* ── Slider ── */
[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
  background: var(--gold) !important;
}

/* ── Alerts ── */
[data-testid="stAlert"] {
  border-radius: 12px !important;
  border: none !important;
}

/* ── Spinner ── */
[data-testid="stSpinner"] { color: var(--gold) !important; }

/* ── Columns gap fix ── */
[data-testid="column"] { padding: 0 6px !important; }
</style>

<!-- Particle canvas — z-index:-1 so it's purely decorative -->
<div id="particles-wrap"><canvas id="particles-canvas"></canvas></div>

<script>
(function() {
  // Defer until DOM is ready
  function initParticles() {
    var canvas = document.getElementById('particles-canvas');
    if (!canvas) { setTimeout(initParticles, 300); return; }
    var ctx = canvas.getContext('2d');
    var W, H, particles = [];
    var N = 60;

    function resize() {
      W = canvas.width = window.innerWidth;
      H = canvas.height = window.innerHeight;
    }

    function rnd(a, b) { return a + Math.random() * (b - a); }

    function makeParticle() {
      return {
        x: rnd(0, W), y: rnd(0, H),
        r: rnd(0.6, 2.0),
        vx: rnd(-0.25, 0.25),
        vy: rnd(-0.20, 0.20),
        a: rnd(0.06, 0.18)
      };
    }

    function init() {
      particles = [];
      for (var i = 0; i < N; i++) particles.push(makeParticle());
    }

    function draw() {
      ctx.clearRect(0, 0, W, H);
      // dots
      for (var i = 0; i < particles.length; i++) {
        var p = particles[i];
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0) p.x = W;
        if (p.x > W) p.x = 0;
        if (p.y < 0) p.y = H;
        if (p.y > H) p.y = 0;
        ctx.beginPath();
        ctx.fillStyle = 'rgba(245,196,0,' + p.a + ')';
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }
      // connections
      for (var i = 0; i < particles.length; i++) {
        for (var j = i + 1; j < particles.length; j++) {
          var dx = particles[i].x - particles[j].x;
          var dy = particles[i].y - particles[j].y;
          var d = Math.sqrt(dx * dx + dy * dy);
          if (d < 130) {
            ctx.strokeStyle = 'rgba(245,196,0,' + ((1 - d / 130) * 0.07) + ')';
            ctx.lineWidth = 0.8;
            ctx.beginPath();
            ctx.moveTo(particles[i].x, particles[i].y);
            ctx.lineTo(particles[j].x, particles[j].y);
            ctx.stroke();
          }
        }
      }
      requestAnimationFrame(draw);
    }

    resize();
    init();
    draw();
    window.addEventListener('resize', function() { resize(); init(); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initParticles);
  } else {
    initParticles();
  }
})();
</script>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Toasts
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.toast == "mm_ok":
    st.success("Wallet connected. Dashboard unlocked.")
elif st.session_state.toast == "mm_fail":
    st.warning(f"MetaMask connect failed: {st.session_state.toast_val}")
elif st.session_state.toast == "no_js":
    st.error("MetaMask unavailable (missing streamlit-javascript). Add it to requirements.txt.")
elif st.session_state.toast == "manual_ok":
    st.success("Address saved (read-only mode).")
elif st.session_state.toast == "manual_bad":
    st.error("Invalid Ethereum address.")
elif st.session_state.toast == "manual_empty":
    st.warning("Please enter a wallet address.")

st.session_state.toast = None
st.session_state.toast_val = None


# ─────────────────────────────────────────────────────────────────────────────
# Content config
# ─────────────────────────────────────────────────────────────────────────────
CONTENT = {
    "hero_title": "Decentralized Lottery",
    "hero_sub": "Fully on-chain. Transparent. Verifiable.",
    "hero_note": "Edit this text in code — add your whitepaper, tokenomics, and messaging below.",
    "sections": [
        ("How It Works", """
<div class="muted">Full round lifecycle</div>
<ul>
  <li>Each round has a fixed ticket price in USDT</li>
  <li>Sales close automatically at the configured timestamp</li>
  <li>Admin commits a hash before the draw; revealed on-chain for verifiability</li>
  <li>Draw is triggered after the draw timestamp passes</li>
  <li>6 winners are selected; prizes are distributed automatically</li>
</ul>
"""),
        ("Security Model", """
<div class="muted">How we protect participants</div>
<ul>
  <li>Smart contract deployed on BSC mainnet — fully auditable</li>
  <li>Commit-reveal randomness prevents manipulation</li>
  <li>Admin cannot alter ticket sales once sales close</li>
  <li>All events (TicketsBought, DrawRevealed, WinnerPaid) are public on-chain</li>
  <li>No custody of private keys — MetaMask signs all user transactions</li>
</ul>
"""),
        ("Prize & Fees", """
<div class="muted">How the pot is split</div>
<ul>
  <li>6 winners receive a pre-configured share of the pot (sum = 100% after fees)</li>
  <li>Admin fee is deducted from the pot at draw time</li>
  <li>Payouts are automatic on-chain transfers — no manual claiming</li>
</ul>
"""),
        ("How To Buy Tickets", """
<div class="muted">Step-by-step guide</div>
<ul>
  <li><b>1.</b> Install MetaMask browser extension</li>
  <li><b>2.</b> Add BSC Mainnet (Chain ID 56) to your networks</li>
  <li><b>3.</b> Acquire BNB for gas fees and USDT for ticket purchase</li>
  <li><b>4.</b> Click Connect above and approve the connection</li>
  <li><b>5.</b> Enter the number of tickets and click Buy — MetaMask will prompt for USDT approval then the purchase</li>
</ul>
"""),
        ("Transparency", """
<div class="muted">Everything is verifiable</div>
<ul>
  <li>Contract address visible on BscScan with full source</li>
  <li>USDT token address verifiable on-chain</li>
  <li>All TicketsBought, DrawRevealed, WinnerPaid events are public logs</li>
  <li>Prize pool balance is live — shown in the dashboard after connecting</li>
</ul>
"""),
        ("FAQ", """
<ul>
  <li><b>Do I need an account?</b> No — wallet only, no sign-up required.</li>
  <li><b>Is it secure?</b> Yes. You sign transactions in MetaMask; the app never sees your private key.</li>
  <li><b>Can I verify everything?</b> Yes — all balances, events, and contract logic are public on BSC.</li>
  <li><b>What if I miss the draw?</b> Prizes are distributed automatically; no action needed from winners.</li>
</ul>
"""),
    ]
}

wallet = st.session_state.wallet
is_mm = st.session_state.wallet_type == "metamask"
is_manual = st.session_state.wallet_type == "manual"
net_badge = "BSC Mainnet" if CHAIN_ID == 56 else f"Chain {CHAIN_ID}"


# ─────────────────────────────────────────────────────────────────────────────
# NAVBAR
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="nav">', unsafe_allow_html=True)

nav_l, nav_m, nav_r = st.columns([2.0, 2.8, 2.8], gap="small")

with nav_l:
    st.markdown(f"""
<div class="brand-row">
  <div class="brand-icon">&#x1F3B0;</div>
  <div>
    <div class="brand-name">LOTTO</div>
    <span class="pill">{net_badge}</span>
  </div>
</div>
""", unsafe_allow_html=True)

with nav_m:
    rpc_display = (ACTIVE_RPC or "Not connected")
    if len(rpc_display) > 35:
        rpc_display = rpc_display[:32] + "…"
    wallet_display = fmt_addr(wallet) if wallet else "Not connected"
    st.markdown(f"""
<div class="nav-info">
  RPC: <b>{rpc_display}</b><br>
  Wallet: <b>{wallet_display}</b>
</div>
""", unsafe_allow_html=True)

with nav_r:
    b1, b2, b3 = st.columns([1, 1, 1.1], gap="small")
    with b1:
        st.markdown('<div class="btn-primary">', unsafe_allow_html=True)
        if not wallet:
            st.button("Connect", on_click=do_connect_metamask, key="nav_connect")
        else:
            st.button(fmt_addr(wallet), disabled=True, key="nav_wallet")
        st.markdown("</div>", unsafe_allow_html=True)

    with b2:
        if not wallet:
            st.button("Manual", on_click=open_manual, key="nav_manual")
        else:
            st.button("Disconnect", on_click=do_disconnect, key="nav_disc")

    with b3:
        if st.button("Whitepaper", key="nav_wp"):
            st.session_state.ui_mode = "landing"

st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Manual connect panel
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.show_manual and not wallet:
    st.markdown("""
<div class="glass" style="margin-bottom:20px;">
  <div class="glass-head">Connect Wallet (Read-only)</div>
  <div class="glass-body muted">Paste a wallet address to view your tickets. Buying tickets requires MetaMask.</div>
</div>
""", unsafe_allow_html=True)

    st.text_input("Wallet address", key="manual_input", placeholder="0x1234…abcd", label_visibility="collapsed")
    b1, b2 = st.columns(2, gap="small")
    with b1:
        st.markdown('<div class="btn-primary">', unsafe_allow_html=True)
        st.button("Use This Address", on_click=submit_manual, key="manual_submit")
        st.markdown("</div>", unsafe_allow_html=True)
    with b2:
        st.button("Cancel", on_click=close_manual, key="manual_cancel")
    st.markdown('<div class="sep"></div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# HERO
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="hero">
  <h1>{CONTENT['hero_title']}</h1>
  <p class="sub">{CONTENT['hero_sub']}</p>
  <p class="note">{CONTENT['hero_note']}</p>
</div>
""", unsafe_allow_html=True)

cta1, cta2, cta3 = st.columns([1.2, 1.2, 1.6], gap="small")
with cta1:
    st.markdown('<div class="btn-primary">', unsafe_allow_html=True)
    st.button("Buy Tickets", key="cta_buy", on_click=lambda: st.session_state.update(ui_mode="buy"))
    st.markdown("</div>", unsafe_allow_html=True)
with cta2:
    st.button("My Tickets", key="cta_tickets", on_click=lambda: st.session_state.update(ui_mode="my_tickets"))
with cta3:
    st.button("Refresh", key="cta_refresh", on_click=do_refresh)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# Whitepaper sections — always visible, no animation class needed
for i, (title, body) in enumerate(CONTENT["sections"], start=1):
    glass_card(title, body, id_=f"sec_{i}")

st.markdown('<div class="sep"></div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Config / connection guards
# ─────────────────────────────────────────────────────────────────────────────
if missing:
    st.error(
        "Missing required config keys. Add these in Streamlit Cloud Secrets: "
        + ", ".join(missing)
    )
    st.stop()

if not w3:
    st.error("Cannot connect to any BSC RPC endpoint. Add a reliable RPC URL in Secrets (BSC_RPC).")
    st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Chain objects
# ─────────────────────────────────────────────────────────────────────────────
LOTTO_CONTRACT = Web3.to_checksum_address(LOTTO_CONTRACT_ADDR)
USDT           = Web3.to_checksum_address(USDT_ADDRESS)
ADMIN          = Web3.to_checksum_address(ADMIN_WALLET)

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
# Cached on-chain reads
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

    return dict(block=blk, dec=dec, sym=sym,
                c_usdt=tok(c_raw, dec), a_usdt=tok(a_raw, dec),
                c_bnb=bnb(c_bnb), a_bnb=bnb(a_bnb), logs=logs)

@st.cache_data(ttl=15)
def get_round_snap():
    if not lotto_c:
        return {}
    try:
        rid = int(lotto_c.functions.roundId().call())
        cr  = lotto_c.functions.currentRound().call()
        state    = int(cr[0])
        draw_ts  = int(cr[1])
        close_ts = int(cr[2])
        sold     = int(cr[3])
        start_id = int(cr[4])
        dec = int(usdt_c.functions.decimals().call())
        sym = str(usdt_c.functions.symbol().call())
        tp_units = int(lotto_c.functions.ticketPrice().call())
        return dict(
            round_id=rid, state=state,
            draw_ts=draw_ts, close_ts=close_ts,
            sold=sold, start_id=start_id,
            draw_str=ts(draw_ts), close_str=ts(close_ts),
            price_units=tp_units,
            price_str=f"{tp_units / 10**dec:,.4f} {sym}",
            dec=dec, sym=sym,
        )
    except Exception:
        return {}

@st.cache_data(ttl=60)
def get_tickets_for_wallet(wallet_addr: str, lookback_blocks: int = 120_000):
    if not lotto_c:
        return []
    wallet_addr = Web3.to_checksum_address(wallet_addr)
    latest = int(w3.eth.block_number)
    frm = max(0, latest - int(lookback_blocks))
    out = []
    try:
        evs = lotto_c.events.TicketsBought.create_filter(
            from_block=frm,
            to_block="latest",
            argument_filters={"buyer": wallet_addr}
        ).get_all_entries()
        for ev in evs:
            args = ev["args"]
            out.append({
                "round": int(args.get("roundId")),
                "qty": int(args.get("qty")),
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
# DASHBOARD (wallet required)
# ─────────────────────────────────────────────────────────────────────────────
snap  = get_snap()
rsnap = get_round_snap()

if wallet:
    st.markdown('<span class="pill" style="font-size:11px;">DASHBOARD UNLOCKED</span>', unsafe_allow_html=True)
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    pool = snap["c_usdt"]
    sym  = snap["sym"]

    left, right = st.columns([1.1, 1], gap="large")

    with left:
        st.markdown('<div class="glass">', unsafe_allow_html=True)
        st.markdown('<div class="glass-head">Live Round</div>', unsafe_allow_html=True)
        if not rsnap:
            st.markdown('<div class="glass-body muted">Could not read round data — check ABI file.</div>', unsafe_allow_html=True)
        else:
            round_state_html = state_lbl_contract(rsnap.get("state", 0))
            st.markdown(f"""
<div class="glass-body">
  <div style="font-family:'Syne',sans-serif;font-size:28px;font-weight:900;color:var(--gold);margin-bottom:16px;">
    Round #{rsnap.get("round_id")}
  </div>
  <div class="stat-row"><span class="stat-label">State</span><span class="stat-value">{round_state_html}</span></div>
  <div class="stat-row"><span class="stat-label">Sales Close</span><span class="stat-value">{rsnap.get("close_str","N/A")}</span></div>
  <div class="stat-row"><span class="stat-label">Next Draw</span><span class="stat-value">{rsnap.get("draw_str","N/A")}</span></div>
  <div class="stat-row"><span class="stat-label">Ticket Price</span><span class="stat-value">{rsnap.get("price_str","N/A")}</span></div>
  <div class="stat-row"><span class="stat-label">Tickets Sold</span><span class="stat-value">{rsnap.get("sold","—")}</span></div>
</div>
""", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="glass">', unsafe_allow_html=True)
        st.markdown('<div class="glass-head">Prize Pool</div>', unsafe_allow_html=True)
        st.markdown(f"""
<div class="glass-body">
  <div class="muted">Total USDT in Contract</div>
  <div class="pool-amount">{pool:,.2f}<span class="pool-sym">{sym}</span></div>
  <div style="height:12px"></div>
  <div class="stat-row"><span class="stat-label">Contract BNB</span><span class="stat-value">{snap["c_bnb"]:.6f}</span></div>
  <div class="stat-row"><span class="stat-label">Admin BNB</span><span class="stat-value">{snap["a_bnb"]:.6f}</span></div>
  <div class="stat-row"><span class="stat-label">Block</span><span class="stat-value">#{snap["block"]:,}</span></div>
</div>
""", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    a1, a2, a3 = st.columns([1.2, 1.2, 1.6], gap="small")
    with a1:
        st.markdown('<div class="btn-primary">', unsafe_allow_html=True)
        st.button("Buy Tickets", key="dash_buy", on_click=lambda: st.session_state.update(ui_mode="buy"))
        st.markdown("</div>", unsafe_allow_html=True)
    with a2:
        st.button("My Tickets", key="dash_tickets", on_click=lambda: st.session_state.update(ui_mode="my_tickets"))
    with a3:
        st.button("Refresh Dashboard", key="dash_refresh", on_click=do_refresh)

    st.markdown('<div class="sep"></div>', unsafe_allow_html=True)

    # ── BUY PANEL ──
    if st.session_state.ui_mode == "buy":
        st.markdown('<div class="glass">', unsafe_allow_html=True)
        st.markdown('<div class="glass-head">Buy Tickets</div>', unsafe_allow_html=True)

        if not lotto_c:
            st.markdown('<div class="glass-body muted">ABI not loaded. Add lotto_abi.json to the repo root.</div>', unsafe_allow_html=True)
        elif is_manual:
            st.markdown('<div class="glass-body">Read-only mode — connect MetaMask to purchase tickets.</div>', unsafe_allow_html=True)
            st.button("Connect MetaMask", key="buy_mm", on_click=do_connect_metamask)
        else:
            qty = st.number_input("Number of tickets", min_value=1, max_value=100, value=1, step=1, key="buy_qty")
            tp_units = rsnap.get("price_units")
            dec = rsnap.get("dec", snap["dec"])
            total_cost_units = int(tp_units) * int(qty) if tp_units is not None else None

            if total_cost_units is not None:
                cost_display = total_cost_units / 10**dec
                st.success(f"Total cost: {cost_display:,.4f} {snap['sym']}")

            if not HAS_JS:
                st.error("Install streamlit-javascript to enable MetaMask transactions.")
            elif total_cost_units is None:
                st.error("Could not read ticket price from contract — check ABI.")
            else:
                st.markdown('<div class="glass-body muted" style="margin-bottom:10px;">MetaMask will prompt for USDT approval (if needed), then the ticket purchase.</div>', unsafe_allow_html=True)
                label = f"Buy {int(qty)} Ticket{'s' if int(qty) > 1 else ''} via MetaMask"
                st.markdown('<div class="btn-primary">', unsafe_allow_html=True)
                if st.button(label, key="buy_btn"):
                    js = f"""
async()=>{{
  try {{
    if(!window.ethereum) return {{ok:false, err:"MetaMask not detected"}};
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
                        st.success(f"Purchased! Tx: {res.get('hash')}")
                        st.markdown(f"[View on BscScan](https://bscscan.com/tx/{res.get('hash')})")
                        st.cache_data.clear()
                    else:
                        err = res.get("err") if isinstance(res, dict) else str(res)
                        st.error(f"Transaction failed: {err}")
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # ── MY TICKETS PANEL ──
    if st.session_state.ui_mode == "my_tickets":
        st.markdown('<div class="glass">', unsafe_allow_html=True)
        st.markdown('<div class="glass-head">My Tickets</div>', unsafe_allow_html=True)

        if not lotto_c:
            st.markdown(f"""
<div class="glass-body">
  <p class="muted">ABI not loaded — add lotto_abi.json to the repo root.</p>
  <p>View events directly: <a href="https://bscscan.com/address/{LOTTO_CONTRACT}#events" target="_blank">BscScan Events &#x2197;</a></p>
</div>
""", unsafe_allow_html=True)
        else:
            mode_label = "MetaMask" if is_mm else "Read-only"
            st.markdown(f'<div class="glass-body muted">Wallet: {wallet} ({mode_label})</div>', unsafe_allow_html=True)

            lookback = st.slider("Lookback blocks", min_value=10_000, max_value=300_000,
                                 value=120_000, step=10_000, key="lb")

            with st.spinner("Fetching your ticket purchases…"):
                purchases = get_tickets_for_wallet(wallet, lookback_blocks=int(lookback))

            if not purchases:
                st.info("No TicketsBought events found in the selected block range.")
            else:
                rounds = sorted({p["round"] for p in purchases}, reverse=True)
                pick_round = st.selectbox("Round", rounds, index=0, key="pick_round")
                subset = [p for p in purchases if p["round"] == pick_round]

                st.markdown(f'<div class="glass-body"><b>{len(subset)}</b> purchase(s) in Round <b>#{pick_round}</b></div>', unsafe_allow_html=True)

                expand_small = st.checkbox("Show individual ticket numbers (qty ≤ 50)", value=False, key="expand")

                for p in subset:
                    qty0  = int(p["qty"])
                    start = int(p["start"])
                    end   = int(p["end"])
                    tx    = p["tx"]
                    st.markdown(f"""
<div class="ticket-entry">
  <div class="ticket-round">Round #{p["round"]} &nbsp;·&nbsp; {qty0} ticket{"s" if qty0 != 1 else ""}</div>
  <div class="ticket-meta">
    Ticket IDs: <b>{start}</b> &#x2192; <b>{end}</b><br>
    Tx: <a href="https://bscscan.com/tx/{tx}" target="_blank">{fmt_addr(tx)} &#x2197;</a>
  </div>
</div>
""", unsafe_allow_html=True)
                    if expand_small and qty0 <= 50:
                        st.code(", ".join(map(str, range(start, end + 1))))

        st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="footer">
  LOTTO &nbsp;·&nbsp;
  Contract <span>{fmt_addr(LOTTO_CONTRACT_ADDR)}</span> &nbsp;·&nbsp;
  USDT <span>{fmt_addr(USDT_ADDRESS)}</span> &nbsp;·&nbsp;
  Admin <span>{fmt_addr(ADMIN_WALLET)}</span>
</div>
""", unsafe_allow_html=True)
