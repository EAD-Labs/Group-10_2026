const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 1) => (n === null || n === undefined) ? "—" : Number(n).toFixed(d);
const clock = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const cap = (s) => s ? s[0].toUpperCase() + s.slice(1) : s;
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (_) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
};

const STEPS = [
  ["calibrate", "Measure voice"], ["translate", "Translate & fit"], ["synthesize", "Voice"],
  ["align", "Align"], ["fit_audio", "Fine-tune"], ["export", "Mix video"],
];
const WEIGHTS = { calibrate: .06, translate: .34, synthesize: .38, align: .08, fit_audio: .04, export: .10 };

const S = {
  health: null, tutorials: [], voices: [], languages: [], selected: null, upload: false,
  pace: store.get("pace", "0.9"), job: null, track: null, timer: null, clip: new Audio(),
  view: "dubbed", hear: "dubbed", drawer: null, filter: "all", editing: null,
};

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

/* ------------------------------------------------------------------ setup */

async function init() {
  const [health, library, voices] = await Promise.all([api("/api/health"), api("/api/library"), api("/api/voices")]);
  S.health = health; S.tutorials = library.tutorials; S.voices = voices.voices;
  const ready = health.sarvam_key && health.indictrans_installed;
  $("#healthDot").className = `dot ${ready ? "ok" : "bad"}`;

  const fill = (el, values, preferred) => el.innerHTML = values.map((v) => `<option ${v === preferred ? "selected" : ""}>${esc(v)}</option>`).join("");
  fill($("#translator"), health.translators, !health.sarvam_key ? "echo" : health.indictrans_installed ? "indictrans+sarvam" : "sarvam");
  fill($("#tts"), health.tts, health.sarvam_key ? "sarvam" : "silent");
  fill($("#aligner"), health.aligners, health.sarvam_key ? "vad" : "clip-bounds");

  const option = (v) => `<option value="${v.id}">${cap(v.id)} · ${v.gender}</option>`;
  $("#voice").innerHTML = `<optgroup label="Recommended">${S.voices.filter((v) => v.featured).map(option).join("")}</optgroup>` +
    `<optgroup label="All voices">${S.voices.filter((v) => !v.featured).map(option).join("")}</optgroup>`;
  $("#voice").value = store.get("voice", voices.default);

  S.selected = store.get("tutorial", null);
  if (!S.tutorials.some((t) => t.id === S.selected)) S.selected = S.tutorials[0]?.id ?? null;
  renderTutorials();
  renderPace();
  await refreshLanguages(store.get("language", "ta"));

  const job = new URLSearchParams(location.search).get("job");
  if (job) openJob(job); else showSetup();
}

function renderTutorials() {
  const poster = (t) => t.video ? `style="background-image:url('/api/library/poster?video=${encodeURIComponent(t.video)}')"` : "";
  $("#tutorials").innerHTML = S.tutorials.map((t) => `
    <button class="tut ${!S.upload && S.selected === t.id ? "selected" : ""}" data-tut="${t.id}">
      <div class="poster" ${poster(t)}>${t.video ? "" : "▶"}</div>
      <div class="meta"><div class="title">${esc(t.title)}</div>
        <div class="sub">${t.duration ? clock(t.duration) + " · " : ""}${t.lines} lines${t.video ? "" : " · no video"}</div></div>
    </button>`).join("") + `
    <button class="tut ${S.upload ? "selected" : ""}" data-tut="__upload">
      <div class="poster">＋</div>
      <div class="meta"><div class="title">Upload your own</div><div class="sub">English script + video</div></div>
    </button>`;
  $("#uploadBox").hidden = !S.upload;
  renderPreview();
}

// The English original, playable before dubbing: a sample streams from the
// server, an upload plays straight from the chosen file without being sent.
function renderPreview() {
  const t = S.upload ? null : S.tutorials.find((x) => x.id === S.selected);
  const file = S.upload ? $("#uploadVideo").files[0] : null;
  const key = file ? `file:${file.name}:${file.size}` : t?.video || "";
  if (key === S.previewKey) return;  // re-rendering the cards must not restart playback
  S.previewKey = key;
  const player = $("#previewVideo");
  player.pause();
  if (S.previewUrl) { URL.revokeObjectURL(S.previewUrl); S.previewUrl = null; }
  if (file) S.previewUrl = URL.createObjectURL(file);
  const src = file ? S.previewUrl : t?.video ? `/api/library/video?video=${encodeURIComponent(t.video)}` : "";
  if (src) player.src = src; else player.removeAttribute("src");
  $("#preview").hidden = !src;
}
$("#uploadVideo").addEventListener("change", renderPreview);

$("#tutorials").addEventListener("click", (e) => {
  const card = e.target.closest("[data-tut]");
  if (!card) return;
  S.upload = card.dataset.tut === "__upload";
  if (!S.upload) { S.selected = card.dataset.tut; store.set("tutorial", S.selected); }
  renderTutorials();
  summarise();
});

function renderPace() {
  for (const b of $("#pace").children) b.classList.toggle("on", b.dataset.pace === S.pace);
}
$("#pace").addEventListener("click", (e) => {
  if (!e.target.dataset.pace) return;
  S.pace = e.target.dataset.pace; store.set("pace", S.pace); renderPace(); summarise(); refreshLanguages();
});
$("#voice").addEventListener("change", () => { store.set("voice", $("#voice").value); refreshLanguages(); });
$("#language").addEventListener("change", () => { store.set("language", $("#language").value); hintLanguage(); });

async function refreshLanguages(preferred) {
  const keep = preferred || $("#language").value || "ta";
  const data = await api(`/api/languages?voice=${encodeURIComponent($("#voice").value)}&pace=${S.pace}`);
  S.languages = data.languages;
  $("#language").innerHTML = S.languages.map((l) => `<option value="${l.code}">${esc(l.name)}</option>`).join("");
  $("#language").value = S.languages.some((l) => l.code === keep) ? keep : "ta";
  hintLanguage();
}

function hintLanguage() {
  const lang = S.languages.find((l) => l.code === $("#language").value);
  const voice = cap($("#voice").value);
  $("#languageHint").textContent = !lang ? "" : lang.rate
    ? `${voice} measured at ${fmt(lang.rate, 2)} aksharas/s at this pace`
    : `First run measures ${voice}'s speed in ${lang.name} (~20 clips)`;
  const v = S.voices.find((x) => x.id === $("#voice").value);
  $("#voiceHint").textContent = v ? `${cap(v.gender)} voice · Sarvam Bulbul` : "";
  summarise();
}

function summarise() {
  const t = S.upload ? null : S.tutorials.find((x) => x.id === S.selected);
  const what = S.upload ? "Your upload" : t ? t.title : "No tutorial chosen";
  const lang = S.languages.find((l) => l.code === $("#language").value)?.name || "";
  $("#goHint").textContent = `${what} → ${lang} · ${cap($("#voice").value)} · pace ${S.pace}`;
}

$("#go").addEventListener("click", async () => {
  const data = new FormData();
  if (S.upload) {
    const script = $("#uploadScript").files[0], video = $("#uploadVideo").files[0];
    if (!script) return showSetupError("Choose an English script to upload.");
    data.append("script", script);
    if (video) data.append("video", video);
  } else {
    const t = S.tutorials.find((x) => x.id === S.selected);
    if (!t) return showSetupError("Choose a tutorial first.");
    data.append("sample_script", t.script);
    if (t.video) data.append("sample_video", t.video);
  }
  data.append("language", $("#language").value);
  data.append("voice", $("#voice").value);
  data.append("pace", S.pace);
  data.append("translator", $("#translator").value);
  data.append("tts", $("#tts").value);
  data.append("aligner", $("#aligner").value);
  data.append("workers", $("#workers").value);
  $("#go").disabled = true;
  try {
    const job = await api("/api/jobs", { method: "POST", body: data });
    openJob(job.id);
  } catch (err) {
    showSetupError(err.message);
  } finally {
    $("#go").disabled = false;
  }
});

function showSetupError(message) { $("#setupError").hidden = false; $("#setupError").textContent = message; }

function showSetup() {
  clearInterval(S.timer); stopPlayers();
  history.replaceState(null, "", location.pathname);
  $("#setup").hidden = false; $("#jobView").hidden = true; $("#setupError").hidden = true;
  S.job = S.track = null;
  window.scrollTo(0, 0);
}
$("#anotherBtn").addEventListener("click", showSetup);

/* ---------------------------------------------------------------- running */

function openJob(id) {
  history.replaceState(null, "", `?job=${id}`);
  clearInterval(S.timer); stopPlayers(); $("#previewVideo").pause();
  S.track = null; S.job = null; S.view = "dubbed"; S.hear = "dubbed";
  $("#setup").hidden = true; $("#jobView").hidden = false;
  $("#running").hidden = false; $("#result").hidden = true;
  $("#feed").innerHTML = ""; S.feedKey = null; $("#jobError").hidden = true;
  poll(id);
  S.timer = setInterval(() => poll(id), 1000);
  window.scrollTo(0, 0);
}

async function poll(id) {
  let job;
  try { job = await api(`/api/jobs/${id}`); } catch (_) { clearInterval(S.timer); return; }
  S.job = job;
  renderJobHead(job);
  if (job.status === "done") { clearInterval(S.timer); loadTrack(id); return; }
  renderRunning(job);
  if (job.status === "error") clearInterval(S.timer);
}

function langName(code) { return S.languages.find((l) => l.code === code)?.name || code; }

function renderJobHead(job) {
  $("#jobTitle").textContent = job.title || job.script_name;
  $("#jobLang").textContent = langName(job.language);
  $("#jobVoice").textContent = job.voice ? cap(job.voice) : job.tts;
  $("#jobPace").textContent = `pace ${Number(job.pace ?? 1).toFixed(1)}`;
  const end = job.finished || Date.now() / 1000;
  const start = job.started || job.created;
  $("#jobClock").textContent = start ? clock(Math.max(0, end - start)) : "";
  const stubs = (job.stubs || []).filter((n) => n !== "manifest");  // older jobs listed the exporter too
  $("#stubNotice").hidden = !stubs.length;
  $("#stubNotice").textContent = `Stand-ins in use: ${stubs.join(", ")}. Numbers from these stages are not from real audio.`;
  $("#jobError").hidden = !job.error;
  $("#jobError").textContent = job.error ? `This run stopped: ${job.error}` : "";
}

function stepState(job, key, index) {
  const order = STEPS.map((s) => s[0]);
  const current = order.indexOf(job.stage);
  const [done, total] = job.progress[key] || [0, 0];
  if (job.status === "done") return "done";
  if (key === job.stage) return total && done >= total && job.status !== "running" ? "done" : "active";
  if (current > index) return "done";
  return total && done >= total ? "done" : "";
}

function renderRunning(job) {
  const used = STEPS.filter(([key]) => key !== "calibrate" || job.progress.calibrate);
  let overall = 0, weight = 0;
  $("#steps").innerHTML = used.map(([key, label]) => {
    const index = STEPS.findIndex((s) => s[0] === key);
    const state = stepState(job, key, index);
    const [done, total] = job.progress[key] || [0, 0];
    const pct = state === "done" ? 100 : total ? Math.round(100 * done / total) : 0;
    overall += WEIGHTS[key] * pct; weight += WEIGHTS[key];
    return `<div class="step ${state}"><div class="name"><span class="badge">${state === "done" ? "✓" : ""}</span>${label}</div>
      <div class="bar"><i style="width:${pct}%"></i></div>
      <div class="count">${total > 1 && key !== "fit_audio" && state !== "" ? `${done} / ${total}` : ""}</div></div>`;
  }).join("");
  const pct = Math.round(overall / weight);
  $("#overallBar").style.width = `${pct}%`;
  $("#overallPct").textContent = `${pct}%`;
  $("#overallLabel").textContent = job.status === "error" ? "Stopped" : describe(job);
  renderFeed(job);
}

function describe(job) {
  const [done, total] = job.progress[job.stage] || [0, 0];
  const lang = langName(job.language);
  switch (job.stage) {
    case "parse": return "Reading the script…";
    case "calibrate": return done === 0
      ? `Drafting the script in ${lang}, to measure how fast ${cap(job.voice)} speaks it…`
      : `Measuring how fast ${cap(job.voice)} speaks ${lang} at this pace (${done} of ${total} clips)…`;
    case "translate": return done === 0 ? `Drafting every line in ${lang} with IndicTrans2…` : `Fitting each line to its time slot (${done} of ${total})…`;
    case "synthesize": return `Recording the ${lang} voice (${done} of ${total})…`;
    case "align": return "Measuring where speech starts and ends in each clip…";
    case "fit_audio": return "Re-recording any clip that runs long…";
    case "export": return "Mixing the dub into the video…";
    default: return "Queued…";
  }
}

function chipFor(e) {
  if (e.fitted === false) return `<span class="chip review">Needs review</span>`;
  if (e.stage === "shortened") return `<span class="chip condensed">Condensed to fit</span>`;
  if (e.stage === "draft") return `<span class="chip kept">Kept as translated</span>`;
  return "";
}

function renderFeed(job) {
  const items = [...(job.feed || [])].reverse();
  // Re-render only when the feed changed, and animate only the new lines:
  // replacing it every poll restarts the fade-in and the lines never settle.
  const keys = items.map((e) => `${e.kind}:${e.id}`);
  const key = keys.join("|") + job.stage + job.status;
  if (key === S.feedKey) return;
  const seen = new Set((S.feedKey || "").split("|"));
  S.feedKey = key;
  const header = job.stage === "synthesize" || job.stage === "align" || job.stage === "fit_audio" ? "Just voiced" : "Just translated";
  if (!items.length) {
    $("#feed").innerHTML = `<div class="waiting">${job.status === "queued" ? "Waiting to start…" : "Lines will appear here as they are translated and voiced."}</div>`;
    return;
  }
  $("#feed").innerHTML = `<h3>${header}</h3>` + items.map((e) => `
    <div class="feed-item ${seen.has(`${e.kind}:${e.id}`) ? "" : "new"}">
      <span class="mono muted">${esc(e.id)}</span>
      <div><div class="src">${esc(e.source)}</div><div class="dst">${esc(e.text)}</div></div>
      <div>${e.kind === "voiced" && e.audio ? `<button class="play" data-play="${e.audio}" title="Play">▶</button>` : chipFor(e)}</div>
    </div>`).join("");
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-play]");
  if (!b) return;
  S.clip.pause(); S.clip = new Audio(b.dataset.play); S.clip.play();
});

/* ----------------------------------------------------------------- result */

async function loadTrack(id) {
  try { S.track = await api(`/api/jobs/${id}/track`); } catch (_) { return; }
  $("#running").hidden = true; $("#result").hidden = false;
  renderPlayer(); renderStats();
  if (S.drawer === "details") renderDrawer();
}

function exportsOf(track) {
  const names = Object.keys(track.exports).filter((n) => track.exports[n]);
  return {
    names,
    video: names.find((n) => /-dub\.(webm|mp4|mkv)$/.test(n)),
    wav: names.find((n) => /-dub\.wav$/.test(n)),
    srt: names.find((n) => n.endsWith(".srt")),
    script: names.find((n) => n.endsWith("-script.docx")),
  };
}

function stopPlayers() { for (const v of document.querySelectorAll("#player video, #player audio")) v.pause(); S.clip.pause(); }

function renderPlayer() {
  const t = S.track, x = exportsOf(t);
  const dubbed = x.video ? t.exports[x.video] : null;
  const original = t.original;
  $("#download").hidden = !dubbed && !x.wav;
  $("#download").href = dubbed || (x.wav ? t.exports[x.wav] : "#");
  $("#downloadScript").hidden = !x.script;
  $("#downloadScript").href = x.script ? t.exports[x.script] : "#";
  for (const b of document.querySelectorAll(".player-tabs [data-view]")) {
    b.classList.toggle("on", b.dataset.view === S.view);
    b.hidden = (b.dataset.view !== "dubbed" && !original) || (!dubbed && b.dataset.view !== "dubbed");
  }
  $("#hear").hidden = S.view !== "sbs";
  for (const b of document.querySelectorAll("[data-hear]")) b.classList.toggle("on", b.dataset.hear === S.hear);

  if (!dubbed) {
    $("#player").innerHTML = x.wav
      ? `<div style="padding:20px;background:var(--panel)"><p class="muted">No base video was given — the dubbed track on its own:</p><audio controls style="width:100%" src="${t.exports[x.wav]}"></audio></div>`
      : `<div class="empty" style="background:var(--panel)">No mixdown was produced.</div>`;
    return;
  }
  if (S.view === "sbs") {
    $("#player").innerHTML = `<div class="sbs">
      <figure><video id="vDub" controls preload="metadata" src="${dubbed}"></video><figcaption>${esc(t.settings.language)} dub</figcaption></figure>
      <figure><video id="vOrig" preload="metadata" src="${original}"></video><figcaption>English original</figcaption></figure></div>`;
    if (x.srt) attachSubtitles($("#vDub"), t.exports[x.srt]);
    syncPair($("#vDub"), $("#vOrig"));
    applyHearing();
  } else {
    $("#player").innerHTML = `<video id="vMain" controls preload="metadata" src="${S.view === "original" ? original : dubbed}"></video>`;
    if (S.view === "dubbed" && x.srt) attachSubtitles($("#vMain"), t.exports[x.srt]);
  }
}

function applyHearing() {
  const dub = $("#vDub"), orig = $("#vOrig");
  if (!dub || !orig) return;
  dub.muted = S.hear !== "dubbed"; orig.muted = S.hear !== "original";
}

function syncPair(master, follower) {
  const align = () => { if (Math.abs(follower.currentTime - master.currentTime) > 0.25) follower.currentTime = master.currentTime; };
  master.addEventListener("play", () => { align(); follower.play().catch(() => {}); });
  master.addEventListener("pause", () => follower.pause());
  master.addEventListener("seeked", align);
  master.addEventListener("ratechange", () => follower.playbackRate = master.playbackRate);
  master.addEventListener("timeupdate", align);
}

document.querySelector(".player-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.hear) { S.hear = b.dataset.hear; applyHearing(); for (const h of document.querySelectorAll("[data-hear]")) h.classList.toggle("on", h === b); return; }
  if (!b.dataset.view || b.dataset.view === S.view) return;
  // Keep the moment and the play state across the switch: the point is to compare the same line.
  const current = $("#vMain") || $("#vDub");
  const at = current ? current.currentTime : 0, playing = current && !current.paused;
  S.view = b.dataset.view;
  renderPlayer();
  const next = $("#vMain") || $("#vDub");
  next.addEventListener("loadedmetadata", () => { next.currentTime = at; if (playing) next.play().catch(() => {}); }, { once: true });
});

async function attachSubtitles(video, srtUrl) {
  // Browsers only take WebVTT in <track>; SRT differs in the header and the decimal comma.
  const srt = await (await fetch(srtUrl)).text();
  const vtt = "WEBVTT\n\n" + srt.replace(/(\d\d:\d\d:\d\d),(\d\d\d)/g, "$1.$2");
  const track = document.createElement("track");
  Object.assign(track, { kind: "subtitles", label: S.track.settings.language, srclang: S.job.language, default: true,
    src: URL.createObjectURL(new Blob([vtt], { type: "text/vtt" })) });
  video.appendChild(track);
}

function renderStats() {
  const s = S.track.summary;
  const review = s.review;
  const stat = (n, l, cls = "") => `<div class="card stat ${cls}"><div class="n">${n}</div><div class="l">${l}</div></div>`;
  $("#stats").innerHTML =
    stat(`${s.within_drift}/${s.segments}`, "lines land in their time slot", s.within_drift === s.segments ? "good" : "") +
    stat(s.shortened, "lines condensed to fit") +
    stat(review, "lines to review", review ? "flag" : "good") +
    stat(`${fmt(s.median_pause, 1)}s`, "typical pause between lines");
}

/* ---------------------------------------------------------------- drawers */

const DRAWERS = {
  details: { title: () => "Details", tabs: [["lines", "Lines"], ["quality", "Quality"], ["settings", "Settings"], ["files", "Files"]] },
  history: { title: () => "History", tabs: [], narrow: true },
  system: { title: () => "System", tabs: [], narrow: true },
};
let drawerTab = "lines";

function openDrawer(name, tab) {
  S.drawer = name; if (tab) drawerTab = tab;
  $("#overlay").hidden = false;
  $("#drawer").classList.toggle("narrow", !!DRAWERS[name].narrow);
  renderDrawer();
}
function closeDrawer() { S.drawer = null; S.editing = null; $("#overlay").hidden = true; }
$("#scrim").addEventListener("click", closeDrawer);
$("#drawerClose").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.drawer) closeDrawer(); });
$("#detailsBtn").addEventListener("click", () => openDrawer("details"));
$("#historyBtn").addEventListener("click", () => openDrawer("history"));
$("#systemBtn").addEventListener("click", () => openDrawer("system"));
$("#drawerTabs").addEventListener("click", (e) => { if (e.target.dataset.tab) { drawerTab = e.target.dataset.tab; renderDrawer(); } });

async function renderDrawer() {
  const d = DRAWERS[S.drawer];
  if (!d) return;
  $("#drawerTitle").textContent = d.title();
  $("#drawerTabs").hidden = !d.tabs.length;
  $("#drawerTabs").innerHTML = d.tabs.map(([k, l]) => `<button class="tab ${k === drawerTab ? "on" : ""}" data-tab="${k}">${l}</button>`).join("");
  const body = $("#drawerBody");
  if (S.drawer === "history") body.innerHTML = await historyHtml();
  else if (S.drawer === "system") body.innerHTML = systemHtml();
  else if (!S.track) body.innerHTML = `<div class="empty">Details appear when the run finishes.</div>`;
  else body.innerHTML = { lines: linesHtml, quality: qualityHtml, settings: settingsHtml, files: filesHtml }[drawerTab]();
}

// Not every note is a problem: "predicted over, but the audio fits" is information.
const needsReview = (r) => r.review;  // the rule lives on the server (backend/app/timeline/qa.py needs_review)

const FILTERS = {
  all: ["All", () => true],
  review: ["To review", (r) => needsReview(r)],
  condensed: ["Condensed", (r) => r.stage === "shortened"],
  kept: ["Kept as translated", (r) => r.stage === "draft"],
};

function linesHtml() {
  const rows = S.track.rows;
  const filters = `<div class="filters">${Object.entries(FILTERS).map(([k, [label, f]]) =>
    `<button class="${S.filter === k ? "on" : ""}" data-filter="${k}">${label} · ${rows.filter(f).length}</button>`).join("")}</div>`;
  const shown = rows.filter(FILTERS[S.filter][1]);
  if (!shown.length) return filters + `<div class="empty">Nothing here.</div>`;
  return filters + `<div class="lines">` + shown.map((r) => {
    const flagged = needsReview(r);
    const editing = S.editing === r.id;
    const drift = r.drift === null ? "" : `<span class="${r.within_drift ? "under" : "over"}">${r.drift > 0 ? "+" : ""}${fmt(r.drift, 2)}s</span>`;
    const chip = !r.fitted ? `<span class="chip review">Needs review</span>` : r.stage === "shortened" ? `<span class="chip condensed">Condensed</span>` : r.stage === "draft" ? `<span class="chip kept">Kept</span>` : "";
    return `<div class="card line-row ${flagged ? "flagged" : ""}">
      <div class="when">${r.id}<br>${clock(r.start)}<br>${fmt(r.budget)}s slot</div>
      <div class="en">${esc(r.source)}</div>
      <div>${editing ? `<textarea id="edit-${r.id}">${esc(r.text)}</textarea>`
        : `<div>${esc(r.text) || "<em class='muted'>no translation</em>"}</div>`}
        ${!editing && r.draft && r.draft !== r.text ? `<div class="mt">Machine draft: ${esc(r.draft)}</div>` : ""}
        ${r.note ? `<div class="note">${esc(r.note)}</div>` : ""}</div>
      <div class="side">${chip}${r.cue ? ` <span class="chip clip">clip</span>` : ""}
        <div class="mono">${r.actual === null ? "" : `${fmt(r.actual, 2)}s spoken`} ${drift}</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          ${r.audio ? `<button class="small-btn" data-play="${r.audio}">▶ Play</button>` : ""}
          ${editing ? `<button class="small-btn primary-ish" data-save="${r.id}">Save & re-voice</button><button class="small-btn" data-cancel>Cancel</button>`
            : `<button class="small-btn" data-edit="${r.id}">Edit</button><button class="small-btn" data-redo="${r.id}" title="Translate and voice this line again">Redo</button>`}
        </div></div>
    </div>`;
  }).join("") + `</div>`;
}

function qualityHtml() {
  const s = S.track.summary;
  const rows = [
    ["Lines", s.segments],
    ["Fit their time slot on paper", `${s.fitted} / ${s.segments}`],
    ["Land in their slot in the audio (within 0.25 s)", `${s.within_drift} / ${s.segments}`],
    ["Kept exactly as machine-translated", s.drafts_kept],
    ["Condensed by the language model to fit", s.shortened],
    ["Could not be made to fit — need a person", s.escalated],
    ["Worst overrun", `${fmt(s.max_drift, 2)} s`],
    ["Typical pause left between lines", `${fmt(s.median_pause, 2)} s`],
    ["Speaking rate vs. target (1.00 = on target)", fmt(s.mean_rate_ratio, 2)],
    ["Total speech", clock(s.audio_seconds)],
    ["Video length", clock(S.track.duration)],
  ];
  return `<div class="card kv">${rows.map(([k, v]) => `<div class="k">${k}</div><div class="mono">${v}</div>`).join("")}</div>
    <p class="explain">Each English line has a time slot in the video. The translation is first drafted by machine translation;
    if the draft would take longer to say than the slot allows, a language model condenses it while keeping every on-screen term.
    A clip that still runs long is re-recorded up to 10% faster. Anything left over is flagged for a person.</p>`;
}

function settingsHtml() {
  const c = S.track.settings;
  const rows = [
    ["Language", c.language], ["Voice", c.voice ? `${cap(c.voice)} (${c.model || c.tts})` : c.tts],
    ["Speaking pace", Number(c.pace).toFixed(2)], ["Measured voice speed", `${fmt(c.rate, 2)} aksharas / s`],
    ["Pause kept after each line", `${fmt(c.pause_reserve, 2)} s`],
    ["Machine translation", c.mt || "—"], ["Condensing model", c.llm || "—"],
    ["Translator pipeline", c.translator], ["Aligner", c.aligner],
  ];
  return `<div class="card kv">${rows.map(([k, v]) => `<div class="k">${k}</div><div class="mono">${esc(v)}</div>`).join("")}</div>
    <p class="explain">Inputs are only the English script and the English video; the voice speed is measured from this pipeline's own output.</p>`;
}

function filesHtml() {
  const t = S.track, names = Object.keys(t.exports).filter((n) => t.exports[n]);
  const label = (n) => /-dub\.(webm|mp4|mkv)$/.test(n) ? "Dubbed video" : n.endsWith("-script.docx") ? "Dubbed script (Word)" : /\.wav$/.test(n) ? "Dubbed audio track" : n.endsWith(".srt") ? "Subtitles (SRT)" : n.endsWith(".json") ? "Timing manifest" : "File";
  return `<div class="card files">${names.map((n) => `<a href="${t.exports[n]}" download><span>${label(n)}</span><span class="muted mono">${esc(n)}</span></a>`).join("")}</div>`;
}

async function historyHtml() {
  const jobs = await api("/api/jobs");
  if (!jobs.length) return `<div class="empty">No dubs yet.</div>`;
  const poster = (j) => {
    const t = S.tutorials.find((x) => x.video && j.video_name && x.video.endsWith(j.video_name));
    return t ? `style="background-image:url('/api/library/poster?video=${encodeURIComponent(t.video)}')"` : "";
  };
  return jobs.map((j) => {
    const s = j.summary || {};
    const result = j.status === "done" ? (s.segments ? `${s.within_drift ?? s.on_time}/${s.segments} on time` : "done") : j.status;
    return `<button class="card history-item" data-job="${j.id}"><div class="thumb" ${poster(j)}></div>
      <div><div style="font-weight:600">${esc(j.title || j.script_name)}</div>
      <div class="muted" style="font-size:13px">${esc(langName(j.language))} · ${esc(cap(j.voice || j.tts))} · pace ${Number(j.pace ?? 1).toFixed(1)}</div>
      <div class="muted" style="font-size:12px">${new Date(j.created * 1000).toLocaleString()} · ${esc(result)}</div></div></button>`;
  }).join("");
}

function systemHtml() {
  const h = S.health;
  const row = (ok, label, detail) => `<div class="k"><span class="dot ${ok ? "ok" : "bad"}"></span>${label}</div><div class="muted">${detail}</div>`;
  return `<div class="card kv">
    ${row(h.indictrans_installed, "Machine translation", h.indictrans_installed ? esc(h.indictrans_model) : "IndicTrans2 not installed (requirements-mt.txt)")}
    ${row(h.sarvam_key, "Sarvam key", h.sarvam_key ? "present — voice and condensing available" : "missing — set SARVAM_API_KEY in .env")}
    ${row(true, "Translators", esc(h.translators.join(", ")))}
    ${row(true, "Speech", esc(h.tts.join(", ")))}
  </div><p class="explain">Keys are read from the server's environment and never sent to this page.</p>`;
}

$("#drawerBody").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.job) { closeDrawer(); openJob(b.dataset.job); return; }
  if (b.dataset.filter) { S.filter = b.dataset.filter; renderDrawer(); return; }
  if (b.dataset.edit) { S.editing = b.dataset.edit; await renderDrawer(); $(`#edit-${b.dataset.edit}`)?.focus(); return; }
  if (b.dataset.cancel !== undefined) { S.editing = null; renderDrawer(); return; }
  if (b.dataset.save || b.dataset.redo) {
    const id = b.dataset.save || b.dataset.redo;
    const body = b.dataset.save ? { text: $(`#edit-${id}`).value } : {};
    b.disabled = true; b.textContent = "Working…";
    try {
      S.track = await api(`/api/jobs/${S.job.id}/segments/${id}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      S.editing = null;
      renderDrawer(); renderPlayer(); renderStats();
    } catch (err) {
      b.disabled = false; b.textContent = "Retry"; b.title = err.message;
    }
  }
});

init().catch((err) => { $("#setup").hidden = false; showSetupError(`Could not reach the server: ${err.message}`); });
