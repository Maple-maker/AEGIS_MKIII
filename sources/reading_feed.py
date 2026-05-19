"""
sources/reading_feed.py
AEGIS reading feed — curated RSS from Bitcoin/finance publications + vault reading queue.
No API keys required. Runs on demand or during the daily brief.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

VAULT = Path("/Users/jaidenrabatin/Documents/aegis_vault/wiki")
READING_QUEUE = VAULT / "areas/strategy/reading-queue.md"
SOURCES_DIR   = VAULT / "sources"

# ── Curated RSS feeds by niche ────────────────────────────────────────────────

FEEDS = [
    # Bitcoin / Macro
    {"url": "https://bitcoinmagazine.com/.rss/full/",         "source": "Bitcoin Magazine",    "niche": "bitcoin"},
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/","source": "CoinDesk",            "niche": "bitcoin"},
    {"url": "https://unchainedcrypto.com/feed/",               "source": "Unchained (Podcast)", "niche": "bitcoin"},
    {"url": "https://medium.com/feed/tag/bitcoin",            "source": "Medium / Bitcoin",    "niche": "bitcoin"},
    {"url": "https://thebitcoinlayer.substack.com/feed",      "source": "The Bitcoin Layer",   "niche": "bitcoin"},
    # Personal Finance / Investing
    {"url": "https://www.mrmoneymustache.com/feed/",          "source": "Mr. Money Mustache",  "niche": "personal-finance"},
    {"url": "https://affordanything.com/feed/",               "source": "Afford Anything",     "niche": "personal-finance"},
    # Travel Hacking / Credit
    {"url": "https://thepointsguy.com/feed/",                 "source": "The Points Guy",      "niche": "credit"},
    {"url": "https://viewfromthewing.com/feed/",              "source": "View from the Wing",  "niche": "credit"},
]

# Keywords that score relevance to Jaiden's niches
RELEVANCE_KEYWORDS = {
    "bitcoin":          ["bitcoin", "btc", "sats", "satoshi", "lightning", "halving", "mstr", "strategy", "blackrock etf", "spot etf"],
    "personal-finance": ["wealth", "financial freedom", "investing", "compound", "savings", "net worth", "income"],
    "credit":           ["credit card", "miles", "points", "amex", "chase", "travel hacking", "transfer", "lounge"],
}


def _score_relevance(text: str, niche: str) -> int:
    text_lower = text.lower()
    keywords = RELEVANCE_KEYWORDS.get(niche, [])
    return sum(1 for kw in keywords if kw in text_lower)


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


def fetch_rss_articles(days_back: int = 7, max_per_feed: int = 5) -> list[dict]:
    """Fetch recent articles from all curated RSS feeds."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    articles: list[dict] = []

    for feed in FEEDS:
        try:
            r = requests.get(feed["url"], timeout=10, headers={"User-Agent": "AEGIS/1.0 (RSS Reader)"})
            r.raise_for_status()
            root = ET.fromstring(r.content)

            # Handle both RSS 2.0 and Atom
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item") or root.findall(".//atom:entry", ns)

            count = 0
            for item in items:
                if count >= max_per_feed:
                    break

                def _get(tag):
                    el = item.find(tag)
                    if el is None:
                        el = item.find(f"atom:{tag}", ns)
                    return (el.text or "").strip() if el is not None else ""

                title   = _get("title")
                # <link> in RSS is text; in Atom it's an empty element with href attr
                link_el = item.find("link")
                if link_el is None:
                    link_el = item.find("atom:link", ns)
                link = ""
                if link_el is not None:
                    link = (link_el.text or link_el.get("href", "")).strip()
                desc    = re.sub(r"<[^>]+>", "", _get("description") or _get("summary"))[:200]
                pub_raw = _get("pubDate") or _get("published") or _get("updated")
                pub_dt  = _parse_date(pub_raw)

                if not title or not link:
                    continue
                if pub_dt and pub_dt < cutoff:
                    continue

                score = _score_relevance(f"{title} {desc}", feed["niche"])
                articles.append({
                    "title":     title,
                    "url":       link,
                    "source":    feed["source"],
                    "niche":     feed["niche"],
                    "summary":   desc.strip(),
                    "published": pub_dt.strftime("%Y-%m-%d") if pub_dt else "recent",
                    "score":     score,
                })
                count += 1

        except Exception:
            continue

    # Sort by relevance score then recency
    articles.sort(key=lambda x: (x["score"], x["published"]), reverse=True)
    return articles


def get_reading_queue() -> list[dict]:
    """Parse the vault reading queue for items still marked 'queued'."""
    if not READING_QUEUE.exists():
        return []

    items = []
    try:
        text = READING_QUEUE.read_text(encoding="utf-8")
        for line in text.splitlines():
            # Match table rows: | priority | file | status | domain | notes |
            m = re.match(r"\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|\s*(\w+)\s*\|\s*([^|]+)\s*\|\s*([^|]*)\s*\|", line)
            if m and m.group(3).lower() == "queued":
                items.append({
                    "priority": int(m.group(1)),
                    "file":     m.group(2).strip(),
                    "domain":   m.group(4).strip(),
                    "notes":    m.group(5).strip(),
                })
    except Exception:
        pass

    items.sort(key=lambda x: x["priority"])
    return items


def get_ingested_sources(limit: int = 8) -> list[dict]:
    """Return recently ingested vault sources."""
    if not SOURCES_DIR.exists():
        return []

    sources = []
    for f in sorted(SOURCES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            text = f.read_text(encoding="utf-8")
            title_m = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', text, re.M)
            tags_m  = re.search(r'^tags:\s*\[(.+?)\]', text, re.M)
            title   = title_m.group(1).strip() if title_m else f.stem.replace("-", " ").title()
            tags    = [t.strip() for t in tags_m.group(1).split(",")] if tags_m else []
            sources.append({"title": title, "file": f.name, "tags": tags[:3]})
        except Exception:
            continue
    return sources


def get_full_feed(days_back: int = 7) -> dict:
    """Return the complete reading feed: articles + queue + ingested sources."""
    return {
        "articles":  fetch_rss_articles(days_back=days_back),
        "queue":     get_reading_queue(),
        "ingested":  get_ingested_sources(),
        "as_of":     datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
