"""Search tools for the research agent: whole-web search via Tavily (needs TAVILY_API_KEY; 1 credit per basic
search, page text included) and Wikipedia (free, no key). Hits share one shape: {id, title, snippet, url[, text]}."""
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "")
SOCIAL = ["instagram.com", "facebook.com", "x.com", "twitter.com", "youtube.com", "tiktok.com", "pinterest.com", "reddit.com", "quora.com"]
# Wikimedia policy: identify the client with contact info, or anonymous HTTP/1.1 requests get throttled (429)
_UA = {"User-Agent": f"podcast-agent/0.1 ({os.environ.get('CONTACT_EMAIL') or 'no contact set'}) python-urllib"}
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


# ponytail: cluster DNS quirk (2026-10-22): the default IPv4+IPv6 lookup of api.tavily.com fails every time while
# IPv4-only lookups work, so resolve that one host over IPv4. Remove when the cluster resolver is fixed.
_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_tavily_v4(host, port, family=0, type=0, proto=0, flags=0):
    if host == "api.tavily.com" and family == 0:
        family = socket.AF_INET
    return _getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _getaddrinfo_tavily_v4


def _tavily(endpoint, body):
    req = urllib.request.Request(f"https://api.tavily.com/{endpoint}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {TAVILY_KEY}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def web_search(query, k=5):
    """Whole web (Tavily, basic depth = 1 credit). Page text comes back with the hit, so reading it is free."""
    out = _tavily("search", {"query": query, "max_results": k, "search_depth": "basic", "include_raw_content": True,
                             "exclude_domains": SOCIAL})
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
            text = res[0].get("raw_content") or hit.get("snippet") or ""  # e.g. scanned PDFs: keep the snippet
        return text[:max_chars]
    lang, pid = hit["id"].split(":")
    page = _api(lang, action="query", prop="extracts", explaintext=1, pageids=pid)["query"]["pages"][pid]
    return page.get("extract", "")[:max_chars]
