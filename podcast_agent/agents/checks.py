"""Code-based critic: deterministic checks on generated dialogue (no model calls). Its findings are written as
instructions to the writer. Most name a line and the words to change, and the editor turns them into word edits;
the STRUCTURAL ones need the whole segment rewritten."""
import re
import unicodedata
from collections import Counter

from ..episode import CUT_OFF, TAGS
from ..languages import LANGS, SCRIPTS, chars_per_min

LATIN_SHARE = {"light": (0.02, 0.15), "medium": (0.08, 0.35), "heavy": (0.25, 0.60)}  # share of English words
MAX_TURN_CHARS = 400  # one TTS call per turn
BANNED_OPENERS = ("great question", "that's a great", "what a great", "absolutely", "exactly", "welcome back",
                  "fascinating", "that's fascinating", "that's so interesting", "you know what", "let's dive", "wow")
SYMBOLS = re.compile(r"[*#_\[\]{}<>\\$%&@|~^=+/]")
MAX_BACKCHANNEL_WORDS = 4
# One word may start at most this share of an episode's lines. In run langs_20261029, one-word habits ("yes",
# "meaning") started 14-22% of lines, while ordinary "but" or "so" stayed near 10%.
FIRST_WORD_SHARE = 0.12
DANGLING = re.compile(r"[A-Za-z]-(?=$|[^\w])")  # a hyphen with no ending after it ("Immunity-।")
MAX_PER_KIND = 5  # word problems of one kind reported per round; the rest come up in the next round
# Problems that word edits cannot fix, so the writer rewrites the segment
STRUCTURAL = ("No dialogue lines", "Not a valid dialogue line", "too long for one turn", "The segment is ",
              "romanized form", "must come right after")


def is_structural(issue):
    return any(s in issue for s in STRUCTURAL)


def english_share(turns):
    """Share of words in Latin letters, which the line format keeps for English."""
    counts = Counter(word_script(w) for _, tx, _ in turns for w in words(tx))
    return counts["Latin"] / (sum(counts.values()) or 1)


def adds_english(find, replace, script):
    """True if a fix puts English words in place of words in the episode's script (ശരീരത്തിൽ -> body-യിൽ). Respelling
    an English word written in that script (ബോഡി -> body) counts too; fixing a word in a wrong script (Hindi वायरस in
    Kannada -> virus) does not."""
    f, r = (Counter(word_script(w) for w in words(s)) for s in (find, replace))
    return r["Latin"] > f["Latin"] and r[script] < f[script]


def words(text):
    """Words as letters + combining marks only (Indic vowel signs are marks, not \\w)."""
    out = ("".join(c for c in w if unicodedata.category(c)[0] in "LM") for w in text.split())
    return [w for w in out if w]


def char_script(c):
    o = ord(c)
    return next((s for s, ranges in SCRIPTS.items() if any(a <= o <= b for a, b in ranges)), "other")


def word_script(w):
    return Counter(char_script(c) for c in w).most_common(1)[0][0]


def glued(tok):
    """An English word and an Indic ending written as one word ('bodyಗೆ'); they take a hyphen. Only letters count, so
    punctuation such as the Devanagari danda '।' after an English word is fine."""
    s = [char_script(c) if unicodedata.category(c)[0] in "LM" else None for c in tok]
    return any(a and b and a != b and "Latin" in (a, b) and "other" not in (a, b) for a, b in zip(s, s[1:]))


def check_segment(turns, bad, lang, code_mix, budget_chars, history):
    """Issues (as instructions to the writer) for one segment; history = turns of earlier segments."""
    if not turns:
        return ["No dialogue lines found. Output only lines like NAME: text."]
    name, script, _ = LANGS[lang]
    issues = [f"Not a valid dialogue line (use NAME: text with the cast names, no markdown): {b[:80]!r}"
              for b in bad[:5]]
    floor, held = None, 0  # speaker and number of the last line that holds the floor (not a backchannel)
    for k, (sp, tx, mode) in enumerate(turns, 1):
        if mode and floor in (None, sp):
            issues.append(f"Line {k}: a ({TAGS[mode]}) line must come right after a line by another speaker in this "
                          f"segment; make it a normal line.")
        elif mode in ("cut", "fade") and not turns[held - 1][1].rstrip().endswith(CUT_OFF):
            issues.append(f"Line {k} {TAGS[mode]}, but line {held} is a finished sentence, so the audio plays line {k} "
                          f"as an ordinary reply. Cut line {held} off mid-sentence with a dash (—), for example by "
                          f"dropping its last words.")
        held = k if mode != "backchannel" else held
        if mode == "backchannel" and len(words(tx)) > MAX_BACKCHANNEL_WORDS:
            issues.append(f"Line {k}: a backchannel is a word or two; shorten it or make it a normal line.")
        floor = sp if mode != "backchannel" else floor
        if re.search(r"\d", tx):
            issues.append(f"Line {k}: contains digits; write numbers as spoken words.")
        if m := SYMBOLS.search(tx):
            issues.append(f"Line {k}: contains the symbol {m.group(0)!r}; say it in words or drop it.")
        if len(tx) > MAX_TURN_CHARS:
            issues.append(f"Line {k}: {len(tx)} characters is too long for one turn; split or shorten it.")
        if mode != "backchannel" and tx.lower().startswith(BANNED_OPENERS):
            issues.append(f"Line {k}: starts with a stock phrase; start it differently.")

    joined, mixed, wrong = [], [], []
    for k, (_, tx, _) in enumerate(turns, 1):
        for tok in tx.split():
            scripts = {char_script(c) for c in tok if unicodedata.category(c)[0] in "LM"} - {"Latin", "other"}
            if len(scripts) > 1:
                mixed.append(f"Line {k}: {tok!r} mixes letters from two scripts; spell it correctly in {script} script.")
            elif lang != "en" and glued(tok):
                joined.append(f"Line {k}: {tok!r} joins an English word and a {name} ending; put a hyphen between them.")
            elif DANGLING.search(tok):
                joined.append(f"Line {k}: {tok!r} has a hyphen with nothing after it; remove the hyphen.")
        for w in words(tx):
            if any(0xC0 <= ord(c) <= 0x24F for c in w):  # accented Latin letters ("espécie"), not English
                wrong.append(f"Line {k}: {w!r} is not an English word; write it in plain English or in {name}.")
            elif (s := word_script(w)) not in (script, "Latin"):
                wrong.append(f"Line {k}: {w!r} is in {s} script; write it in {script} script or as an English word in "
                             f"Latin letters.")
    issues += mixed[:MAX_PER_KIND] + joined[:MAX_PER_KIND] + wrong[:MAX_PER_KIND]

    if lang != "en":
        lo, hi = LATIN_SHARE[code_mix]
        share = english_share(turns)
        if share < lo:
            issues.append(f"Only {share:.0%} of words are English; target code-mixing is {code_mix} "
                          f"({lo:.0%}-{hi:.0%}). Use English words where speakers naturally would.")
        elif share > 0.7:  # almost all Latin: the language itself is romanized
            issues.append(f"{share:.0%} of words are in Latin letters: {name} is written in romanized form. Write every "
                          f"{name} word in {script} script; only English words stay in Latin letters.")
        elif share > hi:
            issues.append(f"{share:.0%} of words are English; the target for {code_mix} code-mixing is {lo:.0%}-{hi:.0%}. "
                          f"Say more of it in {name}.")

    n = sum(len(tx) for _, tx, _ in turns)
    if not 0.75 * budget_chars <= n <= 1.3 * budget_chars:
        issues.append(f"The segment is {n} characters; the target is about {budget_chars}. "
                      f"{'Expand' if n < budget_chars else 'Shorten'} it.")

    opener = lambda tx: " ".join(w.lower() for w in words(tx)[:2])  # noqa: E731
    seen = Counter(opener(tx) for _, tx, mode in history if mode != "backchannel")
    firsts = Counter(words(tx)[0].lower() for _, tx, mode in history if mode != "backchannel" and words(tx))
    n, overused = sum(firsts.values()), []
    for k, (_, tx, mode) in enumerate(turns, 1):
        if mode == "backchannel" or not words(tx):  # short reactions repeat naturally
            continue
        seen[opener(tx)] += 1
        if seen[opener(tx)] == 4:
            issues.append(f"Line {k}: the opening words {opener(tx)!r} are used too often in this episode; vary them.")
        first = words(tx)[0].lower()
        firsts[first] += 1
        n += 1
        if firsts[first] > max(3, FIRST_WORD_SHARE * n):
            overused.append(f"Line {k}: starts with {first!r}, which already starts {firsts[first]} of the {n} lines so "
                            f"far; replace or drop that first word.")
    return issues + overused[:MAX_PER_KIND]


def segment_issues(ep, i, turns, bad=()):
    """check_segment for segment i of an episode, with its length budget and the lines of earlier segments."""
    segs, r = ep["plan"]["segments"], ep["request"]
    budget = int(float(segs[i]["minutes"]) * chars_per_min(r["lang"]))
    history = [tuple(t) for s in segs[:i] for t in s.get("turns", [])]
    return check_segment([tuple(t) for t in turns], list(bad), r["lang"], r["code_mix"], budget, history)
