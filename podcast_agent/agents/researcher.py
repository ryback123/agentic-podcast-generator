"""Researcher agent: a tool loop (search / read / done) that builds a sourced fact sheet for the research questions.
Its tools are in search.py."""
import json
from concurrent.futures import ThreadPoolExecutor

from ..episode import ask, log
from ..languages import LANGS
from . import search
from .prompts import NOTES, RESEARCHER


def take_notes(ep, hit):
    try:
        text = search.read_page(hit)
    except (OSError, ValueError, KeyError) as e:  # tool errors are reported back to the agent
        return [], f"could not read: {e}"
    if len(text.strip()) < 80:
        return [], "page has no readable text"
    qs = "\n".join(f"{q}: {t}" for q, t in ep["questions"].items())
    try:
        out = ask(ep, NOTES.format(questions=qs, title=hit["title"], text=text), "notes", json_reply=True, temperature=0.2)
    except ValueError:  # reply was not JSON twice; the raw replies are in calls.jsonl
        return [], "could not extract facts from this page"
    facts = []
    for f in out.get("facts", []):
        qid = str(f.get("q", "")).strip()
        qid = qid if qid.startswith("Q") else f"Q{qid}"
        if qid in ep["questions"] and f.get("fact"):
            facts.append({"q": qid, "fact": f["fact"], "source": hit["title"], "url": hit["url"]})
    return facts, None


def research(ep, max_steps=20):
    """Tool loop: the agent picks search / read / done until questions are covered. Starts a fresh fact sheet."""
    plan, qs = ep["plan"], ep["questions"]
    ep["facts"] = []
    name, _, wiki = LANGS[ep["request"]["lang"]]
    lang_note = (f'lang is "en" or "{wiki}" ({name} Wikipedia); English usually has more detail.'
                 if wiki != "en" else 'lang must be "en".')
    wiki_note = f"Wikipedia queries are 2-4 words (a topic name, not a question); {lang_note}"
    if search.TAVILY_KEY:
        sources = '"web" | "wikipedia"'
        search_note = ('source "web" searches the whole web: best for news, statistics, recent or local topics; '
                       f'queries can be a short phrase. Source "wikipedia" is best for background. {wiki_note}')
    else:
        sources, search_note = '"wikipedia"', f"searches Wikipedia (web search is not configured). {wiki_note}"
    results, read, history, searched = {}, set(), [], set()
    credits = 0  # Tavily credits used
    for step in range(1, max_steps + 1):
        cov = {q: sum(f["q"] == q for f in ep["facts"]) for q in qs}
        if all(c >= 2 for c in cov.values()):
            ep["research_stats"] = {"steps": step - 1, "credits": credits}
            log(ep, "researcher", f"stop: every question has 2+ facts ({credits} search credits)")
            return
        prompt = RESEARCHER.format(
            title=plan["title"], audience=plan["audience"], lang_note=lang_note, step=step, max_steps=max_steps,
            sources=sources, search_note=search_note,
            coverage="\n".join(f"{q} [{cov[q]} facts] {t}" for q, t in qs.items()),
            history="\n".join(history[-8:]) or "none yet")
        act = ask(ep, prompt, "researcher", json_reply=True, temperature=0.3, max_tokens=500)
        tool, args = act.get("tool"), act.get("args") or {}
        if tool == "done":
            ep["research_stats"] = {"steps": step, "credits": credits}
            log(ep, "researcher", f"done: {args.get('reason', '')} ({credits} search credits)", thought=act.get("thought"))
            return
        source = args.get("source") or ("web" if search.TAVILY_KEY else "wikipedia")
        key = (args.get("query", "").lower().strip(), source, args.get("lang", "en"))
        n_words = len(args.get("query", "").split())
        if tool == "search" and n_words > 10:  # long multi-question queries return poor results and waste credits
            obs = f"query too long ({n_words} words): search for one question in at most 8 words"
        elif tool == "search" and key in searched:
            obs = "already searched; read one of the results above or try a different query"
        elif tool == "search" and source == "web" and not search.TAVILY_KEY:
            obs = 'web search is not configured; use source "wikipedia"'
        elif tool == "search":
            searched.add(key)
            try:
                if source == "web":
                    credits += 1
                    hits = search.web_search(args.get("query", ""))
                else:
                    hits = search.wiki_search(args.get("query", ""), args.get("lang", "en"))
                lines = []
                for h in hits:
                    rid = f"r{len(results) + 1}"
                    results[rid] = h
                    lines.append(f"   [{rid}] {h['title']}: {h['snippet'][:160]}")
                obs = f"{len(hits)} results\n" + "\n".join(lines) if hits else "no results"
            except (OSError, ValueError, KeyError) as e:
                obs = f"search failed: {e}"
        elif tool == "read":
            ids = args.get("ids") or [args.get("id")]
            ids = [i for i in ids if i in results and results[i]["id"] not in read][:3]
            if not ids:
                obs = "nothing to read: unknown or already-read ids"
            else:
                credits += sum(1 for i in ids if results[i]["id"].startswith("http") and not results[i].get("text"))
                with ThreadPoolExecutor(len(ids)) as ex:
                    outs = list(ex.map(lambda i: take_notes(ep, results[i]), ids))
                parts = []
                for i, (facts, err) in zip(ids, outs):
                    if not err:  # failed reads stay retryable
                        read.add(results[i]["id"])
                    for f in facts:
                        f["id"] = f"F{len(ep['facts']) + 1}"
                        ep["facts"].append(f)
                    got = sorted({f["q"] for f in facts})
                    parts.append(f"[{i}] {results[i]['title']}: " +
                                 (err or (f"added {len(facts)} facts ({', '.join(got)})" if facts else "nothing relevant")))
                obs = "; ".join(parts)
        else:
            obs = f"unknown tool {tool!r}; use search, read, or done"
        history.append(f"{step}. {tool} {json.dumps(args, ensure_ascii=False)} -> {obs}")
        log(ep, "researcher", f"{tool} {json.dumps(args, ensure_ascii=False)}", thought=act.get("thought"), result=obs)
    ep["research_stats"] = {"steps": max_steps, "credits": credits}
    log(ep, "researcher", f"stop: step budget used ({credits} search credits)")
