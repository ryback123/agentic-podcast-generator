"""Settings, all from environment variables (see .env.example)."""
import os
from pathlib import Path

# Script model: any OpenAI-compatible chat endpoint
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemma-4-31b")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "EMPTY")

# Research: Tavily web search (optional) and Wikipedia
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")  # sent to Wikipedia, which throttles anonymous clients

# Text-to-speech: OpenAI-style /audio/speech endpoint (optional; needed for the audio step only)
TTS_BASE_URL = os.environ.get("TTS_BASE_URL", "")
TTS_MODEL = os.environ.get("TTS_MODEL", "tts")
TTS_API_KEY = os.environ.get("TTS_API_KEY", "EMPTY")


def parse_voices(s):
    """TTS_VOICES: comma-separated voice names, each optionally name:gender:lang (Amit:male:hi), so a speaker can start
    on a voice of their gender in the episode's language. Returns {name: {"gender", "lang"}} in the given order."""
    out = {}
    for item in s.split(","):
        name, gender, lang = ([p.strip() for p in item.split(":")] + ["", ""])[:3]
        if name:
            out[name] = {"gender": gender, "lang": lang}
    return out


TTS_VOICE_INFO = parse_voices(os.environ.get("TTS_VOICES", ""))
TTS_VOICES = list(TTS_VOICE_INFO)

# Where episodes are saved, one folder each
RUNS = Path(os.environ.get("PODCAST_RUNS") or Path.home() / "podcast_runs")  # empty counts as unset
