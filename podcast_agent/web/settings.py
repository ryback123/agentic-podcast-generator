"""Settings changed from the web app's Settings and Voices tabs, kept in settings.json in the episodes folder (RUNS).
Server addresses and API keys stay in the environment (config.py) and never reach the page."""
import json
import os
import re

from ..config import RUNS
from ..languages import CODE_MIX, LANGS

DEFAULTS = {
    "lang": "hi", "speakers": 2, "minutes": 12, "code_mix": "medium",  # what a new episode starts with
    "research_steps": 20, "review_rounds": 2, "web_search": True,  # agent limits, read when a job starts
    "voice_female": "", "voice_male": "",  # default voices in the Audio step; "" = the first free one
    "speed": 1.0,  # audio speed-up, applied when an episode track is built (audio/mix.py load_clip)
    "model": "",  # the model every agent uses, as the endpoint names it; "" = the server's LLM_MODEL
}


def _int(v, lo, hi):
    return type(v) is int and lo <= v <= hi  # type(...) is int: True and False are ints too


def check(s):
    """The full settings from s: missing keys take their defaults, unknown keys are dropped. ValueError names the
    first bad value."""
    out = {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS}}
    ok = {"lang": out["lang"] in LANGS, "speakers": _int(out["speakers"], 2, 5),
          "minutes": _int(out["minutes"], 5, 20), "code_mix": out["code_mix"] in CODE_MIX,
          "research_steps": _int(out["research_steps"], 4, 40), "review_rounds": _int(out["review_rounds"], 0, 3),
          "web_search": type(out["web_search"]) is bool,
          "speed": type(out["speed"]) in (int, float) and 1 <= out["speed"] <= 1.5,
          "voice_female": isinstance(out["voice_female"], str) and len(out["voice_female"]) <= 100,
          "voice_male": isinstance(out["voice_male"], str) and len(out["voice_male"]) <= 100,
          "model": isinstance(out["model"], str) and bool(re.fullmatch(r"[\w.:/@-]{0,200}", out["model"]))}
    if bad := next((k for k, good in ok.items() if not good), None):
        raise ValueError(f"bad setting {bad}: {out[bad]!r}")
    return out


def load():
    f = RUNS / "settings.json"
    return check(json.loads(f.read_text())) if f.exists() else dict(DEFAULTS)


def save(s):
    s = check(s)
    f = RUNS / "settings.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1))
    os.replace(tmp, f)
    return s
