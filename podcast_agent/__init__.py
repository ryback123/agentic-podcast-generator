"""Agentic podcast generator.

The agents hand one episode along:
  producer    agents/producer.py    plans the cast, segments and research questions
  researcher  agents/researcher.py  searches and reads the web (agents/search.py) for a sourced fact sheet
  writer      agents/writer.py      writes each segment; critics (agents/checks.py, a fact-checker, an editor)
                                    send it back for fixes
  audio       audio/                one TTS clip per line, mixed into one episode file

pipeline.py runs them in order. The web app (web/) and the command line (__main__.py) start them.
Every step reads and saves the episode's episode.json (episode.py).
"""
