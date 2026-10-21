"""Search tool for the research agent. Wikipedia for now (free, no key); swap in a web search API
later by keeping the same two functions and result shape."""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

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


def web_search(query, lang="en", k=5):
    """-> [{id, title, snippet, url}]"""
    hits = _api(lang, action="query", list="search", srsearch=query, srlimit=k)["query"]["search"]
    return [{"id": f"{lang}:{h['pageid']}", "title": h["title"],
             "snippet": re.sub(r"<[^>]+>", "", h["snippet"]),
             "url": f"https://{lang}.wikipedia.org/?curid={h['pageid']}"} for h in hits]


def read_page(page_id, max_chars=24000):
    # ponytail: truncates long pages to the first max_chars; chunk + pick relevant parts if facts sit deep in pages
    lang, pid = page_id.split(":")
    page = _api(lang, action="query", prop="extracts", explaintext=1, pageids=pid)["query"]["pages"][pid]
    return page.get("extract", "")[:max_chars]
