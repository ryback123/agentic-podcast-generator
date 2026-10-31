"""Web app: FastAPI backend + static UI (static/). Every long action runs as a background job (jobs.py) on one
episode; the UI polls GET /api/episodes/{id}, which reads the episode.json the job keeps saving.

  python -m uvicorn podcast_agent.web.app:app --host 127.0.0.1 --port 8842
"""
import base64
import binascii
import hashlib
import json
import shutil
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .. import document, edits, llm, pipeline
from ..agents import producer, researcher, writer
from ..audio import tts
from ..config import RUNS, TAVILY_API_KEY, TTS_VOICE_INFO, TTS_VOICES
from ..episode import load, new_episode, script_json, script_text, update_stats
from ..languages import CODE_MIX, LANGS
from . import settings
from .jobs import editable, episode_dir, jobs, start

app = FastAPI(title="Podcast Studio")
STATIC = Path(__file__).resolve().parent / "static"


@app.middleware("http")
async def revalidate(request, call_next):
    """Browsers check for a newer app.js or style.css on every load (a quick 304 when unchanged), so an update shows
    up on a normal reload instead of whenever their cached copy expires."""
    r = await call_next(request)
    r.headers.setdefault("Cache-Control", "no-cache")
    return r


def segment_index(ep, i):
    if not ep.get("plan") or not 0 <= i < len(ep["plan"]["segments"]):
        raise HTTPException(404, "no such segment")
    return i


# ---------------------------------------------------------------- read
@app.get("/api/config")
def config():
    return {"languages": [{"code": c, "name": n, "script": s} for c, (n, s, _) in LANGS.items()],
            "code_mix": list(CODE_MIX), "model": llm.MODEL,
            "tts": {"configured": tts.configured(), "voices": TTS_VOICES, "voice_info": TTS_VOICE_INFO, "model": tts.MODEL}}


def job_progress(ep, task, run):
    """How far a running job got, from 0 to 1, or None when there is no way to tell (planning, a whole-episode run)."""
    segs = (ep.get("plan") or {}).get("segments") or []
    if task == "generating audio" or task.startswith("new take"):
        ls = [ln for ln in tts.lines(ep) if ln["file"]]
        return sum((run / ln["file"]).exists() for ln in ls) / len(ls) if ls else None
    if (task == "writing the script" or task.startswith("rewrite segment")) and segs:
        last = next((e["event"] for e in reversed(ep.get("log", [])) if e.get("agent") == "writer"
                     and e.get("event", "").startswith("writing segment ")), None)
        return (int(last.split()[2].rstrip(":")) - 1) / len(segs) if last else 0.0
    if task == "researching" and ep.get("questions"):
        found = {f.get("q") for f in ep.get("facts", [])}
        return sum(q in found for q in ep["questions"]) / len(ep["questions"])
    return None


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
                    "running": job.get("running", False), "task": job.get("task"), "cover": cover_name(f.parent),
                    "progress": job_progress(ep, job["task"], f.parent) if job.get("running") else None,
                    "has_script": any(s.get("turns") for s in plan.get("segments", [])),
                    "has_audio": bool((ep.get("audio") or {}).get("episode"))})
    return out


@app.get("/api/episodes/{eid}")
def get_episode(eid: str):
    ep = load(episode_dir(eid))
    run = Path(ep["dir"])
    ep["job"] = jobs.get(eid, {"task": None, "running": False, "error": None})
    ep["lines"] = [{**ln, "ready": bool(ln["file"]) and (run / ln["file"]).exists()} for ln in tts.lines(ep)]
    ep["cover"] = cover_name(run)
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


# ---------------------------------------------------------------- library: duplicate, delete
@app.post("/api/episodes/{eid}/duplicate")
def duplicate(eid: str):
    """A new episode with the same request, planned from scratch."""
    r = load(episode_dir(eid))["request"]
    doc = r.get("document")
    ep = new_episode(r["topic"], r.get("description", ""), r["lang"], r["speakers"], r["minutes"], r["code_mix"], out=RUNS,
                     document=(doc["name"], (episode_dir(eid) / doc["file"]).read_bytes()) if doc else None,
                     doc_web=r.get("doc_web", False))
    start(ep["id"], "planning", producer.produce)
    return {"id": ep["id"]}


@app.delete("/api/episodes/{eid}")
def delete(eid: str):
    """Moves the episode's folder to RUNS/.trash, out of the list. Delete it from there by hand to free the space."""
    run = episode_dir(eid)
    if jobs.get(eid, {}).get("running"):
        raise HTTPException(409, "wait for the running job to finish")
    dest = RUNS / ".trash" / eid
    if dest.exists():
        dest = dest.with_name(f"{eid}_{int(time.time())}")
    dest.parent.mkdir(exist_ok=True)
    shutil.move(run, dest)
    jobs.pop(eid, None)
    return {"ok": True}


# ---------------------------------------------------------------- settings, service status, voice samples
@app.get("/api/settings")
def get_settings():
    return settings.load()


@app.put("/api/settings")
def put_settings(body: dict = Body(...)):
    try:
        return settings.save(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/status")
def status():
    """What the Settings tab shows: whether each service works, never its address or key."""
    try:
        llm._client.with_options(timeout=5, max_retries=0).models.list()
        model = {"name": llm.MODEL, "ok": True}
    except Exception as e:  # any failure means not reachable; its kind is shown
        model = {"name": llm.MODEL, "ok": False, "error": type(e).__name__}
    eps = []
    for f in RUNS.glob("*/episode.json"):
        try:
            eps.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            continue
    # ponytail: walks every file each time; cache it if the Settings tab gets slow with thousands of episodes
    size = sum(f.stat().st_size for f in RUNS.rglob("*") if f.is_file())
    return {"model": model,
            "web_search": {"key": bool(TAVILY_API_KEY),
                           "credits": sum((e.get("research_stats") or {}).get("credits", 0) for e in eps)},
            "tts": {"configured": tts.configured(), "voices": len(TTS_VOICES)},
            "storage": {"episodes": sum(1 for e in eps if "id" in e), "bytes": size}}


@app.get("/api/voices/{voice}/sample.wav")
def voice_sample(voice: str):
    """A short line in this voice, made on first play and kept in RUNS/.voices."""
    if not tts.configured() or voice not in TTS_VOICES:
        raise HTTPException(404, "no such voice")
    f = RUNS / ".voices" / f"{hashlib.sha1(f'{voice}|{tts.sample_line(voice)[0]}'.encode()).hexdigest()[:16]}.wav"
    if not f.exists():
        f.parent.mkdir(exist_ok=True)
        tts.sample(voice, f)
    return FileResponse(f, media_type="audio/wav")


# ---------------------------------------------------------------- cover image
# A file next to episode.json rather than a field in it, so a running job saving the episode can't drop it.
COVER_MAX = 2 * 1024 * 1024  # the page uploads a square of at most 1000 px, well under this


def image_type(data):
    """File extension for a PNG, JPEG or WebP image, judged by its first bytes; None for anything else."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def cover_name(run):
    """The uploaded cover's file name, with a version so browsers fetch a replaced one; None if there is none."""
    f = next(iter(sorted(run.glob("cover.*"))), None)
    return f"{f.name}?v={f.stat().st_mtime_ns}" if f else None


@app.put("/api/episodes/{eid}/cover")
async def set_cover(eid: str, request: Request):
    run = episode_dir(eid)
    data = b""
    async for chunk in request.stream():
        data += chunk
        if len(data) > COVER_MAX:
            raise HTTPException(413, "the image is over 2 MB")
    ext = image_type(data)
    if not ext:
        raise HTTPException(400, "use a PNG, JPEG or WebP image")
    for f in run.glob("cover.*"):
        f.unlink()
    (run / f"cover.{ext}").write_bytes(data)
    return {"cover": cover_name(run)}


@app.delete("/api/episodes/{eid}/cover")
def drop_cover(eid: str):
    for f in episode_dir(eid).glob("cover.*"):
        f.unlink()
    return {"cover": None}


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
    """A new episode, planned at once (or made whole with auto). An uploaded document comes as
    {"name": file name, "data": base64 of its bytes}, so a file with nothing to read is refused before any folder
    is made."""
    doc = req.get("document")
    try:
        if doc and len(doc.get("data", "")) > document.MAX_BYTES * 4 // 3 + 4:
            raise ValueError(f"the document is over {document.MAX_BYTES // 2**20} MB")
        ep = new_episode(req.get("topic", ""), req.get("description", ""), req.get("lang", "en"),
                         int(req.get("speakers", 2)), float(req.get("minutes", 12)), req.get("code_mix", "medium"), out=RUNS,
                         document=(str(doc["name"]), base64.b64decode(doc["data"], validate=True)) if doc else None,
                         doc_web=bool(req.get("doc_web")))
    except (ValueError, TypeError, KeyError, binascii.Error) as e:
        raise HTTPException(400, str(e))
    if req.get("auto"):
        start(ep["id"], "making the whole episode", run_all)
    else:
        start(ep["id"], "planning", producer.produce)
    return {"id": ep["id"]}


def run_all(ep):
    s = settings.load()
    pipeline.run_all(ep, s["research_steps"], s["review_rounds"], s["web_search"])


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
    s = settings.load()
    return start(eid, "researching", lambda ep: researcher.research(ep, s["research_steps"], s["web_search"]))


@app.post("/api/episodes/{eid}/write")
def write(eid: str, body: dict = Body(default={})):
    only_missing = bool(body.get("only_missing"))
    rounds = settings.load()["review_rounds"]
    return start(eid, "writing the script", lambda ep: pipeline.write_all(ep, rounds, only_missing=only_missing))


@app.post("/api/episodes/{eid}/continue")
def continue_all(eid: str):
    return start(eid, "running the remaining steps", run_all)


@app.post("/api/episodes/{eid}/segments/{i}/{action}")
def segment_action(eid: str, i: int, action: str, body: dict = Body(default={})):
    segment_index(load(episode_dir(eid)), i)
    note = (body.get("note") or "").strip() or None
    rounds = settings.load()["review_rounds"]
    if action == "rewrite":
        fn = lambda ep: (writer.write_segment(ep, i, rounds, note=note), update_stats(ep))  # noqa: E731
    elif action == "fix":
        fn = lambda ep: (writer.write_segment(ep, i, rounds, note=note, from_current=True), update_stats(ep))  # noqa: E731
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
    return start(eid, "generating audio", lambda ep: tts.synthesize(ep, voices, settings.load()["speed"]))


@app.post("/api/episodes/{eid}/audio/{i}/{k}")
def retake(eid: str, i: int, k: int):
    return start(eid, f"new take of line {k + 1}", lambda ep: tts.new_take(ep, i, k, settings.load()["speed"]))


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
