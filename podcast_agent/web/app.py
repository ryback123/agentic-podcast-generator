"""Web app: FastAPI backend + static UI (static/). Every long action runs as a background job (jobs.py) on one
episode; the UI polls GET /api/episodes/{id}, which reads the episode.json the job keeps saving.

  python -m uvicorn podcast_agent.web.app:app --host 127.0.0.1 --port 8842
"""
import json
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .. import edits, llm, pipeline
from ..agents import producer, researcher, writer
from ..audio import tts
from ..config import RUNS, TTS_VOICES
from ..episode import load, new_episode, script_json, script_text, update_stats
from ..languages import CODE_MIX, LANGS
from .jobs import editable, episode_dir, jobs, start

app = FastAPI(title="Podcast Studio")
STATIC = Path(__file__).resolve().parent / "static"


def segment_index(ep, i):
    if not ep.get("plan") or not 0 <= i < len(ep["plan"]["segments"]):
        raise HTTPException(404, "no such segment")
    return i


# ---------------------------------------------------------------- read
@app.get("/api/config")
def config():
    return {"languages": [{"code": c, "name": n, "script": s} for c, (n, s, _) in LANGS.items()],
            "code_mix": list(CODE_MIX), "model": llm.MODEL,
            "tts": {"configured": tts.configured(), "voices": TTS_VOICES, "model": tts.MODEL}}


@app.get("/api/episodes")
def list_episodes():
    out = []
    for f in sorted(RUNS.glob("*/episode.json"), reverse=True):
        try:
            ep = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if "id" not in ep:  # runs from before the web app
            continue
        plan = ep.get("plan") or {}
        job = jobs.get(ep["id"], {})
        out.append({"id": ep["id"], "title": plan.get("title") or ep["request"]["topic"],
                    "topic": ep["request"]["topic"], "lang": ep["request"]["lang"], "created": ep.get("created"),
                    "speakers": len(plan.get("speakers") or []) or ep["request"].get("speakers"),
                    "minutes": (ep.get("stats") or {}).get("est_minutes"),
                    "running": job.get("running", False), "task": job.get("task"),
                    "has_script": any(s.get("turns") for s in plan.get("segments", [])),
                    "has_audio": bool((ep.get("audio") or {}).get("episode"))})
    return out


@app.get("/api/episodes/{eid}")
def get_episode(eid: str):
    ep = load(episode_dir(eid))
    run = Path(ep["dir"])
    ep["job"] = jobs.get(eid, {"task": None, "running": False, "error": None})
    ep["lines"] = [{**ln, "ready": bool(ln["file"]) and (run / ln["file"]).exists()} for ln in tts.lines(ep)]
    ep.pop("dir")
    return ep


def with_script(eid):
    ep = load(episode_dir(eid))
    if not any(s.get("turns") for s in (ep.get("plan") or {}).get("segments", [])):
        raise HTTPException(404, "no script yet")
    return ep


@app.get("/api/episodes/{eid}/script.txt", response_class=PlainTextResponse)
def get_script_txt(eid: str):
    return script_text(with_script(eid))


@app.get("/api/episodes/{eid}/script.json")
def get_script_json(eid: str):
    return script_json(with_script(eid))


@app.get("/api/episodes/{eid}/files/{path:path}")
def get_file(eid: str, path: str):
    run = episode_dir(eid).resolve()
    f = (run / path).resolve()
    if run not in f.parents or not f.is_file() or f.name in ("calls.jsonl",):
        raise HTTPException(404, "no such file")
    return FileResponse(f)


# ---------------------------------------------------------------- create + agent stages
@app.post("/api/episodes")
def create(req: dict = Body(...)):
    try:
        ep = new_episode(req.get("topic", ""), req.get("description", ""), req.get("lang", "en"),
                            int(req.get("speakers", 2)), float(req.get("minutes", 12)), req.get("code_mix", "medium"))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    if req.get("auto"):
        start(ep["id"], "making the whole episode", pipeline.run_all)
    else:
        start(ep["id"], "planning", producer.produce)
    return {"id": ep["id"]}


@app.post("/api/episodes/{eid}/plan")
def replan(eid: str):
    return start(eid, "planning", producer.produce)


@app.put("/api/episodes/{eid}/plan")
def save_plan(eid: str, plan: dict = Body(...)):
    ep = editable(eid)
    try:
        edits.set_plan(ep, plan)
    except (ValueError, TypeError, KeyError, IndexError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/episodes/{eid}/research")
def research(eid: str):
    return start(eid, "researching", researcher.research)


@app.post("/api/episodes/{eid}/write")
def write(eid: str, body: dict = Body(default={})):
    only_missing = bool(body.get("only_missing"))
    return start(eid, "writing the script", lambda ep: pipeline.write_all(ep, only_missing=only_missing))


@app.post("/api/episodes/{eid}/continue")
def continue_all(eid: str):
    return start(eid, "running the remaining steps", pipeline.run_all)


@app.post("/api/episodes/{eid}/segments/{i}/{action}")
def segment_action(eid: str, i: int, action: str, body: dict = Body(default={})):
    segment_index(load(episode_dir(eid)), i)
    note = (body.get("note") or "").strip() or None
    if action == "rewrite":
        fn = lambda ep: (writer.write_segment(ep, i, note=note), update_stats(ep))  # noqa: E731
    elif action == "fix":
        fn = lambda ep: (writer.write_segment(ep, i, note=note, from_current=True), update_stats(ep))  # noqa: E731
    elif action == "review":
        fn = lambda ep: (writer.review_segment(ep, i), update_stats(ep))  # noqa: E731
    else:
        raise HTTPException(404, "unknown action")
    return start(eid, f"{action} segment {i + 1}", fn)


@app.post("/api/episodes/{eid}/sample")
def sample(eid: str, speaker: dict = Body(...)):
    """Three lines in a speaker's persona, from the cast card as typed (nothing is saved)."""
    ep = load(episode_dir(eid))
    if not ep.get("plan"):
        raise HTTPException(409, "plan the episode first")
    return {"lines": writer.sample_lines(ep, speaker)}


@app.put("/api/episodes/{eid}/segments/{i}")
def save_segment(eid: str, i: int, body: dict = Body(...)):
    ep = editable(eid)
    segment_index(ep, i)
    try:
        edits.set_turns(ep, i, body["turns"])
    except (ValueError, TypeError, KeyError, IndexError) as e:
        raise HTTPException(400, str(e))
    return {"issues": ep["plan"]["segments"][i]["open_issues"]}


# ---------------------------------------------------------------- audio
@app.post("/api/episodes/{eid}/audio")
def make_audio(eid: str, body: dict = Body(default={})):
    voices = body.get("voices") or None
    return start(eid, "generating audio", lambda ep: tts.synthesize(ep, voices))


@app.post("/api/episodes/{eid}/audio/{i}/{k}")
def retake(eid: str, i: int, k: int):
    return start(eid, f"new take of line {k + 1}", lambda ep: tts.new_take(ep, i, k))


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
