"""Mixing line clips into an episode, with synthetic clips, and what is sent to the TTS (a fake client)."""
import io
import json
import subprocess
import wave
from types import SimpleNamespace

import numpy as np

from podcast_agent.audio import tts
from podcast_agent.audio.mix import BACKCHANNEL_GAIN, RATE as R, _pause_near, load_clip, mix, modes, pauses
from podcast_agent.audio.tts import lines, stitch
from podcast_agent.config import parse_voices

ONE = np.full(R, 0.1, np.float32)  # a 1 s "line" of constant level


def track(clips, gaps=None):
    return mix(clips, gaps)[0]


def loudness(path):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "loudnorm=print_format=json",
                          "-f", "null", "-"], capture_output=True, text=True, check=True).stderr
    return float(json.loads(err[err.rindex("{"):])["input_i"])


def test_stitch_writes_the_episode(tmp_path):
    ep = {"id": "test", "dir": str(tmp_path), "log": [], "request": {"seed": 7},
          "plan": {"title": "A; test", "segments": [{"title": "शुरुआत", "turns": [["A", "one", ""], ["B", "two", ""]]},
                                                    {"title": "End", "turns": [["A", "three", ""]]}]},
          "audio": {"voices": {"A": "v1", "B": "v2"}, "takes": {}}}
    (tmp_path / "audio").mkdir()
    for ln in lines(ep):  # 0.5 s tone with 0.2 s silence on each side, at 16 kHz to exercise resampling
        t = np.arange(int(0.5 * 16000)) / 16000
        tone = np.concatenate([np.zeros(3200), 0.3 * np.sin(2 * np.pi * 220 * t), np.zeros(3200)])
        with wave.open(str(tmp_path / ln["file"]), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
            w.writeframes((tone * 32767).astype(np.int16).tobytes())
    stitch(ep)
    built, gap = ep["audio"]["episode"], pauses([("A", ""), ("B", ""), ("A", "")], 7)[1]
    secs = built["seconds"]
    assert abs(secs - (3 * 0.6 + gap + 0.8)) < 0.1, secs  # 3 trimmed clips (~0.6 s each), B's pause, a segment gap
    assert [c["title"] for c in built["chapters"]] == ["शुरुआत", "End"] and built["chapters"][0]["start"] == 0
    assert [f for f, *_ in built["times"]] == [ln["file"] for ln in lines(ep)]
    assert built["chapters"][1]["start"] == built["times"][2][1]  # the second segment starts with its first line
    assert abs(loudness(tmp_path / "episode.wav") + 19) < 1  # podcast loudness for mono, whatever the clips' level
    info = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(tmp_path / "episode.mp3")], capture_output=True, text=True).stderr
    assert "title           : A; test" in info and info.count("Chapter #") == 2
    assert not list(tmp_path.glob("episode.part.wav")) + list(tmp_path.glob("episode.meta"))  # no temporary files left
    stitch(ep, speed=1.25)  # each 0.5 s tone plays in ~0.4 s (its sharp edges smear a little); pauses stay as they are
    fast = ep["audio"]["episode"]
    assert fast["speed"] == 1.25 and 0.15 < secs - fast["seconds"] < 0.4, (secs, fast["seconds"])
    # a new take of a line gets a new clip file
    assert lines(ep)[0]["file"] != lines({**ep, "audio": {"voices": {"A": "v1"}, "takes": {"A|one": 1}}})[0]["file"]


def test_lines_follow_each_other_after_a_pause():
    assert len(track([(0, "", ONE), (0, "", ONE)])) == int(2.25 * R)
    out, spans = mix([(0, "", ONE), (0, "", ONE)], [0, -0.2])  # a reply that starts 0.2 s early overlaps the end
    assert len(out) == int(1.8 * R) and spans == [(0, 1), (0.8, 1.8)] and abs(out[int(0.9 * R)] - 0.2) < 1e-6


def test_pauses_vary_but_stay_put():
    talk = [("A", ""), ("B", "")] * 200
    p = pauses(talk, 3)
    assert p == pauses(talk, 3) and p != pauses(talk, 4)  # the same each build of an episode
    median = sorted(p)[len(p) // 2]
    assert min(p) >= 0.1 and 0.35 < median < 0.55 and max(p) <= 1.4  # like real handovers (median 0.46), none early
    after_filler = pauses([("A", ""), ("B", "backchannel"), ("A", "")] * 50, 3)[2::3]
    assert min(after_filler) >= 0.2  # A still holds the floor: carrying on after a filler is a breath, never overlap


def test_filler_goes_in_a_pause_of_the_line_it_reacts_to():
    bc = track([(0, "", ONE), (0, "backchannel", ONE[: R // 4]), (0, "", ONE)])
    assert len(bc) == int(2.25 * R)  # the next line still waits for the line holding the floor
    assert abs(bc[int(0.5 * R)] - 0.1 * (1 + BACKCHANNEL_GAIN)) < 1e-6  # no pause in that line: at 40%, quieter
    hm, gap = ONE[: R // 4], np.zeros(int(0.3 * R), np.float32)
    talk = np.concatenate([ONE, gap, ONE, ONE])  # 3.3 s line with one pause, at 1.0 s
    two = track([(0, "", talk), (0, "backchannel", hm), (0, "backchannel", hm)])
    assert len(two) == len(talk) and abs(two[int(1.2 * R)] - 0.1 * BACKCHANNEL_GAIN) < 1e-6  # 1st in the pause, alone
    assert abs(two[int(1.45 * R)] - 0.1 * (1 + BACKCHANNEL_GAIN)) < 1e-6  # 2nd: no pause left, so after the 1st (1.33 s)
    assert _pause_near(np.concatenate([ONE, gap[: R // 10], ONE]), 0.5, 0) is None  # 0.1 s gaps are not pauses


def test_cut_ins_overlap_the_last_words_of_the_line_they_interrupt():
    TWO = np.full(2 * R, 0.1, np.float32)
    cut = track([(0, "", TWO), (0, "cut", ONE)])
    assert len(cut) == int(2.7 * R)  # starts 0.3 s before line 1 ends: both heard together for 0.3 s
    assert abs(cut[int(1.8 * R)] - 0.2) < 1e-6 and abs(cut[int(2.1 * R)] - 0.1) < 1e-6  # line 1 plays to its end
    # Opening Hook 5-6 of the Poland episode: the line pauses before its last word, the cut-in after its first, so near
    # the end they are hardly heard together; the cut-in starts 0.8 s before the end, where they are
    q = lambda s: np.zeros(int(s * R), np.float32)  # noqa: E731
    line = np.concatenate([TWO[: int(1.4 * R)], q(0.4), ONE[: int(0.2 * R)]])
    cutin = np.concatenate([ONE[: int(0.3 * R)], q(0.4), ONE])
    assert abs(mix([(0, "", line), (0, "cut", cutin)])[1][1][0] - 1.2) < 1e-6
    fade = track([(0, "", TWO), (0, "fade", ONE)])  # starts 0.6 s before line 1 ends
    assert len(fade) == int(2.4 * R) and abs(fade[int(1.5 * R)] - 0.2) < 1e-3  # both at full for half the overlap
    assert abs(fade[int(1.85 * R)] - 0.15) < 1e-3 and abs(fade[int(2.2 * R)] - 0.1) < 1e-3  # then line 1 fades out
    assert len(track([(0, "", ONE), (0, "fade", ONE)])) == int(1.5 * R)  # short line: cut-in no earlier than halfway


def test_only_a_line_cut_off_with_a_dash_is_talked_over():
    lines = [("", "So the bank checks the—"), ("cut", "the PIN?"), ("fade", "Right, and then"), ("backchannel", "hmm"),
             ("cut", "But—"), ("fade", "Wait")]
    assert modes(lines) == ["", "cut", "", "backchannel", "", "fade"]  # a question is answered, not talked over
    assert modes([("", "So who removed them?"), ("backchannel", "हाँ।")]) == ["", ""]  # a filler answering it waits too
    assert modes([("", "बस तमाशा देखती रह जाएगी!"), ("backchannel", "True.")]) == ["", ""]  # one phrase: after it
    assert modes([("", "हाँ, वो अब Prime Minister हैं। पर problem ये है"), ("backchannel", "हम्म")]) == ["", "backchannel"]


def test_a_filler_after_a_cut_in_waits_for_its_speaker_to_finish():
    # Chaos 17-19 (Poland): Rahul cuts in on Ananya's line, Ananya's filler goes in his line; at 40% of it she would
    # still be saying her own line
    TWO = np.full(2 * R, 0.1, np.float32)
    spans = mix([(0, "", TWO), (0, "fade", ONE), (0, "backchannel", ONE[: R // 4])])[1]
    assert spans[1][0] == 1.4 and abs(spans[2][0] - 2.1) < 1e-6  # not at 1.8 s: line 1 runs to 2.0 s, then a breath


def test_a_clip_cut_off_mid_sound_fades_out(tmp_path):
    t = np.arange(R) / R  # 1 s tone that stops at full swing, as the TTS service's clips often do
    with wave.open(str(tmp_path / "c.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(R)
        w.writeframes((0.3 * np.sin(2 * np.pi * 220 * t + 1) * 32767).astype(np.int16).tobytes())
    x = load_clip(tmp_path / "c.wav")
    assert abs(x[-1]) < 1e-3 and np.abs(x[-int(0.1 * R):-int(0.08 * R)]).max() > 0.1  # no click; full until the end


def test_no_overlap_across_segments():
    assert len(track([(0, "", ONE), (1, "cut", ONE)])) == int(2.8 * R)
    assert len(track([(0, "cut", ONE)])) == R  # nothing to cut into: plays as a normal line


def test_voices_carry_gender_and_language():
    assert parse_voices(" Amit:male:hi, Kavya:female:hi ,plain,") == {
        "Amit": {"gender": "male", "lang": "hi"}, "Kavya": {"gender": "female", "lang": "hi"}, "plain": {"gender": "", "lang": ""}}


def test_each_line_is_sent_in_the_episode_language(tmp_path, monkeypatch):
    """Bodhan's indic-speak reads the language from instructions, a JSON string."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(R)
        w.writeframes((0.3 * np.sin(2 * np.pi * 220 * np.arange(R // 2) / R) * 32767).astype(np.int16).tobytes())
    calls = []

    class Speech:
        def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(content=buf.getvalue())

    monkeypatch.setattr(tts, "_client", SimpleNamespace(audio=SimpleNamespace(speech=Speech())))
    ep = {"id": "t", "dir": str(tmp_path), "log": [], "request": {"lang": "ta"},
          "plan": {"segments": [{"turns": [["A", "வணக்கம்", ""], ["B", "training-ஆ?", ""]]}]}}
    tts.synthesize(ep, {"A": "Arun", "B": "Anitha"})
    assert sorted(c["voice"] for c in calls) == ["Anitha", "Arun"]
    assert {c["instructions"] for c in calls} == {'{"lang": "ta"}'} and ep["audio"]["episode"]["seconds"] > 0.5
