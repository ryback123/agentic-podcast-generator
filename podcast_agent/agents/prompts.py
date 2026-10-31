"""Every prompt the agents use, plus how episode data is shown to the model. Placeholders in {braces} are filled
in by the agent that uses the prompt; doubled braces are literal JSON braces."""
from ..episode import label

# The producer picks one format and one opening hook per episode, at random
FORMATS = [
    "two friends chatting; one knows the topic well, the other is curious",
    "a host interviewing an expert guest",
    "co-hosts exploring the topic together, sometimes disagreeing",
    "myth-busting: each main segment tests a common belief",
    "story-led: each main segment opens with a real example or case",
    "a panel with different viewpoints",
]
HOOKS = ["a surprising fact", "a short story or scene", "a question listeners have probably wondered about",
         "a common misconception", "a relatable everyday situation"]


# ---------------------------------------------------------------- producer
PRODUCER = """You are the producer of an audio podcast. Plan one episode.

Topic: {topic}
Notes from the requester: {notes}
Language: {lang}. {lang_rule}
Number of speakers: exactly {n}
Target length: {minutes} minutes

Plan:
- Cast: exactly {n} speakers. For each: a first name common among {lang} speakers, written in Latin letters only (it is the speaker label); gender (female or male; mix genders); a role (for example host, co-host, expert, guest, skeptic); what they know about the topic; a persona: two to four sentences on who they are and how they speak (attitude, energy, sentence length, humour, how they explain, ask or push back), describing habits rather than catchphrases or example words, which get overused. Give the cast useful contrast: someone who explains and someone who asks what the listener would ask{extra_role}. List the host first: they open the episode, introduce the others and steer the conversation. Match the audience level in the requester's notes; with no level given, aim at curious adults with no background.
- Format for this episode: {fmt}. Opening hook: {hook}.
- Exactly {k} segments whose minutes add up to {minutes}: an opening (hook, then the speakers introduce themselves; about 1 minute), {main} main segments, and a closing (recap and one memorable takeaway; about 1 minute). Each main segment has one clear goal and builds on the one before.
- For each main segment, one to three research questions whose answers (facts, numbers, real examples, stories) would make the segment concrete and correct. The opening and closing have no questions.

Write the plan in English, except the title, which is in {lang} ({script} script).
Reply with only this JSON:
{{"title": str, "audience": str, "format": str,
 "speakers": [{{"name": str, "gender": "female" | "male", "role": str, "knowledge": str, "style": str}}],
 "segments": [{{"title": str, "goal": str, "minutes": number, "questions": [str]}}]}}"""


# Three lines in one speaker's persona, so a persona can be tried before any script is written
SAMPLE = """You are writing for one speaker of the podcast episode "{title}" (topic: {topic}; audience: {audience}).
Speaker: {name} ({gender}, {role}). Knows: {knowledge}
Persona: {persona}
Language: {lang}. {lang_rule}

Write three short lines this speaker might say in the episode: one explaining something, one reacting to what someone else just said, and one asking a question or pushing back. Let the persona show in word choice, sentence length and attitude; do not repeat a signature phrase. Write numbers as words.
Reply with only the three lines, one per line, without the speaker's name."""


# ---------------------------------------------------------------- researcher
RESEARCHER = """You are the research agent for the podcast episode "{title}" (audience: {audience}).
Find facts that answer the research questions. Facts are saved only from pages you read; do not rely on memory.

Research questions and facts found so far:
{coverage}

Your recent actions:
{history}

Tools:
- search {{"query": str, "source": {sources}, "lang": str}}: {search_note}
- read {{"ids": [str]}}: reads up to three search results by id (like "r3"); facts relevant to the questions are extracted and saved.
- done {{"reason": str}}: stops research. Use it when every question has at least two facts, or when more searching is not helping.

How to research well:
- One search targets one question. Keep queries short: at most 8 words for the web, 2-4 words for Wikipedia.
- After a search, read the one to three most promising results before searching again.
- If two searches for a question find nothing useful, move on to other questions; some questions can stay thin.

Step {step} of {max_steps}.
Reply with only JSON: {{"thought": "<one sentence>", "tool": "search" | "read" | "done", "args": {{...}}}}"""

NOTES = """Extract facts from this page that help answer the research questions.

Research questions:
{questions}

Page: {title}
---
{text}
---
Each fact is one self-contained English sentence that keeps numbers, names, and dates exactly as on the page. Use only what the page says. Skip anything that does not help answer a question. At most 8 facts.
Reply with only JSON: {{"facts": [{{"q": "Q1", "fact": str}}]}}"""


# ---------------------------------------------------------------- writer
# CONTEXT is shared by WRITER and REVISE: the episode, this segment, its facts, and the writing rules.
CONTEXT = """Episode: "{title}". Format: {format}. Audience: {audience}.
Cast:
{cast}

Outline:
{outline}

This segment: "{seg_title}". Goal: {goal}
Length: about {chars} characters of dialogue (about {minutes} minutes spoken), roughly {t_lo}-{t_hi} turns, not counting backchannels.
{position}

Facts to use (use what fits; never mention fact ids or sources):
{facts}
Do not state any fact, number, name, or date that is not in this list or common knowledge.
{prev}
Language: {lang}. {lang_rule}
Rules:
- Write every number, date, unit, and symbol as spoken words (no digits, %, /, & and so on). Apostrophes and ordinary punctuation are fine; in English use contractions (it's, don't, you're).
- No markdown, stage directions, sound effects, or emojis.
- Short turns: one to three sentences, sometimes just a quick reaction. Vary turn lengths.
- Speakers react to what was just said, ask follow-up questions, sometimes disagree, and use concrete examples and analogies that suit the audience.
- Each speaker talks like their persona in the cast: it shows in word choice, sentence length, attitude and how they react. Show it, never announce it, and do not repeat any phrase as a signature.
- The facts come from sources written for experts. Explain each technical term in everyday words when it first comes up, or leave it out; keep only the few terms the listener needs.
- Do not start turns with stock reactions ({banned}, or the same words in {lang}) and do not reuse the same reaction within the episode. Vary how turns begin: no single word (like yes, so, but, or meaning) should start more than one turn in ten.
- Speakers never say their own name, except when introducing themselves in the opening.
- Whenever a speaker's name is said, write it in Latin letters with normal capitalisation (Riya, not RIYA), even inside {lang} sentences.
- Use the right grammatical gender for each speaker (see the cast).
- Make it sound live. In real conversation the listener reacts with a word or two every ten seconds or so while the other is still talking (like "hmm", "right" or "I see", in {lang} or English as people really say it). Write it as its own line straight after the line it reacts to: NAME (backchannel): text. About {backchannels} in this segment, spread out, at most one after any line, varied, never by the speaker of the line they react to.
- Real speakers rarely interrupt: about one handover in ten. {overlaps} To write one, end the interrupted line mid-sentence with a dash (—), then tag the next line NAME (cuts in): text for a sharp interruption (disagreement, alarm), or NAME (talks over): text when the first speaker trails off underneath (eager agreement, finishing their thought).{note}"""

WRITER = """You are writing one segment of a podcast episode as spoken dialogue, not an essay.

{ctx}

Output only dialogue lines, one turn per line, as NAME: text (or NAME (tag): text for the tags above), using only these names: {names}."""

REVISE = """You are revising one segment of a podcast episode.

{ctx}

Current draft:
{draft}

Reviewers found these problems:
{issues}

Rewrite the segment so every problem is fixed; keep what works. Output the full revised segment only, one turn per line, as NAME: text (or NAME (tag): text for the tags above), using only these names: {names}."""


# ---------------------------------------------------------------- critics
FACTCHECK = """You are a strict fact-checker for one segment of a podcast for {audience}.
Check every factual claim in the segment (numbers, dates, names, how things work, causes and effects) against the facts list. Opinions, questions, and everyday common knowledge are fine.

Facts:
{facts}

Segment:
{numbered}

Report each claim that contradicts the facts, and each specific fact (a number, date, name, or technical detail) that the facts list does not support.
Fix each one by changing as few words as possible. "find" is the exact words to change, copied character for character from that line; "replace" is what the line should say instead, in the same language mix, with numbers as words ("" removes the words).
Severity: "major" if a listener would be misinformed (wrong or invented fact); "minor" for wording that is loose but not wrong.
Reply with only JSON: {{"issues": [{{"line": int, "severity": "major" | "minor", "claim": str, "problem": str, "find": str, "replace": str}}]}} (an empty list if everything is supported)."""

EDITOR = """You are the story editor of a podcast for {audience}. This is {role}. Review it and report only concrete problems of these kinds:
1. Level: too advanced or too childish for the audience, or a technical term left unexplained.
2. Speech: lines that sound written rather than spoken, lecture-like monologues, or unnatural language. Target language: {lang}. {lang_rule}
3. Words: {words_rule}.
4. Characters: a speaker acting outside their role or knowledge, or sounding unlike their persona. Cast:
{cast}
5. Flow: the segment misses its goal ("{goal}"), repeats earlier segments (including ending the same way they did), or does not follow from the previous segment.
Fixed rules the script must keep (never suggest breaking them): numbers and symbols written as words; short turns; lines tagged (backchannel), (cuts in) or (talks over) are deliberate overlaps, and a line cut off mid-sentence before a cut-in is deliberate.

Problems the code checks found, to fix as well (each one is major; start its problem with "Code check:"):
{code}

Earlier segments covered:
{covered}

Segment:
{numbered}

Fix each problem by changing as few words as possible. "find" is the exact words to change, copied character for character from that line; "replace" is the new words ("" removes them). To explain a technical term, add a few everyday words or swap it for a plain one. Use "find": "" only for a Flow problem that small edits cannot fix; the segment is then rewritten.
Severity: "major" if a typical listener would notice it and it hurts the episode; "minor" for polish. Do not report taste-level rewording as major.
Reply with only JSON: {{"issues": [{{"line": int, "severity": "major" | "minor", "problem": str, "find": str, "replace": str}}]}} with at most eight issues, most important first; an empty list if the segment works."""


def fact_lines(facts):
    return "\n".join(f"{f['id']}: {f['fact']}" for f in facts) or "(none)"


def numbered(turns):
    return "\n".join(f"{k}. {label(sp, mode)}: {tx}" for k, (sp, tx, mode) in enumerate(turns, 1))
