"""
AEGIS - Phase 3.0 (Vault-Integrated Intelligence)

Pulls live context from the aegis_vault wiki before generating the brief:
  - Bitcoin portfolio (stack, cost basis, accumulation triggers)
  - X intelligence log (latest trade ideas, macro, content angles)
  - Watchlist (active topics)
  - Content pipeline (what's in flight)
  - Jaiden profile (goals, deployment context)
  - AEGIS Inbox (today's notes)
  - Live market data (yfinance)

Audio saved locally + iCloud. Plays immediately.
"""

import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from openai import OpenAI

from sources.portfolio import get_portfolio_summary
from sources.voice import VOICE, TTS_MODEL, VOICE_INSTRUCTIONS as _VI

load_dotenv()

claude = Anthropic()
openai_client = OpenAI()

VOICE_INSTRUCTIONS = _VI

# Vault paths
VAULT = Path("/Users/jaidenrabatin/Documents/aegis_vault/wiki")
INBOX_FILE = Path("/Users/jaidenrabatin/Documents/aegis_vault/AEGIS Inbox.md")

# Audio output paths
BRIEFS_DIR = Path(__file__).parent / "briefs"
BRIEFS_DIR.mkdir(exist_ok=True)
ICLOUD_DIR = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/AEGIS"
ICLOUD_DIR.mkdir(exist_ok=True)


SYSTEM_PROMPT = """You are AEGIS — the personal intelligence system for Jaiden Rabatin.
Jaiden is a US Army officer currently deployed in Jordan, a Bitcoin investor with a sound
money conviction rooted in Austrian economics, and a content creator building a YouTube
channel across Bitcoin, military finance, faith, and leadership niches.

Your tone is direct, calm, and professional — like a trusted aide-de-camp. Mission-focused.
Never waste words. No cheerleading. No filler.

You have full context from Jaiden's knowledge vault: his Bitcoin portfolio, watchlist,
X intelligence, content pipeline, and personal goals. Use this to make the brief feel
precise and personal — not generic.

Structure the brief exactly as follows:

SITUATION: One sentence. Where things stand right now across his life and work.

MARKETS: Bitcoin price and approximate stack value. Any notable movers from his holdings
(MSTR, BTC). One sentence on broader market direction. Call out what's notable — skip
what's flat. Speak naturally: say "up two and a half percent" not "+2.5%".

INTEL: The one or two signals from the X intelligence log or watchlist worth knowing this
morning. Actionable or notable only — skip noise.

CONTENT: What's active in the pipeline. Any content angle from today's intel worth flagging.

PRIORITIES: The two or three most important things from his inbox. Not more.

INSIGHT: One observation, question, or recommendation synthesized across the vault.
This is where you earn your place — make it sharp.

Keep the entire brief under 350 words. It will be spoken aloud while Jaiden gets ready
for work. Use natural spoken language. No markdown, no bullet symbols, no "+2.5%"-style
formatting, no anything that sounds awkward read aloud. Speak prices and percentages
naturally. Transition between sections with natural spoken phrasing, not headers."""


def read_vault_file(relative_path: str, max_chars: int = 2000) -> str:
    path = VAULT / relative_path
    if not path.exists():
        return f"(not found: {relative_path})"
    content = path.read_text().strip()
    if len(content) > max_chars:
        content = content[:max_chars] + "\n[truncated]"
    return content


def read_vault_file_tail(relative_path: str, max_chars: int = 2000) -> str:
    """Read from the END of a file — best for append-only logs where recent = bottom."""
    path = VAULT / relative_path
    if not path.exists():
        return f"(not found: {relative_path})"
    content = path.read_text().strip()
    if len(content) > max_chars:
        content = "[truncated]\n..." + content[-max_chars:]
    return content


def load_vault_context() -> str:
    sections = []

    sections.append("=== BITCOIN PORTFOLIO ===")
    sections.append(read_vault_file("areas/finance/bitcoin-portfolio.md", 2000))

    sections.append("\n=== RECENT X INTELLIGENCE (most recent entries) ===")
    sections.append(read_vault_file_tail("areas/strategy/x-intel-log.md", 1500))

    sections.append("\n=== WATCHLIST — ACTIVE TOPICS ===")
    sections.append(read_vault_file("areas/strategy/watchlist.md", 800))

    sections.append("\n=== CONTENT PIPELINE ===")
    sections.append(read_vault_file("areas/content/content-pipeline.md", 800))

    sections.append("\n=== JAIDEN CONTEXT ===")
    sections.append(read_vault_file("people/jaiden-rabatin.md", 1000))

    sections.append("\n=== AEGIS INBOX (today's notes) ===")
    if INBOX_FILE.exists():
        content = INBOX_FILE.read_text().strip()
        sections.append(content if content else "(inbox is empty — no notes today)")
    else:
        sections.append("(AEGIS Inbox.md not found)")

    return "\n".join(sections)


def build_context() -> str:
    parts = []
    parts.append(load_vault_context())
    parts.append("\n=== LIVE MARKET DATA ===")
    parts.append(get_portfolio_summary())
    return "\n".join(parts)


def get_brief(context: str) -> str:
    response = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=900,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Generate my daily brief from the following context:\n\n{context}",
            }
        ],
    )
    return response.content[0].text


def speak_and_save(text: str, play: bool = True) -> Path:
    """Generate audio, save locally + iCloud. Plays immediately if play=True."""
    response = openai_client.audio.speech.create(
        model=TTS_MODEL,
        voice=VOICE,
        input=text,
        instructions=VOICE_INSTRUCTIONS,
    )

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"brief_{timestamp}.mp3"
    audio_bytes = response.content

    local_path = BRIEFS_DIR / filename
    local_path.write_bytes(audio_bytes)

    icloud_path = ICLOUD_DIR / filename
    icloud_path.write_bytes(audio_bytes)

    if play:
        try:
            subprocess.run(["afplay", str(local_path)], check=True)
        except Exception:
            pass  # cron has no audio session — file still saved to iCloud

    return icloud_path


def speak_test(text: str) -> None:
    """Voice test — plays without saving."""
    response = openai_client.audio.speech.create(
        model=TTS_MODEL,
        voice=VOICE,
        input=text,
        instructions=VOICE_INSTRUCTIONS,
    )
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(response.content)
        audio_path = Path(tmp.name)
    try:
        subprocess.run(["afplay", str(audio_path)], check=True)
    finally:
        audio_path.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("AEGIS: Voice test...")
        speak_test("AEGIS online. Vault connected. Standing by, sir.")
        print("Test complete.")
    else:
        print("AEGIS: Reading vault and market data...")
        context = build_context()

        print("AEGIS: Generating brief...\n")
        brief = get_brief(context)
        print(brief)

        print("\n--- Speaking now ---")
        audio_path = speak_and_save(brief)
        print(f"\nSaved to iCloud: {audio_path}")
        print("Brief complete.")
