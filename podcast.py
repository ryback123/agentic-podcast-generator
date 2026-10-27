"""Agentic podcast script generator.

  producer   plans cast + segments + research questions
  researcher tool loop (search / read / done) that builds a sourced fact sheet
  writer     writes each segment;  critics (code checks, fact-checker, editor) send it back until clean

  python podcast.py --topic "How UPI payments work" --lang hi --description "for class 8 students"

Each stage is a function on an episode dict that is saved to <run dir>/episode.json after every
step, so the web app (app.py) can run stages one at a time and show progress while they run.
Every model call goes through llm.py (env LLM_BASE_URL / LLM_MODEL / LLM_API_KEY).
"""
import argparse
import json
import os
import random
import re
import secrets
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import llm
from checks import BANNED_OPENERS, LANGS, TAGS, check_segment, chars_per_min, label, parse_turns
import search

REPO = Path(__file__).resolve().parent
RUNS = Path(os.environ.get("PODCAST_RUNS") or Path.home() / "podcast_runs")  # empty counts as unset

CODE_MIX = {
    "light": "Mostly {lang}; English only for technical terms that people normally say in English.",
    "medium": "Natural everyday code-mixing: {lang} sentences with common English words and short phrases, "
              "the way urban {lang} speakers talk.",
    "heavy": "Heavy code-mixing: many English words and phrases inside {lang} sentences, switching freely.",
}
FORMATS = [
    "two friends chatting; one knows the topic well, the other is curious",
    "a host interviewing an expert guest",
    "co-hosts exploring the topic together, sometimes disagreeing",
    "myth-busting: each main segment tests a common belief",
    "story-led: each main segment opens with a real example or case",
    "a panel with different viewpoints",
]
HOOKS = ["a surprising fact", "a short story or scene", "a question listeners have probably wondered about",
         "a common misconception", "a relatable everyday situation"]

# ---------------------------------------------------------------- prompts
PRODUCER = """You are the producer of an audio podcast. Plan one episode.

Topic: {topic}
Notes from the requester: {notes}
Language: {lang}. {lang_rule}
Number of speakers: exactly {n}
Target length: {minutes} minutes

Plan:
- Cast: exactly {n} speakers. For each: a first name common among {lang} speakers, written in Latin letters only (it is the speaker label); gender (female or male; mix genders); a role (for example host, co-host, expert, guest, skeptic); what they know about the topic; how they talk (tone and rhythm only; do not give catchphrases or example words, they get overused). Give the cast useful contrast: someone who explains and someone who asks what the listener would ask{extra_role}. Match the audience level in the requester's notes; with no level given, aim at curious adults with no background.
- Format for this episode: {fmt}. Opening hook: {hook}.
- Exactly {k} segments whose minutes add up to {minutes}: an opening (hook, then the speakers introduce themselves; about 1 minute), {main} main segments, and a closing (recap and one memorable takeaway; about 1 minute). Each main segment has one clear goal and builds on the one before.
- For each main segment, one to three research questions whose answers (facts, numbers, real examples, stories) would make the segment concrete and correct. The opening and closing have no questions.

Write the plan in English, except the title, which is in {lang} ({script} script).
Reply with only this JSON:
{{"title": str, "audience": str, "format": str,
 "speakers": [{{"name": str, "gender": "female" | "male", "role": str, "knowledge": str, "style": str}}],
 "segments": [{{"title": str, "goal": str, "minutes": number, "questions": [str]}}]}}"""

RESEARCHER = """You are the research agent for the podcast episode "{title}" (audience: {audience}).
Find facts that answer the research questions. Facts are saved only from pages you read; do not rely on memory.

Research questions and facts found so far:
{coverage}

Your recent actions:
{history}

Tools:
- search {{"query": str, "source": {sources}, "lang": str}}: {search_note}
- read {{"ids": [str]}}: reads up to three search results by id (like "r3"); facts relevant to the questions are extracted and saved.
- done {{"reason": str}}: stops research. Use it when every question has at least two facts, or when more searching is not helping.

How to research well:
- One search targets one question. Keep queries short: at most 8 words for the web, 2-4 words for Wikipedia.
- After a search, read the one to three most promising results before searching again.
- If two searches for a question find nothing useful, move on to other questions; some questions can stay thin.

Step {step} of {max_steps}.
Reply with only JSON: {{"thought": "<one sentence>", "tool": "search" | "read" | "done", "args": {{...}}}}"""

NOTES = """Extract facts from this page that help answer the research questions.

Research questions:
{questions}

Page: {title}
---
{text}
---
Each fact is one self-contained English sentence that keeps numbers, names, and dates exactly as on the page. Use only what the page says. Skip anything that does not help answer a question. At most 8 facts.
Reply with only JSON: {{"facts": [{{"q": "Q1", "fact": str}}]}}"""

CONTEXT = """Episode: "{title}". Format: {format}. Audience: {audience}.
Cast:
{cast}

Outline:
{outline}

This segment: "{seg_title}". Goal: {goal}
Length: about {chars} characters of dialogue (about {minutes} minutes spoken), roughly {t_lo}-{t_hi} turns.
{position}

Facts to use (use what fits; never mention fact ids or sources):
{facts}
Do not state any fact, number, name, or date that is not in this list or common knowledge.
{prev}
Language: {lang}. {lang_rule}
Rules:
- Write every number, date, unit, and symbol as spoken words (no digits, %, /, & and so on). Apostrophes and ordinary punctuation are fine; in English use contractions (it's, don't, you're).
- No markdown, stage directions, sound effects, or emojis.
- Short turns: one to three sentences, sometimes just a quick reaction. Vary turn lengths.
- Speakers react to what was just said, ask follow-up questions, sometimes interrupt or disagree, and use concrete examples and analogies that suit the audience.
- Do not start turns with stock phrases ({banned}) and do not reuse the same reaction within the episode.
- Speakers never say their own name, except when introducing themselves in the opening.
- Whenever a speaker's name is said, write it in Latin letters with normal capitalisation (Riya, not RIYA), even inside {lang} sentences.
- Use the right grammatical gender for each speaker (see the cast).
- Make it sound live. Now and then a listener reacts with a word or two while the other is still talking (like "hmm" or "right", in {lang} or English as people really say it). Write it as its own line straight after the line it reacts to: NAME (backchannel): text. Two to four per segment, varied, never by the speaker of the line they react to.
- Once or twice per segment, someone cuts in before the other finishes. End the interrupted line mid-sentence with a dash (—), then tag the next line NAME (cuts in): text for a sharp interruption (disagreement, alarm), or NAME (talks over): text when the first speaker trails off underneath (eager agreement, finishing their thought). Use both kinds.{note}"""

WRITER = """You are writing one segment of a podcast episode as spoken dialogue, not an essay.

{ctx}

Output only dialogue lines, one turn per line, as NAME: text (or NAME (tag): text for the tags above), using only these names: {names}."""

REVISE = """You are revising one segment of a podcast episode.

{ctx}

Current draft:
{draft}

Reviewers found these problems:
{issues}

Rewrite the segment so every problem is fixed; keep what works. Output the full revised segment only, one turn per line, as NAME: text (or NAME (tag): text for the tags above), using only these names: {names}."""

FACTCHECK = """You are a strict fact-checker for one segment of a podcast for {audience}.
Check every factual claim in the segment (numbers, dates, names, how things work, causes and effects) against the facts list. Opinions, questions, and everyday common knowledge are fine.

Facts:
{facts}

Segment:
{numbered}

Report each claim that contradicts the facts, and each specific fact (a number, date, name, or technical detail) that the facts list does not support.
Severity: "major" if a listener would be misinformed (wrong or invented fact); "minor" for wording that is loose but not wrong.
Reply with only JSON: {{"issues": [{{"line": int, "severity": "major" | "minor", "claim": str, "problem": str, "fix": str}}]}} (an empty list if everything is supported)."""

EDITOR = """You are the story editor of a podcast for {audience}. This is {role}. Review it and report only concrete problems of these kinds:
1. Level: too advanced or too childish for the audience, or jargon left unexplained.
2. Speech: lines that sound written rather than spoken, lecture-like monologues, or unnatural language. Target language: {lang}. {lang_rule}
3. Characters: a speaker acting outside their role or knowledge. Cast:
{cast}
4. Flow: the segment misses its goal ("{goal}"), repeats earlier segments (including ending the same way they did), or does not follow from the previous segment.
Fixed rules the script must keep (never suggest breaking them): numbers and symbols written as words; no stock openers like {banned}; short turns; lines tagged (backchannel), (cuts in) or (talks over) are deliberate overlaps, and a line cut off mid-sentence before a cut-in is deliberate.

Earlier segments covered:
{covered}

Segment:
{numbered}

Severity: "major" if a typical listener would notice it and it hurts the episode; "minor" for polish. Do not report taste-level rewording as major.
Reply with only JSON: {{"issues": [{{"line": int, "severity": "major" | "minor", "problem": str, "fix": str}}]}} with at most five issues, most important first; an empty list if the segment works."""


# ---------------------------------------------------------------- episode state
def save(ep):
    path = Path(ep["dir"]) / "episode.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ep, ensure_ascii=False, indent=1))
    os.replace(tmp, path)  # atomic, so the web app never reads a half-written file


def load(run_dir):
    ep = json.loads((Path(run_dir) / "episode.json").read_text())
    ep["dir"] = str(Path(run_dir).resolve())  # saves go where it was loaded from, even if the folder was copied or moved
    for seg in (ep.get("plan") or {}).get("segments", []):  # lines are [speaker, text, mode]; older episodes lack mode
        seg["turns"] = [list(t) + [""] * (3 - len(t)) for t in seg.get("turns") or []]
    return ep


def new_episode(topic, description="", lang="en", speakers=2, minutes=12, code_mix="medium", seed=None, out=RUNS):
    if lang not in LANGS or code_mix not in CODE_MIX:
        raise ValueError(f"unsupported language {lang!r} or code-mix {code_mix!r}")
    if not topic.strip() or not 2 <= speakers <= 5 or not 2 <= minutes <= 30:
        raise ValueError("need a topic, 2-5 speakers and 2-30 minutes")
    seed = seed if seed is not None else random.randrange(10**6)
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:40] or "episode"
    run = Path(out) / f"{time.strftime('%Y%m%d_%H%M%S')}_{lang}_{slug}_{secrets.token_hex(2)}"
    run.mkdir(parents=True)
    git = lambda *c: subprocess.run(["git", "-C", str(REPO), *c], capture_output=True, text=True).stdout.strip()  # noqa: E731
    ep = {"id": run.name, "dir": str(run), "created": time.time(),
          "request": {"topic": topic.strip(), "description": description.strip(), "lang": lang, "speakers": speakers,
                      "minutes": minutes, "code_mix": code_mix, "seed": seed},
          "provenance": {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain")),
                         "model": llm.MODEL, "base_url": str(llm._client.base_url)},
          "plan": None, "questions": {}, "facts": [], "log": []}
    save(ep)
    return ep


def log(ep, agent, event, **info):
    ep["log"].append({"t": round(time.time(), 1), "agent": agent, "event": event, **info})
    print(f"[{time.strftime('%H:%M:%S')}] {ep['id'][:32]} {agent}: {event[:150]}", flush=True)
    save(ep)


def ask(ep, prompt, agent, json_reply=False, **kw):
    fn = llm.chat_json if json_reply else llm.chat
    return fn(prompt, agent, log=Path(ep["dir"]) / "calls.jsonl", **kw)


# ---------------------------------------------------------------- helpers
def lang_rule(ep):
    lang, code_mix = ep["request"]["lang"], ep["request"]["code_mix"]
    name, script, _ = LANGS[lang]
    if lang == "en":
        return "Natural spoken English, the way Indian podcast hosts talk."
    return CODE_MIX[code_mix].format(lang=name) + f" Write {name} words in {script} script and English words in Latin script."


def cast_text(plan):
    return "\n".join(f"- {s['name']} ({s.get('gender', '?')}, {s['role']}): knows {s['knowledge']}; talks {s['style']}"
                     for s in plan["speakers"])


def fact_lines(facts):
    return "\n".join(f"{f['id']}: {f['fact']}" for f in facts) or "(none)"


def numbered(turns):
    return "\n".join(f"{k}. {label(sp, mode)}: {tx}" for k, (sp, tx, mode) in enumerate(turns, 1))


def turns_text(turns):
    return "\n".join(f"{label(sp, mode)}: {tx}" for sp, tx, mode in turns)


# ---------------------------------------------------------------- producer
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
                             script=LANGS[r["lang"]][1], lang_rule=lang_rule(ep), n=n, minutes=minutes, fmt=fmt,
                             hook=hook, k=main + 2, main=main,
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


def set_plan(ep, plan):
    """User edit of cast/outline. Renamed speakers are renamed in the script too (matched by position)."""
    if err := check_plan(plan):
        raise ValueError(err)
    old = [s["name"] for s in ep["plan"]["speakers"]]
    new = [s["name"].upper() for s in plan["speakers"]]
    written = any(s.get("turns") for s in plan["segments"])
    if written and len(old) != len(new):
        raise ValueError("the script is already written: keep the same number of speakers (rename them instead)")
    rename = {o: n for o, n in zip(old, new) if o != n}
    said = renamer(rename)
    for s, name in zip(plan["speakers"], new):
        s["name"] = name
    for seg in plan["segments"]:
        seg["minutes"] = float(seg["minutes"])
        seg["goal"] = said(seg.get("goal") or "")
        seg["turns"] = [[rename.get(sp, sp), said(tx), *rest] for sp, tx, *rest in seg.get("turns") or []]
    if rename and (a := ep.get("audio")):  # chosen voices and re-rolled takes follow the speaker
        a["voices"] = {rename.get(sp, sp): v for sp, v in a.get("voices", {}).items()}
        a["takes"] = {f"{rename.get(sp, sp)}|{said(tx)}": n
                      for sp, tx, n in ((*k.split("|", 1), n) for k, n in a.get("takes", {}).items())}
    plan.setdefault("hook", ep["plan"].get("hook", "a surprising fact"))
    assign_questions(ep, plan)
    ep["plan"] = plan
    log(ep, "user", "edited the plan" + (f", renamed {', '.join(f'{o} to {n}' for o, n in rename.items())}" if rename else ""))
    if written:
        finish(ep)  # script files and speaker shares use the new names


def renamer(rename):
    """Function that swaps old speaker names for new ones where the lines say them ("I'm Riya", "मैं हूँ Riya").
    ponytail: Latin-letter mentions only (the writer is told to write names that way); scripts written before that
    rule may still have native-script spellings, and a name that is also a capitalised word ("Will") gets swapped too."""
    pairs = {}
    for o, n in rename.items():
        pairs.update({o: n, o.capitalize(): n.capitalize()})
    if not pairs:
        return lambda text: text
    rx = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(map(re.escape, pairs), key=len, reverse=True)) + r")(?![A-Za-z])")
    return lambda text: rx.sub(lambda m: pairs[m.group(1)], text)


# ---------------------------------------------------------------- researcher
def take_notes(ep, hit):
    try:
        text = search.read_page(hit)
    except (OSError, ValueError, KeyError) as e:  # tool errors are reported back to the agent
        return [], f"could not read: {e}"
    if len(text.strip()) < 80:
        return [], "page has no readable text"
    qs = "\n".join(f"{q}: {t}" for q, t in ep["questions"].items())
    try:
        out = ask(ep, NOTES.format(questions=qs, title=hit["title"], text=text), "notes", json_reply=True, temperature=0.2)
    except ValueError:  # reply was not JSON twice; the raw replies are in calls.jsonl
        return [], "could not extract facts from this page"
    facts = []
    for f in out.get("facts", []):
        qid = str(f.get("q", "")).strip()
        qid = qid if qid.startswith("Q") else f"Q{qid}"
        if qid in ep["questions"] and f.get("fact"):
            facts.append({"q": qid, "fact": f["fact"], "source": hit["title"], "url": hit["url"]})
    return facts, None


def research(ep, max_steps=20):
    """Tool loop: the agent picks search / read / done until questions are covered. Starts a fresh fact sheet."""
    plan, qs = ep["plan"], ep["questions"]
    ep["facts"] = []
    name, _, wiki = LANGS[ep["request"]["lang"]]
    lang_note = (f'lang is "en" or "{wiki}" ({name} Wikipedia); English usually has more detail.'
                 if wiki != "en" else 'lang must be "en".')
    wiki_note = f"Wikipedia queries are 2-4 words (a topic name, not a question); {lang_note}"
    if search.TAVILY_KEY:
        sources = '"web" | "wikipedia"'
        search_note = ('source "web" searches the whole web: best for news, statistics, recent or local topics; '
                       f'queries can be a short phrase. Source "wikipedia" is best for background. {wiki_note}')
    else:
        sources, search_note = '"wikipedia"', f"searches Wikipedia (web search is not configured). {wiki_note}"
    results, read, history, searched = {}, set(), [], set()
    credits = 0  # Tavily credits used
    for step in range(1, max_steps + 1):
        cov = {q: sum(f["q"] == q for f in ep["facts"]) for q in qs}
        if all(c >= 2 for c in cov.values()):
            ep["research_stats"] = {"steps": step - 1, "credits": credits}
            log(ep, "researcher", f"stop: every question has 2+ facts ({credits} search credits)")
            return
        prompt = RESEARCHER.format(
            title=plan["title"], audience=plan["audience"], lang_note=lang_note, step=step, max_steps=max_steps,
            sources=sources, search_note=search_note,
            coverage="\n".join(f"{q} [{cov[q]} facts] {t}" for q, t in qs.items()),
            history="\n".join(history[-8:]) or "none yet")
        act = ask(ep, prompt, "researcher", json_reply=True, temperature=0.3, max_tokens=500)
        tool, args = act.get("tool"), act.get("args") or {}
        if tool == "done":
            ep["research_stats"] = {"steps": step, "credits": credits}
            log(ep, "researcher", f"done: {args.get('reason', '')} ({credits} search credits)", thought=act.get("thought"))
            return
        source = args.get("source") or ("web" if search.TAVILY_KEY else "wikipedia")
        key = (args.get("query", "").lower().strip(), source, args.get("lang", "en"))
        n_words = len(args.get("query", "").split())
        if tool == "search" and n_words > 10:  # long multi-question queries return poor results and waste credits
            obs = f"query too long ({n_words} words): search for one question in at most 8 words"
        elif tool == "search" and key in searched:
            obs = "already searched; read one of the results above or try a different query"
        elif tool == "search" and source == "web" and not search.TAVILY_KEY:
            obs = 'web search is not configured; use source "wikipedia"'
        elif tool == "search":
            searched.add(key)
            try:
                if source == "web":
                    credits += 1
                    hits = search.web_search(args.get("query", ""))
                else:
                    hits = search.wiki_search(args.get("query", ""), args.get("lang", "en"))
                lines = []
                for h in hits:
                    rid = f"r{len(results) + 1}"
                    results[rid] = h
                    lines.append(f"   [{rid}] {h['title']}: {h['snippet'][:160]}")
                obs = f"{len(hits)} results\n" + "\n".join(lines) if hits else "no results"
            except (OSError, ValueError, KeyError) as e:
                obs = f"search failed: {e}"
        elif tool == "read":
            ids = args.get("ids") or [args.get("id")]
            ids = [i for i in ids if i in results and results[i]["id"] not in read][:3]
            if not ids:
                obs = "nothing to read: unknown or already-read ids"
            else:
                credits += sum(1 for i in ids if results[i]["id"].startswith("http") and not results[i].get("text"))
                with ThreadPoolExecutor(len(ids)) as ex:
                    outs = list(ex.map(lambda i: take_notes(ep, results[i]), ids))
                parts = []
                for i, (facts, err) in zip(ids, outs):
                    if not err:  # failed reads stay retryable
                        read.add(results[i]["id"])
                    for f in facts:
                        f["id"] = f"F{len(ep['facts']) + 1}"
                        ep["facts"].append(f)
                    got = sorted({f["q"] for f in facts})
                    parts.append(f"[{i}] {results[i]['title']}: " +
                                 (err or (f"added {len(facts)} facts ({', '.join(got)})" if facts else "nothing relevant")))
                obs = "; ".join(parts)
        else:
            obs = f"unknown tool {tool!r}; use search, read, or done"
        history.append(f"{step}. {tool} {json.dumps(args, ensure_ascii=False)} -> {obs}")
        log(ep, "researcher", f"{tool} {json.dumps(args, ensure_ascii=False)}", thought=act.get("thought"), result=obs)
    ep["research_stats"] = {"steps": max_steps, "credits": credits}
    log(ep, "researcher", f"stop: step budget used ({credits} search credits)")


# ---------------------------------------------------------------- writer + critics
def segment_context(ep, i, note=None):
    plan, segs = ep["plan"], ep["plan"]["segments"]
    seg, lang = segs[i], ep["request"]["lang"]
    chars = int(float(seg["minutes"]) * chars_per_min(lang))
    outline = "\n".join(f"{k + 1}. {s['title']}: {s.get('goal', '')}" +
                        (" (done)" if k < i else "  <- THIS SEGMENT" if k == i else " (later)")
                        for k, s in enumerate(segs))
    if i == 0:
        position = (f"This is the opening. Start with the hook ({plan.get('hook', 'a surprising fact')}), then the "
                    "speakers introduce themselves naturally and say what the episode will cover.")
        facts = [next(f for f in ep["facts"] if f["q"] == q) for q in ep["questions"]
                 if any(f["q"] == q for f in ep["facts"])][:6]
    elif i == len(segs) - 1:
        position = ("This is the closing. Recap the main ideas in a fresh way (do not list them), "
                    "give one memorable takeaway, and sign off.")
        facts = []
    else:
        position = "Continue directly from the previous segment: no greetings, no re-introductions, no summary at the end."
        facts = [f for f in ep["facts"] if f["q"] in seg.get("qids", [])]
    prev = segs[i - 1].get("turns", [])[-6:] if i else []
    prev = f"\nLast lines of the previous segment:\n{turns_text(prev)}\n" if prev else ""
    ctx = CONTEXT.format(title=plan["title"], format=plan.get("format", ""), audience=plan["audience"],
                         cast=cast_text(plan), outline=outline, seg_title=seg["title"], goal=seg.get("goal", ""),
                         chars=chars, minutes=seg["minutes"], t_lo=max(4, int(chars / 160)), t_hi=max(6, int(chars / 80)),
                         position=position, facts=fact_lines(facts), prev=prev, lang=LANGS[lang][0],
                         lang_rule=lang_rule(ep), banned=", ".join(f'"{b}"' for b in BANNED_OPENERS),
                         note=f"\n\nThe producer's note for this segment (follow it): {note}" if note else "")
    return ctx, chars


def quick_check(ep, i, turns, bad=()):
    """Deterministic checks only (no model calls)."""
    segs, r = ep["plan"]["segments"], ep["request"]
    budget = int(float(segs[i]["minutes"]) * chars_per_min(r["lang"]))
    history = [tuple(t) for s in segs[:i] for t in s.get("turns", [])]
    return check_segment([tuple(t) for t in turns], list(bad), r["lang"], r["code_mix"], budget, history)


def review(ep, i, text):
    """All critics on one segment's text -> (turns, major issues)."""
    plan, segs, r = ep["plan"], ep["plan"]["segments"], ep["request"]
    turns, bad = parse_turns(text, [s["name"] for s in plan["speakers"]])
    issues = quick_check(ep, i, turns, bad)
    if not turns:
        return turns, issues
    num = numbered(turns)
    fc = FACTCHECK.format(audience=plan["audience"], facts=fact_lines(ep["facts"]), numbered=num)
    role = ("the opening segment" if i == 0 else "the closing segment, which ends the episode" if i == len(segs) - 1
            else f"main segment {i} of {len(segs) - 2}")
    ed = EDITOR.format(audience=plan["audience"], role=role, lang=LANGS[r["lang"]][0], lang_rule=lang_rule(ep),
                       cast=cast_text(plan), goal=segs[i].get("goal", ""), numbered=num,
                       banned=", ".join(f'"{b}"' for b in BANNED_OPENERS[:6]),
                       covered="\n".join(f"- {s['title']}: {s.get('goal', '')} (ended with: "
                                         f"{s['turns'][-1][1] if s.get('turns') else '-'})" for s in segs[:i]) or "(none)")
    with ThreadPoolExecutor(2) as ex:
        jobs = [ex.submit(ask, ep, p, f"{who}:{i + 1}", True, temperature=0.2) for who, p in (("factcheck", fc), ("editor", ed))]
        for who, job in zip(("fact-check", "editor"), jobs):
            for x in job.result().get("issues") or []:
                if x.get("severity") != "major":  # minor issues stay in calls.jsonl but do not trigger a rewrite
                    continue
                issues.append(f"Line {x.get('line', '?')} ({who}): {x.get('problem', '')} Fix: {x.get('fix', '')}")
    return turns, issues


def write_segment(ep, i, max_revisions=2, note=None, from_current=False):
    """Draft (or, with from_current, start from the current turns), then critics <-> revisions."""
    seg = ep["plan"]["segments"][i]
    names = ", ".join(s["name"] for s in ep["plan"]["speakers"])
    ctx, _ = segment_context(ep, i, note)
    if from_current and seg.get("turns"):
        text = turns_text(seg["turns"])
    else:
        log(ep, "writer", f"writing segment {i + 1}: {seg['title']}" + (f" (note: {note})" if note else ""))
        text = ask(ep, WRITER.format(ctx=ctx, names=names), f"writer:{i + 1}", temperature=0.8)
    for rnd in range(max_revisions + 1):
        turns, issues = review(ep, i, text)
        seg["turns"], seg["open_issues"] = [list(t) for t in turns], issues
        log(ep, "critics", f"segment {i + 1} round {rnd}: {len(issues)} issues", issues=issues)
        if not issues or rnd == max_revisions:
            break
        text = ask(ep, REVISE.format(ctx=ctx, draft=text, issues="\n".join(f"- {x}" for x in issues), names=names),
                   f"writer:{i + 1}:rev{rnd + 1}", temperature=0.6)


def review_segment(ep, i):
    seg = ep["plan"]["segments"][i]
    _, seg["open_issues"] = review(ep, i, turns_text(seg.get("turns", [])))
    log(ep, "critics", f"segment {i + 1} reviewed: {len(seg['open_issues'])} issues", issues=seg["open_issues"])


def set_turns(ep, i, turns):
    """User edit of one segment's lines; returns the deterministic-check issues."""
    names = {s["name"] for s in ep["plan"]["speakers"]}
    clean = [[t[0], " ".join(str(t[1]).split()), t[2] if len(t) > 2 else ""] for t in turns if str(t[1]).strip()]
    if bad := {sp for sp, _, _ in clean} - names:
        raise ValueError(f"unknown speakers {sorted(bad)}")
    if bad := {m for *_, m in clean} - {"", *TAGS}:
        raise ValueError(f"unknown line modes {sorted(bad)}")
    seg = ep["plan"]["segments"][i]
    seg["turns"], seg["open_issues"] = clean, quick_check(ep, i, clean)
    log(ep, "user", f"edited segment {i + 1}: {len(clean)} lines")
    finish(ep)


def write_all(ep, max_revisions=2, only_missing=False):
    for i, seg in enumerate(ep["plan"]["segments"]):
        if not (only_missing and seg.get("turns")):
            write_segment(ep, i, max_revisions)
    finish(ep)


# ---------------------------------------------------------------- output
def finish(ep):
    """Write script.json (for TTS) and script.txt, and refresh stats."""
    plan, lang, run = ep["plan"], ep["request"]["lang"], Path(ep["dir"])
    turns = [{"speaker": sp, "text": tx, **({"mode": mode} if mode else {})}
             for s in plan["segments"] for sp, tx, mode in s.get("turns", [])]
    chars = sum(len(t["text"]) for t in turns) or 1
    calls = run / "calls.jsonl"
    ep["stats"] = {"turns": len(turns), "chars": chars, "est_minutes": round(chars / chars_per_min(lang), 1),
                   "speaker_share": {s["name"]: round(sum(len(t["text"]) for t in turns if t["speaker"] == s["name"])
                                                      / chars, 2) for s in plan["speakers"]},
                   "facts": len(ep["facts"]), "open_issues": sum(len(s.get("open_issues", [])) for s in plan["segments"]),
                   "llm_calls": sum(1 for _ in open(calls)) if calls.exists() else 0}
    sources = sorted({(f["source"], f["url"]) for f in ep["facts"]})
    (run / "script.json").write_text(json.dumps({
        "title": plan["title"], "language": lang, "speakers": plan["speakers"], "turns": turns,
        "sources": [{"title": t, "url": u} for t, u in sources]}, ensure_ascii=False, indent=1))
    lines = [plan["title"], cast_text(plan), ""]
    for k, s in enumerate(plan["segments"], 1):
        lines += [f"## {k}. {s['title']}"] + [f"{label(sp, mode)}: {tx}" for sp, tx, mode in s.get("turns", [])] + [""]
    (run / "script.txt").write_text("\n".join(lines))
    log(ep, "done", f"script ready: {ep['stats']['turns']} lines, ~{ep['stats']['est_minutes']} min, "
                    f"{ep['stats']['open_issues']} open issues")


def run_all(ep, max_research_steps=20, max_revisions=2):
    """Everything still missing: plan -> research -> unwritten segments -> script files."""
    if not ep["plan"]:
        produce(ep)
    if not ep["facts"]:
        research(ep, max_research_steps)
    write_all(ep, max_revisions, only_missing=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic", required=True)
    ap.add_argument("--description", default="", help="free text: audience level, tone, angle")
    ap.add_argument("--lang", default="en", choices=LANGS)
    ap.add_argument("--speakers", type=int, default=2)
    ap.add_argument("--minutes", type=float, default=12)
    ap.add_argument("--code-mix", default="medium", choices=CODE_MIX)
    ap.add_argument("--max-research-steps", type=int, default=20)
    ap.add_argument("--max-revisions", type=int, default=2)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--out", type=Path, default=RUNS)
    a = ap.parse_args()
    ep = new_episode(a.topic, a.description, a.lang, a.speakers, a.minutes, a.code_mix, a.seed, a.out)
    print(f"run dir: {ep['dir']}", flush=True)
    run_all(ep, a.max_research_steps, a.max_revisions)


if __name__ == "__main__":
    main()
