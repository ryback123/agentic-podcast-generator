"""One episode: the episode.json that every step reads and saves, and the format of script lines.

Each episode has its own folder, config.RUNS/<id>/:
  episode.json   the whole episode (below), saved after every step
  calls.jsonl    every prompt sent to the model, and its reply
  audio/         one clip per line, plus episode.wav and episode.mp3 (audio/tts.py)

episode.json:
  id, created
  request         what was asked for: topic, description, lang, speakers, minutes, code_mix, seed; for an episode
                  made from an uploaded document also document {file (document.pdf etc. in this folder), name,
                  pages (PDF), chars} and doc_web (search the web for what it leaves open)
  digest          a long document's summary per part, made once by the producer [[label, summary]]
  provenance      code commit and model used
  plan            by the producer, editable by the user: title, audience, format, hook,
                  speakers [{name, gender, role, knowledge, style}] (style is the persona: who they are and
                  how they speak, a few sentences),
                  segments [{title, goal, minutes, questions, qids, turns, open_issues}]
  plans_made      how many plans were made (varies the producer's random choices)
  questions       research questions by id, {"Q1": text}
  facts           [{id, q, fact, source, url}] from the researcher
  research_stats  research steps and search credits used
  stats           script length, speaker shares, open issues (update_stats)
  audio           voices {speaker: voice}, takes {"SPEAKER|text": n}, episode (the mixed file: seconds, speed,
                  chapters [{title, start}], times [[clip file, start, end]] for each line in script order)
  log             what every agent and the user did, in order

A script line ("turn") is [speaker, text, mode]. The mode says how the line starts:
  ""             after the previous line ends
  "backchannel"  a filler ("hmm") in a pause of the line holding the floor, which carries on
  "cut"          cuts in before that line ends, which stops dead
  "fade"         cuts in before that line ends, which fades out underneath
"""
import json
import os
import random
import re
import secrets
import subprocess
import time
from pathlib import Path

from . import llm
from .config import RUNS
from .document import pages
from .languages import CODE_MIX, LANGS, chars_per_min

TAGS = {"backchannel": "backchannel", "cut": "cuts in", "fade": "talks over"}  # mode -> tag in "NAME (tag): text"
CUT_OFF = ("—", "–", "-")  # a line someone cuts into or talks over ends with one of these, mid-sentence
LINE = re.compile(r"^\s*([A-Za-z]+)\s*(?:\(([A-Za-z ]+)\))?\s*:\s*(.+?)\s*$")


# ---------------------------------------------------------------- storage
def new_episode(topic, description="", lang="en", speakers=2, minutes=12, code_mix="medium", seed=None, out=RUNS,
                document=None, doc_web=False):
    """A new episode folder with its request. document: (file name, bytes) of an uploaded document to make the
    episode from (the topic then defaults to its name); doc_web: also search the web for what it leaves open."""
    if lang not in LANGS or code_mix not in CODE_MIX:
        raise ValueError(f"unsupported language {lang!r} or code-mix {code_mix!r}")
    doc_pages = pages(*document) if document else None  # ValueError, for the user, if it has no text to read
    if document and not topic.strip():
        topic = re.sub(r"[_\s]+", " ", Path(document[0]).stem)
    if not topic.strip() or not 2 <= speakers <= 5 or not 2 <= minutes <= 30:
        raise ValueError("need a topic, 2-5 speakers and 2-30 minutes")
    seed = seed if seed is not None else random.randrange(10**6)
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:40] or "episode"
    run = Path(out) / f"{time.strftime('%Y%m%d_%H%M%S')}_{lang}_{slug}_{secrets.token_hex(2)}"
    run.mkdir(parents=True)
    code = Path(__file__).resolve().parent
    git = lambda *c: subprocess.run(["git", "-C", str(code), *c], capture_output=True, text=True).stdout.strip()  # noqa: E731
    ep = {"id": run.name, "dir": str(run), "created": time.time(),
          "request": {"topic": topic.strip(), "description": description.strip(), "lang": lang, "speakers": speakers,
                      "minutes": minutes, "code_mix": code_mix, "seed": seed},
          "provenance": {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain")),
                         "model": llm.MODEL, "base_url": str(llm._client.base_url)},
          "plan": None, "questions": {}, "facts": [], "log": []}
    if document:
        name, data = document
        file = "document" + Path(name).suffix.lower()
        (run / file).write_bytes(data)
        ep["request"]["document"] = {"file": file, "name": Path(name).name,
                                     "pages": doc_pages[-1][0], "chars": sum(len(t) for _, t in doc_pages)}
        ep["request"]["doc_web"] = bool(doc_web)
    save(ep)
    return ep


def load(run_dir):
    ep = json.loads((Path(run_dir) / "episode.json").read_text())
    ep["dir"] = str(Path(run_dir).resolve())  # saves go where it was loaded from, even if the folder was copied or moved
    for seg in (ep.get("plan") or {}).get("segments", []):  # lines are [speaker, text, mode]; older episodes lack mode
        seg["turns"] = [list(t) + [""] * (3 - len(t)) for t in seg.get("turns") or []]
    return ep


def save(ep):
    path = Path(ep["dir"]) / "episode.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ep, ensure_ascii=False, indent=1))
    os.replace(tmp, path)  # atomic, so the web app never reads a half-written file


def log(ep, agent, event, **info):
    ep["log"].append({"t": round(time.time(), 1), "agent": agent, "event": event, **info})
    print(f"[{time.strftime('%H:%M:%S')}] {ep['id'][:32]} {agent}: {event[:150]}", flush=True)
    save(ep)


def ask(ep, prompt, agent, json_reply=False, **kw):
    """One model call, recorded in the episode's calls.jsonl."""
    fn = llm.chat_json if json_reply else llm.chat
    return fn(prompt, agent, log=Path(ep["dir"]) / "calls.jsonl", **kw)


# ---------------------------------------------------------------- script lines as text
def label(sp, mode=""):
    return f"{sp} ({TAGS[mode]})" if mode else sp


def parse_turns(text, names):
    """'NAME: text' or 'NAME (tag): text' lines -> ([(NAME, text, mode)], [lines that are not valid turns])."""
    modes = {tag: mode for mode, tag in TAGS.items()}
    turns, bad = [], []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = LINE.match(line)
        tag = " ".join((m.group(2) or "").lower().split()) if m else ""
        if m and m.group(1).upper() in names and (not tag or tag in modes):
            turns.append((m.group(1).upper(), m.group(3), modes.get(tag, "")))
        else:
            bad.append(line.strip())
    return turns, bad


def turns_text(turns):
    return "\n".join(f"{label(sp, mode)}: {tx}" for sp, tx, mode in turns)


def cast_text(plan):
    return "\n".join(f"- {s['name']} ({s.get('gender', '?')}, {s['role']}). Knows: {s['knowledge']}\n  Persona: {s['style']}"
                     for s in plan["speakers"])


# ---------------------------------------------------------------- the finished script
def _turns(plan):
    return [{"speaker": sp, "text": tx, **({"mode": mode} if mode else {})}
            for s in plan["segments"] for sp, tx, mode in s.get("turns", [])]


def update_stats(ep):
    """Refresh the script's stats (length, speaker shares, open issues) after it was written or edited."""
    plan, lang, run = ep["plan"], ep["request"]["lang"], Path(ep["dir"])
    turns = _turns(plan)
    chars = sum(len(t["text"]) for t in turns) or 1
    calls = run / "calls.jsonl"
    ep["stats"] = {"turns": len(turns), "chars": chars, "est_minutes": round(chars / chars_per_min(lang), 1),
                   "speaker_share": {s["name"]: round(sum(len(t["text"]) for t in turns if t["speaker"] == s["name"])
                                                      / chars, 2) for s in plan["speakers"]},
                   "facts": len(ep["facts"]), "open_issues": sum(len(s.get("open_issues", [])) for s in plan["segments"]),
                   "llm_calls": sum(1 for _ in open(calls)) if calls.exists() else 0}
    log(ep, "done", f"script ready: {ep['stats']['turns']} lines, ~{ep['stats']['est_minutes']} min, "
                    f"{ep['stats']['open_issues']} open issues")


def script_text(ep):
    """The script to read or print: title, cast, then each segment's lines."""
    plan = ep["plan"]
    lines = [plan["title"], cast_text(plan), ""]
    for k, s in enumerate(plan["segments"], 1):
        lines += [f"## {k}. {s['title']}"] + [f"{label(sp, mode)}: {tx}" for sp, tx, mode in s.get("turns", [])] + [""]
    return "\n".join(lines)


def script_json(ep):
    """The script for other programs: cast, lines (with their mode when they overlap) and the facts' sources."""
    plan = ep["plan"]
    sources = sorted({(f["source"], f["url"]) for f in ep["facts"]})
    return {"title": plan["title"], "language": ep["request"]["lang"], "speakers": plan["speakers"],
            "turns": _turns(plan), "sources": [{"title": t, "url": u} for t, u in sources]}
