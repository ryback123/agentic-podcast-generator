---
version: 1
slug: "podcast-agent-web-static-index-html"
primary_target: "podcast_agent/web/static/index.html"
related_targets: ["podcast_agent/web/static/app.js","podcast_agent/web/static/style.css"]
---

# Surface brief: Podcast Studio web app (all screens)

Scope: the whole web app in `podcast_agent/web/static/` (New, Episodes, Voices, Settings, and an episode's Plan,
Research, Script and Audio steps). Visitor mode: Operate. Audience and job: see PRODUCT.md. Constraints: plain
HTML/CSS/JS, no build step; 10 writing systems; light and dark themes; phone and desktop.

## Direction contract

THESIS: The category standard, played straight at Riverside's level of polish: a calm workspace where the episode's
pipeline and its audio are the content. It refuses decoration and world motifs; precision, state and motion carry it.

OWN-WORLD: Light workspace (#F6F7F9 ground, white panels, #E3E6EB hairlines, #14171F ink) beside a dark #16181D
sidebar; one violet accent #5B3DF5 for primary actions, current tab, playing line and current chapter; speaker
colours blue, pink, amber, green, teal; dark theme to match (#0E0F13 ground, #17191F panels). Inter with Noto Sans
for every Indian script; tabular numerals; 8px radii on controls, 12-14px on panels and the player; soft offset shadows.

STORY: The visitor starts an episode, leaves while agents work, and comes back: the sidebar and step tabs show what
is running and how far it got; facts, lines and log entries arrive into view; on Audio they listen, follow the
transcript and fix single lines.

FIRST VIEWPORT: Desktop: sidebar left (logo, New, Episodes with count, Voices, Settings, running jobs at the bottom);
episode header (cover, title, facts, quiet Duplicate/Delete); a segmented step bar with live progress; the step's work
area with the activity column on the right. Phone: slim top bar, bottom tab bar, one column.

FORM: Category standard (the standing exit), chosen by the user over the assigned Exercise book, the Metro map, the
Station board and two catalog challengers. seed:9daf53dd8b6850ef. Signature interaction: motion that shows state:
shared-axis page transitions, cover-to-episode morph, live step progress, arriving items, a transcript that follows
playback. 150-250 ms, ease-out, reduced-motion safe.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
