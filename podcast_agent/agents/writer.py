"""Writer agent and its critics. The writer drafts a segment; the code checks (checks.py), a fact-checker and an
editor review it, and major issues send it back for a rewrite, at most max_revisions times."""
from concurrent.futures import ThreadPoolExecutor

from ..episode import ask, cast_text, log, parse_turns, turns_text
from ..languages import LANGS, chars_per_min, lang_rule
from .checks import BANNED_OPENERS, segment_issues
from .prompts import CONTEXT, EDITOR, FACTCHECK, REVISE, WRITER, fact_lines, numbered


def segment_context(ep, i, note=None):
    plan, segs = ep["plan"], ep["plan"]["segments"]
    seg, lang, code_mix = segs[i], ep["request"]["lang"], ep["request"]["code_mix"]
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
                         lang_rule=lang_rule(lang, code_mix), banned=", ".join(f'"{b}"' for b in BANNED_OPENERS),
                         note=f"\n\nThe producer's note for this segment (follow it): {note}" if note else "")
    return ctx, chars


def review(ep, i, text):
    """All critics on one segment's text -> (turns, major issues)."""
    plan, segs, r = ep["plan"], ep["plan"]["segments"], ep["request"]
    turns, bad = parse_turns(text, [s["name"] for s in plan["speakers"]])
    issues = segment_issues(ep, i, turns, bad)
    if not turns:
        return turns, issues
    num = numbered(turns)
    fc = FACTCHECK.format(audience=plan["audience"], facts=fact_lines(ep["facts"]), numbered=num)
    role = ("the opening segment" if i == 0 else "the closing segment, which ends the episode" if i == len(segs) - 1
            else f"main segment {i} of {len(segs) - 2}")
    ed = EDITOR.format(audience=plan["audience"], role=role, lang=LANGS[r["lang"]][0],
                       lang_rule=lang_rule(r["lang"], r["code_mix"]), cast=cast_text(plan), goal=segs[i].get("goal", ""), numbered=num,
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
