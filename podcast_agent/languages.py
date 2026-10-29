"""The 12 supported languages, their scripts, speaking pace, and what each code-mix level means."""

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
# Unicode ranges of each script, to tell which script a word is written in
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
# How much English each code-mix level asks for, as the agents are told
CODE_MIX = {
    "light": "Mostly {lang}; English only for technical terms that people normally say in English.",
    # The budget brought first drafts over 35% English from 49 to 31 of 120 (replay of swapfix_20261029).
    "medium": "Everyday code-mixing: {lang} sentences with some common English words, the way {lang} speakers talk "
              "with friends. About one word in five should be English, and never more than one in three: English for "
              "technical terms and the odd everyday word, while verbs, explanations, analogies and whole sentences "
              "stay in {lang}.",
    "heavy": "Heavy code-mixing: many English words and phrases inside {lang} sentences, switching freely.",
}
# ponytail: speaking-rate guesses; replace with characters/minute measured from the TTS API per language
CHARS_PER_MIN = {"en": 900}
DEFAULT_CHARS_PER_MIN = 750


def chars_per_min(lang):
    return CHARS_PER_MIN.get(lang, DEFAULT_CHARS_PER_MIN)


def lang_rule(lang, code_mix):
    """The language instruction the agents get."""
    name, script, _ = LANGS[lang]
    if lang == "en":
        return "Natural spoken English, the way Indian podcast hosts talk."
    return (CODE_MIX[code_mix].format(lang=name) + f" Write {name} words in {script} script and every English word in Latin "
            f"letters, even everyday ones like body or doctor (never spell an English word in {script} script, but never "
            f"swap a {name} word for an English one either). When a {name} ending attaches to an English word, put a "
            f"hyphen between them.")
