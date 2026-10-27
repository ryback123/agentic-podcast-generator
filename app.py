"""Web app: FastAPI backend + static UI (static/). Every long action runs as a background job on one
episode; the UI polls GET /api/episodes/{id}, which reads the episode.json the job keeps saving.

  uvicorn app:app --host 127.0.0.1 --port 8840
"""
import json
import re
import threading
import traceback
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import audio
import llm
import podcast as pc
from checks import LANGS

app = FastAPI(title="Podcast Studio")
STATIC = Path(__file__).resolve().parent / "static"
jobs = {}  # episode id -> {"task", "running", "error"}
_jobs_lock = threading.Lock()


def episode_dir(eid):
    if not re.fullmatch(r"[\w-]+", eid) or not (pc.RUNS / eid / "episode.json").exists():
        raise HTTPException(404, "no such episode")
    return pc.RUNS / eid


def start(eid, task, fn):
    """Run fn(ep) in a background thread; one job per episode at a time."""
    with _jobs_lock:
        if jobs.get(eid, {}).get("running"):
            raise HTTPException(409, f"busy: {jobs[eid]['task']}")
        jobs[eid] = {"task": task, "running": True, "error": None}
    ep = pc.load(episode_dir(eid))

    def target():
        try:
            fn(ep)
        except Exception as e:  # job boundary: the error is shown in the UI, the traceback goes to the server log
            traceback.print_exc()
            jobs[eid]["error"] = f"{type(e).__name__}: {e}"
            pc.log(ep, "error", f"{task} failed: {type(e).__name__}: {e}")
        finally:
            jobs[eid]["running"] = False

    threading.Thread(target=target, daemon=True).start()
    return {"ok": True, "task": task}


def editable(eid):
    if jobs.get(eid, {}).get("running"):
        raise HTTPException(409, "wait for the running job to finish")
    return pc.load(episode_dir(eid))


def segment_index(ep, i):
    if not ep.get("plan") or not 0 <= i < len(ep["plan"]["segments"]):
        raise HTTPException(404, "no such segment")
    return i


# ---------------------------------------------------------------- read
@app.get("/api/config")
def config():
    return {"languages": [{"code": c, "name": n, "script": s} for c, (n, s, _) in LANGS.items()],
            "code_mix": list(pc.CODE_MIX), "model": llm.MODEL,
            "tts": {"configured": audio.configured(), "voices": audio.VOICES, "model": audio.MODEL}}


@app.get("/api/episodes")
def list_episodes():
    out = []
    for f in sorted(pc.RUNS.glob("*/episode.json"), reverse=True):
        try:
            ep = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if "id" not in ep:  # runs from before the web app
            continue
        plan = ep.get("plan") or {}
        out.append({"id": ep["id"], "title": plan.get("title") or ep["request"]["topic"],
                    "topic": ep["request"]["topic"], "lang": ep["request"]["lang"], "created": ep.get("created"),
                    "running": jobs.get(ep["id"], {}).get("running", False),
                    "has_script": any(s.get("turns") for s in plan.get("segments", [])),
                    "has_audio": bool((ep.get("audio") or {}).get("episode"))})
    return out


@app.get("/api/episodes/{eid}")
def get_episode(eid: str):
    ep = pc.load(episode_dir(eid))
    run = Path(ep["dir"])
    ep["job"] = jobs.get(eid, {"task": None, "running": False, "error": None})
    ep["lines"] = [{**ln, "ready": bool(ln["file"]) and (run / ln["file"]).exists()} for ln in audio.lines(ep)]
    ep.pop("dir")
    return ep


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
        ep = pc.new_episode(req.get("topic", ""), req.get("description", ""), req.get("lang", "en"),
                            int(req.get("speakers", 2)), float(req.get("minutes", 12)), req.get("code_mix", "medium"))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    if req.get("auto"):
        start(ep["id"], "making the whole episode", pc.run_all)
    else:
        start(ep["id"], "planning", pc.produce)
    return {"id": ep["id"]}


@app.post("/api/episodes/{eid}/plan")
def replan(eid: str):
    return start(eid, "planning", pc.produce)


@app.put("/api/episodes/{eid}/plan")
def save_plan(eid: str, plan: dict = Body(...)):
    ep = editable(eid)
    try:
        pc.set_plan(ep, plan)
    except (ValueError, TypeError, KeyError, IndexError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/episodes/{eid}/research")
def research(eid: str):
    return start(eid, "researching", pc.research)


@app.post("/api/episodes/{eid}/write")
def write(eid: str, body: dict = Body(default={})):
    only_missing = bool(body.get("only_missing"))
    return start(eid, "writing the script", lambda ep: pc.write_all(ep, only_missing=only_missing))


@app.post("/api/episodes/{eid}/continue")
def continue_all(eid: str):
    return start(eid, "running the remaining steps", pc.run_all)


@app.post("/api/episodes/{eid}/segments/{i}/{action}")
def segment_action(eid: str, i: int, action: str, body: dict = Body(default={})):
    segment_index(pc.load(episode_dir(eid)), i)
    note = (body.get("note") or "").strip() or None
    if action == "rewrite":
        fn = lambda ep: (pc.write_segment(ep, i, note=note), pc.finish(ep))  # noqa: E731
    elif action == "fix":
        fn = lambda ep: (pc.write_segment(ep, i, note=note, from_current=True), pc.finish(ep))  # noqa: E731
    elif action == "review":
        fn = lambda ep: (pc.review_segment(ep, i), pc.finish(ep))  # noqa: E731
    else:
        raise HTTPException(404, "unknown action")
    return start(eid, f"{action} segment {i + 1}", fn)


@app.put("/api/episodes/{eid}/segments/{i}")
def save_segment(eid: str, i: int, body: dict = Body(...)):
    ep = editable(eid)
    segment_index(ep, i)
    try:
        pc.set_turns(ep, i, body["turns"])
    except (ValueError, TypeError, KeyError, IndexError) as e:
        raise HTTPException(400, str(e))
    return {"issues": ep["plan"]["segments"][i]["open_issues"]}


# ---------------------------------------------------------------- audio
@app.post("/api/episodes/{eid}/audio")
def make_audio(eid: str, body: dict = Body(default={})):
    voices = body.get("voices") or None
    return start(eid, "generating audio", lambda ep: audio.synthesize(ep, voices))


@app.post("/api/episodes/{eid}/audio/{i}/{k}")
def retake(eid: str, i: int, k: int):
    return start(eid, f"new take of line {k + 1}", lambda ep: audio.new_take(ep, i, k))


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
