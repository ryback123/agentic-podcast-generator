"""Search tool for the research agent. Wikipedia for now (free, no key); swap in a web search API
later by keeping the same two functions and result shape."""
import json
import re
import urllib.parse
import urllib.request

_UA = {"User-Agent": "podcast-agent/0.1 (course project)"}


def _api(lang, **params):
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=20) as r:
        return json.load(r)


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
