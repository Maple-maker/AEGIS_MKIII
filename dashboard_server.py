"""
AEGIS Dashboard Server
Serves live vault data + market data to the dashboard HTML.
Run: python3 dashboard_server.py
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, send_from_directory, request, Response
from flask_cors import CORS
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))

_vault_base = os.getenv("VAULT_PATH", "/Users/jaidenrabatin/Documents/aegis_vault")
VAULT      = Path(_vault_base) / "wiki"
INBOX      = Path(_vault_base) / "AEGIS Inbox.md"
BRIEFS_DIR = Path(__file__).parent / "briefs"

app = Flask(__name__, static_folder="dashboard", static_url_path="")
CORS(app)
app.secret_key = os.getenv("SECRET_KEY", "aegis-dev-secret-change-in-production")

# ── First-boot: copy defaults if user files don't exist ─────────────────────
_CONFIG_DIR = Path(__file__).parent / "config"
_CONFIG_DIR.mkdir(exist_ok=True)
for _fname in ("user_config.json", "habits.json"):
    _dest = _CONFIG_DIR / _fname
    _src  = _CONFIG_DIR / _fname.replace(".json", ".default.json")
    if not _dest.exists() and _src.exists():
        import shutil
        shutil.copy(_src, _dest)


def read_vault(rel: str, max_chars: int = 4000) -> str:
    p = VAULT / rel
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8").strip()
    return text[:max_chars] if len(text) > max_chars else text


def read_vault_tail(rel: str, max_chars: int = 3000) -> str:
    p = VAULT / rel
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8").strip()
    return text[-max_chars:] if len(text) > max_chars else text


# ── API: net worth ───────────────────────────────────────────────────────────

@app.route("/api/networth")
def api_networth():
    try:
        from sources.networth import calculate
        data = calculate()
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── API: portfolio / market data ────────────────────────────────────────────

@app.route("/api/portfolio")
def api_portfolio():
    try:
        from sources.portfolio import get_quote, load_tickers
        tickers = load_tickers()
        prices = {}
        for ticker in tickers:
            q = get_quote(ticker)
            if "error" not in q:
                sign = "+" if q["pct_change"] >= 0 else ""
                prices[ticker] = {
                    "price": q["price"],
                    "change": f"{sign}{q['pct_change']}%",
                    "pct_change": q["pct_change"],
                }
            else:
                prices[ticker] = {"price": None, "change": "—", "pct_change": 0}
        return jsonify({"ok": True, "data": {"prices": prices}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── API: inbox / priorities ──────────────────────────────────────────────────

@app.route("/api/inbox")
def api_inbox():
    text = ""
    if INBOX.exists():
        text = INBOX.read_text(encoding="utf-8").strip()
    return jsonify({"ok": True, "text": text})


# ── API: X intel ─────────────────────────────────────────────────────────────

@app.route("/api/intel")
def api_intel():
    raw = read_vault_tail("areas/strategy/x-intel-log.md", 3000)
    entries = []
    for line in raw.splitlines():
        line = line.strip()
        # Format: - `2026-05-16` @source — Signal. `| trade`
        m = re.match(r"-\s+`([^`]+)`\s+(.+?)\s+[—–]\s+(.+?)\s+`\|\s*(\w[\w\s/]*)`", line)
        if m:
            entries.append({
                "date": m.group(1),
                "source": m.group(2),
                "signal": m.group(3),
                "category": m.group(4).split("/")[0].strip(),
            })
    # Return most recent 8
    entries = entries[-8:]
    try:
        from sources.x_intel import last_sync
        last_synced = last_sync()
    except Exception:
        last_synced = None
    return jsonify({"ok": True, "entries": entries, "last_sync": last_synced})


@app.route("/api/intel/add", methods=["POST"])
def api_intel_add():
    """Add a single intel entry manually (e.g., from Telegram bot or webhook)."""
    body = request.json or {}
    source   = body.get("source", "").strip()
    signal   = body.get("signal", "").strip()
    category = body.get("category", "macro").strip()
    date     = body.get("date")
    if not source or not signal:
        return jsonify({"ok": False, "error": "source and signal required"}), 400
    try:
        from sources.x_intel import append_entry
        line = append_entry(source, signal, category, date)
        return jsonify({"ok": True, "entry": line})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/intel/sync", methods=["POST"])
def api_intel_sync():
    """Trigger a full X account sync. Returns count of new entries added."""
    try:
        from sources.x_intel import sync
        result = sync()
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── API: Coinbase balance ────────────────────────────────────────────────────

@app.route("/api/coinbase/balance")
def api_coinbase_balance():
    try:
        from sources.coinbase import get_balance
        data = get_balance()
        return jsonify({"ok": True, "data": data})
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/coinbase/refresh", methods=["POST"])
def api_coinbase_refresh():
    try:
        from sources.coinbase import fetch, save_cache
        data = fetch()
        save_cache(data)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── API: content pipeline ────────────────────────────────────────────────────

@app.route("/api/content")
def api_content():
    try:
        from sources.content_pipeline import read_pipeline
        items = read_pipeline()
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "items": []})

@app.route("/api/reading/feed")
def api_reading_feed():
    try:
        days = int(request.args.get("days", 7))
        from sources.reading_feed import get_full_feed
        return jsonify({"ok": True, **get_full_feed(days_back=days)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/ideas/suggest", methods=["POST"])
def api_ideas_suggest():
    body  = request.json or {}
    topic = body.get("topic", "").strip() or None
    try:
        from sources.idea_gen import suggest_ideas
        ideas = suggest_ideas(topic)
        return jsonify({"ok": True, "ideas": ideas})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/content/add", methods=["POST"])
def api_content_add():
    body = request.json or {}
    raw  = body.get("idea", "").strip()
    if not raw:
        return jsonify({"ok": False, "error": "idea text required"}), 400
    try:
        from sources.content_pipeline import create_idea
        result = create_idea(raw)
        return jsonify({"ok": True, "data": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── API: bitcoin portfolio ───────────────────────────────────────────────────

@app.route("/api/btc-portfolio")
def api_btc_portfolio():
    raw = read_vault("areas/finance/bitcoin-portfolio.md", 2000)
    data = {
        "stack_btc": None,
        "cost_basis": None,
        "text": raw,
    }
    # Match table row: | **Total BTC held** | 0.58125823 |
    m = re.search(r"\*\*Total BTC held\*\*\s*\|\s*([\d.]+)", raw)
    if m:
        data["stack_btc"] = float(m.group(1))
    # Match table row: | **Average cost per BTC (USD)** | $80,673 |
    m = re.search(r"\*\*Average cost per BTC[^|]*\|\s*\$?([\d,]+)", raw)
    if m:
        data["cost_basis"] = float(m.group(1).replace(",", ""))
    return jsonify({"ok": True, "data": data})


# ── API: on-chain ────────────────────────────────────────────────────────────

@app.route("/api/onchain")
def api_onchain():
    try:
        from sources.onchain import load_cache, update
        data = load_cache() or update()
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/onchain/refresh", methods=["POST"])
def api_onchain_refresh():
    try:
        from sources.onchain import update
        data = update()
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── API: mNAV ────────────────────────────────────────────────────────────────

POSITIONS_FILE = Path(__file__).parent / "config" / "positions.json"

@app.route("/api/mnav")
def api_mnav():
    try:
        import yfinance as yf
        cfg = json.loads(POSITIONS_FILE.read_text())
        mstr_btc_held = cfg.get("mstr_btc_held", 0)

        mstr_info = yf.Ticker("MSTR").info
        btc_price  = yf.Ticker("BTC-USD").fast_info.last_price
        market_cap = mstr_info.get("marketCap", 0)
        shares     = mstr_info.get("sharesOutstanding", 0)

        btc_nav    = mstr_btc_held * btc_price if mstr_btc_held else 0
        mnav       = round(market_cap / btc_nav, 4) if btc_nav else None
        btc_per_sh = round(mstr_btc_held / shares, 6) if shares else None

        return jsonify({
            "ok": True,
            "mnav":          mnav,
            "market_cap":    market_cap,
            "btc_nav":       round(btc_nav, 0),
            "mstr_btc_held": mstr_btc_held,
            "btc_per_share": btc_per_sh,
            "btc_price":     round(btc_price, 0),
            "rotate_at":     4.0,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── API: latest brief ────────────────────────────────────────────────────────

@app.route("/api/brief/latest")
def api_brief_latest():
    try:
        log = BRIEFS_DIR / "cron.log"
        if log.exists():
            lines = log.read_text(encoding="utf-8", errors="ignore")
            # Extract the brief text (between "Generating brief..." and "--- Speaking")
            m = re.search(r"Generating brief\.\.\.\n+(.*?)\n+---", lines, re.S)
            if m:
                return jsonify({"ok": True, "text": m.group(1).strip()})
        # Try reading brief files
        briefs = sorted(BRIEFS_DIR.glob("*.mp3"))
        return jsonify({"ok": True, "text": "", "briefs": [b.name for b in briefs[-3:]]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── API: goals ───────────────────────────────────────────────────────────────

GOALS_FILE = VAULT / "areas/goals/goals.md"

@app.route("/api/goals")
def api_goals():
    try:
        if not GOALS_FILE.exists():
            return jsonify({"ok": True, "groups": []})
        text = GOALS_FILE.read_text(encoding="utf-8")

        groups = {}
        current_group = None
        for line in text.splitlines():
            # Section header
            h = re.match(r"^##\s+(.+)", line)
            if h:
                current_group = h.group(1).strip()
                groups[current_group] = []
                continue
            # Goal item: - [ ] Label | current: X | target: Y | by: YYYY-MM-DD
            m = re.match(
                r"-\s+\[.\]\s+(.+?)\s*\|\s*current:\s*([\d.]+)\s*\|\s*target:\s*([\d.]+)\s*\|\s*by:\s*(\d{4}-\d{2}-\d{2})",
                line.strip()
            )
            if m and current_group is not None:
                label   = m.group(1).strip()
                current = float(m.group(2))
                target  = float(m.group(3))
                by_date = m.group(4)
                pct     = round(min(current / target * 100, 100), 1) if target else 0
                groups[current_group].append({
                    "label":   label,
                    "current": current,
                    "target":  target,
                    "by":      by_date,
                    "pct":     pct,
                })

        result = [{"group": g, "items": items} for g, items in groups.items() if items]
        return jsonify({"ok": True, "groups": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/goals/update", methods=["POST"])
def api_goals_update():
    """Update a goal's current value in goals.md."""
    try:
        body    = request.json or {}
        label   = body.get("label", "").strip()
        target  = body.get("target")
        by_date = body.get("by", "").strip()
        new_val = body.get("current")

        if not label or new_val is None:
            return jsonify({"ok": False, "error": "label and current required"}), 400

        text  = GOALS_FILE.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        updated = False

        for i, line in enumerate(lines):
            # Match the exact goal line by label + target + by date
            m = re.match(
                rf"-\s+\[.\]\s+{re.escape(label)}\s*\|\s*current:\s*[\d.]+\s*\|\s*target:\s*{re.escape(str(target))}\s*\|\s*by:\s*{re.escape(by_date)}",
                line.strip()
            )
            if m:
                lines[i] = re.sub(
                    r"current:\s*[\d.]+",
                    f"current: {new_val}",
                    line
                )
                updated = True
                break

        if not updated:
            return jsonify({"ok": False, "error": "Goal line not found"}), 404

        GOALS_FILE.write_text("".join(lines), encoding="utf-8")
        return jsonify({"ok": True, "label": label, "current": new_val})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── API: watchlist ────────────────────────────────────────────────────────────

@app.route("/api/watchlist")
def api_watchlist():
    raw = read_vault("areas/strategy/watchlist.md", 2000)
    return jsonify({"ok": True, "text": raw})


# ── API: calendar events ─────────────────────────────────────────────────────

CALENDAR_CACHE = Path(__file__).parent / "data" / "calendar_cache.json"

@app.route("/api/calendar")
def api_calendar():
    if not CALENDAR_CACHE.exists():
        return jsonify({"ok": True, "events": [], "updated": None})
    try:
        data = json.loads(CALENDAR_CACHE.read_text())
        return jsonify({"ok": True, "events": data.get("events", []), "updated": data.get("updated")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/calendar/sync", methods=["POST"])
def api_calendar_sync():
    try:
        from sources.calendar_sync import sync
        events = sync()
        return jsonify({"ok": True, "count": len(events)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── API: voice notes (from Telegram bot) ─────────────────────────────────────

VOICE_LOG = Path("/Users/jaidenrabatin/Documents/aegis_vault/wiki/areas/notes/voice-notes.md")

@app.route("/api/voice-notes")
def api_voice_notes():
    if not VOICE_LOG.exists():
        return jsonify({"ok": True, "notes": []})
    text = VOICE_LOG.read_text(encoding="utf-8")
    sections = [s.strip() for s in text.split("---") if s.strip() and "Voice Notes" not in s]
    notes = []
    for sec in sections[-6:]:
        lines = sec.splitlines()
        if not lines:
            continue
        header = lines[0].lstrip("#").strip()
        body = "\n".join(lines[1:]).strip()
        notes.append({"header": header, "body": body})
    return jsonify({"ok": True, "notes": list(reversed(notes))})


# ── API: speak (TTS) ─────────────────────────────────────────────────────────

@app.route("/api/speak", methods=["POST"])
def api_speak():
    text = (request.json or {}).get("text", "").strip()
    if not text:
        return jsonify({"ok": False, "error": "No text"}), 400
    if len(text) > 3000:
        text = text[:3000]
    try:
        from openai import OpenAI
        from sources.voice import VOICE, TTS_MODEL, VOICE_INSTRUCTIONS
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.audio.speech.create(
            model=TTS_MODEL, voice=VOICE,
            input=text, instructions=VOICE_INSTRUCTIONS,
        )
        return Response(resp.content, mimetype="audio/mpeg",
                        headers={"Cache-Control": "no-cache"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/brief/live")
def api_brief_live():
    """Generate a fresh brief via Claude, return text + audio URL."""
    try:
        from aegis import build_context, get_brief
        from sources.voice import VOICE, TTS_MODEL, VOICE_INSTRUCTIONS
        from openai import OpenAI

        context = build_context()
        text = get_brief(context)

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        audio_resp = client.audio.speech.create(
            model=TTS_MODEL, voice=VOICE,
            input=text, instructions=VOICE_INSTRUCTIONS,
        )

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        fname = f"brief_{timestamp}.mp3"
        (BRIEFS_DIR / fname).write_bytes(audio_resp.content)

        return jsonify({"ok": True, "text": text, "audio": f"/api/brief/audio/{fname}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/brief/audio/<fname>")
def api_brief_audio(fname):
    return send_from_directory(str(BRIEFS_DIR), fname)


# ── API: voice query (HUD push-to-talk) ─────────────────────────────────────

_HUD_SYSTEM = """You are AEGIS — the personal AI command system for Jaiden Rabatin. You have full, live access to his portfolio, goals, content pipeline, intel feed, and vault data provided in context.

Your response will be spoken aloud through a premium voice system directly into his HUD. Rules:
- Keep responses under 120 words unless the query clearly requires detail
- Use natural spoken language — no markdown, no bullet points, no symbols
- Be direct, precise, and confident. Occasionally address him as "sir" but not every response
- If you have specific data in context, quote it precisely (prices, percentages, dates)
- If asked about a topic outside the context, say so briefly and redirect
- Maintain the persona of a calm, trusted, highly capable AI advisor — like JARVIS crossed with Alfred Pennyworth"""

@app.route("/api/voice/query", methods=["POST"])
def api_voice_query():
    import tempfile
    from openai import OpenAI
    from anthropic import Anthropic as Ant
    from sources.voice import VOICE, TTS_MODEL, VOICE_INSTRUCTIONS

    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"ok": False, "error": "No audio file"}), 400

    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        audio_file.save(f)
        tmp = f.name

    try:
        oai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        with open(tmp, "rb") as f:
            tr = oai.audio.transcriptions.create(model="whisper-1", file=f, language="en")
        transcript = tr.text.strip()
        if not transcript:
            return jsonify({"ok": False, "error": "No speech detected"})

        try:
            from aegis import build_context
            context = build_context()
        except Exception:
            context = "(Context unavailable)"

        ant = Ant(api_key=os.getenv("ANTHROPIC_API_KEY"))
        msg = ant.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=_HUD_SYSTEM,
            messages=[{"role": "user", "content": f"[LIVE CONTEXT]\n{context}\n\n[QUERY]\n{transcript}"}],
        )
        response_text = msg.content[0].text.strip()

        audio_resp = oai.audio.speech.create(
            model=TTS_MODEL, voice=VOICE,
            input=response_text, instructions=VOICE_INSTRUCTIONS,
        )
        fname = f"query_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        (BRIEFS_DIR / fname).write_bytes(audio_resp.content)

        return jsonify({
            "ok": True,
            "transcript": transcript,
            "response": response_text,
            "audio_url": f"/api/brief/audio/{fname}",
        })
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


# ── Serve dashboard ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    try:
        cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
        if cfg.get("onboarding", {}).get("completed"):
            from flask import redirect
            return redirect("/hud")
    except Exception:
        pass
    return send_from_directory("dashboard", "land.html")

@app.route("/onboard")
def onboard():
    return send_from_directory("dashboard", "onboard.html")

@app.route("/hud")
def hud():
    return send_from_directory("dashboard", "hud.html")

@app.route("/settings")
def settings():
    return send_from_directory("dashboard", "settings.html")


# ── API: user config ─────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "config" / "user_config.json"

@app.route("/api/config")
def api_config():
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
        return jsonify({"ok": True, "config": cfg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/config", methods=["POST"])
def api_config_save():
    try:
        body = request.json or {}
        cfg  = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
        # Deep merge incoming keys
        def deep_merge(base, patch):
            for k, v in patch.items():
                if isinstance(v, dict) and isinstance(base.get(k), dict):
                    deep_merge(base[k], v)
                else:
                    base[k] = v
        deep_merge(cfg, body)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
        return jsonify({"ok": True, "config": cfg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/config/voices")
def api_config_voices():
    """Return available TTS voices with descriptions."""
    voices = [
        {"id": "fable",   "name": "Fable",   "desc": "British, warm baritone — JARVIS-inspired (default)"},
        {"id": "onyx",    "name": "Onyx",     "desc": "Deep, authoritative American male"},
        {"id": "echo",    "name": "Echo",     "desc": "Neutral, clear American male"},
        {"id": "nova",    "name": "Nova",     "desc": "Warm, confident American female"},
        {"id": "shimmer", "name": "Shimmer",  "desc": "Bright, articulate American female"},
        {"id": "alloy",   "name": "Alloy",    "desc": "Balanced, professional neutral"},
    ]
    return jsonify({"ok": True, "voices": voices})

@app.route("/api/config/voice/preview", methods=["POST"])
def api_voice_preview():
    """Generate a short TTS preview clip for the selected voice."""
    voice_id = (request.json or {}).get("voice", "fable")
    ai_name  = (request.json or {}).get("ai_name", "AEGIS")
    text = f"This is {ai_name}. Systems online. Ready to assist."
    try:
        from openai import OpenAI
        from sources.voice import TTS_MODEL, VOICE_INSTRUCTIONS
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.audio.speech.create(
            model=TTS_MODEL, voice=voice_id,
            input=text, instructions=VOICE_INSTRUCTIONS,
        )
        return Response(resp.content, mimetype="audio/mpeg",
                        headers={"Cache-Control": "no-cache"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

HABITS_FILE = Path(__file__).parent / "config" / "habits.json"

@app.route("/api/habits")
def api_habits():
    try:
        data = json.loads(HABITS_FILE.read_text())
        habits = data.get("habits", [])
        log    = data.get("log", {})
        today  = datetime.now().strftime("%Y-%m-%d")

        # Last 7 days for weekly completion rate
        from datetime import timedelta
        days7 = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

        result = []
        for h in habits:
            done_today = h["id"] in log.get(today, [])
            week_done  = sum(1 for d in days7 if h["id"] in log.get(d, []))
            # Streak: count consecutive days ending today
            streak = 0
            for i in range(60):
                d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                if h["id"] in log.get(d, []):
                    streak += 1
                else:
                    break
            result.append({**h, "done_today": done_today, "week_done": week_done, "streak": streak})

        # Overall health score (0.0–1.0)
        if result:
            health = sum(h["done_today"] for h in result) / len(result)
        else:
            health = 1.0

        return jsonify({"ok": True, "habits": result, "health": health, "today": today})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/habits/log", methods=["POST"])
def api_habits_log():
    try:
        body     = request.json or {}
        habit_id = body.get("id", "").strip()
        done     = body.get("done", True)
        today    = datetime.now().strftime("%Y-%m-%d")

        data = json.loads(HABITS_FILE.read_text())
        log  = data.setdefault("log", {})
        day  = log.setdefault(today, [])

        if done and habit_id not in day:
            day.append(habit_id)
        elif not done and habit_id in day:
            day.remove(habit_id)

        HABITS_FILE.write_text(json.dumps(data, indent=2))
        return jsonify({"ok": True, "today": day})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/habits/save", methods=["POST"])
def api_habits_save():
    """Replace the full habits definition (called from onboarding wizard)."""
    try:
        body = request.json or {}
        data = json.loads(HABITS_FILE.read_text()) if HABITS_FILE.exists() else {}
        if "habits" in body:
            data["habits"] = body["habits"]
        if "log" in body:
            data["log"] = body["log"]
        HABITS_FILE.write_text(json.dumps(data, indent=2))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/vault/graph")
def api_vault_graph():
    try:
        vault = VAULT
        DOMAIN_TAGS = {
            "bitcoin":    ["bitcoin","btc","monetary","sound-money","austrian","inflation","halving","lightning"],
            "finance":    ["finance","investing","wealth","net-worth","portfolio","stocks","etf"],
            "military":   ["army","military","leadership","ncm","doctrine","adr","soldier","ranger"],
            "faith":      ["faith","theology","apologetics","bible","christian","god","resurrection"],
            "health":     ["fitness","health","nutrition","acft","workout","sleep"],
            "content":    ["content","youtube","video","creator","pipeline","social"],
            "strategy":   ["strategy","planning","goals","decisions","systems"],
        }
        FOLDER_DOMAIN = {
            "finance": "finance", "military": "military", "content": "content",
            "faith": "faith", "health": "health", "strategy": "strategy",
            "leadership": "military", "notes": "other",
        }

        nodes = {}
        for f in vault.rglob("*.md"):
            slug  = f.stem
            parts = f.relative_to(vault).parts
            top   = parts[0] if parts else "root"
            sub   = parts[1] if len(parts) > 2 else ""

            text = f.read_text(encoding="utf-8", errors="ignore")
            title_m = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', text, re.M)
            title   = (title_m.group(1).strip() if title_m else f.stem.replace("-"," ").title())[:28]
            tags_m  = re.search(r'^tags:\s*\[(.+?)\]', text, re.M)
            tags    = [t.strip().strip('"\'') for t in tags_m.group(1).split(",")] if tags_m else []

            domain = FOLDER_DOMAIN.get(sub, None)
            if not domain:
                for dom, kws in DOMAIN_TAGS.items():
                    if any(kw in t for t in tags for kw in kws) or any(kw in slug for kw in kws):
                        domain = dom; break
                else:
                    domain = {"sources":"source","projects":"project","concepts":"concept",
                              "people":"person","sops":"sop","dailies":"daily"}.get(top,"other")

            links = list(set(re.findall(r'\[\[([^\]|#\n]+)', text)))
            nodes[slug] = {"id": slug, "title": title, "domain": domain,
                           "size": min(len(links), 20), "links": links}

        edges, seen = [], set()
        for slug, node in nodes.items():
            for lk in node["links"]:
                tgt = lk.strip().lower().replace(" ", "-")
                if tgt in nodes and tgt != slug:
                    key = tuple(sorted([slug, tgt]))
                    if key not in seen:
                        seen.add(key)
                        edges.append({"from": slug, "to": tgt})

        node_list = [{"id": n["id"], "title": n["title"], "domain": n["domain"], "size": n["size"]}
                     for n in nodes.values()]
        return jsonify({"ok": True, "nodes": node_list, "edges": edges})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/config/integrations/test", methods=["POST"])
def api_test_integration():
    """Quick-test a specific integration by type."""
    itype = (request.json or {}).get("type", "")
    try:
        if itype == "coinbase":
            from sources.coinbase import get_balance
            d = get_balance()
            return jsonify({"ok": True, "result": "Coinbase connected", "data": d})
        elif itype == "obsidian":
            cfg  = json.loads(CONFIG_FILE.read_text())
            vp   = cfg.get("integrations", {}).get("obsidian", {}).get("vault_path", "")
            ok   = Path(vp).exists() if vp else False
            return jsonify({"ok": ok, "result": f"Vault {'found' if ok else 'not found'} at {vp}"})
        elif itype == "google_calendar":
            from sources.calendar_sync import sync
            events = sync()
            return jsonify({"ok": True, "result": f"{len(events)} events synced"})
        else:
            return jsonify({"ok": False, "error": f"Unknown integration: {itype}"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 7777))
    print(f"AEGIS Dashboard running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
