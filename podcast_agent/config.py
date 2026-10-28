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
TTS_VOICES = [v.strip() for v in os.environ.get("TTS_VOICES", "").split(",") if v.strip()]

# Where episodes are saved, one folder each
RUNS = Path(os.environ.get("PODCAST_RUNS") or Path.home() / "podcast_runs")  # empty counts as unset
