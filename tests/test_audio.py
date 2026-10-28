"""Mixing line clips into an episode, with synthetic clips (no TTS needed)."""
import wave
from pathlib import Path

import numpy as np

from podcast_agent.audio.mix import BACKCHANNEL_GAIN, RATE as R, _pause_near, mix
from podcast_agent.audio.tts import lines, stitch

ONE = np.full(R, 0.1, np.float32)  # a 1 s "line" of constant level


def test_stitch_writes_the_episode(tmp_path):
    ep = {"id": "test", "dir": str(tmp_path), "log": [],
          "plan": {"segments": [{"turns": [["A", "one", ""], ["B", "two", ""]]}, {"turns": [["A", "three", ""]]}]},
          "audio": {"voices": {"A": "v1", "B": "v2"}, "takes": {}}}
    (tmp_path / "audio").mkdir()
    for ln in lines(ep):  # 0.5 s tone with 0.2 s silence on each side, at 16 kHz to exercise resampling
        t = np.arange(int(0.5 * 16000)) / 16000
        tone = np.concatenate([np.zeros(3200), 0.3 * np.sin(2 * np.pi * 220 * t), np.zeros(3200)])
        with wave.open(str(tmp_path / ln["file"]), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
            w.writeframes((tone * 32767).astype(np.int16).tobytes())
    stitch(ep)
    secs = ep["audio"]["episode"]["seconds"]
    assert 2.6 < secs < 3.0, secs  # 3 trimmed clips (~0.6 s each) + one turn gap (0.25) + one segment gap (0.8)
    assert (Path(tmp_path) / "episode.mp3").stat().st_size > 1000
    # a new take of a line gets a new clip file
    assert lines(ep)[0]["file"] != lines({**ep, "audio": {"voices": {"A": "v1"}, "takes": {"A|one": 1}}})[0]["file"]


def test_lines_follow_each_other_after_a_pause():
    assert len(mix([(0, "", ONE), (0, "", ONE)])) == int(2.25 * R)


def test_filler_goes_in_a_pause_of_the_line_it_reacts_to():
    bc = mix([(0, "", ONE), (0, "backchannel", ONE[: R // 4]), (0, "", ONE)])
    assert len(bc) == int(2.25 * R)  # the next line still waits for the line holding the floor
    assert abs(bc[int(0.7 * R)] - 0.1 * (1 + BACKCHANNEL_GAIN)) < 1e-6  # no pause in that line: at 60%, quieter
    hm, gap = ONE[: R // 4], np.zeros(int(0.3 * R), np.float32)
    talk = np.concatenate([ONE, gap, ONE, ONE])  # 3.3 s line with one pause, at 1.0 s
    two = mix([(0, "", talk), (0, "backchannel", hm), (0, "backchannel", hm)])
    assert len(two) == len(talk) and abs(two[int(1.2 * R)] - 0.1 * BACKCHANNEL_GAIN) < 1e-6  # 1st in the pause, alone
    assert abs(two[int(2.1 * R)] - 0.1 * (1 + BACKCHANNEL_GAIN)) < 1e-6  # 2nd: no pause left, so at 60% (1.98 s)
    assert _pause_near(np.concatenate([ONE, gap[: R // 10], ONE]), 0.5, 0) is None  # 0.1 s gaps are not pauses


def test_cut_ins_stop_or_fade_the_line_they_interrupt():
    cut = mix([(0, "", ONE), (0, "cut", ONE)])
    assert len(cut) == int(1.5 * R)  # starts 0.5 s before line 1 ends
    assert abs(cut[int(0.55 * R)] - 0.2) < 1e-6 and abs(cut[int(0.7 * R)] - 0.1) < 1e-6  # both, then line 1 stops
    fade = mix([(0, "", np.full(2 * R, 0.1, np.float32)), (0, "fade", ONE)])  # 2 s line, cut-in 1 s before its end
    assert len(fade) == 2 * R and abs(fade[int(1.5 * R)] - 0.15) < 1e-3 and abs(fade[-1] - 0.1) < 1e-3  # fades under
    assert len(mix([(0, "", ONE), (0, "fade", ONE)])) == int(1.5 * R)  # short line: cut-in no earlier than halfway


def test_no_overlap_across_segments():
    assert len(mix([(0, "", ONE), (1, "cut", ONE)])) == int(2.8 * R)
    assert len(mix([(0, "cut", ONE)])) == R  # nothing to cut into: plays as a normal line
