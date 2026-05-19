"""
AEGIS Telegram Bot
Receives text and voice messages, writes them into the vault.

Setup:
  1. Add to .env:  TELEGRAM_BOT_TOKEN=...  TELEGRAM_CHAT_ID=...
  2. Run:  venv/bin/python3 telegram_bot.py
  3. Get your chat ID: message @userinfobot on Telegram
"""

import os
import sys
import time
import tempfile
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))

import requests
from openai import OpenAI

BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_ID   = os.getenv("TELEGRAM_CHAT_ID", "")   # leave blank to allow any chat

VAULT_INBOX  = Path("/Users/jaidenrabatin/Documents/aegis_vault/AEGIS Inbox.md")
VOICE_LOG    = Path("/Users/jaidenrabatin/Documents/aegis_vault/wiki/areas/notes/voice-notes.md")

TG = f"https://api.telegram.org/bot{BOT_TOKEN}"
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))


# ── Telegram helpers ────────────────────────────────────────────────────────

def tg_get(endpoint, **params):
    r = requests.get(f"{TG}/{endpoint}", params=params, timeout=35)
    return r.json()

def tg_post(endpoint, **data):
    r = requests.post(f"{TG}/{endpoint}", json=data, timeout=15)
    return r.json()

def send(chat_id, text, parse_mode=""):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    tg_post("sendMessage", **payload)

def get_updates(offset=None):
    params = {"timeout": 30, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    r = requests.get(f"{TG}/getUpdates", params=params, timeout=35)
    return r.json()

def download_file(file_id) -> bytes:
    info = tg_get("getFile", file_id=file_id)
    path = info["result"]["file_path"]
    url  = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
    return requests.get(url, timeout=60).content


# ── Vault helpers ───────────────────────────────────────────────────────────

def ensure_voice_log():
    VOICE_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not VOICE_LOG.exists():
        VOICE_LOG.write_text(
            "---\ntitle: Voice Notes\ntype: capture\n---\n\n# Voice Notes\n\n"
            "Transcribed voice messages from Telegram. Auto-generated.\n\n",
            encoding="utf-8"
        )

def append_inbox(text: str):
    """Append a bullet to AEGIS Inbox.md under a ## Telegram section."""
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
    bullet = f"- [{ts}] {text}\n"

    content = VAULT_INBOX.read_text(encoding="utf-8") if VAULT_INBOX.exists() else ""

    if "## Telegram" in content:
        content = content + bullet
    else:
        content = content.rstrip("\n") + "\n\n## Telegram\n" + bullet

    VAULT_INBOX.write_text(content, encoding="utf-8")

def append_voice_note(transcript: str, duration_s: int):
    ensure_voice_log()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (
        f"\n## {ts} ({duration_s}s)\n\n"
        f"{transcript}\n\n"
        f"---\n"
    )
    with open(VOICE_LOG, "a", encoding="utf-8") as f:
        f.write(entry)


# ── Transcription ────────────────────────────────────────────────────────────

def transcribe(audio_bytes: bytes, ext: str = "ogg") -> str:
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
        f.write(audio_bytes)
        tmp = f.name
    try:
        with open(tmp, "rb") as f:
            result = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="en",
            )
        return result.text.strip()
    finally:
        os.unlink(tmp)


# ── Command handlers ─────────────────────────────────────────────────────────

def cmd_start(chat_id):
    send(chat_id,
        "AEGIS is online.\n\n"
        "Send me a *text note* and I'll drop it in your inbox.\n"
        "Send a *voice message* and I'll transcribe it.\n\n"
        "Commands:\n"
        "/inbox  — read current inbox\n"
        "/portfolio  — live BTC + MSTR prices\n"
        "/notes  — last 3 voice notes\n"
        "/idea [text]  — capture + build a content idea\n"
        "/pipeline  — view content pipeline\n"
        "/suggest [topic]  — AEGIS suggests 5 video ideas from niche trends\n"
        "/intel @source signal | category  — log an intel signal\n"
        "/help  — this message",
        parse_mode="Markdown"
    )

def cmd_inbox(chat_id):
    if not VAULT_INBOX.exists():
        send(chat_id, "Inbox is empty."); return
    lines = [l for l in VAULT_INBOX.read_text(encoding="utf-8").splitlines()
             if l.strip().startswith("- ")][:10]
    if not lines:
        send(chat_id, "Inbox has no bullet items."); return
    send(chat_id, "📋 *AEGIS Inbox*\n\n" + "\n".join(lines), parse_mode="Markdown")

def cmd_portfolio(chat_id):
    try:
        from sources.portfolio import get_quote
        btc  = get_quote("BTC-USD")
        mstr = get_quote("MSTR")
        hut  = get_quote("HUT")
        lines = ["📊 *Portfolio Snapshot*\n"]
        for q in [btc, mstr, hut]:
            if "error" not in q:
                sign = "+" if q["pct_change"] >= 0 else ""
                lines.append(f"*{q['ticker']}*  ${q['price']:,.2f}  {sign}{q['pct_change']}%")
            else:
                lines.append(f"{q['ticker']}: unavailable")
        send(chat_id, "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        send(chat_id, f"Portfolio error: {e}")

def cmd_notes(chat_id):
    if not VOICE_LOG.exists():
        send(chat_id, "No voice notes yet."); return
    text = VOICE_LOG.read_text(encoding="utf-8")
    sections = [s.strip() for s in text.split("---") if s.strip() and "Voice Notes" not in s]
    recent = sections[-3:]
    if not recent:
        send(chat_id, "No voice notes yet."); return
    out = "🎙 *Recent voice notes*\n\n" + "\n\n---\n\n".join(recent)
    send(chat_id, out[:4000], parse_mode="Markdown")

def cmd_idea(chat_id, args: str):
    """
    /idea Bitcoin just hit $120K — should I post a milestone video?
    Also triggered when a voice note starts with 'content idea' or 'video idea'.
    """
    raw = args.strip()
    if not raw:
        send(chat_id,
            "Send me a content idea and I'll build it out.\n\n"
            "Example:\n"
            "`/idea Bitcoin just hit $120K — is now the time to post a milestone video?`\n\n"
            "Or just speak it as a voice message starting with 'content idea:'",
            parse_mode="Markdown"
        )
        return

    send(chat_id, "✓ Idea captured — building content brief (takes ~30s)…")
    try:
        from sources.content_pipeline import create_idea
        from sources.content_skill import run_skill_async
        from pathlib import Path

        result = create_idea(raw)

        # Quick confirmation
        msg = (
            f"💡 *Idea locked in*\n\n"
            f"*{result['title']}*\n"
            f"{result['platform']} · {result['niche'].title()}\n\n"
            f"Hook A: _{result['hook1']}_\n"
            f"Hook B: _{result['hook2']}_\n\n"
            f"Running full content skill… I'll ping you when the script outline is ready."
        )
        send(chat_id, msg, parse_mode="Markdown")

        # Fire skill in background — sends follow-up when done
        vault_page = Path(result["file_path"])
        run_skill_async(
            raw,
            vault_page,
            telegram_callback=lambda m: send(chat_id, m, parse_mode="Markdown"),
        )

    except Exception as e:
        send(chat_id, f"Error processing idea: {e}")


def cmd_pipeline(chat_id):
    """Show current content pipeline stages."""
    try:
        from sources.content_pipeline import read_pipeline
        items = read_pipeline()
        if not items:
            send(chat_id, "No content ideas in vault yet. Use /idea to add one.")
            return

        stage_icons = {
            "idea": "💡", "outlined": "📋", "scripted": "✍️",
            "scheduled": "📅", "published": "✅", "archived": "📦"
        }
        active = [i for i in items if i["stage"] not in ("published", "archived")]
        published = [i for i in items if i["stage"] == "published"]

        lines = ["📹 *Content Pipeline*\n"]
        for item in active[-8:]:
            icon = stage_icons.get(item["stage"], "•")
            lines.append(f"{icon} *{item['title'][:45]}*")
            lines.append(f"   {item['platform']} · {item['stage']}\n")

        if published:
            lines.append(f"\n✅ {len(published)} published")

        send(chat_id, "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        send(chat_id, f"Pipeline error: {e}")


def cmd_suggest(chat_id, args: str):
    """
    /suggest               — scan Bitcoin/personal finance niche for 5 fresh ideas
    /suggest bitcoin loans — focused scan on a specific topic
    """
    topic = args.strip() or None
    label = f'"{topic}"' if topic else "niche scan"
    send(chat_id, f"🔍 Scanning YouTube for {label}… (15-20s)", parse_mode="Markdown")
    try:
        import threading
        from sources.idea_gen import suggest_ideas, format_for_telegram

        def run():
            ideas = suggest_ideas(topic)
            if not ideas:
                send(chat_id, "⚠ Couldn't generate ideas — check YOUTUBE_API_KEY.")
                return
            msg = format_for_telegram(ideas, topic)
            send(chat_id, msg, parse_mode="Markdown")

        threading.Thread(target=run, daemon=True).start()
    except Exception as e:
        send(chat_id, f"Suggest error: {e}")


def cmd_intel(chat_id, args: str):
    """
    /intel @source signal text | category
    /intel @woonomic MVRV approaching 3.5 — cycle top signal | trade
    """
    args = args.strip()
    if not args:
        send(chat_id,
            "Usage: /intel @source signal | category\n\n"
            "Example:\n"
            "`/intel @woonomic MVRV approaching 3.5 | trade`\n\n"
            "Categories: trade · macro · content",
            parse_mode="Markdown"
        )
        return

    # Split on | for category
    if "|" in args:
        body, cat = args.rsplit("|", 1)
        category = cat.strip().lower()
    else:
        body = args
        category = "macro"

    body = body.strip()
    # Extract source (@handle at start)
    parts = body.split(None, 1)
    if not parts:
        send(chat_id, "Couldn't parse — include @source first."); return

    if parts[0].startswith("@"):
        source = parts[0]
        signal = parts[1].strip() if len(parts) > 1 else ""
    else:
        send(chat_id, "Start with @source — e.g. `/intel @woonomic ...`", parse_mode="Markdown"); return

    if not signal:
        send(chat_id, "Add signal text after @source."); return

    try:
        from sources.x_intel import append_entry
        line = append_entry(source, signal, category)
        send(chat_id, f"✓ Intel logged\n`{line}`", parse_mode="Markdown")
    except Exception as e:
        send(chat_id, f"Error: {e}")


# ── Message handler ──────────────────────────────────────────────────────────

def handle(msg: dict):
    chat_id = str(msg["chat"]["id"])

    # Security gate
    if ALLOWED_ID and chat_id != str(ALLOWED_ID):
        send(chat_id, "Unauthorized.")
        return

    # Text
    if "text" in msg:
        text = msg["text"].strip()
        if   text == "/start":               cmd_start(chat_id)
        elif text == "/inbox":               cmd_inbox(chat_id)
        elif text == "/portfolio":           cmd_portfolio(chat_id)
        elif text == "/notes":               cmd_notes(chat_id)
        elif text == "/pipeline":            cmd_pipeline(chat_id)
        elif text == "/help":                cmd_start(chat_id)
        elif text.startswith("/idea"):       cmd_idea(chat_id, text[5:])
        elif text.startswith("/intel"):      cmd_intel(chat_id, text[6:])
        elif text.startswith("/suggest"):    cmd_suggest(chat_id, text[8:])
        elif text.startswith("/"):
            send(chat_id, "Unknown command. Try /help")
        else:
            append_inbox(text)
            preview = text[:60] + ("…" if len(text) > 60 else "")
            send(chat_id, f"✓ Inbox: {preview}")
        return

    # Voice message
    if "voice" in msg:
        dur = msg["voice"].get("duration", 0)
        send(chat_id, "🎙 Transcribing…")
        try:
            audio = download_file(msg["voice"]["file_id"])
            transcript = transcribe(audio, ext="ogg")
            if not transcript:
                send(chat_id, "⚠ No speech detected."); return
            append_voice_note(transcript, dur)
            short = transcript[:120] + ("…" if len(transcript) > 120 else "")
            append_inbox(f"[voice {dur}s] {short}")

            # Route to content pipeline if it's a content idea
            lower = transcript.lower()
            content_triggers = ("content idea", "video idea", "youtube idea", "video about", "make a video")
            if any(lower.startswith(t) for t in content_triggers):
                send(chat_id, f"✓ Voice note saved ({dur}s) — detected content idea, processing…")
                cmd_idea(chat_id, transcript)
            else:
                send(chat_id,
                    f"✓ Voice note saved ({dur}s)\n\n_{transcript[:400]}_",
                    parse_mode="Markdown"
                )
        except Exception as e:
            send(chat_id, f"⚠ Transcription failed: {e}")
        return

    # Audio file (if sent as file not voice)
    if "audio" in msg or "document" in msg:
        obj = msg.get("audio") or msg.get("document")
        mime = obj.get("mime_type", "")
        if any(x in mime for x in ["audio", "ogg", "mpeg", "mp4", "wav"]):
            ext = "mp3" if "mpeg" in mime else "ogg"
            send(chat_id, "🎙 Transcribing audio file…")
            try:
                audio = download_file(obj["file_id"])
                transcript = transcribe(audio, ext=ext)
                if transcript:
                    append_voice_note(transcript, 0)
                    append_inbox(f"[audio] {transcript[:120]}")
                    send(chat_id, f"✓ Saved\n\n_{transcript[:400]}_", parse_mode="Markdown")
                else:
                    send(chat_id, "⚠ No speech detected.")
            except Exception as e:
                send(chat_id, f"⚠ Error: {e}")
        else:
            send(chat_id, "Send a voice message or audio file to transcribe.")
        return

    send(chat_id, "Send text or a voice message.")


# ── Main poll loop ───────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    # Verify token
    me = tg_get("getMe")
    if not me.get("ok"):
        print(f"ERROR: Invalid bot token — {me}")
        sys.exit(1)

    name = me["result"]["username"]
    print(f"AEGIS Telegram bot @{name} online — polling for messages")
    if ALLOWED_ID:
        print(f"  Accepting messages from chat ID: {ALLOWED_ID}")
    else:
        print("  WARNING: TELEGRAM_CHAT_ID not set — accepting messages from anyone")

    offset = None
    while True:
        try:
            data = get_updates(offset)
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                if "message" in update:
                    handle(update["message"])
        except requests.exceptions.Timeout:
            pass  # long-poll timeout is normal
        except KeyboardInterrupt:
            print("\nBot stopped.")
            break
        except Exception as e:
            print(f"Poll error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
