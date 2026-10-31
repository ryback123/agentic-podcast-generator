"""Audio step: one TTS call per script line, then the clips are mixed (mix.py) into episode.wav and episode.mp3,
loudness-normalised, with the segments as MP3 chapters.

TTS endpoint: OpenAI-compatible POST {TTS_BASE_URL}/audio/speech {model, voice, input, response_format, instructions},
where instructions is a JSON string {"lang": <episode language>}: Bodhan's indic-speak reads the language from there,
and servers without the field ignore it. Settings: TTS_BASE_URL, TTS_MODEL, TTS_API_KEY, TTS_VOICES (config.py).
Line audio is cached by (voice, text, take), so only changed lines are synthesized again.
"""
import hashlib
import json
import os
import re
import subprocess
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from openai import OpenAI

from ..config import TTS_API_KEY, TTS_BASE_URL, TTS_MODEL as MODEL, TTS_VOICE_INFO
from ..episode import log
from .mix import RATE, load_clip, mix, normalize, pauses

# retries back off on rate limits (Bodhan allowed 4 requests a minute per key in 2026-09) and server errors
_client = OpenAI(base_url=TTS_BASE_URL, api_key=TTS_API_KEY, timeout=600, max_retries=6) if TTS_BASE_URL else None


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


def _tts(text, voice, path, lang):
    r = _client.audio.speech.create(model=MODEL, voice=voice, input=text, response_format="wav",
                                    instructions=json.dumps({"lang": lang}))
    tmp = path.with_suffix(".part")
    tmp.write_bytes(r.content)
    os.replace(tmp, path)  # a crash never leaves a half-written clip that looks finished


# what a voice says on the Voices tab: "Hi, I am <name>!" in the voice's own language (English where there is none)
GREETINGS = {
    "en": "Hi, I am {name}!",
    "hi": "नमस्ते, मैं {name} हूँ!",
    "bn": "নমস্কার, আমি {name}!",
    "mr": "नमस्कार, मी {name} आहे!",
    "te": "నమస్కారం, నేను {name}!",
    "ta": "வணக்கம், நான் {name}!",
    "gu": "નમસ્તે, હું {name} છું!",
    "kn": "ನಮಸ್ಕಾರ, ನಾನು {name}!",
    "ml": "നമസ്കാരം, ഞാൻ {name}!",
    "or": "ନମସ୍କାର, ମୁଁ {name}!",
    "pa": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਮੈਂ {name} ਹਾਂ!",
    "as": "নমস্কাৰ, মই {name}!",
}


def sample_line(voice):
    """(text, lang) a voice says on the Voices tab."""
    lang = (TTS_VOICE_INFO.get(voice) or {}).get("lang", "")
    lang = lang if lang in GREETINGS else "en"
    return GREETINGS[lang].format(name=voice), lang


def sample(voice, path):
    text, lang = sample_line(voice)
    _tts(text, voice, path, lang)


def synthesize(ep, voices=None, speed=1.0, workers=4):
    """Synthesize every line that has no clip yet, then stitch the episode at `speed`."""
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
    lang = ep["request"]["lang"]
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(lambda ln: _tts(ln["text"], ln["voice"], run / ln["file"], lang), todo))
    stitch(ep, speed)


def new_take(ep, segment, line, speed=1.0):
    """Re-roll one line's audio (new take), then re-stitch."""
    ln = next(x for x in lines(ep) if x["segment"] == segment and x["line"] == line)
    ep["audio"]["takes"][f"{ln['speaker']}|{ln['text']}"] = ln["take"] + 1
    synthesize(ep, speed=speed)


def _meta(s):
    return re.sub(r"([=;#\\\n])", r"\\\1", s)  # escaping in ffmpeg's metadata file


def stitch(ep, speed=1.0):
    """Mix the line clips into episode.wav and episode.mp3. Records when each line plays (times: [file, start, end],
    in script order) and where each segment starts (chapters), for the Audio tab and the MP3's chapters."""
    run = Path(ep["dir"])
    all_lines = lines(ep)
    gaps = pauses([(ln["speaker"], ln["mode"]) for ln in all_lines], (ep.get("request") or {}).get("seed", 0))
    audio, spans = mix([(ln["segment"], ln["mode"], load_clip(run / ln["file"], speed)) for ln in all_lines], gaps)
    raw = run / "episode.part.wav"
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())
    normalize(raw, run / "episode.wav")
    raw.unlink()
    seconds = len(audio) / RATE
    segs = ep["plan"]["segments"]
    firsts = {ln["segment"]: k for k, ln in reversed(list(enumerate(all_lines)))}  # segment -> its first line
    chapters = [{"title": segs[i].get("title") or f"Segment {i + 1}", "start": round(spans[k][0], 2)}
                for i, k in sorted(firsts.items())]
    meta = run / "episode.meta"
    meta.write_text(f";FFMETADATA1\ntitle={_meta(ep['plan'].get('title') or '')}\n" + "".join(
        f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(c['start'] * 1000)}\nEND={int(nxt * 1000)}\ntitle={_meta(c['title'])}\n"
        for c, nxt in zip(chapters, [c["start"] for c in chapters[1:]] + [seconds])), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(run / "episode.wav"), "-i", str(meta), "-map_metadata", "1",
                    "-map_chapters", "1", "-id3v2_version", "3", "-b:a", "128k", str(run / "episode.mp3")], check=True)
    meta.unlink()
    chars = sum(len(ln["text"]) for ln in all_lines)
    ep["audio"]["episode"] = {"file": "episode.mp3", "seconds": round(seconds, 1), "built": time.time(), "speed": speed,
                              "chars_per_min": round(chars / (seconds / 60)) if seconds else None, "chapters": chapters,
                              "times": [[ln["file"], round(a, 2), round(b, 2)] for ln, (a, b) in zip(all_lines, spans)]}
    log(ep, "audio", f"episode stitched: {seconds / 60:.1f} min from {len(all_lines)} lines at {speed}x speed")
