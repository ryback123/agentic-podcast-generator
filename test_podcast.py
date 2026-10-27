"""Episode edits without model calls (renames, line modes, old episodes): python test_podcast.py"""
import copy
import json
import tempfile
from pathlib import Path

import podcast as pc


def spk(name, gender):
    return {"name": name, "gender": gender, "role": "host", "knowledge": "basics", "style": "calm"}


with tempfile.TemporaryDirectory() as d:
    ep = {"id": "t", "dir": d, "log": [], "facts": [], "questions": {}, "request": {"lang": "hi", "code_mix": "medium"},
          "plan": {"title": "UPI", "hook": "h", "speakers": [spk("RIYA", "female"), spk("ISHAAN", "male")],
                   "segments": [{"title": "Intro", "minutes": 1, "goal": "Riya explains UPI to Ishaan", "questions": [],
                                 "turns": [["RIYA", "मैं हूँ Riya, और ये Ishaan हैं।", ""],
                                           ["ISHAAN", "நான் Ishaan-உம் Riya-வும். Ishaanpur is a town, RIYA!", "cut"]]}]},
          "audio": {"voices": {"RIYA": "v1", "ISHAAN": "v2"}, "takes": {"RIYA|मैं हूँ Riya, और ये Ishaan हैं।": 2}}}
    plan = copy.deepcopy(ep["plan"])
    plan["speakers"][0]["name"], plan["speakers"][1]["name"] = "Ishaan", "Meera"  # RIYA->ISHAAN, ISHAAN->MEERA
    pc.set_plan(ep, plan)

    seg = ep["plan"]["segments"][0]
    assert seg["turns"] == [["ISHAAN", "मैं हूँ Ishaan, और ये Meera हैं।", ""],
                            ["MEERA", "நான் Meera-உம் Ishaan-வும். Ishaanpur is a town, ISHAAN!", "cut"]], seg["turns"]
    assert seg["goal"] == "Ishaan explains UPI to Meera"
    assert ep["audio"]["voices"] == {"ISHAAN": "v1", "MEERA": "v2"}
    assert ep["audio"]["takes"] == {"ISHAAN|मैं हूँ Ishaan, और ये Meera हैं।": 2}
    assert set(ep["stats"]["speaker_share"]) == {"ISHAAN", "MEERA"}
    out = json.loads((Path(d) / "script.json").read_text())["turns"]
    assert out[0] == {"speaker": "ISHAAN", "text": "मैं हूँ Ishaan, और ये Meera हैं।"} and out[1]["mode"] == "cut", out
    assert "MEERA (cuts in): " in (Path(d) / "script.txt").read_text()

    before = copy.deepcopy(ep["plan"]["segments"])
    pc.set_plan(ep, copy.deepcopy(ep["plan"]))  # saving without renaming changes no line
    assert ep["plan"]["segments"][0]["turns"] == before[0]["turns"]

    # line modes from the editor: kept, checked, and unknown ones refused
    pc.set_turns(ep, 0, [["ISHAAN", "So the bank checks the—"], ["MEERA", "हम्म", "backchannel"], ["ISHAAN", "  "]])
    assert ep["plan"]["segments"][0]["turns"] == [["ISHAAN", "So the bank checks the—", ""], ["MEERA", "हम्म", "backchannel"]]
    try:
        pc.set_turns(ep, 0, [["ISHAAN", "hi", "whisper"]])
        raise AssertionError("unknown mode accepted")
    except ValueError:
        pass

    # episodes saved before line modes stored [speaker, text]
    ep["plan"]["segments"][0]["turns"] = [["ISHAAN", "old line"]]
    pc.save(ep)
    assert pc.load(d)["plan"]["segments"][0]["turns"] == [["ISHAAN", "old line", ""]]

    # a copied episode saves into the copy, never back into the folder it was copied from
    import shutil
    copy_dir = shutil.copytree(d, Path(d) / "copy")
    ep2 = pc.load(copy_dir)
    pc.set_turns(ep2, 0, [["ISHAAN", "edited in the copy"]])
    assert pc.load(d)["plan"]["segments"][0]["turns"] == [["ISHAAN", "old line", ""]]
    assert pc.load(copy_dir)["plan"]["segments"][0]["turns"][0][1] == "edited in the copy"
print("podcast.py test OK")
