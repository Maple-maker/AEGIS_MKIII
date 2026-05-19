"""
AEGIS - Phase 1.2 (OpenAI TTS - Fable voice)
"""

import os
import subprocess
import tempfile
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

claude = Anthropic()
openai_client = OpenAI()

VOICE = "fable"
TTS_MODEL = "gpt-4o-mini-tts"

VOICE_INSTRUCTIONS = """Identity: JARVIS.

Delivery: Calm and deliberate, with measured pacing, subtle pauses, and quiet confidence.
Speech should feel composed and intentional rather than theatrical.

Voice: Refined British baritone or warm tenor with crisp articulation, restrained warmth,
and steady intelligence. Sophisticated, polished, and reassuring without sounding robotic.
You are witty and have charm.

Tone: Witty yet professional, composed, analytical, and quietly protective —
like a trusted aide-de-camp or guardian intelligence. Confident without arrogance,
calm under pressure, and always mission-focused."""


SYSTEM_PROMPT = """You are AEGIS, a calm, precise personal assistant for a US Army officer.

Your tone is direct and professional, like a trusted aide-de-camp. You are not a chatbot.
You are mission-focused, respect the user's time, and never waste words.

When asked for a daily brief, structure your response as:
1. SITUATION: One sentence summary of where things stand.
2. PRIORITIES: The 2-3 most important things to accomplish today.
3. CONTEXT: Any background, deadlines, or context worth remembering.
4. INSIGHT: One proactive observation, recommendation, or question worth considering.

Keep the entire brief under 200 words - it will be spoken aloud during a commute.
Use natural spoken language. Avoid bullet symbols, markdown, or anything that sounds awkward when read."""


NOTES = """
Tasks today:
- Finalize training schedule for next month
- Review NCOER bullets for SSG Martinez
- 1500 PT brief with battalion S3
- Pick up dry cleaning before 1800

Notes:
- BN commander wants the operation order draft by Friday
- I keep putting off updating my finance spreadsheet

Goals this week:
- Establish a consistent morning writing routine
- Make progress on the Series 7 study plan
"""


def get_brief(notes: str) -> str:
    response = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Here are my notes for today:\n\n{notes}\n\nGenerate my daily brief.",
            }
        ],
    )
    return response.content[0].text


def speak(text: str) -> None:
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
    print("AEGIS: Generating daily brief...\n")
    brief = get_brief(NOTES)
    print(brief)
    print("\n--- Speaking now ---")
    speak(brief)
    print("Brief complete.")
