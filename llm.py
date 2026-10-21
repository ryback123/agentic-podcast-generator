"""Thin client for any OpenAI-compatible chat endpoint (local vLLM now, the course API later).

Config via env: LLM_BASE_URL, LLM_MODEL, LLM_API_KEY. Only plain chat completions are used,
so nothing depends on the endpoint supporting tool calling or JSON mode.
"""
import json
import os
import threading
import time

from openai import OpenAI

_client = OpenAI(base_url=os.environ.get("LLM_BASE_URL", "http://bodhanai-node004:8031/v1"),
                 api_key=os.environ.get("LLM_API_KEY", "EMPTY"), timeout=900)
MODEL = os.environ.get("LLM_MODEL", "gemma-4-31b")
_lock = threading.Lock()


def chat(prompt, agent, temperature=0.7, max_tokens=4000, log=None):
    """log: optional path; every call is appended there as one JSON line."""
    t = time.time()
    r = _client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}],
                                        temperature=temperature, max_tokens=max_tokens)
    out, finish = r.choices[0].message.content or "", r.choices[0].finish_reason
    if log:
        rec = {"agent": agent, "prompt": prompt, "output": out, "finish": finish,
               "tokens_in": r.usage.prompt_tokens, "tokens_out": r.usage.completion_tokens,
               "seconds": round(time.time() - t, 1)}
        with _lock, open(log, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if finish == "length":
        raise RuntimeError(f"{agent}: reply cut off at max_tokens={max_tokens}")
    return out


def parse_json(text):
    """First JSON object in the reply (tolerates ```json fences and surrounding prose)."""
    i = text.find("{")
    if i < 0:
        raise ValueError("no JSON object in reply")
    return json.JSONDecoder().raw_decode(text[i:])[0]


def chat_json(prompt, agent, **kw):
    out = chat(prompt, agent, **kw)
    try:
        return parse_json(out)
    except ValueError as e:  # one retry, telling the model what went wrong
        out = chat(f"{prompt}\n\nYour previous reply was not valid JSON ({e}). Reply with only the JSON object.",
                   agent, **kw)
        return parse_json(out)
