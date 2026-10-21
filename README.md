# podcast_agent

Course project: an agentic podcast generator with a web UI. Given a topic (plus optional audience/level notes),
it plans, researches and writes a 10–15 minute, n-speaker, code-mixed podcast script in English or one of
11 major Indian languages (hi, bn, mr, te, ta, gu, kn, ml, or, pa, as), then turns it into audio.

## Agents

| Agent | Tools | Decides |
|---|---|---|
| Producer (`produce`) | — | cast (name, gender, role), format, segment plan, research questions |
| Researcher (`research`) | `search`, `read`, `done` (Wikipedia for now) | what to search/read next, when to stop |
| Writer (`write_segment`) | — | writes each segment from its facts; revises on critic feedback; follows user notes |
| Critics (`review`) | code checks (`checks.py`), fact-checker, editor | issues that send a segment back (only "major" ones; max 2 rounds) |
| Audio (`audio.py`) | TTS API | one call per line (cached by voice+text+take), stitched with pauses and level matching |

Tools are called through plain-text JSON replies, so any OpenAI-compatible chat endpoint works
(no native function calling needed).

## Web app

```bash
cd /projects/data/ttsteam/nikhil/podcast_agent
export LLM_BASE_URL=http://bodhanai-node004:8031/v1 LLM_MODEL=gemma-4-31b LLM_API_KEY=EMPTY      # script model
export TTS_BASE_URL=http://bodhanai-node040:8032/v1 TTS_VOICES=Ira,Aisha,Siya,Zoya              # optional: audio
/projects/data/ttsteam/miniconda3/envs/gemma4/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8840
```

The UI walks through Plan → Research → Script → Audio. Every step can be edited or re-run: edit the cast and
outline, re-run research, edit any line, review or fix a segment, rewrite a segment with a note, pick voices,
re-roll a single line's audio. "Make the whole episode" runs everything in one go. Long steps run as background
jobs; the page polls and shows the agents' activity live.

Switching to the course APIs = changing the `LLM_*` / `TTS_*` env vars.

## CLI

```bash
python podcast.py --topic "How UPI payments work" --description "for class 8 students" --lang hi --minutes 12
python checks.py && python audio.py   # self-tests (no model calls)
```

## Where things live

Episodes: `/projects/data/ttsteam/nikhil/runs/podcast_agent/runs/<timestamp>_<lang>_<topic>_<id>/`
(`episode.json` = plan, facts, script, agent log, audio state; `script.json`/`script.txt`; `calls.jsonl` = every
LLM prompt/response; `audio/` line clips; `episode.mp3`). Override with `PODCAST_RUNS`.

Dev services (local stand-ins for the course APIs), under `/projects/data/ttsteam/nikhil/runs/podcast_agent/services/`:
`gemma31b_local/serve.sbatch` (vLLM, node004, port 8031) and `tts_local/serve.sbatch`
(`dev/tts_standin.py`, rumik-oss-1, node040, port 8032).
