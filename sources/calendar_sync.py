"""
sources/calendar_sync.py
Syncs Google Calendar events into data/calendar_cache.json.

First-time setup:
  1. Go to https://console.cloud.google.com
  2. Create project → Enable "Google Calendar API"
  3. Credentials → Create → OAuth 2.0 → Desktop App → Download JSON
  4. Save it as:  /Users/jaidenrabatin/Documents/AEGIS/data/gcal_credentials.json
  5. Run once:    venv/bin/python3 sources/calendar_sync.py
     → Browser opens, sign in, approve — token saved automatically

After that, it runs headlessly forever (token auto-refreshes).
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT        = Path(__file__).parent.parent
CREDS_FILE  = ROOT / "data" / "gcal_credentials.json"
TOKEN_FILE  = ROOT / "data" / "gcal_token.json"
CACHE_FILE  = ROOT / "data" / "calendar_cache.json"

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# ── Lane classification ────────────────────────────────────────────────────

TRAVEL_KEYWORDS = ["flight", "hotel", "stay at", "airport", "depart", "arrive",
                   "dubrovnik", "munich", "tokyo", "toronto", "charlotte", "dulles",
                   "newark", "cleveland"]
FAMILY_KEYWORDS = ["birthday", "wedding", "anniversary", "mom", "dad", "family",
                   "thanksgiving", "christmas", "reunion"]
MILESTONE_KEYWORDS = ["counseling", "board", "ncoer", "oer", "promotion", "evaluation",
                      "graduation", "ceremony", "completion"]
GOAL_KEYWORDS = ["btc", "bitcoin", "milestone", "launch", "deadline", "goal", "target",
                 "clarity act", "publish", "film", "record"]


def classify(summary: str) -> str:
    s = summary.lower()
    if any(k in s for k in TRAVEL_KEYWORDS):   return "travel"
    if any(k in s for k in FAMILY_KEYWORDS):   return "family"
    if any(k in s for k in MILESTONE_KEYWORDS): return "milestone"
    if any(k in s for k in GOAL_KEYWORDS):     return "goal"
    return "other"


def get_icon(lane: str, summary: str) -> str:
    s = summary.lower()
    if "flight" in s or "depart" in s: return "✈"
    if "hotel" in s or "stay" in s:    return "🏨"
    if "birthday" in s:                return "🎂"
    if "wedding" in s:                 return "💍"
    if "red sox" in s or "game" in s:  return "⚾"
    if "dubrovnik" in s or "beach" in s: return "🏖"
    if lane == "travel":               return "✈"
    if lane == "family":               return "👨‍👩‍👧"
    if lane == "milestone":            return "🎯"
    return "📌"


def build_service():
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_FILE.exists():
                print(f"\nERROR: Google credentials file not found at:\n  {CREDS_FILE}")
                print("\nSetup steps:")
                print("  1. Go to https://console.cloud.google.com")
                print("  2. Enable 'Google Calendar API'")
                print("  3. Create OAuth2 credentials (Desktop app)")
                print("  4. Download JSON → save as data/gcal_credentials.json")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def fetch_events(service, days_ahead: int = 120) -> list[dict]:
    now  = datetime.now(timezone.utc)
    end  = now + timedelta(days=days_ahead)

    result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        maxResults=50,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = []
    for e in result.get("items", []):
        summary = e.get("summary", "").strip()
        if not summary:
            continue

        # Get date
        start = e["start"].get("dateTime") or e["start"].get("date", "")
        date_str = start[:10] if start else ""
        if not date_str:
            continue

        lane = classify(summary)
        if lane == "other":
            continue  # skip noise

        events.append({
            "id":      e["id"][:20],
            "summary": summary,
            "start":   date_str,
            "lane":    lane,
            "icon":    get_icon(lane, summary),
        })

    return events


def sync():
    print("Connecting to Google Calendar…")
    service = build_service()
    print("Fetching events…")
    events = fetch_events(service)
    print(f"  {len(events)} classified events fetched")

    cache = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "events": events,
    }
    CACHE_FILE.write_text(json.dumps(cache, indent=2))
    print(f"  Saved → {CACHE_FILE}")
    return events


if __name__ == "__main__":
    evs = sync()
    for e in evs:
        print(f"  [{e['lane']:10}] {e['start']}  {e['summary']}")
