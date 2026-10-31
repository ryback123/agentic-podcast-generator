"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NATIVE = { en: "English", hi: "हिन्दी", bn: "বাংলা", mr: "मराठी", te: "తెలుగు", ta: "தமிழ்", gu: "ગુજરાતી",
  kn: "ಕನ್ನಡ", ml: "മലയാളം", or: "ଓଡ଼ିଆ", pa: "ਪੰਜਾਬੀ", as: "অসমীয়া" };
const MIX = { light: "Mostly in the language; English only for technical terms.",
  medium: "Everyday mixing, the way people talk in cities.",
  heavy: "Frequent switching between the language and English." };
const AGENT = { producer: "Producer", researcher: "Researcher", writer: "Writer", critics: "Critics", user: "You",
  audio: "Audio", done: "Script", error: "Error" };
const STEPS = [["plan", "Plan"], ["research", "Research"], ["script", "Script"], ["audio", "Audio"]];
const PLAY = '<svg class="go" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 1.2l8 4.8-8 4.8z"/></svg>'
  + '<svg class="pause" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 1.5h2.5v9H2.5zM7 1.5h2.5v9H7z"/></svg>';
const COPY = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5" y="5" width="8.5" height="8.5" rx="1.5"/><path d="M11 5V3.5A1.5 1.5 0 0 0 9.5 2h-6A1.5 1.5 0 0 0 2 3.5v6A1.5 1.5 0 0 0 3.5 11H5"/></svg>';
const ICON = (d) => `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="${d}"/></svg>`;
const MINUS = ICON("M3.5 8h9"), PLUS = ICON("M8 3.5v9M3.5 8h9"), CROSS = ICON("M4.5 4.5l7 7M11.5 4.5l-7 7");
const DOWNLOAD = ICON("M8 2.5v8M4.5 7.5 8 11l3.5-3.5M3 13.5h10");
const IMAGE = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M2.5 11.5l3.5-3.5 3 3 2-2 2.5 2.5"/></svg>';
// the logo's mic, for an episode with no cover image yet
const MARK = '<svg class="mark" viewBox="0 0 64 64" aria-hidden="true"><rect x="25" y="8" width="14" height="27" rx="7" fill="currentColor"/>'
  + '<path d="M22.8 12.3A13 13 0 0 0 22.8 30.7M18.6 8.1A19 19 0 0 0 18.6 34.9M41.2 12.3A13 13 0 0 1 41.2 30.7M45.4 8.1A19 19 0 0 1 45.4 34.9" fill="none" stroke="currentColor" stroke-width="3.6" stroke-linecap="round" opacity=".55"/>'
  + '<path d="M32 35.5V52M23 52.5h18" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"/></svg>';
const TRASH = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 4h11M6.5 4V2.5h3V4M4 4l.7 9.5h6.6L12 4"/></svg>';
const CHECK = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3.2 3L13 4.5"/></svg>';
// iOS-style back: a thin rounded chevron, no box, the size of the cover square beside it; back to Episodes, where the
// page shrinks into its cover
const BACK = '<a class="back" href="#/episodes" aria-label="Back to your episodes"><svg viewBox="0 0 24 24" aria-hidden="true">'
  + '<path d="M15 3.5 6.5 12l8.5 8.5"/></svg></a>';
const PENCIL = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10.5 2.5l3 3L6 13H3v-3z"/></svg>';

let CFG = null, SETTINGS = null, EP = null, TAB = "plan", timer = null, listTimer = null, wasRunning = false;
let LIST = []; // every episode, newest first, from /api/episodes
const dirty = new Set(); // segment indexes with unsaved script edits
let samples = {}; // speaker index -> sample lines written from their persona
const player = new Audio();

// ---------------------------------------------------------------- utils
async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `${r.status} ${r.statusText}`);
  return data;
}
function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (bad ? " bad" : "");
  clearTimeout(toast.h);
  toast.h = setTimeout(() => (t.className = ""), bad ? 8000 : 3000);
}
const color = (i) => `var(--ch${(i % 5) + 1})`;
const chanOf = (name) => color(Math.max(0, EP.plan.speakers.findIndex((s) => s.name === name)));
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
function when(t) {
  const d = new Date(t * 1000), now = new Date(), s = (now - d) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  const hm = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return d.toDateString() === now.toDateString() ? hm : `${d.toLocaleDateString([], { month: "short", day: "numeric" })}, ${hm}`;
}
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
const file = (p) => `/api/episodes/${EP.id}/files/${p}`;
const hasScript = () => !!EP.plan?.segments.some((s) => s.turns?.length);
const empty = (msg) => `<div class="empty"><p>${esc(msg)}</p></div>`;
function autosize(t) { t.style.height = "auto"; t.style.height = t.scrollHeight + 2 + "px"; }
function paint(html) {
  $("#main").innerHTML = html;
  syncShimmer();
}
// every placeholder runs on the page clock, so the shimmer stays in step when the page re-renders during a job
function syncShimmer() { for (const a of document.getAnimations()) if (["sk", "ping"].includes(a.animationName)) a.startTime = 0; }

// ---------------------------------------------------------------- loading placeholders
// Shaped like the content they stand for, using the same layout classes. Widths come from a fixed list, so a
// placeholder keeps its shape when the page re-renders.
const W = [94, 81, 88, 67, 97, 74, 85, 58, 91, 70];
const sk = (w, cls = "") => `<i class="sk ${cls}" style="width:${typeof w === "number" ? w + "%" : w}"></i>`;
const para = (n, seed = 0) => Array.from({ length: n }, (_, j) =>
  sk(n > 1 && j === n - 1 ? 30 + W[(seed + j) % 10] / 2 : W[(seed + j) % 10])).join("");
const times = (n, f) => Array.from({ length: n }, (_, i) => f(i)).join("");
const field = (lines, seed = 0) => `<span class="sk-field">${para(lines, seed)}</span>`;

function planSkeleton(speakers = 2, minutes = 10) {
  return `<section aria-hidden="true"><h2>Cast</h2><div class="strips">${times(speakers, (i) => `
      <div class="strip" style="--c:${color(i)}">${sk(48, "tint")}${["Gender", "Role", "Knows", "Persona"].map((l, j) =>
        `<div class="f"><span>${l}</span>${field(j > 1 ? 2 : 1, i + j)}</div>`).join("")}</div>`)}</div></section>
    <section aria-hidden="true"><h2>Outline</h2><ol class="outline">${times(Math.max(4, Math.round(minutes / 2)), (i) => `
      <li>${field(1, i)}<span class="seglen"><span class="sk-field">${sk("30px")}</span><span>min</span></span><span></span>
        <div class="f wide"><span>Goal</span>${field(1, i + 1)}</div>
        <div class="f wide"><span>Research questions, one per line</span>${field(2, i + 2)}</div></li>`)}</ol></section>`;
}
const factsSkeleton = (seed) => `<ul class="facts" aria-hidden="true">${times(3, (k) => `<li>${para(1 + ((seed + k) % 2), seed + k)}</li>`)}</ul>`;
const researchSkeleton = () => `<div class="qs" aria-hidden="true">${times(4, (i) => `<div class="q"><header>${sk(W[i] * 0.6)}
  ${sk("52px", "n")}</header>${factsSkeleton(i)}</div>`)}</div>`;
const statsSkeleton = () => `<div class="stats" aria-hidden="true">${[["56px", "120px"], ["36px", "40px"], ["32px", "80px"]].map(([a, b]) =>
  `<div>${sk(a, "num")}${sk(b)}</div>`).join("")}<div class="share">${sk("130px")}${sk(100, "bar10")}${sk("55%")}</div></div>`;
// script lines: speakers take turns, and every fifth line is a short filler
const linesSkeleton = (n, seed) => times(n, (k) => {
  const filler = k % 5 === 3;
  return `<div class="ln sk-ln" style="--c:${color(k % (EP?.plan?.speakers.length || 2))}" data-mode="${filler ? "backchannel" : ""}" aria-hidden="true">
    <span class="who">${sk(filler ? 45 : 70, "tint")}</span><span class="tx">${filler ? sk(16) : para(1 + ((k + seed) % 3), k + seed)}</span><span></span></div>`;
});
const scriptSkeleton = () => statsSkeleton() + times(2, (i) => `<section class="sheet" aria-hidden="true">
  <header><span class="n">${i + 1}</span>${sk("38%")}<span class="goal">${sk(70)}</span></header>
  <div class="lines">${linesSkeleton(6, i)}</div></section>`);
const playerSkeleton = () => `<div class="player" aria-hidden="true"><h2>Episode</h2>${sk(100, "wave")}${sk("30%")}</div>`;
const audioSkeleton = () => playerSkeleton() + `<section aria-hidden="true"><h2>Lines</h2>${times(8, (k) =>
  `<div class="al" style="--c:${color(k % 2)}">${sk("32px", "dot")}${sk(60, "tint")}${sk(W[k], "tx")}<span></span></div>`)}</section>`;

function episodeSkeleton(tab) {
  const body = { plan: () => planSkeleton(), research: researchSkeleton, script: scriptSkeleton, audio: audioSkeleton }[tab];
  paint(`<div class="head"><div class="title">${BACK}<i class="sk thumb-sk" aria-hidden="true"></i><div style="flex:1" aria-hidden="true">${sk(55, "h1")}
      <div class="meta">${["70px", "84px", "110px", "150px"].map((w) => sk(w, "chip")).join("")}</div></div></div></div>
    <nav class="steps" aria-hidden="true">${STEPS.map(([k, l], i) =>
      `<a ${k === tab ? 'aria-current="page"' : ""}><span class="l"><b>${i + 1}</b>${l}</span><small>&nbsp;</small></a>`).join("")}</nav>
    <div class="work"><div class="stage">${body()}</div>
      <aside class="cue" aria-hidden="true"><h2>Activity</h2>${times(6, (k) => para(2, k))}</aside></div>
    <p class="vh" role="status">Loading the episode</p>`);
}
const coverSkeleton = () => times(4, () => `<span class="cover-link" aria-hidden="true">${sk(100, "cover-sk")}${sk(55)}</span>`);
function homeSkeleton() { // shaped like renderHome
  paint(page("New episode", `<div class="settings" aria-hidden="true">
    <section class="panel">${["What should the episode be about?", "Who is it for, and how should it feel? (optional)"].map((l, i) =>
      `<div class="f"><span>${l}</span>${field(2, i)}</div>`).join("")}</section>
    <section class="panel"><div class="f"><span>Language</span><div class="langs">${times(12, (i) =>
        `<span>${sk(`${20 + W[i % 10] / 3}px`)}${sk("34px")}</span>`)}</div></div>
      <div class="row">${["Speakers", "Length"].map((l) => `<div class="f"><span>${l}</span>${sk("150px", "btn")}</div>`).join("")}
        <div class="f"><span>English mixing</span>${sk("215px", "btn")}</div></div></section>
    <div class="bar">${sk("220px", "btn")}${sk("200px", "btn")}</div></div>
    <p class="vh" role="status">Loading</p>`));
}
const page = (title, body) => `<div class="page"><div class="pagehead"><h1>${title}</h1><span class="hint" id="count"></span></div>${body}</div>`;
const pageSkeleton = (v) => (v === "episodes"
  ? `<div class="filters" aria-hidden="true">${sk("320px", "btn")}${sk("190px", "btn")}${sk("470px", "btn")}</div><div class="covers">${coverSkeleton()}</div>`
  : (v === "settings" ? [6, 5, 3, 2, 4] : [3, 3]).map((n, i) => // shaped like the page it stands for
    `<section class="panel" aria-hidden="true">${sk(28)}${para(n, i)}</section>`).join("")) + '<p class="vh" role="status">Loading</p>';

// what the running job is working on
const WRITES = ["making the whole episode", "running the remaining steps", "writing the script"];
const writes = () => EP.job.running && (WRITES.includes(EP.job.task) || EP.job.task.startsWith("rewrite segment"));
// research is on: a research job, or a whole-episode job whose latest step was the researcher's
const researching = () => EP.job.running && (EP.job.task === "researching" || (WRITES.slice(0, 2).includes(EP.job.task) &&
  EP.log.findLast((e) => ["producer", "researcher", "writer", "critics"].includes(e.agent))?.agent === "researcher"));
// the segment being drafted right now: its old lines go when its first review round ends
function drafting() {
  if (!writes()) return -1;
  const k = EP.log.findLastIndex((e) => e.agent === "writer" && /^writing segment \d+/.test(e.event));
  if (k < 0) return -1;
  const n = EP.log[k].event.match(/\d+/)[0];
  return EP.log.slice(k + 1).some((e) => e.event.startsWith(`segment ${n} round`) && e.event.includes("word fixes")) ? -1 : n - 1;
}

// ---------------------------------------------------------------- routing
const PAGES = { new: () => renderHome(), episodes: () => renderEpisodes(), voices: () => renderVoices(), settings: () => renderSettings() };
const viewOf = (view, id) => (view === "ep" && id ? "ep" : PAGES[view] ? view : "new");
function setView(v) { // the body's data-view sets the layout; an episode belongs to the Episodes tab
  document.body.dataset.view = v;
  for (const a of $$(".tabs a")) {
    if (a.dataset.tab === (v === "ep" ? "episodes" : v)) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}
async function route() {
  const [, view, id, tab] = location.hash.split("/");
  clearTimeout(timer);
  clearTimeout(listTimer);
  if (dirty.size && EP) await saveDirty();
  const v = viewOf(view, id), kind = navKind(document.body.dataset.view, v), leaving = EP?.id;
  let loading;
  await swap(kind, () => { // paints the next page (or its placeholder) at once; an episode's data follows
    setView(v);
    window.scrollTo(0, 0); // a new page starts at its top, not where the last one was scrolled to
    if (v === "ep") {
      TAB = STEPS.some(([k]) => k === tab) ? tab : "plan";
      if (!EP || EP.id !== id) { dirty.clear(); samples = {}; wasRunning = false; episodeSkeleton(TAB); }
      loading = load(id);
    } else {
      EP = null;
      PAGES[v]();
    }
  }, leaving);
  await loading;
  refreshList();
}

// ---------------------------------------------------------------- page transitions
// Tabs slide like an Android pager (a tab further right comes in from the right); a cover grows into its episode,
// and the episode shrinks back into its cover. Uses the browser's View Transitions; without them, or with reduced
// motion, pages just switch.
const TAB_ORDER = ["new", "episodes", "voices", "settings"];
const tabIndex = (v) => TAB_ORDER.indexOf(v === "ep" ? "episodes" : v);
let OPENING = null; // the cover just clicked
function navKind(from, to) {
  if (!from || !document.startViewTransition || matchMedia("(prefers-reduced-motion: reduce)").matches) return null;
  if (to === "ep") return OPENING?.isConnected ? "open" : null;
  if (from === "ep" && to === "episodes") return "close";
  const d = tabIndex(to) - tabIndex(from);
  return d > 0 ? "forward" : d < 0 ? "back" : null;
}
async function swap(kind, update, leaving) {
  const cover = OPENING, main = $("#main"), root = document.documentElement;
  const name = (el, n) => { if (el) el.style.viewTransitionName = n; };
  OPENING = null;
  if (!kind) return update();
  root.dataset.nav = kind;
  if (kind === "open") name(cover, "ep");
  else name(main, kind === "close" ? "ep" : "page");
  const t = document.startViewTransition(() => {
    update();
    if (kind === "open") name(main, "ep");
    if (kind === "close") { name(main, ""); name($(`.cover-link[href^="#/ep/${leaving}/"] .cover`), "ep"); }
  });
  // wait for the whole animation: refreshing the list meanwhile would redraw the covers and lose the named one
  await t.finished;
  delete root.dataset.nav;
  name(main, "");
  for (const el of $$(".cover")) name(el, "");
}

async function load(id) {
  clearTimeout(timer);
  try {
    EP = await api("GET", `/api/episodes/${id}`);
  } catch (e) {
    $("#main").innerHTML = empty(`Could not open this episode: ${e.message}`);
    return;
  }
  const running = EP.job.running;
  render();
  if (wasRunning && !running) {
    refreshList();
    if (EP.job.error) toast(EP.job.error, true);
    else toast(`Finished: ${EP.job.task}`);
  }
  wasRunning = running;
  if (running) timer = setTimeout(() => load(id), 1500);
}

const tabOf = (e) => (e.has_audio ? "audio" : e.has_script ? "script" : "plan");
async function refreshList() {
  clearTimeout(listTimer);
  LIST = await api("GET", "/api/episodes").catch(() => LIST);
  const live = LIST.filter((e) => e.running);
  $("#busy").innerHTML = live.length // a count on the Episodes tab, like an app's
    ? `<b class="badge" aria-hidden="true">${live.length}</b><span class="vh">, ${live.length} in progress</span>` : "";
  $("#jobs").innerHTML = live.length ? `<h2>In progress</h2>${live.map((e) => `<a class="job" href="#/ep/${e.id}/${tabOf(e)}">
    <span class="t" lang="${e.lang}">${esc(e.title)}</span><span class="task"><i class="dot"></i>${esc(cap(e.task || "working"))}…</span>
    ${progBar(e.progress)}</a>`).join("")}` : "";
  fillCovers();
  syncShimmer();
  if (live.length) listTimer = setTimeout(refreshList, 3000); // keep the in-progress states current
}
function fillCovers() {
  const box = $("#covers");
  if (!box) return;
  const found = filtered();
  box.innerHTML = found.slice(0, SHOWN).map(cover).join("")
    || `<p class="hint">${LIST.length ? "No episodes match these filters." : "Your episodes will appear here."}</p>`;
  $("#count").textContent = found.length === LIST.length ? `${LIST.length} episodes` : `${found.length} of ${LIST.length} episodes`;
  $("#more").hidden = found.length <= SHOWN;
}

// ---------------------------------------------------------------- home: new episode and your episodes
const langChips = (sel) => `<div class="langs" role="radiogroup" aria-label="Language">${CFG.languages.map((l) =>
  `<label><input type="radio" name="lang" value="${l.code}" ${l.code === sel ? "checked" : ""}>
    <span lang="${l.code}">${NATIVE[l.code] || l.name}<small>${l.name}</small></span></label>`).join("")}</div>`;
const mixBox = (sel, lang) => `<div class="f mixbox" ${lang === "en" ? "hidden" : ""}><span>English mixing</span>
  <div class="seg">${CFG.code_mix.map((m) => `<label><input type="radio" name="code_mix" value="${m}" ${m === sel ? "checked" : ""}><span>${cap(m)}</span></label>`).join("")}</div>
  <p class="hint mixhint">${MIX[sel]}</p></div>`;
const stepper = (name, label, min, max, value, unit, less, more) => `<div class="f"><span id="${name}-l">${label}</span>
  <div class="stepper" role="group" aria-labelledby="${name}-l">
    <button class="btn" type="button" data-act="step" data-name="${name}" data-d="-1" aria-label="${less}">${MINUS}</button>
    <input type="number" name="${name}" min="${min}" max="${max}" value="${value}" required aria-labelledby="${name}-l">
    ${unit ? `<span class="unit">${unit}</span>` : ""}
    <button class="btn" type="button" data-act="step" data-name="${name}" data-d="1" aria-label="${more}">${PLUS}</button></div></div>`;

function renderHome() { // laid out like Settings: a title, then panels, then the actions
  const s = SETTINGS;
  paint(page("New episode", `<form id="newform" class="settings">
    <section class="panel">
      <label class="f"><span>What should the episode be about?</span>
        <textarea class="topic" name="topic" rows="2" required placeholder="How UPI payments work"></textarea></label>
      <label class="f"><span>Who is it for, and how should it feel? (optional)</span>
        <textarea name="description" rows="2" placeholder="Class 8 students; friendly, with everyday examples"></textarea></label>
    </section>
    <section class="panel">
      <div class="f"><span>Language</span>${langChips(s.lang)}</div>
      <div class="row">
        ${stepper("speakers", "Speakers", 2, 5, s.speakers, "", "Fewer speakers", "More speakers")}
        ${stepper("minutes", "Length", 5, 20, s.minutes, "min", "Shorter", "Longer")}
        ${mixBox(s.code_mix, s.lang)}
      </div>
    </section>
    <div class="bar">
      <button class="btn btn-primary" type="submit" value="auto">Make the whole episode</button>
      <button class="btn btn-line" type="submit" value="plan">Plan first, then decide</button>
    </div>
    <p class="hint">Making the whole episode runs planning, research and writing in one go, which takes about five to eight minutes.
      Planning first lets you change the cast and outline before research starts.</p>
  </form>`));
}

// ---------------------------------------------------------------- Episodes tab
const STATES = [["", "All"], ["running", "In progress"], ["script", "Script ready"], ["audio", "Audio ready"], ["none", "No script yet"]];
const stateOf = (e) => (e.running ? "running" : e.has_audio ? "audio" : e.has_script ? "script" : "none");
const FIND = { q: "", lang: "", state: "" };
let SHOWN = 24;
// ponytail: search and filters run in the browser over the whole list; past a few thousand episodes, page and filter
// on the server from an index (SQLite) instead
function filtered() {
  const q = FIND.q.trim().toLowerCase();
  return LIST.filter((e) => (!FIND.lang || e.lang === FIND.lang) && (!FIND.state || stateOf(e) === FIND.state)
    && (!q || `${e.title} ${e.topic}`.toLowerCase().includes(q)));
}
function renderEpisodes() {
  paint(page("Episodes", `<div class="filters">
      <label class="search"><span class="vh">Search episodes</span>
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>
        <input type="search" id="find-q" placeholder="Search titles and topics" value="${esc(FIND.q)}"></label>
      <select id="find-lang" aria-label="Language"><option value="">All languages</option>${CFG.languages.map((l) =>
        `<option value="${l.code}" ${l.code === FIND.lang ? "selected" : ""}>${NATIVE[l.code] || l.name} (${l.name})</option>`).join("")}</select>
      <div class="seg" role="radiogroup" aria-label="State">${STATES.map(([v, l]) =>
        `<label><input type="radio" name="find-state" value="${v}" ${v === FIND.state ? "checked" : ""}><span>${l}</span></label>`).join("")}</div>
    </div>
    <div class="covers" id="covers">${coverSkeleton()}</div>
    <div class="bar morebar"><button class="btn btn-line" type="button" id="more" data-act="more" hidden>Show more</button></div>`));
  if (LIST.length) fillCovers();
}

// ---------------------------------------------------------------- Voices tab
const langName = (c) => CFG.languages.find((l) => l.code === c)?.name || c;
function renderVoices() {
  const V = CFG.tts.voices, info = CFG.tts.voice_info || {};
  if (!CFG.tts.configured || !V.length) {
    return paint(page("Voices", `<div class="empty"><p>Audio isn't connected yet. Once the server has a text-to-speech service
      (TTS_BASE_URL and TTS_VOICES), its voices appear here: play a sample of each and pick the default voice for female and
      male speakers.</p></div>`));
  }
  const opts = (sel, g) => `<option value="">The first free ${g} voice</option>${V.filter((v) => !info[v]?.gender || info[v].gender === g)
    .map((v) => `<option ${v === sel ? "selected" : ""}>${esc(v)}</option>`).join("")}`;
  const order = CFG.languages.map((l) => l.code), groups = {}; // voices by their language, in the app's language order
  for (const v of V) (groups[order.includes(info[v]?.lang) ? info[v].lang : ""] ??= []).push(v);
  const keys = [...order.filter((c) => groups[c]), ...(groups[""] ? [""] : [])];
  const item = (v) => `<li><button class="play" type="button" data-act="play"
      data-src="/api/voices/${encodeURIComponent(v)}/sample.wav" aria-label="Play a sample of ${esc(v)}">${PLAY}</button>
    <b>${esc(v)}</b>${info[v]?.gender ? `<span class="hint">${esc(info[v].gender)}</span>` : ""}${
      v === SETTINGS.voice_female ? '<span class="tag">female default</span>' : ""}${
      v === SETTINGS.voice_male ? '<span class="tag">male default</span>' : ""}</li>`;
  paint(page("Voices", `<p class="hint lede">Play a sample to hear each voice in its own language. A speaker starts on a voice of
      their gender in the episode's language; the defaults below are for languages without voices of their own, such as
      English, and for episodes with more speakers than their language has voices. You can change any speaker's voice in an
      episode's Audio step.</p>
    <form class="panel" id="voiceform"><div class="row">
      <label class="f"><span>Default for female speakers</span><select name="voice_female">${opts(SETTINGS.voice_female, "female")}</select></label>
      <label class="f"><span>Default for male speakers</span><select name="voice_male">${opts(SETTINGS.voice_male, "male")}</select></label>
      </div><div class="bar"><button class="btn btn-primary" type="submit">Save default voices</button></div></form>
    ${keys.map((c) => `<section class="voicegroup"><h2>${c ? `<span lang="${c}">${NATIVE[c] || c}</span> <small>${esc(langName(c))}</small>`
      : "Other voices"}</h2><ul class="voicelist">${groups[c].map(item).join("")}</ul></section>`).join("")}`));
}
// the Audio step's starting voices: a saved choice; else a free voice of the speaker's gender in the episode's language;
// else the gender's default from the Voices tab; else any free voice of that gender; else any free voice
function pickVoices(speakers, saved, lang) {
  const V = CFG.tts.voices, info = CFG.tts.voice_info || {}, used = new Set(), out = {};
  const free = (v) => V.includes(v) && !used.has(v);
  const take = (s, v) => { out[s.name] = v; used.add(v); };
  for (const s of speakers) if (V.includes(saved[s.name])) take(s, saved[s.name]);
  for (const s of speakers) {
    if (out[s.name]) continue;
    const mine = (v) => free(v) && info[v]?.gender === s.gender;
    const d = { female: SETTINGS.voice_female, male: SETTINGS.voice_male }[s.gender];
    take(s, V.find((v) => mine(v) && info[v].lang === lang) || (free(d) ? d : "") || V.find(mine) || V.find(free) || V[0]);
  }
  return out;
}
// a speaker's voice menu: the episode language's voices first
function voiceOptions(sel, lang) {
  const V = CFG.tts.voices, info = CFG.tts.voice_info || {};
  const opt = (v) => `<option value="${esc(v)}" ${v === sel ? "selected" : ""}>${esc(v)}${info[v]?.gender ? `, ${info[v].gender}` : ""}${
    info[v]?.lang && info[v].lang !== lang ? `, ${esc(langName(info[v].lang))}` : ""}</option>`;
  const own = V.filter((v) => info[v]?.lang === lang), rest = V.filter((v) => info[v]?.lang !== lang);
  return own.length ? `<optgroup label="${esc(langName(lang))} voices">${own.map(opt).join("")}</optgroup>
    <optgroup label="Other voices">${rest.map(opt).join("")}</optgroup>` : V.map(opt).join("");
}

// ---------------------------------------------------------------- Settings tab
const getTheme = () => { try { return localStorage.getItem("theme") || "system"; } catch { return "system"; } };
function setTheme(t) { // kept in this browser; index.html applies it before the page draws
  try { if (t === "system") localStorage.removeItem("theme"); else localStorage.setItem("theme", t); } catch { /* private window */ }
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
}
const okDot = (ok) => `<i class="ok ${ok ? "yes" : "no"}" aria-hidden="true"></i>`;
const size = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${(b / 1e6).toFixed(1)} MB`);
const statusList = (st) => (st.error ? `<p class="hint">Could not check the services: ${esc(st.error)}</p>` : `<dl class="status">
  <dt>Script model</dt><dd>${okDot(st.model.ok)}${esc(st.model.name)}, ${st.model.ok ? "reachable" : `not reachable (${esc(st.model.error)})`}</dd>
  <dt>Web search</dt><dd>${okDot(st.web_search.key)}${st.web_search.key ? "Tavily key set" : "No Tavily key, so research uses Wikipedia only"};
    ${st.web_search.credits} credits used so far</dd>
  <dt>Text to speech</dt><dd>${okDot(st.tts.configured)}${st.tts.configured ? `connected, ${st.tts.voices} voices` : "not connected"}</dd>
  <dt>Storage</dt><dd>${st.storage.episodes} episodes, ${size(st.storage.bytes)}</dd></dl>`);
// drawn at once from the settings loaded at start-up; only the Services panel waits for its check
function renderSettings() {
  const s = SETTINGS, theme = getTheme();
  paint(page("Settings", `<form id="settingsform" class="settings">
    <section class="panel"><h2>New episodes</h2><p class="hint">What the New tab starts with; each episode can still change them.</p>
      <div class="f"><span>Language</span>${langChips(s.lang)}</div>
      <div class="row">
        ${stepper("speakers", "Speakers", 2, 5, s.speakers, "", "Fewer speakers", "More speakers")}
        ${stepper("minutes", "Length", 5, 20, s.minutes, "min", "Shorter", "Longer")}
        ${mixBox(s.code_mix, s.lang)}
      </div></section>
    <section class="panel"><h2>Agents</h2><p class="hint">Used by every job that starts from now on.</p>
      <div class="row">
        ${stepper("research_steps", "Research steps", 4, 40, s.research_steps, "", "Fewer steps", "More steps")}
        ${stepper("review_rounds", "Review rounds per segment", 0, 3, s.review_rounds, "", "Fewer rounds", "More rounds")}
      </div>
      <p class="hint">A research step is one search or one page read; a web search costs about one Tavily credit, and the
        researcher stops early once every question has two facts. A review round is a fact-check and an editor's pass on a
        segment, then fixes.</p>
      <label class="check"><input type="checkbox" name="web_search" ${s.web_search ? "checked" : ""}>
        Search the whole web with Tavily. When off, research uses Wikipedia only, which costs no credits.</label></section>
    <section class="panel"><h2>Audio</h2>
      <label class="f"><span>Speed</span><span class="seglen">
        <input type="number" name="speed" min="1" max="1.5" step="0.01" value="${s.speed}" required><span>×</span></span></label>
      <p class="hint">A multiplier from 1 (as the voice speaks) to 1.5. It speeds up every line without changing the voice's
        pitch, so a 12-minute script at 1.2× plays in 10
        minutes. It applies when an episode's audio is built: on an existing episode, click Update audio on its Audio tab;
        no lines are generated again.</p></section>
    <section class="panel"><h2>Appearance</h2>
      <div class="seg" role="radiogroup" aria-label="Theme">${[["system", "Same as the system"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) =>
        `<label><input type="radio" name="theme" value="${v}" ${v === theme ? "checked" : ""}><span>${l}</span></label>`).join("")}</div>
      <p class="hint">Changes straight away and is kept in this browser only.</p></section>
    <div class="bar"><button class="btn btn-primary" type="submit">Save settings</button></div></form>
    <section class="panel"><h2>Services</h2><p class="hint">Server addresses and keys are set on the server, not here.</p>
      <div id="services" aria-busy="true"><dl class="status" aria-hidden="true">${times(4, (i) =>
        `<dt>${sk("96px")}</dt><dd>${sk(30 + W[i] / 2)}</dd>`)}</dl></div></section>`));
  api("GET", "/api/status").catch((e) => ({ error: e.message })).then((st) => {
    const box = $("#services");
    if (!box) return; // left the tab meanwhile
    box.innerHTML = statusList(st);
    box.removeAttribute("aria-busy");
  });
  api("GET", "/api/settings").then((fresh) => { SETTINGS = fresh; }).catch(() => {}); // current for the next save
}
async function saveSettings(form) {
  const body = { ...SETTINGS, lang: form.lang.value, speakers: +form.speakers.value, minutes: +form.minutes.value,
    code_mix: form.code_mix.value, research_steps: +form.research_steps.value, review_rounds: +form.review_rounds.value,
    web_search: form.web_search.checked, speed: +form.speed.value };
  try {
    SETTINGS = await api("PUT", "/api/settings", body);
    toast("Settings saved");
  } catch (e) { toast(e.message, true); }
}
async function saveVoices(form) {
  try {
    SETTINGS = await api("PUT", "/api/settings", { ...SETTINGS, voice_female: form.voice_female.value, voice_male: form.voice_male.value });
    toast("Default voices saved");
    renderVoices();
  } catch (e) { toast(e.message, true); }
}

// an episode's cover: a colour and a few speech blocks per speaker, the same every time for that episode
const COVERS = [["#312E81", "#FFFFFF"], ["#0F5E5A", "#FFFFFF"], ["#9D174D", "#FFFFFF"], ["#1E3A8A", "#FFFFFF"],
  ["#92400E", "#FFFFFF"], ["#4C1D95", "#FFFFFF"], ["#155E75", "#FFFFFF"], ["#1F2937", "#FFFFFF"]];
const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.codePointAt(0)) % 233280, 7);
function lanes(n, seed) {
  const r = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
  return times(n, () => {
    let x = r() * 12, out = "";
    while (x < 92) {
      const w = 8 + r() * 22;
      out += `<i style="left:${x.toFixed(1)}%;width:${Math.min(w, 100 - x).toFixed(1)}%"></i>`;
      x += w + 4 + r() * 14;
    }
    return `<span>${out}</span>`;
  });
}
const coverColours = (id) => { const [bg, fg] = COVERS[hash(id) % COVERS.length]; return `--bg-c:${bg};--fg-c:${fg}`; };
const coverImg = (id, name) => `<img src="/api/episodes/${id}/files/${name}" alt="">`;
function cover(e) { // an uploaded image fills the cover and the title goes under it; otherwise colour, bars and title
  const state = e.running ? `<span class="state live"><i class="dot on"></i>${esc(cap(e.task || "working"))}…</span>`
    : `<span class="state">${e.has_audio ? "Audio ready" : e.has_script ? "Script ready" : "No script yet"}${
        e.has_script && e.minutes ? `, about ${e.minutes} minutes` : ""}</span>`;
  const top = `<span class="top"><span lang="${e.lang}">${NATIVE[e.lang] || e.lang}</span><span>${e.speakers} speakers</span></span>`;
  const t = `<span class="t" lang="${e.lang}">${esc(e.title)}</span>`;
  const art = e.cover ? `<span class="cover pic">${coverImg(e.id, e.cover)}${top}</span>${t}`
    : `<span class="cover" style="${coverColours(e.id)}">${top}<span class="lanes" aria-hidden="true">${lanes(e.speakers || 2, hash(e.id))}</span>${t}</span>`;
  return `<a class="cover-link" href="#/ep/${e.id}/${tabOf(e)}">${art}${state}</a>`;
}
function updateNewForm(form) { // the new-episode form and Settings: no English mixing for English
  $(".mixbox", form).hidden = form.lang.value === "en";
  $(".mixhint", form).textContent = MIX[form.code_mix.value];
}
async function submitNew(form, mode) {
  const body = { topic: form.topic.value, description: form.description.value, lang: form.lang.value,
    speakers: +form.speakers.value, minutes: +form.minutes.value, code_mix: form.code_mix.value, auto: mode === "auto" };
  try {
    const { id } = await api("POST", "/api/episodes", body);
    location.hash = `#/ep/${id}/plan`;
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- episode
function stepNote(k) {
  if (k === "plan") return EP.plan ? `${EP.plan.segments.length} segments` : "";
  if (k === "research") return EP.facts.length ? `${EP.facts.length} facts` : "";
  if (k === "script") return liveStep() === "script" ? "being written" : hasScript() && EP.stats ? `~${EP.stats.est_minutes} min` : "";
  if (k === "audio") return EP.audio?.episode ? `${(EP.audio.episode.seconds / 60).toFixed(1)} min` : "";
}

// generating the episode's audio, or a new take of one line
const audioJob = () => EP.job.running && (EP.job.task === "generating audio" || EP.job.task.startsWith("new take"));
// a step is live while the agents work on it, done once it has output
function liveStep() {
  const j = EP.job;
  if (!j.running) return null;
  if (audioJob()) return "audio";
  if (j.task === "planning" || !EP.plan) return "plan";
  if (researching()) return "research";
  return writes() ? "script" : null;
}
function stepState(k) {
  const done = { plan: !!EP.plan, research: EP.facts.length > 0, script: !!EP.plan?.segments.every((s) => s.turns?.length),
    audio: !!EP.audio?.episode }[k];
  return k === liveStep() ? "live" : done ? "done" : "";
}

const progBar = (p) => `<span class="prog ${p == null ? "busy" : ""}" aria-hidden="true"><i style="width:${Math.round((p ?? 0) * 100)}%"></i></span>`;
let SEEN = null; // what this step has shown, so items that arrive during a job can be told apart
function fresh(key) {
  const n = !SEEN.keys.has(key);
  SEEN.keys.add(key);
  return n && !SEEN.first ? " arrive" : "";
}
// how far a running step got: a fraction, or null when there is no way to tell
function stepProgress(k) {
  if (k === "research") {
    const qs = Object.keys(EP.questions);
    return qs.length ? qs.filter((q) => EP.facts.some((f) => f.q === q)).length / qs.length : null;
  }
  if (k === "script") {
    const n = EP.plan.segments.length, now = drafting();
    return now >= 0 ? now / n : EP.plan.segments.filter((s) => s.turns?.length).length / n;
  }
  if (k === "audio") return EP.lines.length ? EP.lines.filter((l) => l.ready).length / EP.lines.length : null;
  return null;
}

function render() {
  const p = EP.plan, r = EP.request, job = EP.job;
  const first = SEEN?.id !== EP.id || SEEN?.tab !== TAB;
  SEEN = first ? { id: EP.id, tab: TAB, keys: new Set(), first: true } : { ...SEEN, first: false };
  const listening = [...$$("main audio")].find((a) => !a.paused || a.currentTime > 0); // carried over the redraw, see below
  const title = p?.title || r.topic;
  const lamp = job.running ? `<div class="lamp on" role="status"><i></i>${esc(cap(job.task))}…</div>`
    : job.error ? `<div class="lamp err" role="status"><i></i>Stopped: ${esc(job.error.slice(0, 90))}</div>`
    : "";
  paint(`
    <div class="head"><div class="title">${BACK}
      <button class="thumb ${EP.cover ? "" : "empty"}" type="button" data-act="pickCover" style="${coverColours(EP.id)}"
        aria-label="${EP.cover ? "Change" : "Add"} cover image" title="${EP.cover ? "Change" : "Add"} cover image">
        ${EP.cover ? coverImg(EP.id, EP.cover) : MARK}<span class="edit" aria-hidden="true">${EP.cover ? PENCIL : IMAGE}</span></button>
      <div>
      <h1 class="${/[^\x00-\x7F]/.test(title) ? "native" : ""}" lang="${r.lang}">${esc(title)}</h1>
      <div class="meta"><span>${NATIVE[r.lang]}</span><span>${r.speakers} speakers</span><span>${r.minutes} minute target</span>
        ${r.lang !== "en" ? `<span>${cap(r.code_mix)} English mixing</span>` : ""}<span>Topic: ${esc(r.topic)}</span></div>
    </div></div>
    <div class="headside">${lamp}<div class="actions">
      ${EP.cover ? '<button class="btn btn-quiet" type="button" data-act="dropCover">Remove cover</button>' : ""}
      <button class="btn btn-quiet" type="button" data-act="duplicate">${COPY}Duplicate</button>
      <button class="btn btn-quiet btn-danger" type="button" data-act="deleteEp">${TRASH}Delete</button></div></div></div>
    <nav class="steps" aria-label="Steps">${STEPS.map(([k, l], i) => {
      const st = stepState(k), mark = st === "live" ? '<i class="dot"></i>' : st === "done" ? CHECK : `<b>${i + 1}</b>`;
      return `<a class="${st}" href="#/ep/${EP.id}/${k}" ${k === TAB ? 'aria-current="page"' : ""}>
        <span class="l">${mark}${l}</span><small>${stepNote(k) || "&nbsp;"}</small>${st === "live" ? progBar(stepProgress(k)) : ""}</a>`;
    }).join("")}</nav>
    <div class="work"><fieldset class="stage" ${job.running && TAB !== "audio" ? "disabled" : ""}>${VIEWS[TAB]()}</fieldset>${cue()}</div>`);
  const same = listening && $(`main audio[src="${listening.getAttribute("src")}"]`);
  if (same) { // taking it out of the page paused it; carry on from the same place
    const resume = !listening.paused;
    same.replaceWith(listening);
    if (resume) listening.play();
    follow(listening);
  }
  $$("textarea.auto").forEach(autosize);
  document.fonts.ready.then(() => $$("textarea.auto").forEach(autosize)); // sized again once the web fonts are in
  const c = $(".cue");
  c.scrollTop = c.scrollHeight;
}

function cue() {
  const items = EP.log.slice(-150);
  return `<aside class="cue" aria-label="Agent activity"><h2>Activity</h2><ol>${items.map((e) =>
    `<li class="${e.agent === "error" ? "error" : ""}${fresh(`c|${e.t}|${e.event}`)}"><span class="who">${esc(AGENT[e.agent] || e.agent)}</span>
      <time datetime="${new Date(e.t * 1000).toISOString()}" title="${new Date(e.t * 1000).toLocaleString()}">${when(e.t)}</time><span class="ev">${esc(e.event)}</span>${e.thought ? `<span class="th">${esc(e.thought)}</span>` : ""}</li>`).join("")}</ol></aside>`;
}

const VIEWS = {
  plan() {
    if (EP.job.running && (!EP.plan || EP.job.task === "planning")) return planSkeleton(EP.request.speakers, EP.request.minutes);
    if (!EP.plan) {
      return `<div class="empty"><p>No plan yet.</p><button class="btn btn-primary" data-act="replan">Plan the episode</button></div>`;
    }
    const p = EP.plan;
    return `<section><h2>Cast</h2>${hasScript() ? '<p class="hint">Renaming a speaker also changes their name in the script lines. Saved voices stay with them.</p>' : ""}<div class="strips">${p.speakers.map((s, i) => `
      <div class="strip" style="--c:${color(i)}">
        <input type="text" class="nm" name="name" value="${esc(s.name)}" aria-label="Speaker name">
        <label class="f"><span>Gender</span><select name="gender">${["female", "male"].map((g) =>
          `<option ${s.gender === g ? "selected" : ""}>${g}</option>`).join("")}</select></label>
        <label class="f"><span>Role</span><input type="text" name="role" value="${esc(s.role)}"></label>
        <label class="f"><span>Knows</span><textarea class="auto" name="knowledge" rows="2">${esc(s.knowledge)}</textarea></label>
        <label class="f"><span>Persona</span><textarea class="auto" name="style" rows="4"
          placeholder="Who they are and how they speak: attitude, energy, sentence length, humour, how they explain or push back">${esc(s.style)}</textarea></label>
        <div class="sample">${sampleLines(i)}</div>
        <button class="btn btn-quiet" type="button" data-act="sample" data-i="${i}">Try this persona</button>
      </div>`).join("")}</div></section>
    <section><h2>Outline</h2><ol class="outline">${p.segments.map((s, i) => `
      <li data-seg="${i}">
        <input type="text" name="title" value="${esc(s.title)}" aria-label="Segment title">
        <label class="seglen">
          <input type="number" name="minutes" min="0.5" step="0.5" value="${s.minutes}" aria-label="Duration in minutes"><span>min</span></label>
        <button class="btn btn-quiet" type="button" data-act="dropSeg" data-i="${i}">Remove</button>
        <label class="f wide"><span>Goal</span><textarea class="auto" name="goal" rows="1">${esc(s.goal || "")}</textarea></label>
        <label class="f wide"><span>Research questions, one per line</span>
          <textarea class="auto" name="questions" rows="2">${esc((s.questions || []).join("\n"))}</textarea></label>
        ${s.turns?.length ? `<p class="hint wide">This segment has ${s.turns.length} script lines.</p>` : ""}
      </li>`).join("")}</ol>
      <div class="bar" style="margin-top:10px"><button class="btn" type="button" data-act="addSeg">Add segment</button>
        <span class="hint">Total ${p.segments.reduce((a, s) => a + (+s.minutes || 0), 0)} minutes</span></div></section>
    <div class="bar">
      <button class="btn btn-primary" data-act="savePlan">Save plan</button>
      <button class="btn" data-act="research">${EP.facts.length ? "Save and research again" : "Save and start research"}</button>
      <span class="grow"></span>
      <button class="btn btn-quiet" data-act="replan">Plan again from scratch</button>
    </div>`;
  },

  research() {
    if (!EP.plan) return EP.job.running ? researchSkeleton() : empty("Plan the episode first.");
    const busy = researching();
    const qs = Object.entries(EP.questions);
    const steps = EP.log.filter((e) => e.agent === "researcher");
    const pages = new Set(EP.facts.map((f) => f.url)).size;
    return `<div class="bar">
        <button class="btn btn-primary" data-act="research">${EP.facts.length ? "Research again" : "Run research"}</button>
        <button class="btn" data-act="writeAll">${hasScript() ? "Rewrite the whole script" : "Write the script"}</button>
        <span class="grow"></span><span class="hint">${EP.facts.length} facts from ${pages} pages${EP.research_stats ? `, ${EP.research_stats.credits} web search credits` : ""}</span></div>
      ${qs.length ? `<div class="qs">${qs.map(([q, t], qi) => {
        const fs = EP.facts.filter((f) => f.q === q);
        return `<div class="q"><header><h3>${esc(t)}</h3>
          <span class="n ${fs.length ? "" : "none"}">${fs.length ? `${fs.length} ${fs.length > 1 ? "facts" : "fact"}` : "No facts yet"}</span></header>
          ${fs.length ? `<ul class="facts">${fs.map((f) => `<li class="${fresh(`f|${f.url}|${f.fact}`)}">${esc(f.fact)} <a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.source)}</a></li>`).join("")}</ul>` : busy ? factsSkeleton(qi) : ""}</div>`;
      }).join("")}</div>` : '<p class="hint">This plan has no research questions, so the writer will use common knowledge only.</p>'}
      ${steps.length ? `<details class="trace" ${EP.job.running ? "open" : ""}><summary>How the research agent worked (${steps.length} steps)</summary>
        <ol>${steps.map((s) => `<li><b>${esc(s.event)}</b>${s.thought ? `<span class="th">${esc(s.thought)}</span>` : ""}
          ${s.result ? `<pre>${esc(s.result)}</pre>` : ""}</li>`).join("")}</ol></details>` : ""}`;
  },

  script() {
    if (!EP.plan) return EP.job.running ? scriptSkeleton() : empty("Plan the episode first.");
    if (!hasScript() && !EP.job.running) {
      return `<div class="empty"><p>${EP.facts.length ? `Research found ${EP.facts.length} facts.` : "There is no research yet, so the writer will only use common knowledge."}
        The writer drafts each segment, then a fact-checker and an editor review it, with up to two rounds of fixes.</p>
        <button class="btn btn-primary" data-act="writeAll">Write the script</button></div>`;
    }
    const segs = EP.plan.segments, now = drafting();
    return `${hasScript() && EP.stats ? statsBar() : writes() ? statsSkeleton() : ""}
      <div class="bar">
        <button class="btn" data-act="writeAll">Rewrite the whole script</button>
        ${segs.some((s) => !s.turns?.length) ? '<button class="btn" data-act="writeMissing">Write missing segments</button>' : ""}
        <span class="grow"></span>
        ${hasScript() ? `<a class="btn btn-quiet" href="/api/episodes/${EP.id}/script.txt" target="_blank">script.txt</a>
          <a class="btn btn-quiet" href="/api/episodes/${EP.id}/script.json" target="_blank">script.json</a>` : ""}
      </div>
      ${segs.map((s, i) => sheet(s, i, writes() && (!s.turns?.length || i === now))).join("")}`;
  },

  audio() {
    if (!EP.plan || !hasScript()) return empty("Write the script first.");
    if (!CFG.tts.configured) {
      return empty("Audio needs a text-to-speech service. Start the server with TTS_BASE_URL and TTS_VOICES set, then reload this page.");
    }
    const picked = pickVoices(EP.plan.speakers, EP.audio?.voices || {}, EP.request.lang), ep = EP.audio?.episode;
    const ready = EP.lines.filter((l) => l.ready).length, busy = audioJob();
    const lock = EP.job.running ? "disabled" : ""; // no voice changes or new takes mid-job; playing is always fine
    const playing = (l) => !player.paused && player.src.endsWith(file(l.file)) ? " playing" : "";
    return `${busy && !ep ? playerSkeleton() : ""}${ep ? playerCard(ep) : ""}
      <section><h2>Voices</h2><div class="voices">${EP.plan.speakers.map((s, i) => `
        <label class="f" style="--c:${color(i)}"><b>${esc(s.name)}</b><span>${esc(s.gender)}, ${esc(s.role)}</span>
          <select data-voice="${esc(s.name)}" ${lock}>${voiceOptions(picked[s.name], EP.request.lang)}</select></label>`).join("")}
        </div>
        <div class="bar" style="margin-top:12px"><button class="btn btn-primary" data-act="genAudio" ${lock}>${ready ? "Update audio" : "Generate audio"}</button>
          <span class="hint">${ready} of ${EP.lines.length} lines have audio${ready && ready < EP.lines.length ? "; only new or changed lines are generated" : ""}.</span></div></section>
      <section><h2>Lines</h2>${EP.plan.segments.map((s, si) => {
        const mine = EP.lines.map((l, i) => [l, i]).filter(([l]) => l.segment === si);
        if (!mine.length) return "";
        const ch = ep?.chapters?.findIndex((c) => c.title === s.title && ep.times?.[mine[0][1]]?.[1] === c.start);
        const span = ch >= 0 ? `${mmss(ep.chapters[ch].start)}–${mmss(ep.chapters[ch + 1]?.start ?? ep.seconds)}, ` : "";
        return `<div class="chap"><h3><span class="n">${si + 1}</span>${esc(s.title)}<span class="hint">${span}${mine.length} lines</span></h3>
        ${mine.map(([l, i], k) => {
          const at = ep?.times?.[i]?.[0] === l.file ? ep.times[i] : null; // [file, start, end] in the episode, if still current
          return `<div class="al" style="--c:${chanOf(l.speaker)}" ${at ? `data-t="${at[1]}" data-e="${at[2]}"` : ""} ${l.mode === "backchannel" ? "data-bc" : ""}
            data-n="${k + 1}" data-sp="${esc(l.speaker)}">
          ${l.ready ? `<button class="play${playing(l)}${fresh(`a|${l.file}`)}" type="button" data-act="play" data-src="${file(l.file)}" aria-label="Play line ${k + 1}">${PLAY}</button>` : busy ? sk("32px", "dot") : "<span></span>"}
          <span class="who"><span class="k">${k + 1}</span>${esc(l.speaker)}${l.mode ? `<small>${MODE_NOTE[l.mode]}</small>` : ""}</span>${at ? `<button class="tx" type="button" data-act="seek" data-t="${at[1]}" lang="${EP.request.lang}"
            title="Play the episode from here">${esc(l.text)}</button>` : `<span class="tx" lang="${EP.request.lang}" title="${esc(l.text)}">${esc(l.text)}</span>`}
          ${l.ready ? `<button class="btn btn-quiet" data-act="retake" data-i="${l.segment}" data-k="${l.line}" ${lock}>New take</button>` : busy ? sk("84px") : '<span class="pending">no audio yet</span>'}
        </div>`;
        }).join("")}</div>`;
      }).join("")}</section>`;
  },
};

// the episode player: play and pause, what is playing now, a scrubber cut at the chapters, the chapters to jump to
function playerCard(ep) {
  const T = ep.seconds, ch = ep.chapters?.length ? ep.chapters : [{ title: "Episode", start: 0 }];
  const segs = ch.map((c, i) => [c.start, ch[i + 1]?.start ?? T]);
  return `<div class="player">
    <audio preload="metadata" src="${file(ep.file)}?v=${ep.built}"></audio>
    <div class="transport">
      <button class="play big" type="button" data-act="toggle" aria-label="Play or pause the episode">${PLAY}</button>
      <div class="np"><b class="np-t">${esc(ch[0].title)}</b><span class="np-s" data-idle="${esc(`${(T / 60).toFixed(1)} minutes${
        ep.speed > 1 ? ` at ${ep.speed}× speed` : ""}${ep.chars_per_min ? `, ${ep.chars_per_min} characters a minute` : ""}`)}">${(T / 60).toFixed(1)} minutes${
        ep.speed > 1 ? ` at ${ep.speed}× speed` : ""}${ep.chars_per_min ? `, ${ep.chars_per_min} characters a minute` : ""}</span></div>
      <span class="dl"><a class="btn btn-quiet" href="${file(ep.file)}" download>${DOWNLOAD}MP3</a>
        <a class="btn btn-quiet" href="${file("episode.wav")}" download>WAV</a></span>
    </div>
    <div class="scrub"><time class="cur">0:00</time>
      <span class="track"><span class="segs" aria-hidden="true">${segs.map(([a, b]) =>
        `<span style="flex:${Math.max(b - a, 1).toFixed(1)}" data-a="${a}" data-b="${b}"><i></i></span>`).join("")}</span>
        <input type="range" class="seek" min="0" max="${T}" step="0.1" value="0" aria-label="Position in the episode"></span>
      <time>${mmss(T)}</time></div>
    ${ep.times ? "" : '<p class="hint">Built before chapters and line highlighting existed: click Update audio below to add them (no lines are generated again).</p>'}
    ${ep.chapters?.length ? `<ol class="chapters" aria-label="Chapters">${ep.chapters.map((c, i) => `<li><button type="button"
      data-act="seek" data-t="${c.start}"><b>${i + 1}</b><span>${esc(c.title)}</span><time>${mmss(c.start)}</time></button></li>`).join("")}</ol>` : ""}
  </div>`;
}

const sampleLines = (i, lines = samples[i]) => lines ? `<ul class="sample-lines" lang="${EP.request.lang}">${lines.map((x) =>
  `<li>${esc(x)}</li>`).join("")}</ul>` : "";

function statsBar() {
  const st = EP.stats, sp = EP.plan.speakers;
  return `<div class="stats">
    <div><b>~${st.est_minutes} min</b><span>estimated, target ${EP.request.minutes}</span></div>
    <div><b>${st.turns}</b><span>lines</span></div>
    <div><b>${st.open_issues}</b><span>open issues</span></div>
    <div class="share"><span>Who talks how much</span>
      <div class="b">${sp.map((s, i) => `<i style="background:${color(i)};width:${(st.speaker_share[s.name] || 0) * 100}%"></i>`).join("")}</div>
      <div class="k">${sp.map((s, i) => `<span><i style="background:${color(i)}"></i>${esc(s.name)} ${Math.round((st.speaker_share[s.name] || 0) * 100)}%</span>`).join("")}</div>
    </div></div>`;
}

// how a line starts (stored as the line's third field); see checks.TAGS
const MODES = [["", "Own turn"], ["backchannel", "Filler, they keep talking"], ["cut", "Cuts in, hard stop"], ["fade", "Cuts in, fade out"]];
const MODE_NOTE = { backchannel: "filler", cut: "cuts in", fade: "cuts in, fades" };

function lineRow(sp, tx, mode = "", cls = "") {
  const names = EP.plan.speakers.map((s) => s.name);
  return `<div class="ln${cls}" style="--c:${chanOf(sp)}" data-mode="${mode}">
    <span class="who"><select class="sp" aria-label="Speaker">${names.map((n) => `<option ${n === sp ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
      <select class="md" aria-label="How this line starts" title="Filler: a quick hmm or I see in a pause of the previous line, which carries on. Cuts in: starts before the previous line ends, which stops dead or fades out.">
        ${MODES.map(([v, t]) => `<option value="${v}" ${v === mode ? "selected" : ""}>${t}</option>`).join("")}</select></span>
    <textarea class="auto" rows="1" lang="${EP.request.lang}" aria-label="Line">${esc(tx)}</textarea>
    <span class="acts"><button class="btn btn-quiet" type="button" data-act="insLine" aria-label="Insert a line below">${PLUS}</button>
      <button class="btn btn-quiet" type="button" data-act="delLine" aria-label="Delete this line">${CROSS}</button></span></div>`;
}

function sheet(s, i, wait = false) { // wait: the lines are being written, show placeholders
  const lines = wait ? [] : s.turns || [];
  return `<section class="sheet" data-seg="${i}">
    <header><span class="n">${i + 1}</span><h3>${esc(s.title)}</h3>
      <span class="hint">${s.minutes} min${lines.length ? `, ${lines.length} lines` : ""}</span>
      <span class="goal">${esc(s.goal || "")}</span></header>
    ${s.open_issues?.length && !wait ? `<ul class="issues">${s.open_issues.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    <div class="lines">${wait ? linesSkeleton(Math.min(8, Math.max(4, Math.round(s.minutes * 3))), i)
      : lines.map(([sp, tx, mode], k) => lineRow(sp, tx, mode, fresh(`l|${i}|${k}|${tx}`))).join("") || '<p class="hint">Not written yet.</p>'}</div>
    <footer>
      <button class="btn btn-primary" data-act="saveSeg" data-i="${i}" ${dirty.has(i) ? "" : "disabled"}>Save edits</button>
      <button class="btn" type="button" data-act="addLine" data-i="${i}">Add line</button>
      <button class="btn" data-act="reviewSeg" data-i="${i}" ${lines.length ? "" : "disabled"}>Review</button>
      <button class="btn" data-act="fixSeg" data-i="${i}" ${lines.length ? "" : "disabled"}>Fix issues</button>
      <input type="text" name="note" placeholder="Note for the writer, e.g. add a cricket analogy" aria-label="Note for the writer">
      <button class="btn" data-act="rewriteSeg" data-i="${i}">${lines.length ? "Rewrite" : "Write"}</button>
    </footer></section>`;
}

// ---------------------------------------------------------------- edits
function collectPlan() {
  const p = structuredClone(EP.plan);
  $$(".strip").forEach((el, i) => {
    for (const n of ["name", "gender", "role", "knowledge", "style"]) p.speakers[i][n] = $(`[name=${n}]`, el).value.trim();
  });
  p.segments = $$(".outline li").map((li) => {
    const g = (n) => $(`[name=${n}]`, li).value;
    return { ...EP.plan.segments[+li.dataset.seg], title: g("title").trim(), minutes: +g("minutes"), goal: g("goal").trim(),
      questions: g("questions").split("\n").map((x) => x.trim()).filter(Boolean) };
  });
  return p;
}
const collectSeg = (i) => $$(`.sheet[data-seg="${i}"] .ln:not(.sk-ln)`).map((ln) => [$(".sp", ln).value, $("textarea", ln).value, $(".md", ln).value]);
function markDirty(i) {
  dirty.add(i);
  const b = $(`.sheet[data-seg="${i}"] [data-act=saveSeg]`);
  if (b) b.disabled = false;
}
async function saveDirty() {
  for (const i of [...dirty]) {
    await api("PUT", `/api/episodes/${EP.id}/segments/${i}`, { turns: collectSeg(i) });
    dirty.delete(i);
  }
}

// run an API call on this episode, then reload it (which starts polling if a job started)
async function act(method, path, body, msg) {
  try {
    if (dirty.size) await saveDirty();
    await api(method, `/api/episodes/${EP.id}${path}`, body);
    if (msg) toast(msg);
    await load(EP.id);
    refreshList();
  } catch (e) {
    toast(e.message, true);
  }
}

const ACTIONS = {
  more: () => { SHOWN += 24; fillCovers(); },
  duplicate: async () => {
    try {
      const { id } = await api("POST", `/api/episodes/${EP.id}/duplicate`);
      toast("Copied. Planning the copy now.");
      location.hash = `#/ep/${id}/plan`;
    } catch (e) { toast(e.message, true); }
  },
  deleteEp: async () => {
    if (!confirm(`Delete "${EP.plan?.title || EP.request.topic}"? It leaves your episodes and moves to the trash folder on the server.`)) return;
    try {
      await api("DELETE", `/api/episodes/${EP.id}`);
      dirty.clear();
      EP = null;
      toast("Deleted");
      location.hash = "#/episodes";
    } catch (e) { toast(e.message, true); }
  },
  pickCover: () => $("#coverfile").click(), // the input lives outside #main, so a re-render can't drop the pick
  dropCover: () => act("DELETE", "/cover", undefined, "Cover removed"),
  step: (b) => { // the − and + beside speakers and length; the number input keeps it within min and max
    const input = b.form[b.dataset.name];
    if (b.dataset.d > 0) input.stepUp(); else input.stepDown();
  },
  sample: async (b) => { // three lines from the persona as typed; nothing is saved
    const i = +b.dataset.i, strip = b.closest(".strip"), box = $(".sample", strip);
    const speaker = Object.fromEntries(["name", "gender", "role", "knowledge", "style"].map((n) => [n, $(`[name=${n}]`, strip).value.trim()]));
    b.disabled = true;
    box.innerHTML = `<ul class="sample-lines" aria-hidden="true">${times(3, (k) => `<li>${para(1 + ((i + k) % 2), i + k)}</li>`)}</ul>
      <p class="vh" role="status">Writing sample lines</p>`;
    syncShimmer();
    try {
      samples[i] = (await api("POST", `/api/episodes/${EP.id}/sample`, speaker)).lines;
    } catch (e) { toast(e.message, true); }
    box.innerHTML = sampleLines(i);
    b.disabled = false;
  },
  replan: () => (!EP.plan || confirm("Plan again from scratch? This replaces the plan, the research and the script.")) && act("POST", "/plan"),
  savePlan: () => act("PUT", "/plan", collectPlan(), "Plan saved"),
  research: async () => {
    if (EP.facts.length && !confirm("Research again? The current facts are replaced.")) return;
    if (TAB === "plan") {
      try { await api("PUT", `/api/episodes/${EP.id}/plan`, collectPlan()); } catch (e) { return toast(e.message, true); }
    }
    act("POST", "/research");
  },
  addSeg: () => {
    EP.plan = collectPlan();
    EP.plan.segments.splice(EP.plan.segments.length - 1, 0, { title: "New segment", minutes: 2, goal: "", questions: [] });
    render();
  },
  dropSeg: (b) => {
    EP.plan = collectPlan();
    const s = EP.plan.segments[+b.dataset.i];
    if (s.turns?.length && !confirm(`Remove "${s.title}" and its ${s.turns.length} script lines?`)) return;
    EP.plan.segments.splice(+b.dataset.i, 1);
    render();
  },
  writeAll: () => (!hasScript() || confirm("Rewrite every segment? Your edits are replaced.")) && act("POST", "/write", {}),
  writeMissing: () => act("POST", "/write", { only_missing: true }),
  saveSeg: async (b) => {
    const i = +b.dataset.i;
    try {
      const { issues } = await api("PUT", `/api/episodes/${EP.id}/segments/${i}`, { turns: collectSeg(i) });
      dirty.delete(i);
      toast(issues.length ? `Saved. ${issues.length} checks to look at.` : "Saved.");
      load(EP.id);
    } catch (e) { toast(e.message, true); }
  },
  addLine: (b) => {
    const i = +b.dataset.i, rows = $$(`.sheet[data-seg="${i}"] .ln`), names = EP.plan.speakers.map((s) => s.name);
    const last = rows.length ? $(".sp", rows[rows.length - 1]).value : names[1];
    const box = $(`.sheet[data-seg="${i}"] .lines`);
    if (!rows.length) box.innerHTML = "";
    box.insertAdjacentHTML("beforeend", lineRow(names.find((n) => n !== last) || names[0], ""));
    $("textarea", box.lastElementChild).focus();
    markDirty(i);
  },
  insLine: (b) => {
    const row = b.closest(".ln"), names = EP.plan.speakers.map((s) => s.name), cur = $(".sp", row).value;
    row.insertAdjacentHTML("afterend", lineRow(names.find((n) => n !== cur) || cur, ""));
    $("textarea", row.nextElementSibling).focus();
    markDirty(+b.closest(".sheet").dataset.seg);
  },
  delLine: (b) => {
    const i = +b.closest(".sheet").dataset.seg;
    b.closest(".ln").remove();
    markDirty(i);
  },
  reviewSeg: (b) => act("POST", `/segments/${b.dataset.i}/review`, {}),
  fixSeg: (b) => act("POST", `/segments/${b.dataset.i}/fix`, { note: $(`.sheet[data-seg="${b.dataset.i}"] [name=note]`).value }),
  rewriteSeg: (b) => {
    const i = +b.dataset.i;
    if (EP.plan.segments[i].turns?.length && !confirm("Rewrite this segment from scratch? Its current lines are replaced.")) return;
    dirty.delete(i);
    act("POST", `/segments/${i}/rewrite`, { note: $(`.sheet[data-seg="${i}"] [name=note]`).value });
  },
  genAudio: () => {
    const voices = Object.fromEntries($$("[data-voice]").map((s) => [s.dataset.voice, s.value]));
    act("POST", "/audio", { voices });
  },
  retake: (b) => act("POST", `/audio/${b.dataset.i}/${b.dataset.k}`),
  toggle: () => {
    const a = $(".player audio");
    player.pause();
    $$(".al .play.playing").forEach((x) => x.classList.remove("playing"));
    if (a.paused) a.play().catch(() => toast("Could not play the episode.", true)); else a.pause();
  },
  seek: (b) => { // a chapter or a line: play the episode from there
    const a = $(".player audio");
    player.pause();
    $$(".play.playing").forEach((x) => x.classList.remove("playing"));
    a.currentTime = +b.dataset.t;
    a.play();
  },
  play: (b) => {
    if (b.classList.contains("ep")) return $(".player audio").pause(); // this row is the episode's line playing now
    $(".player audio")?.pause();
    const playing = b.classList.contains("playing");
    $$(".play.playing").forEach((x) => x.classList.remove("playing"));
    if (playing) return player.pause();
    player.src = b.dataset.src;
    b.classList.add("playing");
    player.play().catch(() => { b.classList.remove("playing"); toast("Could not play this.", true); });
    player.onended = () => $$(".play.playing").forEach((x) => x.classList.remove("playing")); // the button may be redrawn by now
  },
};

// ---------------------------------------------------------------- events
let FOLLOWED = null; // start time of the line the transcript last scrolled to
function follow(a) { // mark what the episode is playing: its chapter, its line, and a filler said over that line
  const t = a.currentTime, chs = $$(".chapters button"), rows = $$(".al[data-t]"), box = a.closest(".player");
  $(".play.big", box).classList.toggle("playing", !a.paused);
  $(".cur", box).textContent = mmss(t);
  if (document.activeElement !== $(".seek", box)) $(".seek", box).value = t;
  $$(".segs > span", box).forEach((s) => {
    const x = +s.dataset.a, y = +s.dataset.b;
    s.firstChild.style.width = `${Math.min(100, Math.max(0, (t - x) / (y - x) * 100))}%`;
    s.classList.toggle("now", t >= x && t < y);
  });
  chs.forEach((b, i) => {
    const now = t >= +b.dataset.t && (i === chs.length - 1 || t < +chs[i + 1].dataset.t);
    if (now && !b.classList.contains("now")) b.closest("ol").scrollTo({ left: b.parentElement.offsetLeft - 16 }); // in view
    b.classList.toggle("now", now);
  });
  rows.forEach((r) => r.classList.toggle("now", t >= +r.dataset.t && t < +r.dataset.e));
  const cur = rows.find((r) => r.classList.contains("now") && !("bc" in r.dataset));
  rows.forEach((r) => $(".play", r)?.classList.toggle("ep", r === cur && !a.paused));
  const chap = chs.find((b) => b.classList.contains("now")), np = $(".np-s", box);
  if (chap) $(".np-t", box).textContent = $("span", chap).textContent;
  np.textContent = cur && (t > 0 || !a.paused) ? `Line ${cur.dataset.n}, ${cur.dataset.sp}` : np.dataset.idle;
  if (!cur || a.paused || cur.dataset.t === FOLLOWED) return;
  FOLLOWED = cur.dataset.t;
  const top = $(".player").getBoundingClientRect().bottom, r = cur.getBoundingClientRect();
  const nav = $(".tabs").getBoundingClientRect().top, floor = nav > innerHeight / 2 ? nav : innerHeight;
  if (r.top < top || r.bottom > floor) { // out of sight: bring it to the middle
    cur.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }
}
for (const ev of ["timeupdate", "play", "pause", "seeked"]) { // capture: media events do not bubble
  document.addEventListener(ev, (e) => { if (e.target.closest?.(".player")) follow(e.target); }, true);
}

document.addEventListener("click", (e) => {
  const c = e.target.closest(".cover-link");
  if (c && e.button === 0 && !(e.metaKey || e.ctrlKey || e.shiftKey)) OPENING = $(".cover", c); // it grows into the episode
  const b = e.target.closest("[data-act]");
  if (!b || b.disabled) return;
  e.preventDefault();
  ACTIONS[b.dataset.act](b);
});
document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.matches("textarea.auto")) autosize(t);
  if (t.form?.id === "newform") updateNewForm(t.form);
  if (t.id === "find-q") { FIND.q = t.value; SHOWN = 24; fillCovers(); }
  if (t.matches(".seek")) { const a = $(".player audio"); a.currentTime = +t.value; follow(a); }
  const sh = t.closest(".sheet");
  if (sh && t.name !== "note") markDirty(+sh.dataset.seg);
});
document.addEventListener("change", (e) => {
  const t = e.target;
  if (t.form?.id === "newform" || t.form?.id === "settingsform") updateNewForm(t.form);
  if (t.name === "theme") setTheme(t.value);
  if (t.id === "find-lang" || t.name === "find-state") {
    FIND[t.id === "find-lang" ? "lang" : "state"] = t.value;
    SHOWN = 24;
    fillCovers();
  }
  const ln = t.closest(".ln");
  if (ln && t.tagName === "SELECT") {
    if (t.matches(".sp")) ln.style.setProperty("--c", chanOf(t.value));
    else ln.dataset.mode = t.value;
    markDirty(+t.closest(".sheet").dataset.seg);
  }
});
document.addEventListener("submit", (e) => {
  const f = e.target, run = { newform: () => submitNew(f, e.submitter?.value), settingsform: () => saveSettings(f), voiceform: () => saveVoices(f) }[f.id];
  if (!run) return;
  e.preventDefault();
  run();
});
// a picked cover is cropped to a centred square of at most 1000 px and re-encoded here, which keeps covers small
// and drops the photo's metadata, then uploaded
$("#coverfile").addEventListener("change", async (e) => {
  const file = e.target.files[0], id = EP?.id;
  e.target.value = "";
  if (!file || !id) return;
  let img;
  try { img = await createImageBitmap(file); } catch { return toast("Could not read that image. Try a JPEG or PNG.", true); }
  const side = Math.min(img.width, img.height), out = Math.min(side, 1000), c = document.createElement("canvas");
  c.width = c.height = out;
  c.getContext("2d").drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, out, out);
  const blob = await new Promise((done) => c.toBlob(done, "image/jpeg", 0.88));
  try {
    const r = await fetch(`/api/episodes/${id}/cover`, { method: "PUT", headers: { "Content-Type": "image/jpeg" }, body: blob });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `${r.status} ${r.statusText}`);
    toast("Cover updated");
    if (EP?.id === id) load(id);
    refreshList();
  } catch (err) { toast(err.message, true); }
});
window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (e) => { if (dirty.size) e.preventDefault(); });

(async () => {
  const [, view, id, tab] = location.hash.split("/"), v = viewOf(view, id);
  setView(v);
  if (v === "ep") episodeSkeleton(STEPS.some(([k]) => k === tab) ? tab : "plan");
  else if (v === "new") homeSkeleton();
  else paint(page(cap(v), pageSkeleton(v)));
  [CFG, SETTINGS] = await Promise.all([api("GET", "/api/config"), api("GET", "/api/settings")]);
  if (!location.hash || location.hash === "#") location.hash = "#/new";
  else route();
})();
