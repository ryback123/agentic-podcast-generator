"""Deterministic checks on generated dialogue. `python checks.py` runs the self-test."""
import re
import unicodedata
from collections import Counter

# code: (name, script, Wikipedia code or None)
LANGS = {
    "en": ("English", "Latin", "en"),
    "as": ("Assamese", "Bengali", "as"),
    "bn": ("Bengali", "Bengali", "bn"),
    "brx": ("Bodo", "Devanagari", None),
    "doi": ("Dogri", "Devanagari", None),
    "gu": ("Gujarati", "Gujarati", "gu"),
    "hi": ("Hindi", "Devanagari", "hi"),
    "kn": ("Kannada", "Kannada", "kn"),
    "ks": ("Kashmiri", "Arabic", "ks"),
    "gom": ("Konkani", "Devanagari", "gom"),
    "mai": ("Maithili", "Devanagari", "mai"),
    "ml": ("Malayalam", "Malayalam", "ml"),
    "mni": ("Manipuri", "Bengali", "mni"),  # Meetei Mayek is also official: use whichever the TTS API expects
    "mr": ("Marathi", "Devanagari", "mr"),
    "ne": ("Nepali", "Devanagari", "ne"),
    "or": ("Odia", "Odia", "or"),
    "pa": ("Punjabi", "Gurmukhi", "pa"),
    "sa": ("Sanskrit", "Devanagari", "sa"),
    "sat": ("Santali", "Ol Chiki", "sat"),
    "sd": ("Sindhi", "Arabic", "sd"),
    "ta": ("Tamil", "Tamil", "ta"),
    "te": ("Telugu", "Telugu", "te"),
    "ur": ("Urdu", "Arabic", "ur"),
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
    "Arabic": [(0x600, 0x6FF), (0x750, 0x77F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)],
    "Ol Chiki": [(0x1C50, 0x1C7F)],
    "Meetei Mayek": [(0xABC0, 0xABFF)],
}
# ponytail: speaking-rate guesses; replace with characters/minute measured from the TTS API per language
CHARS_PER_MIN = {"en": 900}
DEFAULT_CHARS_PER_MIN = 750
LATIN_SHARE = {"light": (0.02, 0.15), "medium": (0.08, 0.35), "heavy": (0.25, 0.60)}  # share of English words
MAX_TURN_CHARS = 400  # one TTS call per turn
BANNED_OPENERS = ("great question", "that's a great", "what a great", "absolutely", "exactly", "welcome back",
                  "fascinating", "that's fascinating", "that's so interesting", "you know what", "let's dive", "wow")
SYMBOLS = re.compile(r"[*#_\[\]{}<>\\$%&@|~^=+/]")
LINE = re.compile(r"^\s*([A-Za-z]+)\s*:\s*(.+?)\s*$")


def chars_per_min(lang):
    return CHARS_PER_MIN.get(lang, DEFAULT_CHARS_PER_MIN)


def parse_turns(text, names):
    """'NAME: text' lines -> ([(NAME, text)], [lines that are not valid turns])."""
    turns, bad = [], []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = LINE.match(line)
        if m and m.group(1).upper() in names:
            turns.append((m.group(1).upper(), m.group(2)))
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
    for k, (_, tx) in enumerate(turns, 1):
        if re.search(r"\d", tx):
            issues.append(f"Line {k}: contains digits; write numbers as spoken words.")
        if m := SYMBOLS.search(tx):
            issues.append(f"Line {k}: contains the symbol {m.group(0)!r}; say it in words or drop it.")
        if len(tx) > MAX_TURN_CHARS:
            issues.append(f"Line {k}: {len(tx)} characters is too long for one turn; split or shorten it.")
        if tx.lower().startswith(BANNED_OPENERS):
            issues.append(f"Line {k}: starts with a stock phrase; start it differently.")

    counts = Counter(word_script(w) for _, tx in turns for w in words(tx))
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
        elif share > hi:
            issues.append(f"{share:.0%} of words are English; target code-mixing is {code_mix} "
                          f"({lo:.0%}-{hi:.0%}). Use more {name}.")

    n = sum(len(tx) for _, tx in turns)
    if not 0.75 * budget_chars <= n <= 1.3 * budget_chars:
        issues.append(f"The segment is {n} characters; the target is about {budget_chars}. "
                      f"{'Expand' if n < budget_chars else 'Shorten'} it.")

    opener = lambda tx: " ".join(w.lower() for w in words(tx)[:2])  # noqa: E731
    seen = Counter(opener(tx) for _, tx in history)
    for k, (_, tx) in enumerate(turns, 1):
        seen[opener(tx)] += 1
        if seen[opener(tx)] == 4:
            issues.append(f"Line {k}: the opening words {opener(tx)!r} are used too often in this episode; vary them.")
    return issues


if __name__ == "__main__":
    names = ["PRIYA", "ARJUN"]
    hi_line = "अर्जुन, ये UPI payments असल में काम कैसे करते हैं?"
    turns, bad = parse_turns(f"PRIYA: {hi_line}\n\n**ARJUN**: hello\nRAVI: who?", names)
    assert turns == [("PRIYA", hi_line)] and len(bad) == 2, (turns, bad)
    assert words(hi_line)[0] == "अर्जुन" and word_script("payments") == "Latin"

    ok = check_segment(turns, [], "hi", "medium", len(hi_line), [])
    assert ok == [], ok  # 2 of 10 words English = 20%, inside medium

    t = "यह 2016 में शुरू हुआ और 50% लोग payments करते हैं"
    iss = check_segment([("ARJUN", t)], [], "hi", "medium", len(t), [])
    assert any("digits" in i for i in iss) and any("symbol" in i for i in iss), iss

    t = "यह बहुत अच्छा है और सबके लिए सरल है"
    assert any("English" in i for i in check_segment([("ARJUN", t)], [], "hi", "medium", len(t), []))

    t = "வணக்கம் நண்பர்களே இது payments பற்றி"
    assert any("wrong script" in i for i in check_segment([("ARJUN", t)], [], "hi", "heavy", len(t), []))

    t = "अच्छा तो UPI payments ऐसे काम करता है"
    hist = [("PRIYA", "अच्छा तो फिर क्या हुआ")] * 3
    assert any("too often" in i for i in check_segment([("ARJUN", t)], [], "hi", "medium", len(t), hist))
    assert any("characters" in i for i in check_segment([("ARJUN", t)], [], "hi", "medium", 10 * len(t), []))
    assert any("stock phrase" in i for i in check_segment([("ARJUN", "Exactly, that is how it works")], [],
                                                          "en", "medium", 29, []))
    print("checks.py self-test OK")
