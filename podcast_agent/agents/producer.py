"""Producer agent: plans the episode (cast, format, segments, research questions)."""
import random
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import document
from ..episode import ask, log
from ..languages import LANGS, lang_rule
from .prompts import DIGEST, DOCUMENT, FORMATS, HOOKS, PRODUCER

PLAN_CHARS = 40000  # of document text the producer reads whole (the model takes 32k tokens); longer: part summaries


def check_plan(plan):
    """Problems with a plan's shape (producer output or a user edit), or None."""
    names = [str(s.get("name", "")) for s in plan.get("speakers", [])]
    if len(names) < 2:
        return "needs at least two speakers"
    if not all(re.fullmatch(r"[A-Za-z]+", x) for x in names) or len({x.upper() for x in names}) != len(names):
        return "speaker names must be distinct single first names in Latin letters"
    if any(s.get("gender") not in ("female", "male") for s in plan["speakers"]):
        return "each speaker needs gender female or male"
    segs = plan.get("segments", [])
    if not segs or any(not s.get("title") or float(s.get("minutes") or 0) <= 0 for s in segs):
        return "every segment needs a title and positive minutes"
    return None


def assign_questions(ep, plan):
    """Give research questions stable ids (Q1, Q2, ...); unchanged questions keep their id and facts."""
    old = {t: q for q, t in ep["questions"].items()}
    nxt = max([int(q[1:]) for q in ep["questions"]] or [0])
    ep["questions"] = {}
    for seg in plan["segments"]:
        seg["qids"] = []
        for t in [str(t).strip() for t in seg.get("questions") or [] if str(t).strip()]:
            if t not in old:
                nxt += 1
                old[t] = f"Q{nxt}"
            ep["questions"][old[t]] = t
            seg["qids"].append(old[t])


def document_brief(ep):
    """The uploaded document as the producer sees it: the whole text, or for a long one a summary of each part
    (made once, kept in ep["digest"])."""
    r = ep["request"]
    doc = r["document"]
    doc_pages = document.pages(doc["name"], (Path(ep["dir"]) / doc["file"]).read_bytes())
    text, note = "\n\n".join(f"[p. {n}]\n{t}" if n else t for n, t in doc_pages), ""
    if len(text) > PLAN_CHARS:
        if not ep.get("digest"):
            pieces = document.parts(doc_pages)
            log(ep, "producer", f"summarising the document in {len(pieces)} parts")
            labels = [label or f"part {k} of {len(pieces)}" for k, (label, _) in enumerate(pieces, 1)]
            words = max(40, 6000 // len(pieces))
            with ThreadPoolExecutor(4) as ex:
                sums = ex.map(lambda lt: ask(ep, DIGEST.format(label=lt[0], name=doc["name"], words=words, text=lt[1]),
                                             "digest", temperature=0.2), zip(labels, (t for _, t in pieces)))
                ep["digest"] = [[label, s.strip()] for label, s in zip(labels, sums)]
        text, note = "\n\n".join(f"[{label}] {s}" for label, s in ep["digest"]), ", summarised part by part (it is long)"
    web = ("questions it leaves open are searched on the web" if r.get("doc_web")
           else "facts come from the document only, so ask nothing it does not cover")
    return DOCUMENT.format(name=doc["name"], web=web, note=note, text=text)


def produce(ep):
    """(Re)plan the episode. Starts over: earlier facts and script are dropped."""
    r = ep["request"]
    n, minutes = r["speakers"], r["minutes"]
    ep["plans_made"] = ep.get("plans_made", 0) + 1
    rng = random.Random(f"{r['seed']}-{ep['plans_made']}")
    main = max(2, round((minutes - 2) / 2))
    fmt = rng.choice([f for f in FORMATS if n >= 3 or "panel" not in f])
    hook = rng.choice(HOOKS)
    prompt = PRODUCER.format(topic=r["topic"], notes=r["description"] or "none", lang=LANGS[r["lang"]][0],
                             document=document_brief(ep) if r.get("document") else "",
                             script=LANGS[r["lang"]][1], lang_rule=lang_rule(r["lang"], r["code_mix"]), n=n,
                             minutes=minutes, fmt=fmt, hook=hook, k=main + 2, main=main,
                             extra_role=", and someone who pushes back or brings a different view" if n >= 3 else "")
    for _ in range(3):
        plan = ask(ep, prompt, "producer", json_reply=True, temperature=0.9)
        total = sum(float(s.get("minutes") or 0) for s in plan.get("segments", []))
        err = check_plan(plan) or (len(plan["speakers"]) != n and f"needs exactly {n} speakers") or \
            (len(plan["segments"]) < 3 and "needs an opening, main segments, and a closing") or \
            (abs(total - minutes) > 1.5 and f"segment minutes add up to {total}, not {minutes}")
        if not err:
            break
        log(ep, "producer", f"plan rejected: {err}")
        prompt += f"\n\nYour previous plan was rejected: {err}. Fix that."
    else:
        raise RuntimeError(f"producer could not make a valid plan: {err}")
    for s in plan["speakers"]:
        s["name"] = s["name"].upper()
    plan["hook"] = hook
    ep["questions"], ep["facts"] = {}, []
    assign_questions(ep, plan)
    ep["plan"] = plan
    log(ep, "producer", f"plan: {plan['title']!r}, {len(plan['segments'])} segments, {len(ep['questions'])} research "
                        f"questions, cast {[s['name'] for s in plan['speakers']]}")
