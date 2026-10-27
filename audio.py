"""Audio stage: one TTS call per script line, then stitch the lines into one episode file.

TTS endpoint: OpenAI-compatible POST {TTS_BASE_URL}/audio/speech {model, voice, input, response_format}.
Env: TTS_BASE_URL, TTS_MODEL, TTS_API_KEY, TTS_VOICES (comma-separated voice names).
Line audio is cached by (voice, text, take), so only changed lines are synthesized again.
"""
import hashlib
import os
import subprocess
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from openai import OpenAI

from podcast import log

BASE_URL = os.environ.get("TTS_BASE_URL", "")
MODEL = os.environ.get("TTS_MODEL", "tts")
VOICES = [v.strip() for v in os.environ.get("TTS_VOICES", "").split(",") if v.strip()]
RATE = 24000
GAP_TURN, GAP_SEGMENT = 0.25, 0.8  # ponytail: fixed pauses; vary by line type if the rhythm sounds mechanical
# Overlaps (line modes, see checks.TAGS). ponytail: fixed spots and timings; anchor them to word timings
# from the TTS/ASR if a backchannel lands on speech awkwardly.
OVERLAP = {"cut": 0.5, "fade": 1.0}  # a cut-in starts this many seconds before the interrupted line ends
CUT_KEEP = 0.12  # with a direct cut, the interrupted line keeps sounding this long under the cut-in, then stops
BACKCHANNEL_AT, BACKCHANNEL_GAIN = 0.6, 0.6  # a backchannel starts 60% into the line it reacts to, a bit quieter
_client = OpenAI(base_url=BASE_URL, api_key=os.environ.get("TTS_API_KEY", "EMPTY"), timeout=600) if BASE_URL else None


def configured():
    return _client is not None


def lines(ep):
    """Script lines in order: dicts with segment, line, speaker, text, voice, take, file (relative to the run dir)."""
    a = ep.get("audio") or {}
    voices, takes = a.get("voices", {}), a.get("takes", {})
    out = []
    for i, seg in enumerate(ep["plan"]["segments"] if ep.get("plan") else []):
        for k, (sp, tx, mode) in enumerate(seg.get("turns", [])):
            voice, take = voices.get(sp), takes.get(f"{sp}|{tx}", 0)
            key = hashlib.sha1(f"{voice}|{tx}|{take}".encode()).hexdigest()[:16]
            out.append({"segment": i, "line": k, "speaker": sp, "text": tx, "mode": mode, "voice": voice, "take": take,
                        "file": f"audio/{key}.wav" if voice else None})
    return out


def _tts(text, voice, path):
    r = _client.audio.speech.create(model=MODEL, voice=voice, input=text, response_format="wav")
    tmp = path.with_suffix(".part")
    tmp.write_bytes(r.content)
    os.replace(tmp, path)  # a crash never leaves a half-written clip that looks finished


def synthesize(ep, voices=None, workers=4):
    """Synthesize every line that has no clip yet, then stitch the episode."""
    if not configured():
        raise RuntimeError("TTS is not configured (set TTS_BASE_URL)")
    a = ep.setdefault("audio", {"voices": {}, "takes": {}})
    if voices:
        a["voices"] = voices
    run = Path(ep["dir"])
    (run / "audio").mkdir(exist_ok=True)
    all_lines = lines(ep)
    if missing := sorted({ln["speaker"] for ln in all_lines if not ln["voice"]}):
        raise ValueError(f"pick a voice for {missing}")
    todo = [ln for ln in all_lines if not (run / ln["file"]).exists()]
    log(ep, "audio", f"synthesizing {len(todo)} of {len(all_lines)} lines")
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(lambda ln: _tts(ln["text"], ln["voice"], run / ln["file"]), todo))
    stitch(ep)


def new_take(ep, segment, line):
    """Re-roll one line's audio (new take), then re-stitch."""
    ln = next(x for x in lines(ep) if x["segment"] == segment and x["line"] == line)
    ep["audio"]["takes"][f"{ln['speaker']}|{ln['text']}"] = ln["take"] + 1
    synthesize(ep)


def _load(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    loud = np.flatnonzero(np.abs(x) > 0.02)  # trim the clip's own leading/trailing silence
    if loud.size:
        pad = int(0.05 * RATE)
        x = x[max(0, loud[0] - pad): loud[-1] + pad]
    rms = float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0
    return np.clip(x * (0.1 / rms), -1, 1) if rms > 0 else x  # level-match lines (~ -20 dBFS)


def mix(clips):
    """clips: [(segment, mode, samples)] in script order -> one track. Normal lines follow each other after a pause.
    A backchannel plays over the line holding the floor. A cut-in starts before that line ends, and the line then
    stops dead (cut) or fades out underneath (fade). Nothing overlaps across segments."""
    placed, floor, end, seg0 = [], None, 0, None  # placed: [(start sample, samples)]; floor: index into placed
    for seg, mode, x in clips:
        if seg != seg0:
            floor = None
        if mode == "backchannel" and floor is not None:
            fs, fx = placed[floor]
            placed.append((fs + int(BACKCHANNEL_AT * len(fx)), x * BACKCHANNEL_GAIN))
            end = max(end, placed[-1][0] + len(x))
            continue
        if mode in OVERLAP and floor is not None:
            fs, fx = placed[floor]
            k = max(len(fx) // 2, len(fx) - int(OVERLAP[mode] * RATE))  # where the cut-in starts, within the line
            fx = fx.copy()
            if mode == "cut":
                keep = min(len(fx), k + int(CUT_KEEP * RATE))
                ramp = min(keep, int(0.02 * RATE))  # 20 ms, so the stop does not click
                fx = fx[:keep]
                fx[keep - ramp:] *= np.linspace(1, 0, ramp)
            else:
                fx[k:] *= np.linspace(1, 0, len(fx) - k)
            placed[floor] = (fs, fx)
            start = fs + k
        else:
            start = end + int(RATE * (GAP_TURN if seg == seg0 else GAP_SEGMENT)) if placed else 0
        placed.append((start, x))
        floor, end, seg0 = len(placed) - 1, start + len(x), seg
    out = np.zeros(max((s + len(x) for s, x in placed), default=0), np.float32)
    for s, x in placed:
        out[s:s + len(x)] += x
    return np.clip(out, -1, 1)


def stitch(ep):
    run = Path(ep["dir"])
    all_lines = lines(ep)
    audio = mix([(ln["segment"], ln["mode"], _load(run / ln["file"])) for ln in all_lines])
    with wave.open(str(run / "episode.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(run / "episode.wav"), "-b:a", "128k",
                    str(run / "episode.mp3")], check=True)
    seconds = len(audio) / RATE
    chars = sum(len(ln["text"]) for ln in all_lines)
    ep["audio"]["episode"] = {"file": "episode.mp3", "seconds": round(seconds, 1), "built": time.time(),
                              "chars_per_min": round(chars / (seconds / 60)) if seconds else None}
    log(ep, "audio", f"episode stitched: {seconds / 60:.1f} min from {len(all_lines)} lines")


if __name__ == "__main__":  # self-test of stitching with synthetic clips (no TTS needed)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ep = {"id": "selftest", "dir": d, "log": [],
              "plan": {"segments": [{"turns": [["A", "one", ""], ["B", "two", ""]]}, {"turns": [["A", "three", ""]]}]},
              "audio": {"voices": {"A": "v1", "B": "v2"}, "takes": {}}}
        (Path(d) / "audio").mkdir()
        for ln in lines(ep):  # 0.5 s tone with 0.2 s silence on each side, at 16 kHz to exercise resampling
            t = np.arange(int(0.5 * 16000)) / 16000
            tone = np.concatenate([np.zeros(3200), 0.3 * np.sin(2 * np.pi * 220 * t), np.zeros(3200)])
            with wave.open(str(Path(d) / ln["file"]), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
                w.writeframes((tone * 32767).astype(np.int16).tobytes())
        stitch(ep)
        secs = ep["audio"]["episode"]["seconds"]
        # 3 trimmed clips (~0.6 s each) + one turn gap (0.25) + one segment gap (0.8)
        assert 2.6 < secs < 3.0, secs
        assert (Path(d) / "episode.mp3").stat().st_size > 1000
        assert lines(ep)[0]["file"] != lines({**ep, "audio": {"voices": {"A": "v1"}, "takes": {"A|one": 1}}})[0]["file"]

    R, one = RATE, np.full(RATE, 0.1, np.float32)  # 1 s "lines" of constant level
    plain = mix([(0, "", one), (0, "", one)])
    assert len(plain) == int(2.25 * R)
    bc = mix([(0, "", one), (0, "backchannel", one[: R // 4]), (0, "", one)])
    assert len(bc) == len(plain) and abs(bc[int(0.7 * R)] - 0.1 * (1 + BACKCHANNEL_GAIN)) < 1e-6  # over line 1, quieter
    cut = mix([(0, "", one), (0, "cut", one)])
    assert len(cut) == int(1.5 * R)  # starts 0.5 s before line 1 ends
    assert abs(cut[int(0.55 * R)] - 0.2) < 1e-6 and abs(cut[int(0.7 * R)] - 0.1) < 1e-6  # both, then line 1 stops
    fade = mix([(0, "", np.full(2 * R, 0.1, np.float32)), (0, "fade", one)])  # 2 s line, cut-in 1 s before its end
    assert len(fade) == 2 * R and abs(fade[int(1.5 * R)] - 0.15) < 1e-3 and abs(fade[-1] - 0.1) < 1e-3  # fades under
    assert len(mix([(0, "", one), (0, "fade", one)])) == int(1.5 * R)  # short line: cut-in no earlier than halfway
    assert len(mix([(0, "", one), (1, "cut", one)])) == int(2.8 * R)  # no overlap across segments
    assert len(mix([(0, "cut", one)])) == R  # nothing to cut into: plays as a normal line
    print("audio.py self-test OK")
