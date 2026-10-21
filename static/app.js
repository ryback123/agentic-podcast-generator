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
const PLAY = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 1l9 5-9 5z"/></svg>';

let CFG = null, EP = null, TAB = "plan", timer = null, wasRunning = false;
const dirty = new Set(); // segment indexes with unsaved script edits
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
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
const file = (p) => `/api/episodes/${EP.id}/files/${p}`;
const hasScript = () => !!EP.plan?.segments.some((s) => s.turns?.length);
const empty = (msg) => `<div class="empty"><p>${esc(msg)}</p></div>`;
function autosize(t) { t.style.height = "auto"; t.style.height = t.scrollHeight + 2 + "px"; }

// ---------------------------------------------------------------- routing
async function route() {
  const [, view, id, tab] = location.hash.split("/");
  clearTimeout(timer);
  if (dirty.size && EP) await saveDirty();
  if (view === "ep" && id) {
    TAB = STEPS.some(([k]) => k === tab) ? tab : "plan";
    if (!EP || EP.id !== id) { dirty.clear(); wasRunning = false; }
    await load(id);
  } else {
    EP = null;
    renderNew();
  }
  renderList();
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
    renderList();
    if (EP.job.error) toast(EP.job.error, true);
    else toast(`Finished: ${EP.job.task}`);
  }
  wasRunning = running;
  if (running) timer = setTimeout(() => load(id), 1500);
}

async function renderList() {
  const list = await api("GET", "/api/episodes").catch(() => []);
  $("#episodes").innerHTML = list.length
    ? list.map((e) => {
        const state = e.running ? '<span class="live">on air</span>' : e.has_audio ? "audio ready" : e.has_script ? "script ready" : "planned";
        const tab = e.has_audio ? "audio" : e.has_script ? "script" : "plan";
        return `<a class="ep-link" href="#/ep/${e.id}/${tab}" ${e.id === EP?.id ? 'aria-current="page"' : ""}>
          <span class="t" lang="${e.lang}">${esc(e.title)}</span><span class="s">${NATIVE[e.lang] || e.lang}, ${state}</span></a>`;
      }).join("")
    : '<p class="ep-link s">Your episodes will appear here.</p>';
}

// ---------------------------------------------------------------- new episode
function renderNew() {
  $("#main").innerHTML = `<form class="new" id="newform">
    <h1>New episode</h1>
    <label class="f"><span>What should the episode be about?</span>
      <textarea class="topic" name="topic" rows="2" required placeholder="How UPI payments work"></textarea></label>
    <label class="f"><span>Who is it for, and how should it feel? (optional)</span>
      <textarea name="description" rows="2" placeholder="Class 8 students; friendly, with everyday examples"></textarea></label>
    <div class="f"><span>Language</span><div class="langs" role="radiogroup" aria-label="Language">
      ${CFG.languages.map((l) => `<label><input type="radio" name="lang" value="${l.code}" ${l.code === "hi" ? "checked" : ""}>
        <span lang="${l.code}">${NATIVE[l.code] || l.name}<small>${l.name}</small></span></label>`).join("")}
    </div></div>
    <div class="row">
      <label class="f"><span>Speakers: <output name="spk">2</output></span>
        <input type="range" name="speakers" min="2" max="5" value="2"></label>
      <label class="f"><span>Length: <output name="mins">12</output> minutes</span>
        <input type="range" name="minutes" min="5" max="20" value="12"></label>
    </div>
    <div class="f" id="mixbox"><span>English mixing</span>
      <div class="seg">${CFG.code_mix.map((m) => `<label><input type="radio" name="code_mix" value="${m}" ${m === "medium" ? "checked" : ""}><span>${cap(m)}</span></label>`).join("")}</div>
      <p class="hint" id="mixhint">${MIX.medium}</p></div>
    <div class="bar">
      <button class="btn btn-primary" type="submit" value="auto">Make the whole episode</button>
      <button class="btn" type="submit" value="plan">Plan first, then decide</button>
    </div>
    <p class="hint">Making the whole episode runs planning, research and writing in one go, which takes about five to eight minutes.
      Planning first lets you change the cast and outline before research starts.</p>
  </form>`;
}
function updateNewForm(form) {
  form.spk.value = form.speakers.value;
  form.mins.value = form.minutes.value;
  $("#mixbox").hidden = form.lang.value === "en";
  $("#mixhint").textContent = MIX[form.code_mix.value];
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
  if (k === "script") return hasScript() && EP.stats ? `~${EP.stats.est_minutes} min` : "";
  if (k === "audio") return EP.audio?.episode ? `${(EP.audio.episode.seconds / 60).toFixed(1)} min` : "";
}

function render() {
  const p = EP.plan, r = EP.request, job = EP.job;
  const title = p?.title || r.topic;
  const lamp = job.running ? `<div class="lamp on" role="status"><i></i>${esc(cap(job.task))}…</div>`
    : job.error ? `<div class="lamp err" role="status"><i></i>Stopped: ${esc(job.error.slice(0, 90))}</div>`
    : `<div class="lamp" role="status"><i></i>Off air</div>`;
  $("#main").innerHTML = `
    <div class="head"><div>
      <h1 class="${/[^\x00-\x7F]/.test(title) ? "native" : ""}" lang="${r.lang}">${esc(title)}</h1>
      <div class="meta"><span>${NATIVE[r.lang]}</span><span>${r.speakers} speakers</span><span>${r.minutes} minute target</span>
        ${r.lang !== "en" ? `<span>${cap(r.code_mix)} English mixing</span>` : ""}<span>Topic: ${esc(r.topic)}</span></div>
    </div>${lamp}</div>
    <nav class="steps" aria-label="Steps">${STEPS.map(([k, l], i) =>
      `<a href="#/ep/${EP.id}/${k}" ${k === TAB ? 'aria-current="page"' : ""}><b>${i + 1}</b>${l}<small>${stepNote(k)}</small></a>`).join("")}</nav>
    <div class="work"><fieldset class="stage" ${job.running ? "disabled" : ""}>${VIEWS[TAB]()}</fieldset>${cue()}</div>`;
  $$("textarea.auto").forEach(autosize);
  const c = $(".cue");
  c.scrollTop = c.scrollHeight;
}

function cue() {
  const items = EP.log.slice(-150);
  return `<aside class="cue" aria-label="Agent activity"><h2>Activity</h2><ol>${items.map((e) =>
    `<li class="${e.agent === "error" ? "error" : ""}"><time>${clock(e.t)}</time><span class="who">${esc(AGENT[e.agent] || e.agent)}</span>
      ${esc(e.event)}${e.thought ? `<span class="th">${esc(e.thought)}</span>` : ""}</li>`).join("")}</ol></aside>`;
}

const VIEWS = {
  plan() {
    if (!EP.plan) {
      return EP.job.running ? empty("The producer is choosing the cast and outline.")
        : `<div class="empty"><p>No plan yet.</p><button class="btn btn-primary" data-act="replan">Plan the episode</button></div>`;
    }
    const p = EP.plan;
    return `<section><h2>Cast</h2><div class="strips">${p.speakers.map((s, i) => `
      <div class="strip" style="--c:${color(i)}">
        <input type="text" class="nm" name="name" value="${esc(s.name)}" aria-label="Speaker name">
        <label class="f"><span>Gender</span><select name="gender">${["female", "male"].map((g) =>
          `<option ${s.gender === g ? "selected" : ""}>${g}</option>`).join("")}</select></label>
        <label class="f"><span>Role</span><input type="text" name="role" value="${esc(s.role)}"></label>
        <label class="f"><span>Knows</span><textarea class="auto" name="knowledge" rows="2">${esc(s.knowledge)}</textarea></label>
        <label class="f"><span>Talks</span><textarea class="auto" name="style" rows="2">${esc(s.style)}</textarea></label>
      </div>`).join("")}</div></section>
    <section><h2>Outline</h2><ol class="outline">${p.segments.map((s, i) => `
      <li data-seg="${i}">
        <input type="text" name="title" value="${esc(s.title)}" aria-label="Segment title">
        <input type="number" name="minutes" min="0.5" step="0.5" value="${s.minutes}" aria-label="Minutes">
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
    if (!EP.plan) return empty("Plan the episode first.");
    const qs = Object.entries(EP.questions);
    const steps = EP.log.filter((e) => e.agent === "researcher");
    const pages = new Set(EP.facts.map((f) => f.url)).size;
    return `<div class="bar">
        <button class="btn btn-primary" data-act="research">${EP.facts.length ? "Research again" : "Run research"}</button>
        <button class="btn" data-act="writeAll">${hasScript() ? "Rewrite the whole script" : "Write the script"}</button>
        <span class="grow"></span><span class="hint">${EP.facts.length} facts from ${pages} pages</span></div>
      ${qs.length ? `<div class="qs">${qs.map(([q, t]) => {
        const fs = EP.facts.filter((f) => f.q === q);
        return `<div class="q"><header><h3>${esc(t)}</h3>
          <span class="pips" title="${fs.length} facts" aria-label="${fs.length} facts">${[0, 1, 2].map((k) => `<i class="${fs.length > k ? "on" : ""}"></i>`).join("")}</span></header>
          ${fs.length ? `<ul class="facts">${fs.map((f) => `<li>${esc(f.fact)} <a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.source)}</a></li>`).join("")}</ul>` : ""}</div>`;
      }).join("")}</div>` : '<p class="hint">This plan has no research questions, so the writer will use common knowledge only.</p>'}
      ${steps.length ? `<details class="trace" ${EP.job.running ? "open" : ""}><summary>How the research agent worked (${steps.length} steps)</summary>
        <ol>${steps.map((s) => `<li><b>${esc(s.event)}</b>${s.thought ? `<span class="th">${esc(s.thought)}</span>` : ""}
          ${s.result ? `<pre>${esc(s.result)}</pre>` : ""}</li>`).join("")}</ol></details>` : ""}`;
  },

  script() {
    if (!EP.plan) return empty("Plan the episode first.");
    if (!hasScript() && !EP.job.running) {
      return `<div class="empty"><p>${EP.facts.length ? `Research found ${EP.facts.length} facts.` : "There is no research yet, so the writer will only use common knowledge."}
        The writer drafts each segment, then a fact-checker and an editor review it, with up to two rounds of fixes.</p>
        <button class="btn btn-primary" data-act="writeAll">Write the script</button></div>`;
    }
    const segs = EP.plan.segments;
    return `${hasScript() && EP.stats ? statsBar() : ""}
      <div class="bar">
        <button class="btn" data-act="writeAll">Rewrite the whole script</button>
        ${segs.some((s) => !s.turns?.length) ? '<button class="btn" data-act="writeMissing">Write missing segments</button>' : ""}
        <span class="grow"></span>
        ${hasScript() ? `<a class="btn btn-quiet" href="${file("script.txt")}" target="_blank">script.txt</a>
          <a class="btn btn-quiet" href="${file("script.json")}" target="_blank">script.json</a>` : ""}
      </div>
      ${segs.map(sheet).join("")}`;
  },

  audio() {
    if (!EP.plan || !hasScript()) return empty("Write the script first.");
    if (!CFG.tts.configured) {
      return empty("Audio needs a text-to-speech service. Start the server with TTS_BASE_URL and TTS_VOICES set, then reload this page.");
    }
    const voices = EP.audio?.voices || {}, V = CFG.tts.voices, ep = EP.audio?.episode;
    const ready = EP.lines.filter((l) => l.ready).length;
    return `${ep ? `<div class="player"><h2>Episode</h2>
        <audio controls preload="none" src="${file(ep.file)}?v=${ep.built}"></audio>
        <div class="bar"><span class="hint">${(ep.seconds / 60).toFixed(1)} minutes${ep.chars_per_min ? `, ${ep.chars_per_min} characters a minute` : ""}</span>
          <span class="grow"></span><a class="btn" href="${file(ep.file)}" download>Download MP3</a>
          <a class="btn btn-quiet" href="${file("episode.wav")}" download>WAV</a></div></div>` : ""}
      <section><h2>Voices</h2><div class="voices">${EP.plan.speakers.map((s, i) => `
        <label class="f" style="--c:${color(i)}"><b>${esc(s.name)}</b><span>${esc(s.gender)}, ${esc(s.role)}</span>
          <select data-voice="${esc(s.name)}">${V.map((v) => `<option ${(voices[s.name] || V[i % V.length]) === v ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>`).join("")}
        </div>
        <div class="bar" style="margin-top:12px"><button class="btn btn-primary" data-act="genAudio">${ready ? "Update audio" : "Generate audio"}</button>
          <span class="hint">${ready} of ${EP.lines.length} lines have audio${ready && ready < EP.lines.length ? "; only new or changed lines are generated" : ""}.</span></div></section>
      <section><h2>Lines</h2>${EP.lines.map((l) => `<div class="al" style="--c:${chanOf(l.speaker)}">
        ${l.ready ? `<button class="play" type="button" data-act="play" data-src="${file(l.file)}" aria-label="Play line">${PLAY}</button>` : "<span></span>"}
        <span class="who">${esc(l.speaker)}</span><span class="tx" lang="${EP.request.lang}" title="${esc(l.text)}">${esc(l.text)}</span>
        ${l.ready ? `<button class="btn btn-quiet" data-act="retake" data-i="${l.segment}" data-k="${l.line}">New take</button>` : '<span class="pending">no audio yet</span>'}
      </div>`).join("")}</section>`;
  },
};

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

function lineRow(sp, tx) {
  const names = EP.plan.speakers.map((s) => s.name);
  return `<div class="ln" style="--c:${chanOf(sp)}">
    <select aria-label="Speaker">${names.map((n) => `<option ${n === sp ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
    <textarea class="auto" rows="1" lang="${EP.request.lang}" aria-label="Line">${esc(tx)}</textarea>
    <span class="acts"><button class="btn btn-quiet" type="button" data-act="insLine" aria-label="Insert a line below">+</button>
      <button class="btn btn-quiet" type="button" data-act="delLine" aria-label="Delete this line">×</button></span></div>`;
}

function sheet(s, i) {
  const lines = s.turns || [];
  return `<section class="sheet" data-seg="${i}">
    <header><span class="n">${i + 1}</span><h3>${esc(s.title)}</h3>
      <span class="hint">${s.minutes} min${lines.length ? `, ${lines.length} lines` : ""}</span>
      <span class="goal">${esc(s.goal || "")}</span></header>
    ${s.open_issues?.length ? `<ul class="issues">${s.open_issues.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    <div class="lines">${lines.map(([sp, tx]) => lineRow(sp, tx)).join("") || '<p class="hint">Not written yet.</p>'}</div>
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
const collectSeg = (i) => $$(`.sheet[data-seg="${i}"] .ln`).map((ln) => [$("select", ln).value, $("textarea", ln).value]);
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
    renderList();
  } catch (e) {
    toast(e.message, true);
  }
}

const ACTIONS = {
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
    const last = rows.length ? $("select", rows[rows.length - 1]).value : names[1];
    const box = $(`.sheet[data-seg="${i}"] .lines`);
    if (!rows.length) box.innerHTML = "";
    box.insertAdjacentHTML("beforeend", lineRow(names.find((n) => n !== last) || names[0], ""));
    $("textarea", box.lastElementChild).focus();
    markDirty(i);
  },
  insLine: (b) => {
    const row = b.closest(".ln"), names = EP.plan.speakers.map((s) => s.name), cur = $("select", row).value;
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
  play: (b) => {
    const playing = b.classList.contains("playing");
    $$(".play.playing").forEach((x) => x.classList.remove("playing"));
    if (playing) return player.pause();
    player.src = b.dataset.src;
    player.play();
    b.classList.add("playing");
    player.onended = () => b.classList.remove("playing");
  },
};

// ---------------------------------------------------------------- events
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (!b || b.disabled) return;
  e.preventDefault();
  ACTIONS[b.dataset.act](b);
});
document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.matches("textarea.auto")) autosize(t);
  if (t.form?.id === "newform") updateNewForm(t.form);
  const sh = t.closest(".sheet");
  if (sh && t.name !== "note") markDirty(+sh.dataset.seg);
});
document.addEventListener("change", (e) => {
  const t = e.target;
  if (t.form?.id === "newform") updateNewForm(t.form);
  const ln = t.closest(".ln");
  if (ln && t.tagName === "SELECT") {
    ln.style.setProperty("--c", chanOf(t.value));
    markDirty(+t.closest(".sheet").dataset.seg);
  }
});
document.addEventListener("submit", (e) => {
  if (e.target.id !== "newform") return;
  e.preventDefault();
  submitNew(e.target, e.submitter?.value);
});
window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (e) => { if (dirty.size) e.preventDefault(); });

(async () => {
  CFG = await api("GET", "/api/config");
  if (!location.hash || location.hash === "#") location.hash = "#/new";
  else route();
})();
