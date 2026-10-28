"""Edits from the web app: renaming speakers and editing lines (edits.py, no model calls)."""
import copy

import pytest

from podcast_agent import edits
from podcast_agent.episode import script_json, script_text


def spk(name, gender):
    return {"name": name, "gender": gender, "role": "host", "knowledge": "basics", "style": "calm"}


def make_episode(d):
    return {"id": "t", "dir": str(d), "log": [], "facts": [], "questions": {},
            "request": {"lang": "hi", "code_mix": "medium"},
            "plan": {"title": "UPI", "hook": "h", "speakers": [spk("RIYA", "female"), spk("ISHAAN", "male")],
                     "segments": [{"title": "Intro", "minutes": 1, "goal": "Riya explains UPI to Ishaan", "questions": [],
                                   "turns": [["RIYA", "मैं हूँ Riya, और ये Ishaan हैं।", ""],
                                             ["ISHAAN", "நான் Ishaan-உம் Riya-வும். Ishaanpur is a town, RIYA!", "cut"]]}]},
            "audio": {"voices": {"RIYA": "v1", "ISHAAN": "v2"}, "takes": {"RIYA|मैं हूँ Riya, और ये Ishaan हैं।": 2}}}


def test_rename_reaches_lines_goals_voices_and_files(tmp_path):
    ep = make_episode(tmp_path)
    plan = copy.deepcopy(ep["plan"])
    plan["speakers"][0]["name"], plan["speakers"][1]["name"] = "Ishaan", "Meera"  # RIYA->ISHAAN, ISHAAN->MEERA
    edits.set_plan(ep, plan)

    seg = ep["plan"]["segments"][0]
    assert seg["turns"] == [["ISHAAN", "मैं हूँ Ishaan, और ये Meera हैं।", ""],
                            ["MEERA", "நான் Meera-உம் Ishaan-வும். Ishaanpur is a town, ISHAAN!", "cut"]], seg["turns"]
    assert seg["goal"] == "Ishaan explains UPI to Meera"
    assert ep["audio"]["voices"] == {"ISHAAN": "v1", "MEERA": "v2"}
    assert ep["audio"]["takes"] == {"ISHAAN|मैं हूँ Ishaan, और ये Meera हैं।": 2}
    assert set(ep["stats"]["speaker_share"]) == {"ISHAAN", "MEERA"}
    out = script_json(ep)["turns"]
    assert out[0] == {"speaker": "ISHAAN", "text": "मैं हूँ Ishaan, और ये Meera हैं।"} and out[1]["mode"] == "cut", out
    assert "MEERA (cuts in): " in script_text(ep)
    assert not list(tmp_path.glob("script.*"))  # built when downloaded, not saved

    before = copy.deepcopy(ep["plan"]["segments"])
    edits.set_plan(ep, copy.deepcopy(ep["plan"]))  # saving without renaming changes no line
    assert ep["plan"]["segments"][0]["turns"] == before[0]["turns"]


def test_line_edits_keep_modes_and_refuse_unknown_ones(tmp_path):
    ep = make_episode(tmp_path)
    edits.set_turns(ep, 0, [["RIYA", "So the bank checks the—"], ["ISHAAN", "हम्म", "backchannel"], ["RIYA", "  "]])
    assert ep["plan"]["segments"][0]["turns"] == [["RIYA", "So the bank checks the—", ""], ["ISHAAN", "हम्म", "backchannel"]]
    with pytest.raises(ValueError):
        edits.set_turns(ep, 0, [["RIYA", "hi", "whisper"]])
