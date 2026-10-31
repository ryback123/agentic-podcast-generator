# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences, in this order (confirmed 2026-10-31):

1. The author and the course evaluators. It is a course project: the author makes episodes and shows the app in a demo
   or review, so it must read as clearly working and worth evaluating.
2. People who want finished podcasts in Indian languages: it should read as a real tool they would come back to.

The author uses it on a phone and on a desktop browser (inferred from use: app-style bottom navigation, iOS-style back
button and phone layout fixes were all requested).

## Product Purpose

Turn a topic into a finished podcast episode: plan, research, script and audio, in English or code-mixed with one of
11 Indian languages. Success is a good, fact-backed episode with little effort, and every step open to inspection and
editing.

## Positioning

An agentic pipeline whose every step is visible and editable: a producer plans the cast and segments, a researcher
searches the web and Wikipedia and keeps sourced facts, a writer drafts each segment in code-mixed speech, critics
fact-check and edit word by word, and the audio has native Indian voices with fillers, cut-ins and varied pauses.
Code-mixing (Hindi words in Devanagari and English words in Latin letters in one line) is the product's language.

## Operating Context

- Long jobs run in the background (research, writing, audio); people leave and come back, so state and progress must
  be readable at a glance.
- An episode walks through Plan, Research, Script, Audio; each step can be run, edited or redone.
- Episodes are reviewed by listening: line-by-line playback, new takes, a follow-along transcript and chapters.

## Capabilities and Constraints

- Plain HTML, CSS and JavaScript served by FastAPI (`podcast_agent/web/static/`); no build step, no framework.
- Scripts in 12 languages and 10 writing systems (Latin, Devanagari, Bengali, Gurmukhi, Gujarati, Odia, Tamil, Telugu,
  Kannada, Malayalam) often mixed within one line; type must render all of them well.
- 23 TTS voices across 12 languages; 2 to 5 speakers per episode; 5 to 20 minute episodes.
- Shared over a Cloudflare tunnel; light and dark themes.

## Brand Commitments

- Name: Podcast Studio.
- Logo: the mic mark in `podcast_agent/web/static/assets/logo.svg` (also icon-32.png, icon-180.png).
- Look: the category standard, played straight (chosen 2026-10-31 over five other directions on the design canvas):
  the familiar, polished creator-tool layout. Craft bar: Riverside. No world motif or quirk.
- Motion matters to the owner: page transitions, jobs in progress, listening, and small feedback should all move
  with purpose.

## Evidence on Hand

- Real episodes in the runs folder, such as "How Shah Rukh Khan built his career" (Hindi, 2 speakers, 91 lines, audio
  built). Real voices with native-language greetings on the Voices tab.
- No users, testimonials, metrics or press exist; do not invent them.

## Product Principles

- Show the work: every agent's output is visible and editable, never a black box.
- Background by default: nothing blocks while a job runs; progress is legible on return.
- Native language first: Indian scripts are first-class content, not a fallback.
- Listen to judge: audio review tools sit next to the text they voice.
