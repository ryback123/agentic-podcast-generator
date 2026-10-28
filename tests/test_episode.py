"""Episode storage and the script line format (episode.py)."""
import shutil

from podcast_agent.episode import label, load, parse_turns, save

NAMES = ["PRIYA", "ARJUN"]


def test_parse_turns():
    hi = "अर्जुन, ये UPI payments असल में काम कैसे करते हैं?"
    turns, bad = parse_turns(f"PRIYA: {hi}\n\n**ARJUN**: hello\nRAVI: who?", NAMES)
    assert turns == [("PRIYA", hi, "")] and len(bad) == 2, (turns, bad)
    turns, bad = parse_turns("PRIYA: So the bank checks the—\nARJUN (Cuts In): wait, which bank?\n"
                             "PRIYA (backchannel): हम्म\nARJUN (talks over): fine\nPRIYA (whispers): no", NAMES)
    assert [m for *_, m in turns] == ["", "cut", "backchannel", "fade"] and bad == ["PRIYA (whispers): no"], (turns, bad)
    assert label("ARJUN", "cut") == "ARJUN (cuts in)" and label("ARJUN") == "ARJUN"


def episode(d, turns):
    return {"id": "t", "dir": str(d), "log": [], "plan": {"segments": [{"turns": turns}]}}


def test_old_episodes_load_with_modes(tmp_path):
    save(episode(tmp_path, [["ISHAAN", "old line"]]))  # saved before line modes: [speaker, text]
    assert load(tmp_path)["plan"]["segments"][0]["turns"] == [["ISHAAN", "old line", ""]]


def test_a_copied_episode_saves_into_the_copy(tmp_path):
    (tmp_path / "a").mkdir()
    save(episode(tmp_path / "a", [["ISHAAN", "original"]]))
    copy_dir = shutil.copytree(tmp_path / "a", tmp_path / "b")  # its episode.json still names folder a
    ep = load(copy_dir)
    ep["plan"]["segments"][0]["turns"] = [["ISHAAN", "edited in the copy", ""]]
    save(ep)
    assert load(tmp_path / "a")["plan"]["segments"][0]["turns"] == [["ISHAAN", "original", ""]]
    assert load(copy_dir)["plan"]["segments"][0]["turns"][0][1] == "edited in the copy"
