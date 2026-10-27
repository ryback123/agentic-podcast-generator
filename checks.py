"""Deterministic checks on generated dialogue. `python checks.py` runs the self-test."""
import re
import unicodedata
from collections import Counter

# code: (name, script, Wikipedia code). English + the 11 major Indian languages.
LANGS = {
    "en": ("English", "Latin", "en"),
    "hi": ("Hindi", "Devanagari", "hi"),
    "bn": ("Bengali", "Bengali", "bn"),
    "mr": ("Marathi", "Devanagari", "mr"),
    "te": ("Telugu", "Telugu", "te"),
    "ta": ("Tamil", "Tamil", "ta"),
    "gu": ("Gujarati", "Gujarati", "gu"),
    "kn": ("Kannada", "Kannada", "kn"),
    "ml": ("Malayalam", "Malayalam", "ml"),
    "or": ("Odia", "Odia", "or"),
    "pa": ("Punjabi", "Gurmukhi", "pa"),
    "as": ("Assamese", "Bengali", "as"),
}
SCRIPTS = {
    "Latin": [(0x41, 0x5A), (0x61, 0x7A), (0xC0, 0x24F)],
    "Devanagari": [(0x900, 0x97F), (0xA8E0, 0xA8FF)],
    "Bengali": [(0x980, 0x9FF)],
    "Gurmukhi": [(0xA00, 0xA7F)],
    "Gujarati": [(0xA80, 0xAFF)],
    "Odia": [(0xB00, 0xB7F)],
    "Tamil": [(0xB80, 0xBFF)],
    "Telugu": [(0xC00, 0xC7F)],
    "Kannada": [(0xC80, 0xCFF)],
    "Malayalam": [(0xD00, 0xD7F)],
}
# ponytail: speaking-rate guesses; replace with characters/minute measured from the TTS API per language
CHARS_PER_MIN = {"en": 900}
DEFAULT_CHARS_PER_MIN = 750
LATIN_SHARE = {"light": (0.02, 0.15), "medium": (0.08, 0.35), "heavy": (0.25, 0.60)}  # share of English words
MAX_TURN_CHARS = 400  # one TTS call per turn
BANNED_OPENERS = ("great question", "that's a great", "what a great", "absolutely", "exactly", "welcome back",
                  "fascinating", "that's fascinating", "that's so interesting", "you know what", "let's dive", "wow")
SYMBOLS = re.compile(r"[*#_\[\]{}<>\\$%&@|~^=+/]")
LINE = re.compile(r"^\s*([A-Za-z]+)\s*(?:\(([A-Za-z ]+)\))?\s*:\s*(.+?)\s*$")
# How a line starts ("" = after the previous line ends). backchannel: a quick reaction over the line holding the floor;
# cut / fade: cuts in before that line ends, which stops dead (cut) or fades out under it (fade).
TAGS = {"backchannel": "backchannel", "cut": "cuts in", "fade": "talks over"}  # mode -> tag in "NAME (tag): text"
MAX_BACKCHANNEL_WORDS = 4


def chars_per_min(lang):
    return CHARS_PER_MIN.get(lang, DEFAULT_CHARS_PER_MIN)


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


def words(text):
    """Words as letters + combining marks only (Indic vowel signs are marks, not \\w)."""
    out = ("".join(c for c in w if unicodedata.category(c)[0] in "LM") for w in text.split())
    return [w for w in out if w]


def char_script(c):
    o = ord(c)
    return next((s for s, ranges in SCRIPTS.items() if any(a <= o <= b for a, b in ranges)), "other")


def word_script(w):
    return Counter(char_script(c) for c in w).most_common(1)[0][0]


def check_segment(turns, bad, lang, code_mix, budget_chars, history):
    """Issues (as instructions to the writer) for one segment; history = turns of earlier segments."""
    if not turns:
        return ["No dialogue lines found. Output only lines like NAME: text."]
    name, script, _ = LANGS[lang]
    issues = [f"Not a valid dialogue line (use NAME: text with the cast names, no markdown): {b[:80]!r}"
              for b in bad[:5]]
    floor = None  # speaker of the last line that holds the floor (not a backchannel)
    for k, (sp, tx, mode) in enumerate(turns, 1):
        if mode and floor in (None, sp):
            issues.append(f"Line {k}: a ({TAGS[mode]}) line must come right after a line by another speaker in this "
                          f"segment; make it a normal line.")
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

    counts = Counter(word_script(w) for _, tx, _ in turns for w in words(tx))
    total = sum(counts.values()) or 1
    wrong = sum(v for s, v in counts.items() if s not in (script, "Latin"))
    if wrong / total > 0.02:
        issues.append(f"{wrong} words are in the wrong script; write {name} in {script} script.")
    if lang != "en":
        lo, hi = LATIN_SHARE[code_mix]
        share = counts["Latin"] / total
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
    for k, (_, tx, mode) in enumerate(turns, 1):
        if mode == "backchannel":  # short reactions repeat naturally
            continue
        seen[opener(tx)] += 1
        if seen[opener(tx)] == 4:
            issues.append(f"Line {k}: the opening words {opener(tx)!r} are used too often in this episode; vary them.")
    return issues


if __name__ == "__main__":
    names = ["PRIYA", "ARJUN"]
    hi_line = "अर्जुन, ये UPI payments असल में काम कैसे करते हैं?"
    turns, bad = parse_turns(f"PRIYA: {hi_line}\n\n**ARJUN**: hello\nRAVI: who?", names)
    assert turns == [("PRIYA", hi_line, "")] and len(bad) == 2, (turns, bad)
    assert words(hi_line)[0] == "अर्जुन" and word_script("payments") == "Latin"

    ok = check_segment(turns, [], "hi", "medium", len(hi_line), [])
    assert ok == [], ok  # 2 of 10 words English = 20%, inside medium

    t = "यह 2016 में शुरू हुआ और 50% लोग payments करते हैं"
    iss = check_segment([("ARJUN", t, "")], [], "hi", "medium", len(t), [])
    assert any("digits" in i for i in iss) and any("symbol" in i for i in iss), iss

    t = "यह बहुत अच्छा है और सबके लिए सरल है"
    assert any("English" in i for i in check_segment([("ARJUN", t, "")], [], "hi", "medium", len(t), []))
    t = "Wahi toh mystery hai, aaj hum samjhenge"  # romanized Hindi must be called out as a script problem
    assert any("Devanagari script" in i for i in check_segment([("ARJUN", t, "")], [], "hi", "medium", len(t), []))
    t = "Kerala side-ல rush ஆகும் winds coastal areas-ல பயங்கர மழை"  # English-heavy, not romanized
    iss = check_segment([("ARJUN", t, "")], [], "ta", "medium", len(t), [])
    assert any("are English" in i for i in iss) and not any("romanized" in i for i in iss), iss

    t = "வணக்கம் நண்பர்களே இது payments பற்றி"
    assert any("wrong script" in i for i in check_segment([("ARJUN", t, "")], [], "hi", "heavy", len(t), []))

    t = "अच्छा तो UPI payments ऐसे काम करता है"
    hist = [("PRIYA", "अच्छा तो फिर क्या हुआ", "")] * 3
    assert any("too often" in i for i in check_segment([("ARJUN", t, "")], [], "hi", "medium", len(t), hist))
    assert any("characters" in i for i in check_segment([("ARJUN", t, "")], [], "hi", "medium", 10 * len(t), []))
    assert any("stock phrase" in i for i in check_segment([("ARJUN", "Exactly, that is how it works", "")], [],
                                                          "en", "medium", 29, []))

    turns, bad = parse_turns("PRIYA: So the bank checks the—\nARJUN (Cuts In): wait, which bank?\n"
                             "PRIYA (backchannel): हम्म\nARJUN (talks over): fine\nPRIYA (whispers): no", names)
    assert [m for *_, m in turns] == ["", "cut", "backchannel", "fade"] and bad == ["PRIYA (whispers): no"], (turns, bad)
    assert label("ARJUN", "cut") == "ARJUN (cuts in)" and label("ARJUN") == "ARJUN"
    ok = [("PRIYA", "So the bank checks the—", ""), ("ARJUN", "हम्म", "backchannel"), ("PRIYA", "and then it pays", ""),
          ("ARJUN", "Wait, who pays?", "cut")]
    assert not any("must come right after" in i for i in check_segment(ok, [], "en", "medium", 60, [])), ok
    iss = check_segment([("ARJUN", "first line", "cut"), ("PRIYA", "ok", ""), ("PRIYA", "me again", "backchannel"),
                         ("ARJUN", "hmm right yes sure okay", "backchannel")], [], "en", "medium", 50, [])
    assert sum("must come right after" in i for i in iss) == 2 and any("word or two" in i for i in iss), iss
    assert not any("stock phrase" in i for i in check_segment([("PRIYA", "a line", ""), ("ARJUN", "Exactly", "backchannel")],
                                                             [], "en", "medium", 15, []))
    print("checks.py self-test OK")
