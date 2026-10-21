"""Search tools for the research agent: whole-web search via Tavily (needs TAVILY_API_KEY; 1 credit per basic
search, page text included) and Wikipedia (free, no key). Hits share one shape: {id, title, snippet, url[, text]}."""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "")
_UA = {"User-Agent": "podcast-agent/0.1 (course project)"}
# ponytail: per-process throttle for Wikipedia's anonymous limits; drop it with a paid search API
_MIN_INTERVAL, _last, _lock = 1.0, [0.0], threading.Lock()


def _api(lang, **params):
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json"})
    for attempt in range(4):
        with _lock:
            time.sleep(max(0.0, _last[0] + _MIN_INTERVAL - time.time()))
            _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 2 ** (attempt + 1)))  # rate limited: back off


def _tavily(endpoint, body):
    req = urllib.request.Request(f"https://api.tavily.com/{endpoint}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {TAVILY_KEY}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def web_search(query, k=5):
    """Whole web (Tavily, basic depth = 1 credit). Page text comes back with the hit, so reading it is free."""
    out = _tavily("search", {"query": query, "max_results": k, "search_depth": "basic", "include_raw_content": True})
    return [{"id": h["url"], "title": h.get("title") or h["url"], "snippet": h.get("content") or "", "url": h["url"],
             "text": h.get("raw_content") or ""} for h in out.get("results", [])]


def wiki_search(query, lang="en", k=5):
    hits = _api(lang, action="query", list="search", srsearch=query, srlimit=k)["query"]["search"]
    return [{"id": f"{lang}:{h['pageid']}", "title": h["title"],
             "snippet": re.sub(r"<[^>]+>", "", h["snippet"]),
             "url": f"https://{lang}.wikipedia.org/?curid={h['pageid']}"} for h in hits]


def read_page(hit, max_chars=24000):
    """Text of a search hit. Web hits normally carry it; otherwise Tavily extract (1 credit per 5 pages)."""
    # ponytail: keeps the first max_chars only; chunk + pick relevant parts if facts sit deep in long pages
    if hit["id"].startswith("http"):
        text = hit.get("text")
        if not text:
            res = _tavily("extract", {"urls": [hit["url"]]}).get("results") or [{}]
            text = res[0].get("raw_content") or ""
        return text[:max_chars]
    lang, pid = hit["id"].split(":")
    page = _api(lang, action="query", prop="extracts", explaintext=1, pageids=pid)["query"]["pages"][pid]
    return page.get("extract", "")[:max_chars]
