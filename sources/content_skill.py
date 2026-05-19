"""
sources/content_skill.py
Full-cycle YouTube content creator skill — Phase 2 (research) + Phase 3 (script).
Triggered async from Telegram /idea. Pulls from vault, X intel, and YouTube.
"""

import os
import re
import threading
from datetime import datetime
from pathlib import Path

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

VAULT       = Path("/Users/jaidenrabatin/Documents/aegis_vault/wiki")
CONTENT_DIR = VAULT / "areas/content"
INTEL_LOG   = VAULT / "areas/strategy/x-intel-log.md"
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY", "")

claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))


# ── Phase 2A: Vault research ─────────────────────────────────────────────────

def _vault_research(topic: str) -> str:
    """Scan vault concept and area pages for context relevant to the topic."""
    keywords = [w.lower() for w in re.split(r"\W+", topic) if len(w) > 3]
    hits = []

    search_dirs = [
        VAULT / "concepts",
        VAULT / "areas/finance",
        VAULT / "areas/strategy",
        VAULT / "areas/content",
        VAULT / "areas/health",
        VAULT / "areas/faith",
    ]
    # Excluded: areas/military — military context bleeds into general-audience scripts

    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            if f.name in ("content-pipeline.md", "voice-guide.md", "x-intel-log.md"):
                continue
            try:
                text = f.read_text(encoding="utf-8")
                score = sum(1 for kw in keywords if kw in text.lower())
                if score >= 2:
                    # Trim to first 800 chars to keep context manageable
                    preview = text[:800].strip()
                    hits.append((score, f.stem, preview))
            except Exception:
                continue

    hits.sort(reverse=True)
    if not hits:
        return "No directly relevant vault pages found."

    sections = []
    for score, name, preview in hits[:6]:
        sections.append(f"### [{name}] (relevance: {score})\n{preview}\n")
    return "\n".join(sections)


# ── Phase 2B: X intel research ───────────────────────────────────────────────

def _x_intel_research(topic: str) -> str:
    """Pull relevant signals from X intel log — strict relevance only."""
    if not INTEL_LOG.exists():
        return "X intel log empty — no signals found."

    # Only use meaningful keywords — skip generic Bitcoin/crypto terms
    # that would match every single entry
    skip_words = {"bitcoin", "btc", "crypto", "market", "price", "this", "that",
                  "with", "from", "they", "their", "about", "have", "will", "more"}
    keywords = [w.lower() for w in re.split(r"\W+", topic)
                if len(w) > 4 and w.lower() not in skip_words]

    if not keywords:
        return "Topic too generic for targeted intel filtering."

    lines = INTEL_LOG.read_text(encoding="utf-8").splitlines()
    hits = []

    for line in lines:
        if not line.strip().startswith("-"):
            continue
        score = sum(1 for kw in keywords if kw in line.lower())
        if score >= 2:  # Require at least 2 specific keyword matches
            hits.append((score, line.strip()))

    hits.sort(reverse=True)
    if not hits:
        return "No closely relevant X intel signals found for this specific topic."

    return "\n".join(line for _, line in hits[:8])


# ── Phase 2C: YouTube competitor research ────────────────────────────────────

def _youtube_search(query: str, max_results: int = 8) -> list[dict]:
    """Search YouTube Data API v3 for top videos on a topic."""
    if not YOUTUBE_KEY:
        return []
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part":       "snippet",
                "q":          query,
                "type":       "video",
                "order":      "viewCount",
                "maxResults": max_results,
                "key":        YOUTUBE_KEY,
            },
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("items", [])

        video_ids = [i["id"]["videoId"] for i in items]
        if not video_ids:
            return []

        # Get view counts
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
        stats = {v["id"]: v for v in stats_r.json().get("items", [])}

        results = []
        for item in items:
            vid_id  = item["id"]["videoId"]
            snippet = item["snippet"]
            stat    = stats.get(vid_id, {}).get("statistics", {})
            results.append({
                "id":          vid_id,
                "title":       snippet.get("title", ""),
                "channel":     snippet.get("channelTitle", ""),
                "published":   snippet.get("publishedAt", "")[:10],
                "description": snippet.get("description", "")[:300],
                "views":       int(stat.get("viewCount", 0)),
                "likes":       int(stat.get("likeCount", 0)),
                "comments":    int(stat.get("commentCount", 0)),
                "url":         f"https://youtube.com/watch?v={vid_id}",
            })

        results.sort(key=lambda x: x["views"], reverse=True)
        return results

    except Exception as e:
        return []


def _get_transcript(video_id: str, max_chars: int = 2000) -> str:
    """Fetch YouTube transcript — no API key required."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        segments = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US"])
        text = " ".join(s["text"] for s in segments)
        return text[:max_chars]
    except Exception:
        return ""


def _youtube_research(topic: str) -> str:
    """Search YouTube, pull top competitor videos and transcripts."""
    videos = _youtube_search(topic)
    if not videos:
        return "YouTube search unavailable — add YOUTUBE_API_KEY to .env."

    sections = []
    for v in videos[:5]:
        transcript = _get_transcript(v["id"])
        hook_snippet = transcript[:400] if transcript else "(transcript unavailable)"
        sections.append(
            f"COMPETITOR VIDEO\n"
            f"─────────────────────────────\n"
            f"Channel: {v['channel']}\n"
            f"Title: {v['title']}\n"
            f"Views: {v['views']:,} · Likes: {v['likes']:,} · Comments: {v['comments']:,}\n"
            f"Published: {v['published']}\n"
            f"URL: {v['url']}\n"
            f"Description: {v['description']}\n"
            f"Opening (transcript): {hook_snippet}\n"
            f"─────────────────────────────"
        )

    return "\n\n".join(sections)


# ── Research brief assembly prompt ────────────────────────────────────────────

_RESEARCH_SYSTEM = """You are AEGIS research analyst for Jaiden Rabatin — Bitcoin investor and YouTube creator (@jaidenrabatin, 700+ subs, 400k+ views). His niches: Bitcoin/investing, personal finance, faith, fitness, leadership. Target audience: broad (25–45 year olds building wealth). IMPORTANT: Do NOT use military, Army, deployment, or soldier framing unless the idea_text explicitly requests it. Default to angles any working adult can relate to.

Given vault context, X intelligence signals, and competitor YouTube data, produce a structured Master Research Brief for one content idea.

Output format:

## MASTER RESEARCH BRIEF

**Topic**:
**Locked Angle**: [The specific take that differentiates from competitors]
**Target Viewer**: [One sentence — who is watching and why]

### Topic Overview
[2-3 paragraphs grounding the topic]

### 5 Strongest Arguments/Claims
1. [Claim] — [Evidence or source]
2.
3.
4.
5.

### 3 Counterarguments to Address
1.
2.
3.

### 5 Key Stats or Quotes to Use
1.
2.
3.
4.
5.

### Competitor Gap Analysis
What top videos cover well:
What NONE of them say that Jaiden can say uniquely:

### X Intelligence Signals Relevant to This Topic
[Filtered signals from intel log]

### Vault Knowledge to Pull In
[Concepts or notes from Jaiden's vault that strengthen the argument]

### Recommended Video Structure
[Section-by-section rough outline, 8-12 min target]

---
CONTEXT HANDOFF
─────────────────────────────
Topic locked:
Angle:
Target audience:
Key differentiator:
Research brief status: Complete
─────────────────────────────"""


_SCRIPT_SYSTEM = """You are AEGIS script writer for Jaiden Rabatin — Bitcoin investor and YouTube creator. Voice: conversational, analytical, direct. No corporate-speak. Assumes audience understands basic investing. IMPORTANT: Do NOT use military, Army, deployment, or soldier framing. Write for a broad audience — any 25–45 year old building wealth on a normal income. If Jaiden's personal context is relevant, frame it as: someone who lived overseas and managed money in unconventional situations (not military-specific).

Given a Master Research Brief, write a full publication-ready YouTube script.

Include:

## HOOK VARIATIONS (5)
One each: Shock Stat · Contrarian Take · Story Open · Direct Promise · Burning Question
Rate each: Retention (1-5) · Thumbnail compat (1-5) · Authenticity (1-5)
Mark recommended with ★

## FULL SCRIPT (~1,400–2,000 words)
Use this structure with [B-ROLL], [GRAPHIC], [TALKING HEAD], [SCREEN RECORD] markers:

[HOOK — 0:00–0:30]
[CONTEXT SETUP — 0:30–1:30]
[SECTION 1 — 1:30–4:00]
[SECTION 2 — 4:00–7:00]
[SECTION 3 — 7:00–10:30]
[SOFT CTA BRIDGE — 10:30–11:00]
[CONCLUSION — 11:00–12:00]
[OUTRO CTA — 12:00–12:30]

## TITLE OPTIONS (5)
- Curiosity gap
- Direct value
- Contrarian
- Number-based
- Personal narrative

## THUMBNAIL CONCEPTS (3)
Visual description for each.

## SHORT-FORM CLIP
Best 60-second segment for YouTube Shorts/Reels — timestamp + script excerpt.

## TWITTER/X THREAD OUTLINE
Hook tweet + 6 body tweets + CTA tweet."""


# ── Main pipeline ─────────────────────────────────────────────────────────────

def _run_full_pipeline(idea_text: str, vault_page: Path, telegram_callback=None):
    try:
        def notify(msg):
            if telegram_callback:
                telegram_callback(msg)

        notify("🔍 *Phase 2: Research starting…*\n\nPulling vault context, X intel, and YouTube competitors.")

        # Phase 2A: Vault
        vault_ctx = _vault_research(idea_text)

        # Phase 2B: X intel
        intel_ctx = _x_intel_research(idea_text)

        # Phase 2C: YouTube
        notify("📺 Analyzing competitor videos…")
        yt_ctx = _youtube_research(idea_text)

        # Assemble research brief via Claude
        notify("🧠 Assembling research brief…")
        research_resp = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            system=_RESEARCH_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Content idea: {idea_text}\n\n"
                    f"=== VAULT CONTEXT ===\n{vault_ctx}\n\n"
                    f"=== X INTELLIGENCE SIGNALS ===\n{intel_ctx}\n\n"
                    f"=== YOUTUBE COMPETITOR DATA ===\n{yt_ctx}"
                )
            }]
        )
        research_brief = research_resp.content[0].text.strip()

        # Phase 3: Full script
        notify("✍️ Writing script and hooks…")
        script_resp = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=_SCRIPT_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Original idea: {idea_text}\n\n"
                    f"=== MASTER RESEARCH BRIEF ===\n{research_brief}"
                )
            }]
        )
        script_output = script_resp.content[0].text.strip()

        # Write to vault page
        if vault_page.exists():
            existing = vault_page.read_text(encoding="utf-8")
            existing = existing.replace("**Stage**: idea", "**Stage**: scripted")
            existing = re.sub(r"^updated:.*$", f"updated: {datetime.now().strftime('%Y-%m-%d')}", existing, flags=re.M)

            full_output = (
                existing
                + "\n\n---\n\n## Phase 2 — Research Brief\n\n"
                + research_brief
                + "\n\n---\n\n## Phase 3 — Script & Hooks\n\n"
                + script_output
            )
            vault_page.write_text(full_output, encoding="utf-8")

        # Extract recommended hook for summary
        hook_m = re.search(r"★.{0,200}", script_output)
        hook   = hook_m.group(0).strip()[:200] if hook_m else "See vault for hooks"

        title_m = re.search(r"(?:Curiosity gap|Title Options).*?\n[-•]\s*(.+)", script_output, re.S)
        title   = title_m.group(1).strip()[:80] if title_m else vault_page.stem.replace("-", " ").title()

        notify(
            f"✅ *Full content brief ready*\n\n"
            f"*{title}*\n\n"
            f"★ Hook: _{hook}_\n\n"
            f"Research brief + full script + hooks + short-form clip + Twitter thread saved to vault:\n"
            f"`areas/content/{vault_page.stem}.md`\n\n"
            f"Open in Obsidian to review and edit before filming."
        )

    except Exception as e:
        if telegram_callback:
            telegram_callback(f"⚠ Pipeline error: {e}")


def run_skill_async(idea_text: str, vault_page: Path, telegram_callback=None):
    """Launch full pipeline in background thread — non-blocking."""
    t = threading.Thread(
        target=_run_full_pipeline,
        args=(idea_text, vault_page, telegram_callback),
        daemon=True,
    )
    t.start()
    return t
