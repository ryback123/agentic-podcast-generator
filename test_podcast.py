"""Renaming speakers after the script is written (no model calls): python test_podcast.py"""
import copy
import json
import tempfile
from pathlib import Path

import podcast as pc


def spk(name, gender):
    return {"name": name, "gender": gender, "role": "host", "knowledge": "basics", "style": "calm"}


with tempfile.TemporaryDirectory() as d:
    ep = {"id": "t", "dir": d, "log": [], "facts": [], "questions": {}, "request": {"lang": "hi"},
          "plan": {"title": "UPI", "hook": "h", "speakers": [spk("RIYA", "female"), spk("ISHAAN", "male")],
                   "segments": [{"title": "Intro", "minutes": 1, "goal": "Riya explains UPI to Ishaan", "questions": [],
                                 "turns": [["RIYA", "मैं हूँ Riya, और ये Ishaan हैं।"],
                                           ["ISHAAN", "நான் Ishaan-உம் Riya-வும். Ishaanpur is a town, RIYA!"]]}]},
          "audio": {"voices": {"RIYA": "v1", "ISHAAN": "v2"}, "takes": {"RIYA|मैं हूँ Riya, और ये Ishaan हैं।": 2}}}
    plan = copy.deepcopy(ep["plan"])
    plan["speakers"][0]["name"], plan["speakers"][1]["name"] = "Ishaan", "Meera"  # RIYA->ISHAAN, ISHAAN->MEERA
    pc.set_plan(ep, plan)

    seg = ep["plan"]["segments"][0]
    assert seg["turns"] == [["ISHAAN", "मैं हूँ Ishaan, और ये Meera हैं।"],
                            ["MEERA", "நான் Meera-உம் Ishaan-வும். Ishaanpur is a town, ISHAAN!"]], seg["turns"]
    assert seg["goal"] == "Ishaan explains UPI to Meera"
    assert ep["audio"]["voices"] == {"ISHAAN": "v1", "MEERA": "v2"}
    assert ep["audio"]["takes"] == {"ISHAAN|मैं हूँ Ishaan, और ये Meera हैं।": 2}
    assert set(ep["stats"]["speaker_share"]) == {"ISHAAN", "MEERA"}
    assert json.loads((Path(d) / "script.json").read_text())["turns"][0]["speaker"] == "ISHAAN"

    before = copy.deepcopy(ep["plan"]["segments"])
    pc.set_plan(ep, copy.deepcopy(ep["plan"]))  # saving without renaming changes no line
    assert ep["plan"]["segments"][0]["turns"] == before[0]["turns"]
print("podcast.py rename test OK")
