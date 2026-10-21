# podcast_agent

Course project: agentic podcast generator. Given a topic (plus optional audience/level notes), it writes a
10–15 minute, n-speaker, code-mixed podcast script in English or any of the 22 scheduled Indian languages.
TTS comes later; this repo currently covers script generation.

## Agents

| Agent | Tools | Decides |
|---|---|---|
| Producer (`produce`) | — | cast, format, segment plan, research questions |
| Researcher (`research`) | `search`, `read`, `done` (Wikipedia for now) | what to search/read next, when to stop |
| Writer (`write_segment`) | — | writes each segment from its facts; revises on critic feedback |
| Critics (`review`) | code checks (`checks.py`), fact-checker, editor | issues that send a segment back (max `--max-revisions` rounds) |

Tools are called through plain-text JSON replies, so any OpenAI-compatible chat endpoint works
(no native function calling needed).

## Run

```bash
export LLM_BASE_URL=http://bodhanai-node004:8031/v1 LLM_MODEL=gemma-4-31b LLM_API_KEY=EMPTY  # local dev server
/projects/data/ttsteam/miniconda3/envs/gemma4/bin/python podcast.py \
    --topic "How UPI payments work" --description "for class 8 students" --lang hi --speakers 2 --minutes 12
python checks.py   # self-test of the deterministic checks
```

Switching to the course API = changing the three env vars.

Each run writes to `/projects/data/ttsteam/nikhil/runs/podcast_agent/runs/<timestamp>_<lang>_<topic>/`:
`script.json` (turns for TTS + sources), `script.txt` (readable), `episode.json` (plan, facts, agent
decision log, open issues, stats, code commit), `calls.jsonl` (every LLM prompt/response).

## Services

Local stand-in for the course Gemma 31B API: `/projects/data/ttsteam/nikhil/runs/podcast_agent/services/gemma31b_local/serve.sbatch`
(Slurm, 2 GPUs on node004, port 8031).
