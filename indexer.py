from __future__ import annotations

import os, json, time
from pathlib import Path

import psycopg2
import psycopg2.extras
from web3 import Web3


# ----------------------------
# ENV (Render worker / local)
# ----------------------------
CHAIN_ID        = int(os.getenv("CHAIN_ID", "56"))
BSC_RPC         = os.getenv("BSC_RPC", "")
LOTTO_CONTRACT  = os.getenv("LOTTO_CONTRACT", "")
LOTTO_ABI_PATH  = os.getenv("LOTTO_ABI_PATH", "lotto_abi.json")
DATABASE_URL    = os.getenv("DATABASE_URL", "")

CONFIRMATIONS   = int(os.getenv("CONFIRMATIONS", "15"))
POLL_SECS       = float(os.getenv("POLL_SECS", "2.0"))
MAX_BATCH       = int(os.getenv("MAX_BATCH", "1500"))
MIN_BATCH       = int(os.getenv("MIN_BATCH", "100"))

START_BLOCK     = int(os.getenv("START_BLOCK", "0"))  # optional for first-time backfill


def die(msg: str):
    raise SystemExit(msg)


if not BSC_RPC:        die("Missing BSC_RPC")
if not LOTTO_CONTRACT: die("Missing LOTTO_CONTRACT")
if not DATABASE_URL:   die("Missing DATABASE_URL")


def load_abi(path: str):
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).parent / path
    raw = json.loads(p.read_text(encoding="utf-8"))
    return raw["abi"] if isinstance(raw, dict) and "abi" in raw else raw


def ensure_tables(conn):
    # You said you already created tables, but keep this safe
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets_bought (
          id BIGSERIAL PRIMARY KEY,
          chain_id INT NOT NULL DEFAULT 56,
          contract_addr TEXT NOT NULL,
          buyer TEXT NOT NULL,
          round_id BIGINT,
          qty BIGINT,
          first_ticket_id BIGINT,
          last_ticket_id BIGINT,
          tx_hash TEXT NOT NULL,
          block_number BIGINT NOT NULL,
          log_index INT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          UNIQUE (tx_hash, log_index)
        );
        """)
        cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_tickets_buyer_block
        ON tickets_bought (buyer, block_number DESC);
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS indexer_state (
          k TEXT PRIMARY KEY,
          v TEXT NOT NULL
        );
        """)
    conn.commit()


def get_state(conn, key: str):
    with conn.cursor() as cur:
        cur.execute("SELECT v FROM indexer_state WHERE k=%s", (key,))
        r = cur.fetchone()
        return r[0] if r else None


def set_state(conn, key: str, val: str):
    with conn.cursor() as cur:
        cur.execute("""
          INSERT INTO indexer_state(k,v) VALUES(%s,%s)
          ON CONFLICT(k) DO UPDATE SET v=EXCLUDED.v
        """, (key, val))
    conn.commit()


def insert_rows(conn, rows, chain_id: int, contract_addr: str):
    if not rows:
        return
    values = [
        (
            chain_id,
            contract_addr.lower(),
            r["buyer"].lower(),
            int(r["round_id"]),
            int(r["qty"]),
            int(r["first_ticket_id"]),
            int(r["last_ticket_id"]),
            r["tx_hash"].lower(),
            int(r["block_number"]),
            int(r["log_index"]),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO tickets_bought
            (chain_id, contract_addr, buyer, round_id, qty, first_ticket_id, last_ticket_id,
             tx_hash, block_number, log_index)
            VALUES %s
            ON CONFLICT (tx_hash, log_index) DO NOTHING
            """,
            values
        )
    conn.commit()


def main():
    w3 = Web3(Web3.HTTPProvider(BSC_RPC, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        die("RPC not connected")

    lotto_addr = Web3.to_checksum_address(LOTTO_CONTRACT)
    abi = load_abi(LOTTO_ABI_PATH)
    lotto = w3.eth.contract(address=lotto_addr, abi=abi)

    conn = psycopg2.connect(DATABASE_URL)
    ensure_tables(conn)

    last = get_state(conn, "last_indexed_block")
    head = int(w3.eth.block_number)

    if last is None:
        # first run
        start = START_BLOCK if START_BLOCK > 0 else max(0, head - 200_000)
        set_state(conn, "last_indexed_block", str(start))
        last_block = start
    else:
        last_block = int(last)

    batch = MAX_BATCH
    print(f"[indexer] start at {last_block}, head={head}, confirmations={CONFIRMATIONS}, batch={batch}")

    while True:
        head = int(w3.eth.block_number)
        target = head - CONFIRMATIONS
        if target <= last_block:
            time.sleep(POLL_SECS)
            continue

        frm = last_block + 1
        to  = min(target, frm + batch - 1)

        try:
            logs = lotto.events.TicketsBought().get_logs(fromBlock=frm, toBlock=to)
        except Exception as e:
            msg = str(e).lower()
            if ("limit exceeded" in msg) or ("-32005" in msg) or ("query returned more than" in msg):
                batch = max(MIN_BATCH, batch // 2)
                print(f"[indexer] limit hit; shrink batch -> {batch} (range {frm}-{to})")
                time.sleep(0.5)
                continue
            print(f"[indexer] get_logs error: {e} (range {frm}-{to})")
            time.sleep(2.0)
            continue

        rows = []
        for ev in logs:
            try:
                a = ev["args"]
                rows.append({
                    "buyer": str(a.get("buyer")),
                    "round_id": int(a.get("roundId", 0)),
                    "qty": int(a.get("qty", 0)),
                    "first_ticket_id": int(a.get("firstTicketId", 0)),
                    "last_ticket_id": int(a.get("lastTicketId", 0)),
                    "tx_hash": ev["transactionHash"].hex(),
                    "block_number": int(ev["blockNumber"]),
                    "log_index": int(ev["logIndex"]),
                })
            except Exception:
                continue

        insert_rows(conn, rows, CHAIN_ID, lotto_addr)

        last_block = to
        set_state(conn, "last_indexed_block", str(last_block))

        # gentle ramp-up if stable
        if batch < MAX_BATCH and len(logs) < 200:
            batch = min(MAX_BATCH, batch + 200)

        time.sleep(0.1)


if __name__ == "__main__":
    main()
