// Shared helpers. Data from the API (including LLM text) is only ever inserted as
// text nodes, never parsed as HTML (Spec §10.5).
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const RISK_LEVELS = ["Rendah", "Sedang", "Tinggi", "Sangat Tinggi"];
const STATUS = {
  normal: { label: "Normal" },
  check: { label: "Perlu Dicek" },
  fire: { label: "Kebakaran Terdeteksi" },
  offline: { label: "Offline" },
  disabled: { label: "Nonaktif" },
};
const SUB_STATUS = {
  unverified: "belum terverifikasi AI",
  POTENSI: "potensi (faktor risiko terlihat)",
  rejected_lookalike: "AI menolak: mirip kabut/senja/lampu",
};
const KIND_BY_LEVEL = { AMAN: "normal", WASPADA: "check", BAHAYA: "fire" };
const COMPASS = ["utara", "timur laut", "timur", "tenggara", "selatan", "barat daya", "barat", "barat laut"];

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = String(value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function replace(node, ...children) {
  node.replaceChildren();
  return append(node, children);
}

function svg(tag, attrs, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, String(value));
  for (const child of children) if (child) node.append(child);
  return node;
}

// Shape + color per status, so status is readable without color (Spec §10.4).
function statusIcon(kind, size = 18, color) {
  const fill = color || `var(--${kind === "offline" || kind === "disabled" ? "offline" : kind})`;
  const icon = svg("svg", { width: size, height: size, viewBox: "0 0 22 22", "aria-hidden": "true", focusable: "false" });
  if (kind === "fire") icon.append(svg("path", { d: "M7 1h8l6 6v8l-6 6H7l-6-6V7Z", fill }));
  else if (kind === "check") icon.append(svg("path", { d: "M11 1 21 20H1Z", fill }));
  else if (kind === "normal") icon.append(svg("circle", { cx: 11, cy: 11, r: 10, fill }));
  else if (kind === "disabled") icon.append(svg("rect", { x: 5, y: 3, width: 4, height: 16, fill }), svg("rect", { x: 13, y: 3, width: 4, height: 16, fill }));
  else icon.append(svg("circle", { cx: 11, cy: 11, r: 9, fill: "none", stroke: fill, "stroke-width": 2.5 }));
  return icon;
}

function cameraKind(cam) {
  if (cam.enabled === false) return "disabled";
  if (!cam.online) return "offline";
  return KIND_BY_LEVEL[cam.level] || "normal";
}

function badge(kind, extraText) {
  return h("span", { class: `badge ${kind}` }, statusIcon(kind, 12, "#fff"), STATUS[kind].label, extraText || null);
}

function riskIndex(level) {
  return RISK_LEVELS.indexOf(level);
}

function compass(deg) {
  return COMPASS[Math.round(((deg % 360) + 360) % 360 / 45) % 8];
}

function fmtTime(iso) {
  if (!iso) return "-";
  return iso.slice(11, 19);
}

function fmtDateTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  const months = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
  const day = Number(iso.slice(8, 10));
  return `${day} ${months[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}, ${iso.slice(11, 16)} WITA`;
}

function ago(seconds) {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 90) return `${Math.round(seconds)} dtk lalu`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} menit lalu`;
  return `${Math.round(seconds / 3600)} jam lalu`;
}

function num(value, digits = 2) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(digits);
}

async function fetchJSON(url) {
  const resp = await fetch(url, { headers: { Accept: "application/json" } });
  if (!resp.ok) throw new Error(`${url}: HTTP ${resp.status}`);
  return resp.json();
}

// State-changing requests (operator only). The custom header is checked by the server.
async function postJSON(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json", "X-MataKlabat": "1" },
    body: JSON.stringify(body || {}),
    credentials: "same-origin",
  });
  let data = null;
  try { data = await resp.json(); } catch (err) { data = null; }
  if (!resp.ok) {
    const error = new Error((data && data.error) || `HTTP ${resp.status}`);
    error.status = resp.status;
    throw error;
  }
  return data;
}

// Live updates: the server sends "update" whenever data changes; pages refetch.
function connectLive(onUpdate) {
  const banner = document.getElementById("live-banner");
  let source;
  const open = () => {
    source = new EventSource("/api/stream");
    source.addEventListener("open", () => { if (banner) banner.hidden = true; });
    source.addEventListener("update", () => onUpdate());
    source.addEventListener("error", () => {
      if (banner) banner.hidden = false; // EventSource reconnects by itself
    });
  };
  open();
  // Fallback refresh, in case the stream is silently buffered by a proxy.
  setInterval(onUpdate, 15000);
}

function showMonitorBanner(monitor) {
  const banner = document.getElementById("monitor-banner");
  if (!banner) return;
  if (monitor.alive) {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  banner.textContent = monitor.last_beat
    ? `Monitor tidak merespons sejak ${fmtTime(monitor.last_beat)} (${ago(monitor.age_s)}). Status di bawah mungkin sudah lama.`
    : "Monitor belum berjalan. Jalankan: python -m mataklabat up";
}

function setHeaderPill(status) {
  const pill = document.getElementById("system-pill");
  if (!pill) return;
  const active = status.cameras.filter((c) => c.enabled !== false);
  const online = active.filter((c) => c.online).length;
  const off = status.cameras.length - active.length;
  const parts = [
    status.monitor.alive ? "Monitor aktif" : "Monitor mati",
    `${online}/${active.length} kamera online${off ? ` · ${off} nonaktif` : ""}`,
    status.llm_enabled ? "AI aktif" : "AI nonaktif",
  ];
  pill.classList.toggle("bad", !status.monitor.alive || online < active.length);
  replace(pill, h("span", { class: "dot", "aria-hidden": "true" }), parts.join(" · "));
}

function startClock() {
  const clock = document.getElementById("clock");
  if (!clock) return;
  const tick = () => {
    const now = new Date();
    const wita = new Date(now.getTime() + (now.getTimezoneOffset() + 480) * 60000);
    const pad = (n) => String(n).padStart(2, "0");
    clock.textContent = `${pad(wita.getHours())}:${pad(wita.getMinutes())}:${pad(wita.getSeconds())} WITA`;
  };
  tick();
  setInterval(tick, 1000);
}

// Minimal, safe markdown for agent reports: headings, lists, emphasis lines, **bold**.
function renderMarkdown(text) {
  const root = h("div", { class: "report" });
  let list = null;
  const inline = (line) => {
    const parts = line.split(/\*\*(.+?)\*\*/g);
    return parts.map((part, i) => (i % 2 ? h("strong", { text: part }) : part));
  };
  for (const raw of (text || "").split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) { list = null; continue; }
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (line.startsWith("#")) {
      list = null;
      root.append(h("h3", { text: line.replace(/^#+\s*/, "") }));
    } else if (bullet || ordered) {
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== tag) { list = h(tag); root.append(list); }
      list.append(h("li", null, inline((bullet || ordered)[1])));
    } else if (/^_.+_$/.test(line)) {
      list = null;
      root.append(h("p", null, h("em", { text: line.slice(1, -1) })));
    } else {
      list = null;
      root.append(h("p", null, inline(line)));
    }
  }
  return root;
}
