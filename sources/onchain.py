"""
sources/onchain.py
Bitcoin on-chain metrics — raw blockchain data, no narrative.

Free sources (no API keys required):
  - blockchain.info/stats   → hash rate, difficulty, tx count, volume, supply
  - mempool.space           → block height, mempool fees
  - alternative.me          → fear/greed index

Optional (set GLASSNODE_API_KEY in .env for MVRV):
  - api.glassnode.com       → MVRV ratio, realized price
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
import yfinance as yf

VAULT      = Path("/Users/jaidenrabatin/Documents/aegis_vault/wiki")
CACHE_FILE = Path(__file__).parent.parent / "data" / "onchain_cache.json"
VAULT_FILE = VAULT / "areas/finance/btc-onchain.md"

SATS = 1e8
TIMEOUT = 8


def _blockchain_info() -> dict:
    r = requests.get("https://api.blockchain.info/stats", timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()
    supply_btc  = d["totalbc"] / SATS
    hash_rate_eh = d["hash_rate"] / 1e9          # GH/s → EH/s
    blocks_to_adj = int(d["nextretarget"]) - int(d["n_blocks_total"])
    mins_per_block = float(d.get("minutes_between_blocks", 10))
    days_to_adj   = round(blocks_to_adj * mins_per_block / 60 / 24, 1)
    return {
        "supply_btc":       round(supply_btc, 2),
        "hash_rate_eh":     round(hash_rate_eh, 2),
        "difficulty":       int(d["difficulty"]),
        "block_height":     int(d["n_blocks_total"]),
        "blocks_to_adj":    blocks_to_adj,
        "days_to_adj":      days_to_adj,
        "tx_count_24h":     int(d["n_tx"]),
        "volume_usd_24h":   round(d.get("estimated_transaction_volume_usd", 0), 0),
        "mins_per_block":   round(mins_per_block, 2),
    }


def _mempool() -> dict:
    fees = requests.get("https://mempool.space/api/v1/fees/recommended", timeout=TIMEOUT).json()
    return {
        "fee_fast_sat":  fees["fastestFee"],
        "fee_mid_sat":   fees["halfHourFee"],
        "fee_slow_sat":  fees["economyFee"],
    }


def _fear_greed() -> dict:
    d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=TIMEOUT).json()
    row = d["data"][0]
    return {"value": int(row["value"]), "label": row["value_classification"]}


def _glassnode_mvrv(api_key: str) -> dict | None:
    try:
        r = requests.get(
            "https://api.glassnode.com/v1/metrics/market/mvrv",
            params={"a": "BTC", "i": "24h", "api_key": api_key},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        rows = r.json()
        val = rows[-1]["v"] if rows else None

        r2 = requests.get(
            "https://api.glassnode.com/v1/metrics/market/price_realized_usd",
            params={"a": "BTC", "i": "24h", "api_key": api_key},
            timeout=TIMEOUT,
        )
        realized = r2.json()[-1]["v"] if r2.status_code == 200 and r2.json() else None

        return {
            "mvrv":           round(val, 3) if val else None,
            "realized_price": round(realized, 0) if realized else None,
        }
    except Exception:
        return None


def _mvrv_zone(mvrv: float) -> str:
    if mvrv < 1:    return "STRONG BUY — historically rare (<1%)"
    if mvrv < 1.5:  return "Accumulation zone"
    if mvrv < 2.5:  return "Fair value"
    if mvrv < 3.5:  return "Elevated — hold discipline"
    return "HISTORICALLY FROTHY — near cycle top territory"


def fetch() -> dict:
    btc_price = round(yf.Ticker("BTC-USD").fast_info.last_price, 2)

    bc   = _blockchain_info()
    mem  = _mempool()
    fng  = _fear_greed()

    glassnode_key = os.getenv("GLASSNODE_API_KEY", "")
    gl = _glassnode_mvrv(glassnode_key) if glassnode_key else None

    data = {
        "updated":   datetime.now(timezone.utc).isoformat(),
        "btc_price": btc_price,
        "fear_greed": fng,
        **bc,
        **mem,
        "mvrv":           gl["mvrv"]           if gl else None,
        "realized_price": gl["realized_price"] if gl else None,
    }
    return data


def write_vault(d: dict):
    fng_pct  = d["fear_greed"]["value"]
    fng_bar  = "█" * (fng_pct // 10) + "░" * (10 - fng_pct // 10)
    mvrv_str = f"{d['mvrv']:.3f} — {_mvrv_zone(d['mvrv'])}" if d["mvrv"] else "—  (add GLASSNODE_API_KEY to .env)"
    rp_str   = f"${d['realized_price']:,.0f}" if d["realized_price"] else "—"

    md = f"""# Bitcoin On-Chain Data

> Updated: {d['updated']}
> Sources: blockchain.info · mempool.space · alternative.me{' · Glassnode' if d['mvrv'] else ''}

---

## Cycle Position

| Metric | Value | Note |
|--------|-------|------|
| **MVRV** | {mvrv_str} | Market cap / realized cap |
| **Realized Price** | {rp_str} | Avg cost basis of all circulating coins |
| **Market Price** | ${d['btc_price']:,.0f} | Spot |

## Sentiment

| Metric | Value |
|--------|-------|
| **Fear & Greed** | {fng_pct}/100 — {d['fear_greed']['label']} |
| Gauge | `{fng_bar}` (0=extreme fear · 100=extreme greed) |

## Network Security

| Metric | Value |
|--------|-------|
| **Hash Rate** | {d['hash_rate_eh']:.2f} EH/s |
| **Difficulty** | {d['difficulty']:,} |
| **Next Adjustment** | {d['blocks_to_adj']:,} blocks · ~{d['days_to_adj']} days |
| **Avg Block Time** | {d['mins_per_block']} min (target: 10.00) |

## Chain Activity (24h)

| Metric | Value |
|--------|-------|
| **Transactions** | {d['tx_count_24h']:,} |
| **On-chain Volume** | ${d['volume_usd_24h']:,.0f} |
| **Block Height** | {d['block_height']:,} |
| **Circulating Supply** | {d['supply_btc']:,.2f} BTC |

## Mempool Fees (sat/vB)

| Speed | Fee |
|-------|-----|
| Fast (next block) | {d['fee_fast_sat']} sat/vB |
| Medium (~30 min) | {d['fee_mid_sat']} sat/vB |
| Slow (economy) | {d['fee_slow_sat']} sat/vB |
"""
    VAULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    VAULT_FILE.write_text(md, encoding="utf-8")


def update() -> dict:
    d = fetch()
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(d, indent=2))
    write_vault(d)
    return d


def load_cache() -> dict | None:
    if not CACHE_FILE.exists():
        return None
    try:
        d = json.loads(CACHE_FILE.read_text())
        updated = datetime.fromisoformat(d["updated"])
        age_h = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
        return d if age_h < 4 else None       # refresh if >4 hours old
    except Exception:
        return None


if __name__ == "__main__":
    print("Fetching on-chain data…")
    d = update()
    print(f"  Fear & Greed : {d['fear_greed']['value']} ({d['fear_greed']['label']})")
    print(f"  Hash Rate    : {d['hash_rate_eh']} EH/s")
    print(f"  Transactions : {d['tx_count_24h']:,} / 24h")
    print(f"  Block Height : {d['block_height']:,}")
    print(f"  Fees (fast)  : {d['fee_fast_sat']} sat/vB")
    if d['mvrv']:
        print(f"  MVRV         : {d['mvrv']}")
    else:
        print("  MVRV         : add GLASSNODE_API_KEY to .env for this metric")
    print(f"\nVault updated: {VAULT_FILE}")
