"""
sources/x_intel.py
X (Twitter) intelligence pipeline for AEGIS.

Setup (free tier — developer.x.com, no cost):
  1. Create an X Developer account at developer.x.com
  2. Create a Project + App, copy the Bearer Token
  3. Add to .env:  TWITTER_BEARER_TOKEN=your_token
  4. Optionally add: X_ACCOUNTS=PlanB,michaelsaylor,woonomic,...

Free tier limit: ~1,500 tweet reads/month. Sync sparingly (1-2x/day max).
Bookmarks require X Basic tier ($100/mo) — add TWITTER_ACCESS_TOKEN + TWITTER_ACCESS_SECRET.

Signal extraction uses Claude Haiku (~$0.0003/call).
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

VAULT       = Path("/Users/jaidenrabatin/Documents/aegis_vault/wiki")
INTEL_LOG   = VAULT / "areas/strategy/x-intel-log.md"
CACHE_FILE  = Path(__file__).parent.parent / "data" / "x_intel_cache.json"

BEARER_TOKEN    = os.getenv("TWITTER_BEARER_TOKEN", "")
ACCESS_TOKEN    = os.getenv("TWITTER_ACCESS_TOKEN", "")
ACCESS_SECRET   = os.getenv("TWITTER_ACCESS_SECRET", "")
API_KEY         = os.getenv("TWITTER_API_KEY", "")
API_SECRET      = os.getenv("TWITTER_API_SECRET", "")

# Curated default list — edit X_ACCOUNTS in .env to override
DEFAULT_ACCOUNTS = [
    "PlanB",           # Stock-to-flow, Bitcoin analytics
    "michael_saylor",  # MSTR / Bitcoin
    "woonomic",        # On-chain analytics
    "PrestonPysh",     # Bitcoin macro
    "DocumentingBTC",  # Bitcoin milestones
    "BitcoinMagazine", # Bitcoin news
    "Excellion",       # Samson Mow, Bitcoin nation-state
    "pete_rizzo_",     # Bitcoin history
    "APompliano",      # Macro / Bitcoin
    "RaoulGMI",        # Macro / global
]

claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))


# ── Intel log helpers ────────────────────────────────────────────────────────

def _load_existing_signals() -> set[str]:
    """Return set of (date, source) tuples already in the log."""
    if not INTEL_LOG.exists():
        return set()
    seen = set()
    for line in INTEL_LOG.read_text(encoding="utf-8").splitlines():
        m = re.search(r"`([^`]+)`\s+(@\w+)", line)
        if m:
            seen.add((m.group(1), m.group(2).lower()))
    return seen


def append_entry(source: str, signal: str, category: str, date: str | None = None) -> str:
    """
    Append one entry to x-intel-log.md.
    Returns the formatted line added.
    """
    if not source.startswith("@"):
        source = f"@{source}"
    date = date or datetime.now().strftime("%Y-%m-%d")
    category = category.strip().lower()
    if category not in ("trade", "macro", "content"):
        category = "macro"

    line = f"- `{date}` {source} — {signal.strip()} `| {category}`\n"

    INTEL_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not INTEL_LOG.exists():
        INTEL_LOG.write_text(
            "# X Intelligence Log\n\n"
            "> Format: `- \\`DATE\\` @source — Signal. \\`| category\\``\n"
            "> Categories: trade · macro · content\n\n",
            encoding="utf-8",
        )

    with open(INTEL_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    return line.strip()


# ── Signal extraction (Claude Haiku) ────────────────────────────────────────

_SYS = """You are AEGIS signal extractor. Given a tweet, decide:
1. Is this a meaningful signal (Bitcoin price insight, macro event, trade setup, Bitcoin adoption news, content angle) — or just noise/opinion/retweet filler?
2. If signal: extract a ONE SENTENCE summary (max 120 chars). Be terse. No hype. Raw insight only.
3. Assign category: trade | macro | content

Respond ONLY with valid JSON: {"signal": true/false, "summary": "...", "category": "..."}
If not a signal, respond: {"signal": false}"""

def _extract_signal(tweet_text: str, author: str) -> dict | None:
    """Returns {summary, category} if tweet is a signal, else None."""
    try:
        resp = claude.messages.create(
            model="claude-haiku-4-5",
            max_tokens=120,
            system=_SYS,
            messages=[{"role": "user", "content": f"@{author}: {tweet_text}"}],
        )
        result = json.loads(resp.content[0].text.strip())
        if result.get("signal"):
            return {"summary": result["summary"], "category": result.get("category", "macro")}
    except Exception:
        pass
    return None


# ── X API fetch ──────────────────────────────────────────────────────────────

def _get_client():
    if not BEARER_TOKEN:
        raise RuntimeError(
            "TWITTER_BEARER_TOKEN not set. Add it to .env.\n"
            "Get one free at developer.x.com → Project → App → Keys."
        )
    import tweepy
    return tweepy.Client(bearer_token=BEARER_TOKEN, wait_on_rate_limit=False)


def _get_user_id(client, username: str) -> str | None:
    try:
        import tweepy
        resp = client.get_user(username=username)
        return resp.data.id if resp.data else None
    except Exception:
        return None


def fetch_accounts(accounts: list[str] | None = None, max_per_account: int = 10) -> list[dict]:
    """
    Fetch recent tweets from monitored accounts, extract signals.
    Returns list of {source, signal, category, date} ready to append.
    """
    import tweepy

    if accounts:
        raw_list = accounts
    else:
        env_accounts = [a.strip().lstrip("@") for a in os.getenv("X_ACCOUNTS", "").split(",") if a.strip()]
        # Always include DEFAULT_ACCOUNTS; add any extras from X_ACCOUNTS
        seen = set(a.lower() for a in DEFAULT_ACCOUNTS)
        extras = [a for a in env_accounts if a.lower() not in seen]
        raw_list = DEFAULT_ACCOUNTS + extras
    raw_list = [a.strip().lstrip("@") for a in raw_list if a.strip()]

    client    = _get_client()
    existing  = _load_existing_signals()
    cache     = _load_cache()
    since_ids = cache.get("since_ids", {})
    new_entries = []

    for username in raw_list:
        uid = _get_user_id(client, username)
        if not uid:
            continue
        try:
            kwargs = dict(
                id=uid,
                max_results=max_per_account,
                tweet_fields=["created_at", "text"],
                exclude=["retweets", "replies"],
            )
            since = since_ids.get(username)
            if since:
                kwargs["since_id"] = since

            resp = client.get_users_tweets(**kwargs)
            if not resp.data:
                continue

            # Track highest ID for next sync
            since_ids[username] = str(resp.data[0].id)

            for tweet in reversed(resp.data):  # oldest first
                date = tweet.created_at.strftime("%Y-%m-%d") if tweet.created_at else datetime.now().strftime("%Y-%m-%d")
                key  = (date, f"@{username}".lower())
                if key in existing:
                    continue

                extracted = _extract_signal(tweet.text, username)
                if not extracted:
                    continue

                new_entries.append({
                    "source":   username,
                    "signal":   extracted["summary"],
                    "category": extracted["category"],
                    "date":     date,
                })
                existing.add(key)

        except tweepy.TooManyRequests:
            break  # hit rate limit, save progress
        except Exception:
            continue

    # Persist since_ids
    cache["since_ids"] = since_ids
    cache["last_sync"]  = datetime.now(timezone.utc).isoformat()
    _save_cache(cache)

    return new_entries


def fetch_bookmarks(max_results: int = 20) -> list[dict]:
    """
    Fetch user bookmarks. Requires X Basic tier + OAuth 1.0a or 2.0 user tokens.
    Add TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET to .env.
    """
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET]):
        raise RuntimeError(
            "Bookmarks require X Basic tier + OAuth tokens.\n"
            "Set TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET in .env."
        )
    import tweepy
    auth   = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET)
    apiv1  = tweepy.API(auth)
    client = tweepy.Client(
        consumer_key=API_KEY, consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN, access_token_secret=ACCESS_SECRET,
    )

    me = client.get_me()
    uid = me.data.id
    resp = client.get_bookmarks(id=uid, max_results=max_results,
                                tweet_fields=["created_at", "author_id", "text"],
                                expansions=["author_id"])

    if not resp.data:
        return []

    users = {u.id: u.username for u in (resp.includes.get("users") or [])}
    existing = _load_existing_signals()
    new_entries = []

    for tweet in resp.data:
        username = users.get(tweet.author_id, "unknown")
        date = tweet.created_at.strftime("%Y-%m-%d") if tweet.created_at else datetime.now().strftime("%Y-%m-%d")
        key  = (date, f"@{username}".lower())
        if key in existing:
            continue
        extracted = _extract_signal(tweet.text, username)
        if not extracted:
            continue
        new_entries.append({
            "source":   username,
            "signal":   extracted["summary"],
            "category": extracted["category"],
            "date":     date,
        })
        existing.add(key)

    return new_entries


# ── Cache ────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}

def _save_cache(data: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, indent=2))


def last_sync() -> str | None:
    cache = _load_cache()
    return cache.get("last_sync")


# ── Main: sync pipeline ──────────────────────────────────────────────────────

def sync(use_bookmarks: bool = False) -> dict:
    """
    Full sync: fetch from X, extract signals, append to vault.
    Returns {"added": N, "entries": [...]}
    """
    entries = []
    try:
        entries = fetch_accounts()
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "added": 0}

    if use_bookmarks:
        try:
            entries += fetch_bookmarks()
        except RuntimeError:
            pass  # bookmarks optional

    added = []
    for e in entries:
        line = append_entry(e["source"], e["signal"], e["category"], e["date"])
        added.append(line)

    return {"ok": True, "added": len(added), "entries": added}


if __name__ == "__main__":
    result = sync()
    print(f"Added {result['added']} new intel entries.")
    for e in result.get("entries", []):
        print(" ", e)
