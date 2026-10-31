"""How line clips become one episode track: pauses between turns, fillers in the other speaker's pauses, cut-ins
that stop or fade the line they interrupt; then loudness. Signal processing on numpy arrays, plus ffmpeg for decoding,
speed and loudness."""
import json
import random
import subprocess

import numpy as np

RATE = 24000
GAP_TURN, GAP_SEGMENT = 0.25, 0.8  # pause between lines when none is given (tests), and between segments
# Pauses between lines of a segment, in seconds, on top of the ~0.1 s of quiet each clip keeps at its ends. Negative:
# the reply starts that much before the last line ends. ponytail: ranges guessed by ear, averaging the old fixed 0.25 s;
# fit them to gaps measured in real two-person conversations if the rhythm still sounds off.
SAME_SPEAKER = (0.3, 0.6)  # the same speaker going on after a filler: a breath
REPLY = [(0.12, (-0.3, -0.12)), (0.68, (0.05, 0.35)), (0.20, (0.4, 0.9))]  # (share, range): early start, quick, a think
LOUDNESS, PEAK = -19, -1.5  # LUFS: -19 for mono plays like the usual podcast -16 for stereo; peaks stay below -1.5 dBFS
# Overlaps (line modes, see episode.py). ponytail: fixed timings; anchor cut-ins to word timings from the TTS/ASR
# if they land awkwardly.
OVERLAP = {"cut": 0.5, "fade": 1.0}  # a cut-in starts this many seconds before the interrupted line ends
CUT_KEEP = 0.12  # with a direct cut, the interrupted line keeps sounding this long under the cut-in, then stops
BACKCHANNEL_AT, BACKCHANNEL_GAIN = 0.6, 0.6  # a backchannel goes in the pause nearest 60% into the line, a bit quieter
PAUSE = 0.2  # a quiet stretch this long is a pause (real TTS: 0.2-1 s at clause breaks; ~0.1 s gaps are consonants)


def load_clip(path, speed=1.0):
    """A line's samples, sped up by `speed` without changing pitch, trimmed and level-matched."""
    tempo = ["-af", f"atempo={speed}"] if speed != 1 else []
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), *tempo, "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    loud = np.flatnonzero(np.abs(x) > 0.02)  # trim the clip's own leading/trailing silence
    if loud.size:
        pad = int(0.05 * RATE)
        x = x[max(0, loud[0] - pad): loud[-1] + pad]
    rms = float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0
    return np.clip(x * (0.1 / rms), -1, 1) if rms > 0 else x  # level-match lines (~ -20 dBFS)


def _pause_near(x, at, earliest):
    """Start (sample) of the pause nearest `at` (a fraction of the line), at or after `earliest` and before the last
    10% of the line; None if there is none."""
    f = int(0.02 * RATE)
    n = len(x) // f
    quiet = np.sqrt((x[: n * f].reshape(n, f) ** 2).mean(1)) < 0.015  # lines are level-matched to rms 0.1
    edges = np.diff(np.concatenate([[0], quiet.astype(np.int8), [0]]))
    runs = zip(np.flatnonzero(edges == 1) * f, np.flatnonzero(edges == -1) * f)
    ok = [s for s, e in runs if e - s >= PAUSE * RATE and earliest <= s <= 0.9 * len(x)]
    return min(ok, key=lambda s: abs(s - at * len(x)), default=None)


def pauses(lines, seed):
    """lines: [(speaker, mode)] in script order -> the pause before each line (see REPLY). Each line's pause comes from
    the episode seed and its position, so building the track again keeps the same rhythm."""
    out, floor = [], None
    for i, (speaker, mode) in enumerate(lines):
        rng = random.Random(f"{seed}|{i}")
        lo, hi = SAME_SPEAKER
        if speaker != floor:
            r = rng.random()
            for share, (lo, hi) in REPLY:
                if r < share:
                    break
                r -= share
        out.append(rng.uniform(lo, hi))
        floor = speaker if mode != "backchannel" else floor
    return out


def mix(clips, gaps=None):
    """clips: [(segment, mode, samples)] in script order -> (track, spans), spans[i] = (start, end) of clip i in
    seconds. Normal lines follow each other after gaps[i] (default GAP_TURN; negative overlaps the last line's end).
    A backchannel plays in a pause of the line holding the floor, which carries on. A cut-in starts before that line
    ends, and the line then stops dead (cut) or fades out underneath (fade). Nothing overlaps across segments."""
    placed, floor, end, seg0 = [], None, 0, None  # placed: [(start sample, samples)]; floor: index into placed
    bc_from = 0  # the next backchannel starts after the last one on the same line ends
    for i, (seg, mode, x) in enumerate(clips):
        if seg != seg0:
            floor = None
        if mode == "backchannel" and floor is not None:
            fs, fx = placed[floor]
            p = _pause_near(fx, BACKCHANNEL_AT, bc_from)
            k = p + int(0.08 * RATE) if p is not None else max(int(BACKCHANNEL_AT * len(fx)), bc_from)
            placed.append((fs + k, x * BACKCHANNEL_GAIN))
            bc_from, end = k + len(x), max(end, fs + k + len(x))
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
        elif not placed:
            start = 0
        elif seg != seg0:
            start = end + int(RATE * GAP_SEGMENT)
        else:  # an early start never begins before the line it overlaps
            start = max(placed[floor][0], end + int(RATE * (gaps[i] if gaps else GAP_TURN)))
        placed.append((start, x))
        floor, end, seg0, bc_from = len(placed) - 1, start + len(x), seg, 0
    out = np.zeros(max((s + len(x) for s, x in placed), default=0), np.float32)
    for s, x in placed:
        out[s:s + len(x)] += x
    return np.clip(out, -1, 1), [(s / RATE, (s + len(x)) / RATE) for s, x in placed]


def normalize(src, dst):
    """The wav src at LOUDNESS (EBU R128), written to the wav dst: one gain for the whole episode, and a limiter that
    only touches the odd peak above PEAK, so the speech keeps its own dynamics."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", "loudnorm=print_format=json",
                          "-f", "null", "-"], capture_output=True, text=True, check=True).stderr
    measured = json.loads(err[err.rindex("{"):])["input_i"]
    f = "anull" if measured == "-inf" else (  # silence: nothing to measure
        f"volume={LOUDNESS - float(measured):.2f}dB,alimiter=limit={10 ** (PEAK / 20):.4f}:level=false")
    # ponytail: alimiter delays everything by its 5 ms attack (ffmpeg 4.4 has no latency option); far below what the
    # line marks on the Audio tab can show. Compensate with atrim if timings ever need to be sample-exact.
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", f, str(dst)], check=True)
