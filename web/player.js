// Full Cast player: plays the mixed drama with the script following along.
// Reads output/mix/<name>/ written by web/mix.py. Serve the repo root with python -m web.serve
// (it supports the Range requests seeking needs) and open /web/?mix=placeholder (the default)
// or /web/?mix=real.
"use strict";

const MIX_NAME = /^[a-z0-9-]+$/;  // the name becomes part of a URL path, so only allow plain names
const requested = new URLSearchParams(location.search).get("mix") || "";
const mixName = MIX_NAME.test(requested) ? requested : "placeholder";
const base = `../output/mix/${mixName}/`;

const audio = document.getElementById("audio");
const scriptEl = document.getElementById("script");
const statusEl = document.getElementById("status");
const chaptersEl = document.getElementById("chapters");
const modeNote = document.getElementById("mode-note");
const flatButton = document.getElementById("mode-flat");
const fullButton = document.getElementById("mode-full");

let timeline = null;
let mode = "full";
let currentKey = null;  // which segment or line is lit, so the DOM only changes when it moves on
let currentNodes = [];
let fullNote = "";
const FLAT_NOTE = "The same lines read by one voice, with no sound design.";
const elementsBySegment = [];  // segment index -> the line/cue elements it speaks
const lineElements = new Map();  // line id -> its element, for per-line highlighting
const chapterButtons = [];

// Same rule as core.interface.strip_tags: drop every [tag], collapse spaces.
function stripTags(text) {
  return text.replace(/\[[^\]]*\]/g, " ").split(/\s+/).filter(Boolean).join(" ");
}

function formatTime(ms) {
  const totalS = Math.floor(ms / 1000);
  return `${Math.floor(totalS / 60)}:${String(totalS % 60).padStart(2, "0")}`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;  // textContent, so script text is never parsed as HTML
  return node;
}

function showError(message, command) {
  statusEl.className = "error";
  statusEl.replaceChildren(document.createTextNode(message));
  if (command) {
    statusEl.append(" Run from the repo root: ", el("code", "", command));
  }
}

// play() rejects with AbortError when a seek or a version switch interrupts it. That is expected
// here, so it is dropped; anything else (e.g. the browser blocking playback) still reaches the console.
function play() {
  audio.play().catch((err) => {
    if (err.name !== "AbortError") throw err;
  });
}

function seekFull(ms) {
  if (mode !== "full") setMode("full", ms);
  else audio.currentTime = ms / 1000;
  play();
}

function renderScript(script) {
  const lines = new Map();
  const scenes = new Map();
  for (const scene of script.scenes) {
    scenes.set(scene.number, scene.title);
    for (const line of scene.lines) lines.set(line.id, line);
  }
  const names = new Map(script.characters.map((c) => [c.id, c.name]));
  const compared = new Set(timeline.compare ? timeline.compare.line_ids : []);

  let lastScene = null;
  timeline.segments.forEach((seg, i) => {
    if (seg.scene !== lastScene) {
      scriptEl.append(el("h3", "", `Scene ${seg.scene}: ${scenes.get(seg.scene) || ""}`));
      lastScene = seg.scene;
    }
    const nodes = [];
    if (seg.kind === "dialogue") {
      for (const id of seg.line_ids) {
        const line = lines.get(id);
        const button = el("button", compared.has(id) ? "line" : "line outside");
        button.type = "button";
        button.append(el("span", "speaker", names.get(line.speaker) || line.speaker),
                      el("span", "text", stripTags(line.text)));
        const timed = seg.line_times && seg.line_times.find((t) => t.line_id === id);
        button.addEventListener("click", () => seekFull(timed ? timed.start_ms : seg.start_ms));
        lineElements.set(id, button);
        nodes.push(button);
      }
    } else {
      const cue = el("button", "cue outside", `Sound: ${seg.cue}`);
      cue.type = "button";
      cue.addEventListener("click", () => seekFull(seg.start_ms));
      nodes.push(cue);
    }
    scriptEl.append(...nodes);
    elementsBySegment[i] = nodes;
  });
}

function renderChapters() {
  if (!timeline.chapters.length) return;
  for (const chapter of timeline.chapters) {
    const button = el("button", "", chapter.title);
    button.type = "button";
    button.append(el("span", "time", formatTime(chapter.start_ms)));
    button.addEventListener("click", () => seekFull(chapter.start_ms));
    const item = el("li");
    item.append(button);
    chaptersEl.append(item);
    chapterButtons.push({ button, startMs: chapter.start_ms });
  }
  document.getElementById("chapters-nav").hidden = false;
}

function segmentAt(ms) {
  // During a gap the segment that just ended stays highlighted.
  let found = -1;
  timeline.segments.forEach((seg, i) => { if (seg.start_ms <= ms) found = i; });
  return found;
}

// One line when the segment has per-line times from Core, otherwise every line in the segment.
function nodesAt(ms) {
  const index = segmentAt(ms);
  const seg = timeline.segments[index];
  if (!seg) return { key: null, nodes: [] };
  if (seg.line_times) {
    // Between two lines the one just spoken stays lit; before the first starts, the first is lit.
    let line = seg.line_times[0];
    for (const t of seg.line_times) if (t.start_ms <= ms) line = t;
    return { key: line.line_id, nodes: [lineElements.get(line.line_id)] };
  }
  return { key: `segment-${index}`, nodes: elementsBySegment[index] || [] };
}

function highlight() {
  if (mode !== "full") return;
  const ms = audio.currentTime * 1000;
  const { key, nodes } = nodesAt(ms);
  if (key !== currentKey) {
    currentNodes.forEach((n) => n.classList.remove("current"));
    nodes.forEach((n) => n.classList.add("current"));
    currentKey = key;
    currentNodes = nodes;
    const first = nodes[0];
    if (first && !audio.paused) {
      const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
      first.scrollIntoView({ block: "center", behavior: smooth ? "smooth" : "auto" });
    }
  }
  let active = null;
  for (const c of chapterButtons) if (c.startMs <= ms) active = c;
  for (const c of chapterButtons) c.button.setAttribute("aria-current", String(c === active));
}

function clearHighlight() {
  currentNodes.forEach((n) => n.classList.remove("current"));
  currentKey = null;
  currentNodes = [];
}

// Switching keeps roughly the same moment: the position is scaled between the flat clip and the
// stretch of the full cast that speaks the same lines. It is an estimate, not a word-level match.
function setMode(next, fullMs) {
  const compare = timeline.compare;
  if (next === mode || (next === "flat" && !compare)) return;
  const wasPlaying = !audio.paused;
  const fullSpanMs = compare ? compare.full_end_ms - compare.full_start_ms : 0;
  let targetMs;
  if (next === "flat") {
    const offset = Math.min(Math.max(audio.currentTime * 1000 - compare.full_start_ms, 0), fullSpanMs);
    targetMs = fullSpanMs ? (offset / fullSpanMs) * compare.flat_ms : 0;
  } else if (fullMs !== undefined) {
    targetMs = fullMs;
  } else {
    targetMs = compare.full_start_ms + (audio.currentTime * 1000 / compare.flat_ms) * fullSpanMs;
  }

  mode = next;
  flatButton.setAttribute("aria-pressed", String(mode === "flat"));
  fullButton.setAttribute("aria-pressed", String(mode === "full"));
  scriptEl.classList.toggle("flat", mode === "flat");
  clearHighlight();
  modeNote.textContent = mode === "flat" ? FLAT_NOTE : fullNote;

  audio.src = base + (mode === "flat" ? compare.flat_file : timeline.file);
  audio.addEventListener("loadedmetadata", () => {
    audio.currentTime = targetMs / 1000;
    if (wasPlaying) play();
    highlight();
  }, { once: true });
}

async function load() {
  statusEl.textContent = "Loading the drama...";
  const src = mixName === "real" ? "../elevenlabs-shared/output" : `output/${mixName}`;
  const command = `python -m web.mix --src ${src} --out output/mix/${mixName}`;
  let script;
  try {
    const [t, s] = await Promise.all([
      fetch(base + "timeline.json"), fetch(base + "script.json"),
    ]);
    if (!t.ok || !s.ok) {
      showError(`No mix found in output/mix/${mixName}/.`, command);
      return;
    }
    [timeline, script] = await Promise.all([t.json(), s.json()]);
  } catch (err) {
    showError(`Could not load output/mix/${mixName}/ (${err.message}). Is the page served over http?`,
              "python -m web.serve");
    return;
  }

  document.title = `${script.title} - Full Cast`;
  document.getElementById("title").textContent = script.title;
  document.getElementById("byline").textContent =
    `by ${script.author}, ${formatTime(timeline.duration_ms)} audio drama`;
  statusEl.textContent = mixName === "placeholder"
    ? "Placeholder audio: tones stand in for voices until the real stems are rendered."
    : "";

  renderChapters();
  renderScript(script);
  // Count who actually speaks: a preview of one scene lists the whole cast but not all of it talks.
  const speakers = new Set(script.scenes.flatMap((s) => s.lines.map((l) => l.speaker)));
  fullNote = `${speakers.size} voices, sound effects and ambience.`;
  modeNote.textContent = fullNote;
  if (!timeline.compare) flatButton.disabled = true;
  audio.src = base + timeline.file;

  audio.addEventListener("timeupdate", highlight);
  audio.addEventListener("seeked", highlight);
  audio.addEventListener("error", () => {
    showError(`Could not play ${audio.src.split("/").pop()}.`, command);
  });
  flatButton.addEventListener("click", () => setMode("flat"));
  fullButton.addEventListener("click", () => setMode("full"));
}

load();
