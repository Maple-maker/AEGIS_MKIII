"""
sources/idea_gen.py
AEGIS video idea suggestion engine.
Searches YouTube for trending content in Jaiden's niches, cross-checks the
existing pipeline, and generates fresh angles via Claude.
"""

import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

VAULT       = Path("/Users/jaidenrabatin/Documents/aegis_vault/wiki")
CONTENT_DIR = VAULT / "areas/content"
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY", "")

claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

# ── Niche search profiles ─────────────────────────────────────────────────────

NICHE_QUERIES = {
    "bitcoin": [
        "bitcoin accumulation strategy 2025",
        "how to buy bitcoin beginner guide",
        "bitcoin investing personal finance",
        "bitcoin vs inflation wealth building",
        "bitcoin stacking DCA strategy",
    ],
    "credit": [
        "credit card travel hacking 2025",
        "best credit cards points miles",
        "how to earn free flights credit cards",
        "amex platinum chase sapphire comparison",
    ],
    "personal_finance": [
        "build wealth normal income 2025",
        "financial freedom young professional",
        "money habits that build wealth",
        "investing on a budget",
    ],
    "faith": [
        "faith and finances christian money",
        "biblical principles money wealth",
    ],
    "fitness": [
        "simple fitness routine busy professional",
        "discipline mindset fitness results",
    ],
}

# Default niches to scan when no topic is specified
DEFAULT_NICHES = ["bitcoin", "personal_finance", "credit"]


def _youtube_trending(queries: list[str], days_back: int = 90) -> list[dict]:
    """Search YouTube for top videos across multiple queries, deduplicated."""
    if not YOUTUBE_KEY:
        return []

    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen_ids: set[str] = set()
    all_videos: list[dict] = []

    for query in queries:
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part":            "snippet",
                    "q":               query,
                    "type":            "video",
                    "order":           "viewCount",
                    "maxResults":      8,
                    "publishedAfter":  since,
                    "key":             YOUTUBE_KEY,
                },
                timeout=10,
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            video_ids = [i["id"]["videoId"] for i in items if i["id"]["videoId"] not in seen_ids]
            if not video_ids:
                continue

            stats_r = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "statistics,snippet",
                    "id":   ",".join(video_ids),
                    "key":  YOUTUBE_KEY,
                },
                timeout=10,
            )
            stats_r.raise_for_status()

            for v in stats_r.json().get("items", []):
                vid_id = v["id"]
                if vid_id in seen_ids:
                    continue
                seen_ids.add(vid_id)
                snip = v["snippet"]
                stat = v.get("statistics", {})
                all_videos.append({
                    "id":        vid_id,
                    "title":     snip.get("title", ""),
                    "channel":   snip.get("channelTitle", ""),
                    "published": snip.get("publishedAt", "")[:10],
                    "views":     int(stat.get("viewCount", 0)),
                    "likes":     int(stat.get("likeCount", 0)),
                    "query":     query,
                })
        except Exception:
            continue

    all_videos.sort(key=lambda x: x["views"], reverse=True)
    return all_videos[:30]


def _read_existing_pipeline() -> list[str]:
    """Return titles/slugs of ideas already in the content pipeline."""
    titles = []
    if not CONTENT_DIR.exists():
        return titles
    skip = {"content-pipeline.md", "voice-guide.md"}
    for f in CONTENT_DIR.glob("*.md"):
        if f.name in skip:
            continue
        try:
            text = f.read_text(encoding="utf-8")
            m = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", text, re.M)
            if m:
                titles.append(m.group(1).strip())
        except Exception:
            continue
    return titles


_SUGGEST_SYSTEM = """You are AEGIS, content strategist for Jaiden Rabatin — Bitcoin investor and YouTube creator (@jaidenrabatin, 724 subs, 466k views).

His niches: Bitcoin accumulation · Credit card travel hacking · Personal finance · Faith · Fitness · Leadership.
His edge: real numbers, authentic journey, bridges travel hacking and Bitcoin. 25-40 year old audience. No military framing.

Given trending YouTube videos in his niche and his existing pipeline, generate exactly 5 fresh video ideas he hasn't covered yet.

For each idea output:

### Idea [N]
**Title**: [One strong working title — curiosity gap or direct value]
**Hook**: [One sentence — the opening line of the video, makes the viewer stop scrolling]
**Why it will perform**: [1-2 sentences — what competitor data shows, what gap exists]
**Unique angle for Jaiden**: [What only he can bring to this topic]
**Niche**: [bitcoin | credit | personal-finance | faith | fitness]

Rules:
- No ideas already in the pipeline
- No military/Army/deployment framing
- Prefer formats that have demonstrably worked recently (journey updates, comparisons, "I tried X for 30 days", real numbers)
- At least 3 of the 5 should be Bitcoin/investing niche
- Ideas should be filmable now, not dependent on future events"""


def suggest_ideas(topic: str | None = None) -> list[dict]:
    """
    Generate 5 fresh video ideas.
    topic: optional focus (e.g. 'bitcoin loans', 'credit cards'). If None, scans all default niches.
    """
    if topic:
        # Build targeted queries from the topic
        queries = [
            f"{topic} youtube 2025",
            f"{topic} investing strategy",
            f"how to {topic}",
            f"{topic} personal finance",
        ]
    else:
        queries = []
        for niche in DEFAULT_NICHES:
            queries.extend(NICHE_QUERIES.get(niche, []))

    trending = _youtube_trending(queries)
    existing = _read_existing_pipeline()

    # Format trending videos for Claude
    trend_lines = []
    for v in trending[:20]:
        trend_lines.append(
            f"- [{v['views']:,} views] \"{v['title']}\" — {v['channel']} ({v['published']})"
        )
    trend_block = "\n".join(trend_lines) if trend_lines else "YouTube data unavailable — generate ideas from niche knowledge."

    existing_block = "\n".join(f"- {t}" for t in existing) if existing else "Pipeline is empty."

    resp = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        system=_SUGGEST_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                f"Topic focus: {topic or 'Bitcoin/investing/personal finance (general)'}\n\n"
                f"=== TRENDING VIDEOS IN NICHE (last 90 days) ===\n{trend_block}\n\n"
                f"=== ALREADY IN JAIDEN'S PIPELINE (skip these) ===\n{existing_block}\n\n"
                "Generate 5 fresh ideas."
            ),
        }],
    )

    raw = resp.content[0].text.strip()

    # Parse into structured list
    ideas = []
    blocks = re.split(r"###\s*Idea\s*\d+", raw)
    for block in blocks:
        if not block.strip():
            continue
        idea: dict = {}
        for field, pattern in [
            ("title",    r"\*\*Title\*\*:\s*(.+)"),
            ("hook",     r"\*\*Hook\*\*:\s*(.+)"),
            ("why",      r"\*\*Why it will perform\*\*:\s*(.+)"),
            ("angle",    r"\*\*Unique angle for Jaiden\*\*:\s*(.+)"),
            ("niche",    r"\*\*Niche\*\*:\s*(.+)"),
        ]:
            m = re.search(pattern, block)
            idea[field] = m.group(1).strip() if m else ""
        if idea.get("title"):
            ideas.append(idea)

    return ideas[:5]


def format_for_telegram(ideas: list[dict], topic: str | None = None) -> str:
    """Format ideas as a Telegram message."""
    header = f"💡 *5 Video Ideas — {topic.title() if topic else 'Niche Scan'}*\n\n"
    lines = [header]
    niche_emoji = {
        "bitcoin": "🟠", "credit": "✈️", "personal-finance": "💰",
        "faith": "✝️", "fitness": "💪", "leadership": "🎯",
    }
    for i, idea in enumerate(ideas, 1):
        emoji = niche_emoji.get(idea.get("niche", ""), "💡")
        lines.append(
            f"{emoji} *Idea {i}: {idea.get('title', '')}*\n"
            f"_{idea.get('hook', '')}_\n"
            f"{idea.get('why', '')}\n"
            f"Jaiden's angle: {idea.get('angle', '')}\n"
        )
    lines.append("→ Reply `/idea [title]` to kick off the full research + script pipeline.")
    return "\n".join(lines)
