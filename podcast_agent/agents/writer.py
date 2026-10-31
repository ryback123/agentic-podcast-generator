"""Writer agent and its critics. The writer drafts a segment; the code checks (checks.py), a fact-checker and an
editor review it. The fact-checker and editor point at the exact words to change and give replacements, which are
patched in place; only problems that word edits cannot fix send the segment back for a full rewrite. At most
max_revisions rounds of fixes."""
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from ..episode import ask, cast_text, log, parse_turns, turns_text
from ..languages import LANGS, chars_per_min, lang_rule
from .checks import BANNED_OPENERS, LATIN_SHARE, adds_english, english_share, is_structural, segment_issues
from .prompts import CONTEXT, EDITOR, FACTCHECK, REVISE, SAMPLE, WRITER, fact_lines, numbered

# Fillers and interruptions in real two-person conversation (IndicVoices conversations, each speaker on their own
# channel, measured in OverlapForge, a diarization data project): about 5.7 backchannels a minute. About 19% of
# handovers overlap without being a backchannel, half of them only on the last word, which the mixer leaves out
# (audio/mix.py REPLY). That leaves about one handover in ten as a written overlap, and 35-45% of those are
# competitive (a sharp cut-in rather than talking over).
BACKCHANNELS_PER_MIN, OVERLAP_SHARE, CUT_SHARE = 5.7, 0.1, 0.4


def segment_size(ep, seg):
    """(characters, fewest turns, most turns) the segment is written to."""
    chars = int(float(seg["minutes"]) * chars_per_min(ep["request"]["lang"]))
    return chars, max(4, int(chars / 160)), max(6, int(chars / 80))


def overlaps(ep):
    """The overlaps to write in each segment, [[(speaker, "cuts in" | "talks over")]]: OVERLAP_SHARE of the expected
    handovers, CUT_SHARE of them cut-ins, spread evenly over the episode. Each kind passes from speaker to speaker, so
    no one does most of the interrupting."""
    names = [s["name"] for s in ep["plan"]["speakers"]]
    out, turns, k, cuts = [], 0, 0, 0
    for seg in ep["plan"]["segments"]:
        _, lo, hi = segment_size(ep, seg)
        turns += (lo + hi) / 2
        out.append([])
        while k < int(OVERLAP_SHARE * turns + 0.5):
            if int(CUT_SHARE * (k + 1) + 0.5) > int(CUT_SHARE * k + 0.5):
                out[-1].append((names[(cuts + 1) % len(names)], "cuts in"))
                cuts += 1
            else:
                out[-1].append((names[(k - cuts) % len(names)], "talks over"))
            k += 1
    return out


def overlap_rule(todo):
    if not todo:
        return "In this segment nobody cuts in or talks over: each speaker lets the other finish."
    times = {1: "once", 2: "twice"}
    said = ", ".join(f"{name} {tag} {times.get(n, f'{n} times')}" for (name, tag), n in Counter(todo).items())
    return f"In this segment, where it fits: {said}. No other line cuts in or talks over."


def segment_context(ep, i, note=None):
    plan, segs = ep["plan"], ep["plan"]["segments"]
    seg, lang, code_mix = segs[i], ep["request"]["lang"], ep["request"]["code_mix"]
    chars, t_lo, t_hi = segment_size(ep, seg)
    outline = "\n".join(f"{k + 1}. {s['title']}: {s.get('goal', '')}" +
                        (" (done)" if k < i else "  <- THIS SEGMENT" if k == i else " (later)")
                        for k, s in enumerate(segs))
    if i == 0:
        host = next((s for s in plan["speakers"] if "host" in s["role"].lower()), plan["speakers"][0])
        guests = [s["name"] for s in plan["speakers"] if s is not host]
        others = " and ".join(guests)
        position = (f"This is the opening. {host['name']} speaks first: greets the listeners (hi, hello or namaste, as "
                    f"people say it in {LANGS[lang][0]}), says their own name, introduces {others} and what they know, "
                    f"and names the topic, in one or two lines. Then {others} {'each say' if len(guests) > 1 else 'says'} "
                    f"a short hello of their own. Only after that comes the hook ({plan.get('hook', 'a surprising fact')}), "
                    f"told plainly (not as \"imagine...\" or \"picture this...\" in any language), and then what the "
                    f"episode will cover.")
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
                         chars=chars, minutes=seg["minutes"], t_lo=t_lo, t_hi=t_hi,
                         backchannels=max(1, round(BACKCHANNELS_PER_MIN * float(seg["minutes"]))),
                         overlaps=overlap_rule(overlaps(ep)[i]),
                         position=position, facts=fact_lines(facts), prev=prev, lang=LANGS[lang][0],
                         lang_rule=lang_rule(lang, code_mix), banned=", ".join(f'"{b}"' for b in BANNED_OPENERS),
                         note=f"\n\nThe producer's note for this segment (follow it): {note}" if note else "")
    return ctx, chars


def review(ep, i, turns, bad=()):
    """Run every critic on one segment. Returns (code, critic, edits): the code checks' findings, the fact-checker's and
    editor's major findings (as text), and the word edits they gave, each {"line", "find", "replace", "issue"}. The
    editor is also asked to fix the code checks' word-level findings."""
    plan, segs, r = ep["plan"], ep["plan"]["segments"], ep["request"]
    code = segment_issues(ep, i, turns, bad)
    if not turns:
        return code, [], []
    lang, script = LANGS[r["lang"]][:2]
    banned = ", ".join(f'"{b}"' for b in BANNED_OPENERS[:6])
    words_rule = (f"a stock reaction at the start of a line ({banned}, or the same in {lang})"
                  + (f"; an English word spelled in {script} script instead of Latin letters (the {script} spelling "
                     f"of \"body\" is one of these; the {lang} word for body is not, and stays as it is); no fix may put "
                     f"English in place of {lang} words unless a code check below says there is too little English"
                     if r["lang"] != "en" else "")
                  + "; a misspelled or garbled word, or one with letters from another script")
    num = numbered(turns)
    fc = FACTCHECK.format(audience=plan["audience"], facts=fact_lines(ep["facts"]), numbered=num)
    role = ("the opening segment" if i == 0 else "the closing segment, which ends the episode" if i == len(segs) - 1
            else f"main segment {i} of {len(segs) - 2}")
    ed = EDITOR.format(audience=plan["audience"], role=role, lang=lang, lang_rule=lang_rule(r["lang"], r["code_mix"]),
                       words_rule=words_rule, cast=cast_text(plan), goal=segs[i].get("goal", ""), numbered=num,
                       code="\n".join(f"- {x}" for x in code if not is_structural(x)) or "(none)",
                       covered="\n".join(f"- {s['title']}: {s.get('goal', '')} (ended with: "
                                         f"{s['turns'][-1][1] if s.get('turns') else '-'})" for s in segs[:i]) or "(none)")
    over = r["lang"] != "en" and english_share(turns) > LATIN_SHARE[r["code_mix"]][1]
    critic, edits = [], []
    with ThreadPoolExecutor(2) as ex:
        jobs = [ex.submit(ask, ep, p, f"{who}:{i + 1}", True, temperature=0.2) for who, p in (("factcheck", fc), ("editor", ed))]
        for who, job in zip(("fact-check", "editor"), jobs):
            try:
                found = job.result().get("issues") or []
            except ValueError:  # not JSON twice (both replies are in calls.jsonl); this round goes on without this critic
                critic.append(f"({who}) review skipped: its reply could not be read.")
                continue
            for x in found:
                if x.get("severity") != "major":  # minor issues stay in calls.jsonl
                    continue
                find, repl = " ".join(str(x.get("find") or "").split()), " ".join(str(x.get("replace") or "").split())
                if over and adds_english(find, repl, script):  # the editor often does this even when told the segment is
                    continue  # already over its English share; dropped like a minor issue (still in calls.jsonl)
                critic.append(f"Line {x.get('line', '?')} ({who}): {x.get('problem', '')}"
                              + (f" Fix: {find!r} -> {repl!r}" if find else ""))
                if find:
                    edits.append({"line": x.get("line"), "find": find, "replace": repl, "issue": critic[-1]})
    return code, critic, edits


def needs_rewrite(code, critic):
    """True if word edits cannot fix the segment: its shape is wrong, or a critic found a problem with no words to
    change (usually flow)."""
    return any(is_structural(x) for x in code) or any(x.startswith("Line ") and " Fix: " not in x for x in critic)


def apply_edits(turns, edits):
    """Word fixes: in the edit's line, replace the exact words `find` with `replace`. If the critic miscounted lines,
    the edit still lands when exactly one line has those words. Returns (new turns, edits that could not be applied).
    Lines left empty are dropped."""
    out, failed = [list(t) for t in turns], []
    for e in edits:
        try:
            k = int(e["line"]) - 1
        except (TypeError, ValueError):
            k = -1
        hits = ([k] if 0 <= k < len(out) and e["find"] in out[k][1]
                else [j for j, t in enumerate(out) if e["find"] in t[1]])
        if len(hits) == 1:
            j = hits[0]
            out[j][1] = " ".join(out[j][1].replace(e["find"], e["replace"], 1).split()).lstrip(",;: ")
        elif not (e["replace"] and any(e["replace"] in t[1] for t in out)):  # not already fixed by an earlier edit
            failed.append(e)
    return [t for t in out if t[1].strip(" ,.;:!?—-")], failed


def write_segment(ep, i, max_revisions=2, note=None, from_current=False):
    """Draft (or, with from_current, start from the current turns), then review rounds. After each review the critics'
    word edits are patched in; the writer rewrites the whole segment only for problems word edits cannot fix."""
    seg = ep["plan"]["segments"][i]
    names = [s["name"] for s in ep["plan"]["speakers"]]
    ctx, _ = segment_context(ep, i, note)
    if from_current and seg.get("turns"):
        text = turns_text(seg["turns"])
    else:
        log(ep, "writer", f"writing segment {i + 1}: {seg['title']}" + (f" (note: {note})" if note else ""))
        text = ask(ep, WRITER.format(ctx=ctx, names=", ".join(names)), f"writer:{i + 1}", temperature=0.8)
    turns, bad = parse_turns(text, names)
    for rnd in range(max_revisions + 1):
        code, critic, edits = review(ep, i, turns, bad)
        issues = code + critic
        if needs_rewrite(code, critic) and rnd < max_revisions:
            log(ep, "critics", f"segment {i + 1} round {rnd}: {len(issues)} issues, rewriting the segment", issues=issues)
            text = ask(ep, REVISE.format(ctx=ctx, draft=text, issues="\n".join(f"- {x}" for x in issues),
                                         names=", ".join(names)), f"writer:{i + 1}:rev{rnd + 1}", temperature=0.6)
            turns, bad = parse_turns(text, names)
            continue
        turns, failed = apply_edits(turns, edits)
        text = turns_text(turns)
        log(ep, "critics", f"segment {i + 1} round {rnd}: {len(issues)} issues, {len(edits) - len(failed)} word fixes",
            issues=issues)
        fixed = {e["issue"] for e in edits} - {e["issue"] for e in failed}
        seg["turns"] = [list(t) for t in turns]
        seg["open_issues"] = segment_issues(ep, i, turns, bad) + [x for x in critic if x not in fixed]
        if not issues or rnd == max_revisions:
            break


def review_segment(ep, i):
    """Review only: record what the critics find, with their suggested word edits; the lines stay as they are."""
    seg = ep["plan"]["segments"][i]
    code, critic, _ = review(ep, i, [tuple(t) for t in seg.get("turns", [])])
    seg["open_issues"] = code + critic
    log(ep, "critics", f"segment {i + 1} reviewed: {len(seg['open_issues'])} issues", issues=seg["open_issues"])


def sample_lines(ep, speaker):
    """Three lines a speaker might say, written from their persona (as typed, not necessarily saved)."""
    r, plan = ep["request"], ep["plan"]
    name = str(speaker.get("name") or "").strip()
    text = ask(ep, SAMPLE.format(title=plan["title"], topic=r["topic"], audience=plan["audience"], name=name,
                                 gender=speaker.get("gender", ""), role=speaker.get("role", ""),
                                 knowledge=speaker.get("knowledge", ""), persona=speaker.get("style", ""),
                                 lang=LANGS[r["lang"]][0], lang_rule=lang_rule(r["lang"], r["code_mix"])),
               f"sample:{name}", temperature=0.8)
    lines = []
    for x in text.splitlines():  # drop numbering, bullets, a "NAME:" label and wrapping quotes
        x = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", x)
        x = re.sub(rf"^{re.escape(name)}\s*:\s*", "", x, flags=re.I) if name else x
        if x := x.strip().strip('"“”').strip():
            lines.append(x)
    return lines[:3]

