"""Background jobs: each long step runs in a thread, one job per episode at a time. The UI polls the episode,
which the job keeps saving."""
import re
import threading
import traceback

from fastapi import HTTPException

from ..config import RUNS
from ..episode import load, log

jobs = {}  # episode id -> {"task", "running", "error"}
_jobs_lock = threading.Lock()


def episode_dir(eid):
    if not re.fullmatch(r"[\w-]+", eid) or not (RUNS / eid / "episode.json").exists():
        raise HTTPException(404, "no such episode")
    return RUNS / eid


def start(eid, task, fn):
    """Run fn(ep) in a background thread; one job per episode at a time."""
    with _jobs_lock:
        if jobs.get(eid, {}).get("running"):
            raise HTTPException(409, f"busy: {jobs[eid]['task']}")
        jobs[eid] = {"task": task, "running": True, "error": None}
    ep = load(episode_dir(eid))

    def target():
        try:
            fn(ep)
        except Exception as e:  # job boundary: the error is shown in the UI, the traceback goes to the server log
            traceback.print_exc()
            jobs[eid]["error"] = f"{type(e).__name__}: {e}"
            log(ep, "error", f"{task} failed: {type(e).__name__}: {e}")
        finally:
            jobs[eid]["running"] = False

    threading.Thread(target=target, daemon=True).start()
    return {"ok": True, "task": task}


def editable(eid):
    if jobs.get(eid, {}).get("running"):
        raise HTTPException(409, "wait for the running job to finish")
    return load(episode_dir(eid))
