# Podcast Agent

An agentic podcast generator with a web UI. Give it a topic, plus optional notes on audience and level. It plans the
episode, researches the topic on the web, and writes a 10–15 minute script for 2–5 speakers. Then it turns the script
into audio with a TTS model.

Scripts can be in English or code-mixed with one of 11 Indian languages: Hindi, Bengali, Marathi, Telugu, Tamil,
Gujarati, Kannada, Malayalam, Odia, Punjabi and Assamese. The mix can be light, medium or heavy.

## How it works

Five agents hand the episode along. Each step can also be run, edited or redone from the UI.

| Agent | Tools | Decides |
|---|---|---|
| Producer | — | cast (name, gender, role), format, segment plan, research questions |
| Researcher | `search` (web via Tavily, Wikipedia), `read`, `done` | what to search and read next, and when to stop |
| Writer | — | writes each segment from the facts found; revises after critic feedback; follows user notes |
| Critics | code checks, fact-checker, editor | which issues send a segment back for a rewrite (major ones only, at most 2 rounds) |
| Audio | TTS endpoint | one call per line (cached), stitched with pauses and level matching |

- **No native tool calling.** Agents call their tools by replying in plain-text JSON, so any OpenAI-compatible
  chat endpoint works.
- **Deterministic checks.** The code checks in `checks.py` cover line format, length against the time budget,
  repeated openers, digits and symbols that TTS reads badly, and script and code-mix balance. For example, they flag
  Hindi written in Latin letters, or too much English for the chosen mix.

## Setup

Python 3.10+ and `ffmpeg` on the PATH (used for audio stitching).

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in the endpoints and keys
set -a; . ./.env; set +a
```

| Variable | Needed for | Notes |
|---|---|---|
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | everything | any OpenAI-compatible chat endpoint; built with Gemma 4 31B |
| `TAVILY_API_KEY` | web search | optional; without it research uses Wikipedia only. A basic search costs 1 credit |
| `CONTACT_EMAIL` | Wikipedia | sent in the User-Agent, as Wikimedia's policy asks; anonymous clients get throttled |
| `TTS_BASE_URL`, `TTS_MODEL`, `TTS_API_KEY`, `TTS_VOICES` | audio | OpenAI-style `POST /audio/speech`; `TTS_VOICES` is a comma-separated list |
| `PODCAST_RUNS` | — | where episodes are saved (default `~/podcast_runs`) |

To serve a model yourself, for example: `vllm serve google/gemma-4-31B-it --served-model-name gemma-4-31b`.

## Web app

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8842
```

Open http://127.0.0.1:8842. The UI walks through Plan → Research → Script → Audio:

- **Plan:** edit the cast and outline.
- **Research:** run research again.
- **Script:** edit any line, review or fix a segment, or rewrite a segment with a note.
- **Audio:** pick voices and re-roll a single line's audio.

"Make the whole episode" runs every step in one go. Long steps run as background jobs while the page shows what the
agents are doing.

To share it from a machine with no public address: `cloudflared tunnel --url http://127.0.0.1:8842`.

## Command line

```bash
python podcast.py --topic "How UPI payments work" --description "for class 8 students" --lang hi --minutes 12
python podcast.py --help        # speakers, code-mix level, research steps, revisions, seed, output dir
python checks.py && python audio.py   # self-tests, no model calls
```

## Output

Each episode gets its own folder, `$PODCAST_RUNS/<timestamp>_<lang>_<topic>_<id>/`, containing:

| File | Contents |
|---|---|
| `episode.json` | the plan, facts, script, agent log and audio state |
| `script.txt`, `script.json` | the final script |
| `calls.jsonl` | every LLM prompt and response |
| `audio/` | line clips |
| `episode.mp3` | the stitched episode |

## Files

| File | Role |
|---|---|
| `podcast.py` | agents, prompts, episode state, CLI |
| `checks.py` | deterministic script checks and language and script tables |
| `search.py` | Tavily and Wikipedia search and page reading |
| `llm.py` | chat client and JSON reply parsing |
| `audio.py` | TTS calls and stitching |
| `app.py`, `static/` | web app (FastAPI backend, plain JS front end with no build step) |
| `dev/tts_standin.py` | local OpenAI-style TTS server, used for development before the course TTS API |

## Development setup

Course runs on our cluster:

- Episodes are saved under `/projects/data/ttsteam/nikhil/runs/podcast_agent/runs/`.
- Service scripts are in `/projects/data/ttsteam/nikhil/runs/podcast_agent/services/`: `gemma31b_local/` (vLLM,
  Gemma 4 31B), `tts_local/` (the TTS stand-in) and `web/` (the app and its Cloudflare tunnel).
