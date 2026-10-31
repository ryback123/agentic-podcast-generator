# Podcast Agent

An agentic podcast generator with a web UI. Give it a topic, plus optional notes on audience and level. It plans the
episode, researches the topic on the web, and writes a 10–15 minute script for 2–5 speakers. Then it turns the script
into audio with a TTS model.

Scripts can be in English or code-mixed with one of 11 Indian languages: Hindi, Bengali, Marathi, Telugu, Tamil,
Gujarati, Kannada, Malayalam, Odia, Punjabi and Assamese. The mix can be light, medium or heavy.

## How it works

Five agents hand the episode along. Each step can also be run, edited or redone from the UI.

| Agent | Code | Tools | Decides |
|---|---|---|---|
| Producer | `agents/producer.py` | — | cast (name, gender, role, persona), format, segment plan, research questions |
| Researcher | `agents/researcher.py` | `search` (web via Tavily, Wikipedia), `read`, `done` | what to search and read next, and when to stop |
| Writer | `agents/writer.py` | — | writes each segment from the facts found; revises after critic feedback; follows user notes |
| Critics | `agents/writer.py`, `agents/checks.py` | code checks, fact-checker, editor | which words to change and what to (patched in place); only problems small edits can't fix send a segment back for a full rewrite (major issues only, at most 2 rounds) |
| Audio | `audio/` | TTS endpoint | one call per line (cached), mixed with pauses, fillers and cut-ins |

All prompts are in `agents/prompts.py`. `pipeline.py` runs the agents in order.

- **No native tool calling.** Agents call their tools by replying in plain-text JSON, so any OpenAI-compatible
  chat endpoint works.
- **Overlapping speech.** The writer adds backchannels (a listener's quick "hmm" or "right" while the other person
  talks) and cut-ins (someone starts before the other finishes). In the audio, a backchannel plays quietly in a pause
  of the other line, which carries on. A cut-in starts before the other line ends, which then stops dead or fades out.
  The pause before each reply varies (a quick reply, a longer think, now and then a reply that starts just before the
  other person finishes) and stays the same each time the episode is built. The rates and timings follow real
  two-person conversation (IndicVoices recordings with each speaker on their own channel): about six backchannels a
  minute, about one handover in ten written as a cut-in or talk-over and shared out between the speakers, and reply
  pauses drawn from measured handover gaps.
- **Word-level critics.** The fact-checker and editor point at the exact words to change and give replacements, which
  are patched into the line, so a fix does not disturb the rest of the segment. When a segment already has more
  English than its mix allows, fixes that put English in place of native words are dropped.
- **Deterministic checks.** The code checks in `agents/checks.py` cover line format, length against the time budget,
  repeated openers, digits and symbols that TTS reads badly, and script and code-mix balance. For example, they flag
  Hindi written in Latin letters, too much English for the chosen mix, a word mixing two scripts, an English word glued
  to an Indian-language ending (it takes a hyphen), or one word starting too many lines.

## Setup

Python 3.10+ and `ffmpeg` on the PATH (used for audio stitching).

```bash
pip install -e .            # or: pip install -e ".[dev]" to run the tests
cp .env.example .env        # fill in the endpoints and keys
set -a; . ./.env; set +a
```

| Variable | Needed for | Notes |
|---|---|---|
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | everything | any OpenAI-compatible chat endpoint; built with Gemma 4 31B |
| `TAVILY_API_KEY` | web search | optional; without it research uses Wikipedia only. A basic search costs 1 credit |
| `CONTACT_EMAIL` | Wikipedia | sent in the User-Agent, as Wikimedia's policy asks; anonymous clients get throttled |
| `TTS_BASE_URL`, `TTS_MODEL`, `TTS_API_KEY`, `TTS_VOICES` | audio | OpenAI-style `POST /audio/speech`, such as Bodhan's `indic-speak` (`.env.example` has its settings); every request sends `instructions` = `{"lang": <episode language>}`. `TTS_VOICES` is a comma-separated list of `name:gender:lang` |
| `PODCAST_RUNS` | — | where episodes are saved (default `~/podcast_runs`) |

To serve a model yourself, for example: `vllm serve google/gemma-4-31B-it --served-model-name gemma-4-31b`.

## Web app

```bash
python -m uvicorn podcast_agent.web.app:app --host 127.0.0.1 --port 8842
```

Open http://127.0.0.1:8842. It has four tabs, in a sidebar on a computer (which also lists the jobs running and how
far each got) and in a bottom tab bar on a phone:

- **New:** the new-episode form.
- **Episodes:** every episode, with search and filters for language and state; a count on the tab shows how many
  are being made. An episode's page has Duplicate (the same request, planned afresh) and Delete, which moves its folder
  to `.trash/` in the episodes folder.
- **Voices:** a sample of each TTS voice, and the default voice for female and male speakers.
- **Settings:** defaults for new episodes, the research step budget, review rounds per segment, web search on or off,
  audio speed (applied when an episode's audio is built, pitch unchanged), light or dark, and whether the model, web search and TTS are working. Saved in `settings.json` in the episodes
  folder; server addresses and keys stay in the environment.

Click the square beside an episode's title to give it a cover image (cropped to a square in the browser; saved as
`cover.jpg` in the episode folder). An episode walks through Plan → Research → Script → Audio:

- **Plan:** edit the cast and outline. Speaker names are made up by the producer; rename anyone at any time, and the
  script lines and voice choices follow. Each speaker has a persona, a few sentences on who they are and how they
  speak, which the writer follows; "Try this persona" writes three sample lines from it before any script exists.
- **Research:** run research again.
- **Script:** edit any line and choose how it starts (own turn, filler while the other keeps talking, cuts in with a
  hard stop, cuts in with a fade), review or fix a segment, or rewrite a segment with a note.
- **Audio:** pick voices and re-roll a single line's audio. The player shows what is playing (chapter, line,
  speaker) over a scrubber cut at the chapters; the lines are grouped by chapter, the playing line lights up and the
  list follows along; click a chapter or a line to play from there.

"Make the whole episode" runs every step in one go. Long steps run as background jobs while the page shows what the
agents are doing.

To share it from a machine with no public address: `cloudflared tunnel --url http://127.0.0.1:8842`.

## Command line

```bash
python -m podcast_agent --topic "How UPI payments work" --description "for class 8 students" --lang hi --minutes 12
python -m podcast_agent --help   # speakers, code-mix level, research steps, revisions, seed, output dir
python -m pytest                 # tests, no model calls
```

## Output

Each episode gets its own folder, `$PODCAST_RUNS/<timestamp>_<lang>_<topic>_<id>/`, containing:

| File | Contents |
|---|---|
| `episode.json` | everything about the episode: plan, facts, script, agent log, audio settings (see `episode.py`) |
| `calls.jsonl` | every LLM prompt and response |
| `audio/` | one clip per line |
| `episode.mp3`, `episode.wav` | the mixed episode at podcast loudness (-19 LUFS, mono); the MP3 has the segments as chapters |

The Script tab downloads the script as `script.txt` (to read) or `script.json` (for other programs; overlapping lines
carry a `mode`: `backchannel`, `cut` or `fade`). The command line prints the script when it finishes.

## Code layout

```
podcast_agent/
├── __main__.py        command line
├── config.py          every setting (environment variables)
├── languages.py       the 12 languages, their scripts, speaking pace, code-mix levels
├── llm.py             chat client for any OpenAI-compatible endpoint, JSON replies
├── episode.py         episode.json: what it holds, saving and loading; the script line format
├── edits.py           edits from the web app: the plan (renaming speakers), a segment's lines
├── pipeline.py        the order the agents run in
├── agents/
│   ├── prompts.py     every prompt
│   ├── producer.py    plans the episode
│   ├── researcher.py  research tool loop
│   ├── search.py      the researcher's tools: Tavily and Wikipedia
│   ├── writer.py      writes each segment; fact-checker and editor review it
│   └── checks.py      code checks on each segment
├── audio/
│   ├── tts.py         TTS call per line, voices, takes; builds the episode files
│   └── mix.py         joins clips: pauses, fillers, cut-ins
└── web/
    ├── app.py         API routes
    ├── jobs.py        background jobs, one per episode at a time
    ├── settings.py    the Settings tab's values, saved as settings.json in the episodes folder
    └── static/        the browser UI (plain JS, no build step)
        └── assets/    the logo: logo.svg is the source; icon-32.png and icon-180.png are exported from it
tests/                 python -m pytest
PRODUCT.md, DESIGN.md  who the app is for, and its visual system (colours, type, motion); read before UI changes
.impeccable/surfaces/  the design brief behind the current look
dev/tts_standin.py     local OpenAI-style TTS server, used for development before the course TTS API
```

## Development setup

Course runs on our cluster:

- Episodes are saved under `/projects/data/ttsteam/nikhil/runs/podcast_agent/runs/`.
- Service scripts are in `/projects/data/ttsteam/nikhil/runs/podcast_agent/services/`: `gemma31b_local/` (vLLM,
  Gemma 4 31B), `tts_local/` (the TTS stand-in) and `web/` (the app and its Cloudflare tunnel).
- Evaluation runs:
  - [langs_20261029](</projects/data/ttsteam/nikhil/runs/podcast_agent_evals/runs/langs_20261029/summary.md>): one
    episode in each of 10 Indian languages with the same settings, to find language-specific script problems (code
    `0607294`).
  - [wordcritic_20261029](</projects/data/ttsteam/nikhil/runs/podcast_agent_evals/runs/wordcritic_20261029/summary.md>):
    the same sweep after the word-level critics and the fixes it prompted (code `c8736f5`).
  - [wordcritic2_20261029](</projects/data/ttsteam/nikhil/runs/podcast_agent_evals/runs/wordcritic2_20261029/summary.md>):
    the same again after fixing the hyphen check (code `02c8093`).
  - [wordcritic3_20261029](</projects/data/ttsteam/nikhil/runs/podcast_agent_evals/runs/wordcritic3_20261029/summary.md>):
    the same again after fixing the accented-word check and cut-off replies.
  - [swapfix_20261029](</projects/data/ttsteam/nikhil/runs/podcast_agent_evals/runs/swapfix_20261029/summary.md>):
    the same again after stopping the editor swapping native words for English (code `ed7a82f`).
  - [budget_20261029](</projects/data/ttsteam/nikhil/runs/podcast_agent_evals/runs/budget_20261029/summary.md>):
    the same again with an English budget for medium code-mixing (code `eab1a98`).

## Licence

MIT, see [LICENSE](LICENSE).
