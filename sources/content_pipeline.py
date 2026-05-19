"""
sources/content_pipeline.py
Content idea pipeline — vault reader and idea creator.

Creates content idea pages at wiki/areas/content/[slug].md using the
AEGIS template. Reads all existing ideas for dashboard display.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

VAULT        = Path("/Users/jaidenrabatin/Documents/aegis_vault/wiki")
CONTENT_DIR  = VAULT / "areas/content"
PIPELINE_LOG = CONTENT_DIR / "content-pipeline.md"

claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

STAGES = ["idea", "outlined", "scripted", "scheduled", "published", "archived"]

_EXTRACT_SYS = """You are AEGIS content strategist for Jaiden Rabatin — Bitcoin investor and content creator.
His niches: Bitcoin & investing · Personal finance · Faith · Fitness · Leadership.
His platforms: YouTube long-form (primary), Shorts/Reels (repurpose), Twitter threads.
Default to broad, relatable angles. Personal context like overseas living or unconventional money situations can be used when it genuinely fits — not as a default.

Given a raw content idea, extract:
1. working_title — punchy, specific, YouTube-ready (max 70 chars)
2. platform — "YouTube" | "Shorts" | "Twitter" | "YouTube + Shorts"
3. niche — "bitcoin" | "military" | "faith" | "fitness" | "leadership" | "multi"
4. hook1 — first hook option (1 sentence, grabs attention in 5 words)
5. hook2 — second hook option (different angle)
6. why — one sentence on why this will perform (audience pain or desire it hits)
7. slug — kebab-case filename slug, max 50 chars

Respond ONLY with valid JSON matching those fields."""


def _extract_idea(raw_text: str) -> dict:
    resp = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=400,
        system=_EXTRACT_SYS,
        messages=[{"role": "user", "content": raw_text}],
    )
    text = resp.content[0].text.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


def create_idea(raw_text: str) -> dict:
    """
    Process a raw content idea, create a vault page, return summary dict.
    Returns {title, platform, niche, hook1, hook2, why, file_path}.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    extracted = _extract_idea(raw_text)

    slug      = extracted.get("slug", "content-idea").lower().replace(" ", "-")
    title     = extracted.get("working_title", raw_text[:60])
    platform  = extracted.get("platform", "YouTube")
    niche     = extracted.get("niche", "bitcoin")
    hook1     = extracted.get("hook1", "")
    hook2     = extracted.get("hook2", "")
    why       = extracted.get("why", "")

    # Deduplicate slug if file already exists
    dest = CONTENT_DIR / f"{slug}.md"
    if dest.exists():
        slug = f"{slug}-{today}"
        dest = CONTENT_DIR / f"{slug}.md"

    md = f"""---
title: "Content: {title}"
type: content-idea
area: content
platform: {platform.lower().replace(' ', '-').replace('+', '')}
niche: {niche}
tags: [content, {platform.lower().split()[0]}, {niche}]
status: active
created: {today}
updated: {today}
gdoc:
---

# Content: {title}

**Summary**: {why}

**Platform**: {platform}
**Niche**: {niche.replace('-', ' ').title()}
**Stage**: idea

---

## Why This Will Perform

{why}

## Hook Options

1. {hook1}
2. {hook2}

## Title Options

1. {title}
2.
3.

## Thumbnail Concept



## Outline

**Hook** (0:00–0:30):

**Setup / Problem** (0:30–):

**Body**:
- Point 1 —
- Point 2 —
- Point 3 —

**CTA**:

## Raw Idea

> {raw_text}

## Related pages

- [[content-pipeline]]
- [[voice-guide]]
"""

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_text(md, encoding="utf-8")

    return {
        "title":     title,
        "platform":  platform,
        "niche":     niche,
        "hook1":     hook1,
        "hook2":     hook2,
        "why":       why,
        "slug":      slug,
        "file_path": str(dest),
        "stage":     "idea",
        "created":   today,
    }


def read_pipeline() -> list[dict]:
    """
    Read all content idea pages from vault, return sorted pipeline list.
    """
    if not CONTENT_DIR.exists():
        return []

    ideas = []
    for f in sorted(CONTENT_DIR.glob("*.md")):
        if f.name in ("content-pipeline.md", "voice-guide.md"):
            continue
        try:
            text = f.read_text(encoding="utf-8")
            # Parse frontmatter
            fm_match = re.match(r"^---\n(.*?)\n---", text, re.S)
            if not fm_match:
                continue
            fm = fm_match.group(1)

            def _fm(key):
                m = re.search(rf'^{key}:\s*["\']?(.+?)["\']?\s*$', fm, re.M)
                return m.group(1).strip() if m else ""

            type_val = _fm("type")
            if type_val != "content-idea":
                continue

            stage = "idea"
            stage_match = re.search(r"\*\*Stage\*\*:\s*(\w+)", text)
            if stage_match:
                stage = stage_match.group(1).lower()

            ideas.append({
                "title":    _fm("title").replace("Content: ", "").strip('"'),
                "platform": _fm("platform"),
                "niche":    _fm("niche"),
                "stage":    stage,
                "created":  _fm("created"),
                "slug":     f.stem,
                "file":     f.name,
                "gdoc":     _fm("gdoc"),
            })
        except Exception:
            continue

    # Sort by stage priority then date
    stage_order = {s: i for i, s in enumerate(STAGES)}
    ideas.sort(key=lambda x: (stage_order.get(x["stage"], 99), x["created"]))
    return ideas


if __name__ == "__main__":
    pipeline = read_pipeline()
    print(f"Pipeline: {len(pipeline)} ideas")
    for p in pipeline:
        print(f"  [{p['stage']:10}] {p['title'][:55]} ({p['platform']})")
