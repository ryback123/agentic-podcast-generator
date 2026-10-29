"""The writer's review loop with a fake model: word edits are patched in place, a rewrite happens only when word edits
can't fix the problem, and an unreadable critic reply does not stop the episode."""
import pytest

from podcast_agent.agents import writer
from podcast_agent.agents.writer import apply_edits

DRAFT = "ASHA: So what is an epitope, really?\nRAVI: It is the part the body learns to spot."


def test_apply_edits():
    turns = [["ASHA", "Exactly! The epitope is small.", ""], ["RAVI", "Yes, a small part.", ""]]
    out, failed = apply_edits(turns, [
        {"line": 1, "find": "Exactly!", "replace": "", "issue": "a"},
        {"line": 2, "find": "The epitope", "replace": "The virus's ID tag", "issue": "b"},  # wrong line: still lands
        {"line": 2, "find": "not there", "replace": "x", "issue": "c"},
        {"line": "2", "find": "Yes, a small part.", "replace": "", "issue": "d"},  # empties the line: dropped
    ])
    assert out == [["ASHA", "The virus's ID tag is small.", ""]], out
    assert [e["issue"] for e in failed] == ["c"]
    assert turns[0][1] == "Exactly! The epitope is small."  # the input is not changed


def episode(tmp_path):
    spk = lambda n: {"name": n, "gender": "female", "role": "host", "knowledge": "-", "style": "-"}  # noqa: E731
    return {"id": "t", "dir": str(tmp_path), "log": [], "facts": [], "questions": {},
            "request": {"lang": "en", "code_mix": "medium", "topic": "Vaccines"},
            "plan": {"title": "Vaccines", "audience": "adults", "format": "chat", "hook": "h",
                     "speakers": [spk("ASHA"), spk("RAVI")],
                     "segments": [{"title": "One", "goal": "explain", "minutes": len(DRAFT) / 900}]}}


@pytest.fixture
def model(monkeypatch):
    """Fake model: replies[agent] is a list of replies, used in order (an exception is raised)."""
    calls, replies = [], {}

    def ask(ep, prompt, agent, json_reply=False, **kw):
        calls.append(agent)
        r = replies[agent.split(":")[0] if ":rev" not in agent else "rev"].pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(writer, "ask", ask)
    return calls, replies


def test_word_fix_is_patched_without_a_rewrite(tmp_path, model):
    calls, replies = model
    replies.update(writer=[DRAFT], factcheck=[{"issues": []}, {"issues": []}],
                   editor=[{"issues": [{"line": 1, "severity": "major", "problem": "jargon",
                                        "find": "an epitope", "replace": "the ID tag"}]}, {"issues": []}])
    ep = episode(tmp_path)
    writer.write_segment(ep, 0)
    seg = ep["plan"]["segments"][0]
    assert seg["turns"][0][1] == "So what is the ID tag, really?" and seg["open_issues"] == []
    assert not any(":rev" in c for c in calls), calls  # no full rewrite


def test_flow_problem_rewrites_and_unreadable_critic_is_recorded(tmp_path, model):
    calls, replies = model
    replies.update(writer=[DRAFT], rev=[DRAFT], factcheck=[ValueError("not JSON"), {"issues": []}],
                   editor=[{"issues": [{"line": 1, "severity": "major", "problem": "misses its goal", "find": ""}]},
                           {"issues": []}])
    ep = episode(tmp_path)
    writer.write_segment(ep, 0, max_revisions=1)
    assert "writer:1:rev1" in calls  # the flow problem had no words to change
    assert ep["plan"]["segments"][0]["open_issues"] == []
    assert any("review skipped" in i for e in ep["log"] for i in e.get("issues", []))  # round 0 went on without it


ML = "ASHA: നമ്മുടെ ശരീരത്തിൽ immune system ഉണ്ട്.\nRAVI: അതെ, body-യെ protect ചെയ്യും."


@pytest.mark.parametrize("draft, swapped", [(ML, False), (ML.replace("immune system", "പ്രതിരോധശേഷി"), True)])
def test_no_fix_adds_english_to_a_segment_over_its_share(tmp_path, model, draft, swapped):
    """The first draft is 44% English (medium allows 35%), the second 25%. Only over the share is the swap dropped."""
    calls, replies = model
    swap = {"line": 1, "severity": "major", "problem": "x", "find": "ശരീരത്തിൽ", "replace": "body-യിൽ"}
    native = {"line": 2, "severity": "major", "problem": "y", "find": "protect ചെയ്യും", "replace": "കാക്കും"}
    replies.update(writer=[draft], factcheck=[{"issues": []}], editor=[{"issues": [swap, native]}])
    ep = episode(tmp_path)
    ep["request"]["lang"] = "ml"
    writer.write_segment(ep, 0, max_revisions=0)
    first, second = (t[1] for t in ep["plan"]["segments"][0]["turns"])
    assert ("body-യിൽ" in first) == swapped and second == "അതെ, body-യെ കാക്കും."



def test_sample_lines_are_cleaned(tmp_path, model):
    calls, replies = model
    replies.update(sample=['1. "It is a fake wanted poster."\n\n- RAVI: Wait, so the body practises?\n* Fine. Prove it.\nOne too many.'])
    lines = writer.sample_lines(episode(tmp_path), {"name": "Ravi", "gender": "male", "role": "skeptic", "style": "blunt"})
    assert lines == ["It is a fake wanted poster.", "Wait, so the body practises?", "Fine. Prove it."]
    assert calls == ["sample:Ravi"]

def test_chat_json_retries_a_cut_off_reply(monkeypatch):
    from podcast_agent import llm
    replies = [ValueError("editor:1: reply cut off at max_tokens=4000"), '{"issues": []}']

    def chat(prompt, agent, **kw):
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(llm, "chat", chat)
    assert llm.chat_json("p", "editor:1") == {"issues": []} and not replies
