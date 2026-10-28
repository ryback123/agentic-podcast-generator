"""Edits made in the web app: the plan (including renaming speakers) and a segment's lines."""
import re

from .agents.checks import segment_issues
from .agents.producer import assign_questions, check_plan
from .episode import TAGS, finish, log


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


def set_turns(ep, i, turns):
    """User edit of one segment's lines; returns the deterministic-check issues."""
    names = {s["name"] for s in ep["plan"]["speakers"]}
    clean = [[t[0], " ".join(str(t[1]).split()), t[2] if len(t) > 2 else ""] for t in turns if str(t[1]).strip()]
    if bad := {sp for sp, _, _ in clean} - names:
        raise ValueError(f"unknown speakers {sorted(bad)}")
    if bad := {m for *_, m in clean} - {"", *TAGS}:
        raise ValueError(f"unknown line modes {sorted(bad)}")
    seg = ep["plan"]["segments"][i]
    seg["turns"], seg["open_issues"] = clean, segment_issues(ep, i, clean)
    log(ep, "user", f"edited segment {i + 1}: {len(clean)} lines")
    finish(ep)
