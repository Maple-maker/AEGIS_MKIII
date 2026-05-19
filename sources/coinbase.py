"""
sources/coinbase.py
Coinbase balance fetcher using CDP (Advanced Trade API) JWT authentication.

Setup:
  1. coinbase.com → Settings → API → New API Key
  2. Permissions: wallet:accounts:read (or View on Advanced Trade)
  3. Add to .env:
       COINBASE_API_KEY=organizations/.../apiKeys/...
       COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----\\n...\\n-----END EC PRIVATE KEY-----\\n
"""

import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import jwt
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY    = os.getenv("COINBASE_API_KEY", "")
API_SECRET = os.getenv("COINBASE_API_SECRET", "")
HOST       = "api.coinbase.com"
BASE_URL   = f"https://{HOST}"
CACHE_FILE = Path(__file__).parent.parent / "data" / "coinbase_cache.json"
TIMEOUT    = 10


def _make_jwt(method: str, path: str) -> str:
    private_key = API_SECRET.replace("\\n", "\n")
    now = int(time.time())
    payload = {
        "sub":  API_KEY,
        "iss":  "cdp",
        "nbf":  now,
        "exp":  now + 120,
        "aud":  ["public_client"],
        "uri":  f"{method.upper()} {HOST}{path}",
    }
    headers = {
        "kid":   API_KEY,
        "nonce": secrets.token_hex(16),
    }
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)


def _get(path: str) -> dict:
    token = _make_jwt("GET", path)
    r = requests.get(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def _get_accounts() -> list[dict]:
    """Fetch all brokerage accounts, handling pagination."""
    accounts = []
    path = "/api/v3/brokerage/accounts"
    while path:
        data = _get(path)
        accounts.extend(data.get("accounts", []))
        if data.get("has_next"):
            cursor = data.get("cursor", "")
            path = f"/api/v3/brokerage/accounts?cursor={cursor}"
        else:
            path = None
    return accounts


def fetch() -> dict:
    """
    Fetch all non-zero crypto balances from Coinbase Advanced Trade.
    Returns dict with btc_balance, all_balances, and timestamp.
    """
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "COINBASE_API_KEY and COINBASE_API_SECRET not set.\n"
            "Get read-only keys at coinbase.com → Settings → API."
        )

    accounts = _get_accounts()
    balances = {}
    for acct in accounts:
        currency = acct.get("currency", "")
        amount   = float(acct.get("available_balance", {}).get("value", 0))
        if amount > 0:
            balances[currency] = round(amount, 8)

    return {
        "updated":     datetime.now(timezone.utc).isoformat(),
        "btc_balance": balances.get("BTC", 0.0),
        "balances":    balances,
    }


def load_cache() -> dict | None:
    if not CACHE_FILE.exists():
        return None
    try:
        d = json.loads(CACHE_FILE.read_text())
        age_m = (datetime.now(timezone.utc) - datetime.fromisoformat(d["updated"])).total_seconds() / 60
        return d if age_m < 15 else None
    except Exception:
        return None


def save_cache(data: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, indent=2))


def get_balance() -> dict:
    """Return cached balance if fresh, otherwise fetch live."""
    cached = load_cache()
    if cached:
        return cached
    data = fetch()
    save_cache(data)
    return data


if __name__ == "__main__":
    print("Fetching Coinbase balances…")
    d = get_balance()
    print(f"  BTC: {d['btc_balance']:.8f}")
    for k, v in d["balances"].items():
        if k != "BTC":
            print(f"  {k}: {v}")
    print(f"  Updated: {d['updated']}")
