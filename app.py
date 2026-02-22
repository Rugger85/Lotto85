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

def state_lbl_contract(s: int) -> str:
    # Your contract enum: OPEN=0, SALES_CLOSED=1, DRAWN=2
    return {0: "🟢 Open", 1: "🔒 Sales Closed", 2: "🎉 Drawn"}.get(int(s), f"State {s}")

def pad_topic_addr(addr: str) -> str:
    return "0x" + "0" * 24 + addr.lower().replace("0x", "")

def donut(split: dict[str, float]):
    fig = go.Figure(go.Pie(labels=list(split.keys()), values=list(split.values()), hole=0.68, sort=False, textinfo="none"))
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=240, showlegend=False)
    return fig

def glass_card(title: str, body_md: str, id_: str):
    st.markdown(
        f"""
<div class="glass card-anim" id="{id_}">
  <div class="glass-head">{title}</div>
  <div class="glass-body">{body_md}</div>
</div>
""",
        unsafe_allow_html=True
    )


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
for k, v in dict(
    wallet=None,
    wallet_type=None,   # "metamask" / "manual"
    show_manual=False,
    manual_input="",
    ui_mode="landing",  # landing / buy / my_tickets
    toast=None,
    toast_val=None,
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
    for k in ["wallet", "wallet_type"]:
        st.session_state[k] = None
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
# UI (Glass + Animations + Particles)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
#MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stStatusWidget"] {display:none!important;}
.block-container{padding-top:1.25rem; padding-bottom:3rem; max-width: 1200px;}
a{color:#f5c400; text-decoration:none;}
a:hover{text-decoration:underline;}

:root{
  --gold:#f5c400;
  --text:#e9eef7;
  --muted:rgba(233,238,247,.60);
  --glass:rgba(20, 25, 40, 0.45);
  --glass2:rgba(15, 19, 31, .72);
  --border:rgba(255,255,255,.12);
  --border2:rgba(245,196,0,.28);
  --shadow: 0 8px 32px rgba(0,0,0,.42);
}

[data-testid="stAppViewContainer"]{
  background:
    radial-gradient(circle at 15% 20%, rgba(245,196,0,0.07), transparent 40%),
    radial-gradient(circle at 85% 70%, rgba(0,150,255,0.05), transparent 40%),
    linear-gradient(180deg,#05070c 0%,#07090f 100%) !important;
  color: var(--text) !important;
}

/* particles layer (behind everything) */
#particles-wrap{
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events:none;
  opacity: .70;
}
canvas#particles{
  width:100%;
  height:100%;
  filter: blur(.2px);
}

/* content above particles */
[data-testid="stAppViewContainer"] > .main { position: relative; z-index: 1; }

/* NAVBAR */
.nav{
  position: sticky;
  top: 0;
  z-index: 50;
  margin: -6px 0 18px 0;
  padding: 12px 14px;
  border-radius: 18px;
  background: rgba(15,19,31,0.50);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}
.nav-inner{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap: 14px;
}
.brand{
  display:flex;
  align-items:center;
  gap: 10px;
}
.brand .logo{
  width: 36px; height: 36px;
  border-radius: 12px;
  display:grid; place-items:center;
  background: rgba(245,196,0,0.12);
  border: 1px solid rgba(245,196,0,0.24);
  box-shadow: 0 0 24px rgba(245,196,0,0.12);
}
.brand .title{
  font-weight: 900;
  letter-spacing: .6px;
}
.badges{
  display:flex;
  align-items:center;
  gap: 10px;
  flex-wrap:wrap;
  color: var(--muted);
  font-size: 12px;
}
.pill{
  display:inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(245,196,0,.10);
  border: 1px solid rgba(245,196,0,.22);
  color: var(--gold);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: .4px;
}

/* GLASS CARDS */
.glass{
  position: relative;
  background: var(--glass);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--border);
  border-radius: 26px;
  padding: 22px 22px;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.glass::before{
  content:"";
  position:absolute;
  inset:-2px;
  border-radius: 28px;
  background: radial-gradient(600px 200px at 10% 20%, rgba(245,196,0,.13), transparent 60%),
              radial-gradient(500px 220px at 90% 70%, rgba(0,150,255,.09), transparent 60%);
  opacity: .55;
  z-index:0;
}
.glass > *{ position:relative; z-index:1; }

.glass-head{
  font-size: 28px;
  font-weight: 950;
  color: var(--gold);
  text-shadow: 0 0 14px rgba(245,196,0,0.35);
  margin-bottom: 10px;
}
.glass-body{
  color: var(--text);
  font-size: 15px;
  line-height: 1.6;
}
.glass-body .muted{ color: var(--muted); }
.glass-body ul{ margin: 10px 0 0 18px; }
.glass-body li{ margin: 6px 0; color: var(--text); }

/* CTA BUTTONS */
div.stButton>button{
  width:100%;
  border-radius: 14px !important;
  font-weight: 900 !important;
  border: 1px solid rgba(255,255,255,.14) !important;
  background: rgba(15,19,31,.70) !important;
  color: var(--text) !important;
  box-shadow: 0 10px 30px rgba(0,0,0,.25) !important;
  transition: all .25s ease !important;
}
div.stButton>button:hover{
  border-color: rgba(245,196,0,.45) !important;
  box-shadow: 0 14px 40px rgba(0,0,0,.35), 0 0 45px rgba(245,196,0,.10) !important;
  transform: translateY(-1px);
}
.btn-gold div.stButton>button{
  background: rgba(245,196,0,.15) !important;
  border: 1px solid rgba(245,196,0,.35) !important;
  color: var(--gold) !important;
}
.btn-gold div.stButton>button:hover{
  background: rgba(245,196,0,.20) !important;
}

/* HERO */
.hero{
  padding: 26px 0 10px 0;
}
.hero h1{
  margin: 0;
  font-size: 48px;
  font-weight: 1000;
  color: var(--gold);
  letter-spacing: .2px;
}
.hero p{
  margin: 8px 0 0 0;
  color: var(--muted);
  font-size: 15px;
}

/* DASHBOARD GRID */
.grid2{ display:grid; grid-template-columns: 1.2fr 1fr; gap: 18px; }
@media(max-width: 980px){ .grid2{ grid-template-columns: 1fr; } }

.sep{ height:1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,.10), transparent); margin: 22px 0; }

/* Scroll animation */
.card-anim{ opacity: 0; transform: translateY(14px); transition: all .75s ease; }
.card-anim.show{ opacity: 1; transform: translateY(0px); }
</style>

<div id="particles-wrap"><canvas id="particles"></canvas></div>

<script>
(function(){
  // particles
  const canvas = document.getElementById('particles');
  if(!canvas) return;
  const ctx = canvas.getContext('2d');
  let w, h, dpr;
  const N = 70;
  const p = [];
  function resize(){
    dpr = window.devicePixelRatio || 1;
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = w*dpr; canvas.height = h*dpr;
    ctx.setTransform(dpr,0,0,dpr,0,0);
  }
  function rnd(a,b){ return a + Math.random()*(b-a); }
  function init(){
    p.length = 0;
    for(let i=0;i<N;i++){
      p.push({x:rnd(0,w), y:rnd(0,h), r:rnd(0.8,2.2), vx:rnd(-0.35,0.35), vy:rnd(-0.25,0.25), a:rnd(0.08,0.22)});
    }
  }
  function step(){
    ctx.clearRect(0,0,w,h);
    for(const s of p){
      s.x += s.vx; s.y += s.vy;
      if(s.x<0) s.x=w; if(s.x>w) s.x=0;
      if(s.y<0) s.y=h; if(s.y>h) s.y=0;
      ctx.beginPath();
      ctx.fillStyle = `rgba(245,196,0,${s.a})`;
      ctx.arc(s.x,s.y,s.r,0,Math.PI*2);
      ctx.fill();
    }
    // connect lines
    for(let i=0;i<p.length;i++){
      for(let j=i+1;j<p.length;j++){
        const a = p[i], b = p[j];
        const dx=a.x-b.x, dy=a.y-b.y;
        const dist = Math.sqrt(dx*dx+dy*dy);
        if(dist < 140){
          ctx.strokeStyle = `rgba(245,196,0,${(1 - dist/140)*0.08})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(a.x,a.y);
          ctx.lineTo(b.x,b.y);
          ctx.stroke();
        }
      }
    }
    requestAnimationFrame(step);
  }
  resize(); init(); step();
  window.addEventListener('resize', () => { resize(); init(); });

  // scroll reveal
  const io = new IntersectionObserver((entries)=>{
    entries.forEach(e=>{
      if(e.isIntersecting) e.target.classList.add('show');
    });
  }, {threshold: 0.12});

  setTimeout(()=>{
    document.querySelectorAll('.card-anim').forEach(el=>io.observe(el));
  }, 350);
})();
</script>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Toasts
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.toast == "mm_ok":
    st.success("✅ Wallet connected. Dashboard unlocked.")
elif st.session_state.toast == "mm_fail":
    st.warning(f"MetaMask connect failed: {st.session_state.toast_val}")
elif st.session_state.toast == "no_js":
    st.error("MetaMask actions disabled (missing `streamlit-javascript`). Add it in requirements.txt.")
elif st.session_state.toast == "manual_ok":
    st.success("✅ Address saved (read-only).")
elif st.session_state.toast == "manual_bad":
    st.error("❌ Invalid address.")
elif st.session_state.toast == "manual_empty":
    st.warning("Please enter a wallet address.")

st.session_state.toast = None
st.session_state.toast_val = None


# ─────────────────────────────────────────────────────────────────────────────
# Landing content (edit text here)
# ─────────────────────────────────────────────────────────────────────────────
CONTENT = {
    "hero_title": "Decentralized Lottery",
    "hero_sub": "Fully on-chain. Transparent. Auditable.",
    "hero_note": "Edit this text in code. Add your own messaging like a whitepaper.",
    "sections": [
        ("How It Works", """
<div class="muted">Explain your full structure here:</div>
<ul>
  <li>Ticket price</li>
  <li>How rounds work</li>
  <li>Sales close timing (auto by timestamp)</li>
  <li>Draw timing</li>
  <li>Commit-reveal security</li>
  <li>Prize distribution</li>
</ul>
"""),
        ("Security Model", """
<div class="muted">Explain:</div>
<ul>
  <li>Smart contract transparency</li>
  <li>BSC mainnet deployment</li>
  <li>Admin permissions</li>
  <li>Commit hash mechanism</li>
  <li>On-chain randomness model</li>
</ul>
"""),
        ("Prize & Fees", """
<div class="muted">Explain the split (edit freely):</div>
<ul>
  <li>Winners split: 6 winners (sum = 100%)</li>
  <li>Admin fee: taken from pot on draw</li>
  <li>Payouts: automatic on-chain transfers</li>
</ul>
"""),
        ("How To Buy Tickets", """
<div class="muted">Step-by-step guide (edit freely):</div>
<ul>
  <li>Install MetaMask</li>
  <li>Add BSC Network</li>
  <li>Buy BNB for gas + buy USDT</li>
  <li>Connect wallet</li>
  <li>Approve USDT</li>
  <li>Buy tickets</li>
</ul>
"""),
        ("Transparency", """
<div class="muted">Add links and proofs:</div>
<ul>
  <li>Contract address (BscScan)</li>
  <li>USDT token address (BscScan)</li>
  <li>Public logs (TicketsBought, DrawRevealed, WinnerPaid)</li>
</ul>
"""),
        ("FAQ", """
<ul>
  <li><b>Do I need an account?</b> No — wallet-only.</li>
  <li><b>Is it secure?</b> Users sign transactions in MetaMask. App never sees private keys.</li>
  <li><b>Can I verify everything?</b> Yes, on-chain events + balances are public.</li>
</ul>
"""),
    ]
}


# ─────────────────────────────────────────────────────────────────────────────
# If critical config missing, still show landing page (but disable dashboard)
# ─────────────────────────────────────────────────────────────────────────────
wallet = st.session_state.wallet
is_mm = st.session_state.wallet_type == "metamask"
is_manual = st.session_state.wallet_type == "manual"
net_badge = "BSC Mainnet" if CHAIN_ID == 56 else f"Chain {CHAIN_ID}"

# NAVBAR (always visible)
st.markdown('<div class="nav"><div class="nav-inner">', unsafe_allow_html=True)

st.markdown(
    f"""
<div class="brand">
  <div class="logo">🎰</div>
  <div>
    <div class="title">LOTTO</div>
    <div class="badges">
      <span class="pill">{net_badge}</span>
      <span>RPC: <span class="muted">{(ACTIVE_RPC or "Not connected")}</span></span>
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True
)

# Right side buttons (unique keys!)
cA, cB, cC = st.columns([1.15, 1.15, 1.25], gap="small")
with cA:
    st.markdown('<div class="btn-gold">', unsafe_allow_html=True)
    if not wallet:
        st.button("🔗 Connect", on_click=do_connect_metamask, key="nav_connect")
    else:
        st.button(f"🦊 {fmt_addr(wallet)}", disabled=True, key="nav_wallet")
    st.markdown("</div>", unsafe_allow_html=True)

with cB:
    if not wallet:
        st.button("✏️ Manual", on_click=open_manual, key="nav_manual")
    else:
        st.button("✕ Disconnect", on_click=do_disconnect, key="nav_disc")

with cC:
    if st.button("⬆️ Whitepaper", key="nav_wp"):
        st.session_state.ui_mode = "landing"

st.markdown("</div></div></div>", unsafe_allow_html=True)


# Manual connect panel (overlay-ish)
if st.session_state.show_manual and not wallet:
    st.markdown('<div class="glass card-anim show" style="margin-top:12px;">', unsafe_allow_html=True)
    st.markdown('<div class="glass-head">Connect Wallet (Read-only)</div>', unsafe_allow_html=True)
    st.markdown('<div class="glass-body muted">Paste a wallet address to view tickets. Buying requires MetaMask.</div>', unsafe_allow_html=True)

    st.text_input("Wallet address", key="manual_input", placeholder="0x1234…abcd", label_visibility="collapsed")

    b1, b2 = st.columns(2, gap="small")
    with b1:
        st.button("✅ Use This Address", on_click=submit_manual, key="manual_submit")
    with b2:
        st.button("Cancel", on_click=close_manual, key="manual_cancel")

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<div class="sep"></div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# LANDING PAGE (always public)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="hero">', unsafe_allow_html=True)
st.markdown(f"<h1>{CONTENT['hero_title']}</h1>", unsafe_allow_html=True)
st.markdown(f"<p>{CONTENT['hero_sub']}</p>", unsafe_allow_html=True)
st.markdown(f"<p class='muted'>{CONTENT['hero_note']}</p>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

cta1, cta2, cta3 = st.columns([1.2, 1.2, 1.6], gap="small")
with cta1:
    st.markdown('<div class="btn-gold">', unsafe_allow_html=True)
    st.button("🟡 Buy Tickets", key="cta_buy", on_click=lambda: st.session_state.update(ui_mode="buy"))
    st.markdown("</div>", unsafe_allow_html=True)
with cta2:
    st.button("🎟️ My Tickets", key="cta_tickets", on_click=lambda: st.session_state.update(ui_mode="my_tickets"))
with cta3:
    st.button("🔄 Refresh", key="cta_refresh", on_click=lambda: (st.cache_data.clear(), st.rerun()))

# Render whitepaper sections (glass)
for i, (title, body) in enumerate(CONTENT["sections"], start=1):
    glass_card(title, body, id_=f"sec_{i}")
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

st.markdown('<div class="sep"></div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Stop early if config missing or no web3
# ─────────────────────────────────────────────────────────────────────────────
if missing:
    st.error(
        "Missing required config. Add these in Streamlit Cloud Secrets:\n\n"
        + ", ".join(missing)
    )
    st.stop()

if not w3:
    st.error("Cannot connect to BSC RPC (all endpoints failed). Add a paid RPC in Secrets for stability.")
    st.stop()

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
        rid = int(lotto_c.functions.roundId().call())
        cr  = lotto_c.functions.currentRound().call()
        # Your currentRound returns: (state, drawTimestamp, salesCloseTimestamp, ticketsSold, startTicketId, commitHash)
        state     = int(cr[0])
        draw_ts   = int(cr[1])
        close_ts  = int(cr[2])
        sold      = int(cr[3])
        start_id  = int(cr[4])

        # price
        dec = int(usdt_c.functions.decimals().call())
        sym = str(usdt_c.functions.symbol().call())

        tp_units = int(lotto_c.functions.ticketPrice().call())
        price_str = f"{tp_units / 10**dec:,.4f} {sym}"

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
            dec=dec,
            sym=sym,
        )
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
    try:
        evs = lotto_c.events.TicketsBought.create_filter(
            from_block=frm,
            to_block="latest",
            argument_filters={"buyer": wallet}
        ).get_all_entries()

        for ev in evs:
            args = ev["args"]
            # Your event fields: qty, firstTicketId, lastTicketId
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
# DASHBOARD (only after wallet connect)
# ─────────────────────────────────────────────────────────────────────────────
snap  = get_snap()
rsnap = get_round_snap()

if wallet:
    st.markdown('<div class="sep"></div>', unsafe_allow_html=True)
    st.markdown(f"<div class='pill'>DASHBOARD UNLOCKED</div>", unsafe_allow_html=True)
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    pool = snap["c_usdt"]
    sym = snap["sym"]

    left, right = st.columns([1.15, 1], gap="large")

    with left:
        st.markdown('<div class="glass card-anim show">', unsafe_allow_html=True)
        st.markdown('<div class="glass-head">Live Round</div>', unsafe_allow_html=True)

        if not rsnap:
            st.markdown('<div class="glass-body muted">Could not read round data (ABI missing or mismatch).</div>', unsafe_allow_html=True)
        else:
            st.markdown(
                f"""
<div class="glass-body">
  <div class="muted">Round</div>
  <div style="font-size:20px;font-weight:950;margin-top:4px;">#{rsnap.get("round_id")}</div>
  <div style="height:10px"></div>
  <div><span class="muted">State:</span> <b>{state_lbl_contract(rsnap.get("state", 0))}</b></div>
  <div><span class="muted">Sales Close:</span> <b>{rsnap.get("close_str","N/A")}</b></div>
  <div><span class="muted">Next Draw:</span> <b>{rsnap.get("draw_str","N/A")}</b></div>
  <div style="height:10px"></div>
  <div><span class="muted">Ticket Price:</span> <b>{rsnap.get("price_str","N/A")}</b></div>
  <div><span class="muted">Tickets Sold:</span> <b>{rsnap.get("sold","—")}</b></div>
</div>
""",
                unsafe_allow_html=True
            )
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="glass card-anim show">', unsafe_allow_html=True)
        st.markdown('<div class="glass-head">Prize Pool</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
<div class="glass-body">
  <div class="muted">Total Pool (USDT in Contract)</div>
  <div style="font-size:44px;font-weight:1000;color:#f5c400;line-height:1;margin-top:6px;">
    {pool:,.2f} <span style="font-size:16px;color:rgba(233,238,247,.70)">{sym}</span>
  </div>
  <div style="height:10px"></div>
  <div class="muted">Contract BNB</div>
  <div style="font-weight:900">{snap["c_bnb"]:.6f}</div>
  <div style="height:10px"></div>
  <div class="muted">Admin BNB</div>
  <div style="font-weight:900">{snap["a_bnb"]:.6f}</div>
</div>
""",
            unsafe_allow_html=True
        )
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ACTIONS
    a1, a2, a3 = st.columns([1.2, 1.2, 1.6], gap="small")
    with a1:
        st.markdown('<div class="btn-gold">', unsafe_allow_html=True)
        st.button("🟡 Buy Tickets", key="dash_buy", on_click=lambda: st.session_state.update(ui_mode="buy"))
        st.markdown("</div>", unsafe_allow_html=True)
    with a2:
        st.button("🎟️ My Tickets", key="dash_tickets", on_click=lambda: st.session_state.update(ui_mode="my_tickets"))
    with a3:
        st.button("🔄 Refresh Dashboard", key="dash_refresh", on_click=lambda: (st.cache_data.clear(), st.rerun()))

    st.markdown('<div class="sep"></div>', unsafe_allow_html=True)

    # BUY PANEL
    if st.session_state.ui_mode == "buy":
        st.markdown('<div class="glass card-anim show">', unsafe_allow_html=True)
        st.markdown('<div class="glass-head">Buy Tickets</div>', unsafe_allow_html=True)

        if not lotto_c:
            st.markdown('<div class="glass-body muted">ABI not loaded. Add lotto_abi.json in repo root.</div>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        elif is_manual:
            st.markdown('<div class="glass-body">Read-only mode. Switch to MetaMask to buy.</div>', unsafe_allow_html=True)
            st.button("🦊 Connect MetaMask", key="buy_mm", on_click=do_connect_metamask)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            qty = st.number_input("Number of tickets", min_value=1, max_value=100, value=1, step=1, key="buy_qty")

            tp_units = rsnap.get("price_units")
            dec = rsnap.get("dec", snap["dec"])
            total_cost_units = int(tp_units) * int(qty) if tp_units is not None else None

            if total_cost_units is not None:
                st.success(f"Total cost: {total_cost_units / 10**dec:,.4f} {snap['sym']}")

            if not HAS_JS:
                st.error("Install `streamlit-javascript` to enable MetaMask transactions.")
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='glass-body muted'>MetaMask will ask you to approve USDT (if needed) then buy tickets.</div>", unsafe_allow_html=True)
                if st.button(f"🟡 Buy {int(qty)} Ticket{'s' if int(qty) > 1 else ''} via MetaMask", key="buy_btn"):
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

    const amt = ethers.BigNumber.from('{int(total_cost_units or 0)}');
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
                    else:
                        st.error(f"❌ Failed: {(res.get('err') if isinstance(res, dict) else res)}")

                st.markdown("</div>", unsafe_allow_html=True)

    # MY TICKETS PANEL
    if st.session_state.ui_mode == "my_tickets":
        st.markdown('<div class="glass card-anim show">', unsafe_allow_html=True)
        st.markdown('<div class="glass-head">My Tickets</div>', unsafe_allow_html=True)

        if not lotto_c:
            st.markdown('<div class="glass-body muted">ABI not loaded — add lotto_abi.json.</div>', unsafe_allow_html=True)
            st.markdown(f"<div class='glass-body'>Events: <a href='https://bscscan.com/address/{LOTTO_CONTRACT}#events' target='_blank'>Open on BscScan ↗</a></div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='glass-body muted'>Wallet: {wallet} ({'MetaMask' if is_mm else 'Read-only'})</div>", unsafe_allow_html=True)

            lookback = st.slider("Lookback blocks", min_value=10_000, max_value=300_000, value=120_000, step=10_000, key="lb")
            with st.spinner("Fetching ticket purchases…"):
                purchases = get_tickets_for_wallet(wallet, lookback_blocks=int(lookback))

            if not purchases:
                st.info("No TicketsBought events found in the selected lookback range.")
            else:
                rounds = sorted({p["round"] for p in purchases}, reverse=True)
                pick_round = st.selectbox("Round", rounds, index=0, key="pick_round")

                subset = [p for p in purchases if p["round"] == pick_round]
                st.markdown(f"<div class='glass-body'><b>{len(subset)}</b> purchase(s) found in Round <b>#{pick_round}</b></div>", unsafe_allow_html=True)

                expand_small = st.checkbox("Expand into individual ticket numbers (only if qty ≤ 50)", value=False, key="expand")

                for p in subset:
                    qty0 = int(p["qty"])
                    start = int(p["start"])
                    end = int(p["end"])
                    tx = p["tx"]

                    st.markdown(
                        f"""
<div style="margin-top:12px; padding:14px; border-radius:18px; border:1px solid rgba(245,196,0,.18); background: rgba(245,196,0,.06);">
  <div style="font-weight:950;color:#f5c400;">Round #{p["round"]} · Qty: {qty0}</div>
  <div class="muted" style="margin-top:6px;">
    Tickets: <b>{start}</b> → <b>{end}</b><br/>
    Tx: <a href="https://bscscan.com/tx/{tx}" target="_blank">{fmt_addr(tx)} ↗</a>
  </div>
</div>
""",
                        unsafe_allow_html=True
                    )

                    if expand_small and qty0 <= 50:
                        ids = list(range(start, end + 1))
                        st.code(", ".join(map(str, ids)))

            st.markdown("</div>", unsafe_allow_html=True)


# Footer (always)
st.markdown(
    f"""
<div style="text-align:center; padding:26px 0 8px 0; color:rgba(233,238,247,.55); font-size:11px;">
  LOTTO · Contract <span style="color:#f5c400;">{fmt_addr(LOTTO_CONTRACT)}</span> ·
  USDT <span style="color:#f5c400;">{fmt_addr(USDT)}</span> ·
  Admin <span style="color:#f5c400;">{fmt_addr(ADMIN)}</span>
</div>
""",
    unsafe_allow_html=True
)
