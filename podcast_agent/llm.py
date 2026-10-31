"""Thin client for any OpenAI-compatible chat endpoint: OpenRouter, a local vLLM server, or the course API.

Settings: LLM_BASE_URL, LLM_MODEL, LLM_API_KEY (config.py). Only plain chat completions are used,
so nothing depends on the endpoint supporting tool calling or JSON mode.
"""
import json
import threading
import time

from openai import OpenAI

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL as MODEL

# max_retries: hosted APIs such as OpenRouter answer 429 when too many calls arrive at once (research and review run
# up to four in parallel); the client waits and retries, longer each time
_client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, timeout=900, max_retries=5)
_lock = threading.Lock()


def chat(prompt, agent, temperature=0.7, max_tokens=4000, log=None):
    """log: optional path; every call is appended there as one JSON line."""
    t = time.time()
    r = _client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}],
                                        temperature=temperature, max_tokens=max_tokens)
    if not r.choices:  # some providers answer an upstream error this way instead of with an error status
        raise ValueError(f"{agent}: the model returned no reply")
    out, finish = r.choices[0].message.content or "", r.choices[0].finish_reason
    if log:
        rec = {"agent": agent, "model": MODEL, "prompt": prompt, "output": out, "finish": finish,
               "tokens_in": r.usage and r.usage.prompt_tokens, "tokens_out": r.usage and r.usage.completion_tokens,
               "seconds": round(time.time() - t, 1)}
        with _lock, open(log, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if finish == "length":  # usually the model looping; callers treat it like an unreadable reply
        raise ValueError(f"{agent}: reply cut off at max_tokens={max_tokens}")
    return out


def parse_json(text):
    """First JSON object in the reply (tolerates ```json fences and surrounding prose)."""
    i = text.find("{")
    if i < 0:
        raise ValueError("no JSON object in reply")
    return json.JSONDecoder().raw_decode(text[i:])[0]


def chat_json(prompt, agent, **kw):
    try:
        return parse_json(chat(prompt, agent, **kw))
    except ValueError as e:  # cut off or not JSON: one retry, telling the model what went wrong
        out = chat(f"{prompt}\n\nYour previous reply was not valid JSON ({e}). Reply with only the JSON object.",
                   agent, **kw)
        return parse_json(out)
