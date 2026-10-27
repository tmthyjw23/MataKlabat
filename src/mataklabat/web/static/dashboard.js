// Dashboard page (Spec §10.1). Re-renders from /api/status on every live update.
"use strict";

const els = {
  riskLevel: document.getElementById("risk-level"),
  riskAdvice: document.getElementById("risk-advice"),
  riskFwi: document.getElementById("risk-fwi"),
  riskUpdated: document.getElementById("risk-updated"),
  riskScale: document.getElementById("risk-scale"),
  riskFacts: document.getElementById("risk-facts"),
  riskForecast: document.getElementById("risk-forecast"),
  riskHistory: document.getElementById("risk-history"),
  counts: document.getElementById("status-counts"),
  incident: document.getElementById("incident-card"),
  grid: document.getElementById("camera-grid"),
  historyBody: document.getElementById("history-body"),
  historyFilter: document.getElementById("history-filter"),
  hotspotNote: document.getElementById("hotspot-note"),
};

const mapView = new MapView(document.getElementById("map"));
let refreshing = false;
let pending = false;
let filterFilled = false;
const operator = { available: false, active: false, busy: new Set(), notes: {} };
let lastCameras = [];
let galleryCamera = null;

function fact(label, value) {
  return h("div", { class: "fact" }, h("span", { class: "fact-label", text: label }), h("span", { class: "fact-value", text: value }));
}

function renderRisk(risk) {
  if (!risk) {
    els.riskLevel.className = "risk-level risk-unknown";
    els.riskLevel.textContent = "Belum ada data cuaca";
    els.riskAdvice.textContent = "Monitor mengambil data Open-Meteo saat mulai berjalan.";
    replace(els.riskScale); replace(els.riskFacts); replace(els.riskForecast);
    els.riskFwi.textContent = "";
    els.riskUpdated.textContent = "";
    return;
  }
  const idx = riskIndex(risk.level);
  els.riskLevel.className = `risk-level ${risk.unknown ? "risk-unknown" : `risk-${idx}`}`;
  els.riskLevel.textContent = risk.unknown ? `Tidak diketahui (terakhir ${risk.level})` : risk.level.toUpperCase();
  els.riskAdvice.textContent = `Penentu: ${risk.driver_text}. ${risk.advice}`;
  els.riskFwi.textContent = `FWI ${num(risk.codes.fwi, 1)}`;
  els.riskUpdated.textContent = risk.stale
    ? `Data cuaca terakhir ${fmtTime(risk.fetched_ts).slice(0, 5)} (${ago(risk.age_s)})`
    : `Diperbarui ${fmtTime(risk.fetched_ts).slice(0, 5)} WITA${risk.observed ? "" : " · siang ini dari prakiraan"}`;

  replace(els.riskScale, ...RISK_LEVELS.map((label, i) =>
    h("div", { class: `scale-step${i <= idx ? " on" : ""}${i === idx ? " current" : ""}` },
      h("div", { class: `scale-bar r${i}`, "aria-hidden": "true" }),
      h("span", { text: label }))));
  els.riskScale.setAttribute("aria-label", `Skala risiko, saat ini ${risk.level}`);

  const levels = risk.indicator_levels || {};
  const now = risk.now || {};
  replace(els.riskFacts,
    fact("Kekeringan tanah (DC)", `${num(risk.codes.dc, 0)} · ${levels.dc || "-"}`),
    fact("Mudah menyala (FFMC)", `${num(risk.codes.ffmc, 0)} · ${levels.ffmc || "-"}`),
    fact("Sulitnya pemadaman (ISI)", `${num(risk.codes.isi, 1)} · ${levels.isi || "-"}`),
    fact("Angin", now.wind_dir_deg === null || now.wind_dir_deg === undefined ? "-" : `${num(now.wind_kmh, 0)} km/j dari ${compass(now.wind_dir_deg)}`),
    fact("Suhu · kelembapan", `${num(now.temp_c, 0)}°C · ${num(now.rh_pct, 0)}%`),
    fact("Hari tanpa hujan", `${risk.days_without_rain} hari`),
  );
  replace(els.riskForecast, h("span", { class: "small muted", text: "Prakiraan:" }),
    ...(risk.forecast || []).map((d) => h("span", { class: "chip", text: `${d.date.slice(8, 10)}/${d.date.slice(5, 7)} · ${d.level}` })));
}

async function renderRiskHistory() {
  try {
    const data = await fetchJSON("/api/risk?days=30");
    const days = data.daily;
    if (!days.length) { replace(els.riskHistory, h("p", { class: "small muted", text: "Belum ada riwayat." })); return; }
    const width = 600, height = 120, pad = 18;
    const max = Math.max(400, ...days.map((d) => d.dc));
    const bar = (width - pad) / days.length;
    const chart = svg("svg", { class: "chart", viewBox: `0 0 ${width} ${height}`, role: "img",
      "aria-label": `Kekeringan (DC) ${days.length} hari terakhir, terakhir ${Math.round(days[days.length - 1].dc)}` });
    const colors = ["var(--risk-0)", "var(--risk-1)", "var(--risk-2)", "var(--risk-3)"];
    days.forEach((d, i) => {
      const value = d.dc;
      const barH = Math.max(1, ((height - pad) * value) / max);
      chart.append(svg("rect", { x: pad + i * bar + 1, y: height - pad - barH, width: Math.max(1, bar - 2), height: barH,
        fill: colors[riskIndex(d.category)] || "var(--muted)", opacity: d.source === "forecast" ? 0.5 : 1 }));
    });
    const first = svg("text", { x: pad, y: height - 4 }); first.textContent = days[0].date.slice(5);
    const last = svg("text", { x: width - 40, y: height - 4 }); last.textContent = days[days.length - 1].date.slice(5);
    chart.append(first, last);
    replace(els.riskHistory, h("p", { class: "small muted", text: "Batang = kekeringan tanah (DC), warna = kelas risiko kawasan hari itu; pudar = prakiraan." }), chart);
  } catch (err) {
    replace(els.riskHistory, h("p", { class: "small muted", text: "Riwayat tidak bisa dimuat." }));
  }
}

function renderCounts(counts) {
  const order = [["fire", counts.fire], ["check", counts.check], ["normal", counts.normal], ["offline", counts.offline], ["disabled", counts.disabled || 0]];
  replace(els.counts, ...order.filter(([kind, n]) => n > 0 || (kind !== "offline" && kind !== "disabled")).map(([kind, n]) =>
    h("div", { class: `count ${kind}` }, statusIcon(kind, 22), h("span", { class: "name", text: STATUS[kind].label }), h("span", { class: "n", text: n }))));
}

function photo(url, alt, placeholder) {
  return h("div", { class: "photo" }, url ? h("img", { src: url, alt, loading: "lazy" }) : h("span", { class: "placeholder", text: placeholder || "Belum ada gambar" }));
}

async function renderIncident(status) {
  const card = els.incident;
  const open = status.open_incidents;
  if (!open.length) {
    card.className = "card narrow stack incident none";
    const checking = status.cameras.filter((c) => cameraKind(c) === "check");
    const active = status.cameras.filter((c) => c.enabled !== false);
    replace(card,
      h("h2", { text: "Tidak ada insiden aktif" }),
      h("p", { class: "muted", text: checking.length
        ? `${checking.length} kamera perlu dicek: ${checking.map((c) => c.id).join(", ")}.`
        : active.length ? "Semua kamera aktif tidak menunjukkan api atau asap." : "Semua kamera sedang dinonaktifkan operator." }),
      h("a", { class: "btn secondary", href: "#history-title" }, "Lihat riwayat"),
    );
    return;
  }
  const latest = open[0];
  let detail;
  try {
    detail = await fetchJSON(`/api/incidents/${latest.id}`);
  } catch (err) {
    return;
  }
  const cam = status.cameras.find((c) => c.id === detail.camera_id) || {};
  const withPhoto = [...detail.events].reverse().find((e) => e.snapshot_url);
  const llmEvent = [...detail.events].reverse().find((e) => e.llm && !e.llm.error);
  const why = [];
  if (cam.explanation) why.push(h("li", { text: cam.explanation }));
  if (llmEvent && llmEvent.llm.reasoning) why.push(h("li", null, "Alasan AI: ", h("span", { class: "quote", text: `“${llmEvent.llm.reasoning}”` })));
  if (llmEvent && llmEvent.llm.evidence && llmEvent.llm.evidence.length) why.push(h("li", { text: `Bukti: ${llmEvent.llm.evidence.join("; ")}` }));
  if (status.risk) why.push(h("li", { text: `Risiko kawasan ${status.risk.level} (karena ${status.risk.driver_text}).` }));
  const messageLines = detail.messages.map((m) => h("span", { text: `${m.kind === "fire" ? "Peringatan" : m.kind === "report" ? "Laporan AI" : m.kind}: ${outboxLabel(m)}` }));

  card.className = "card narrow stack incident";
  replace(card,
    h("div", { class: "chips" }, badge("fire"), h("span", { class: "small muted", text: `sejak ${fmtTime(detail.opened_ts)} WITA` }),
      open.length > 1 ? h("span", { class: "tag", text: `+${open.length - 1} insiden lain` }) : null),
    h("h2", { text: `${detail.camera_id} · ${detail.camera_name}` }),
    photo(withPhoto ? withPhoto.snapshot_url : cam.snapshot_url, `Foto ${detail.camera_id} saat kebakaran terdeteksi`),
    h("div", { class: "stack" }, h("h3", { text: "Mengapa?" }), h("ul", { class: "why" }, ...why)),
    h("div", { class: "box" }, h("strong", { text: "Telegram" }), ...(messageLines.length ? messageLines : [h("span", { text: "Belum ada pesan." })])),
    h("div", { class: "chips" }, h("a", { class: "btn", href: `/incident/${detail.id}` }, "Buka laporan lengkap")),
  );
}

function outboxLabel(m) {
  if (m.status === "sent") return `terkirim ${fmtTime(m.sent_ts).slice(0, 5)}`;
  if (m.status === "dry_run") return "tidak dikirim (mode kering)";
  if (m.status === "failed") return `gagal: ${m.last_error || "-"}`;
  return m.attempts ? `menunggu kirim ulang (${m.last_error || "gagal"})` : "dalam antrean";
}

function cameraNote(cam, kind) {
  if (kind === "disabled") {
    if (cam.pending) return "Mematikan kamera…";
    const since = cam.control_ts ? `Dinonaktifkan operator sejak ${fmtTime(cam.control_ts).slice(0, 5)}` : "Nonaktif sejak sistem dinyalakan";
    return `${since}. Tidak memakai AI dan tidak mengirim Telegram.`;
  }
  if (cam.pending) return "Menyalakan kamera…";
  return cam.offline_reason || "Offline";
}

// The grid re-renders on every live update; the buttons are reused while their state
// is unchanged, so a click that lands during a re-render is not lost.
const actionCache = new Map();

function currentCamera(id) {
  return lastCameras.find((c) => c.id === id);
}

function operatorActions(cam) {
  if (!operator.active) return null;
  const busy = operator.busy.has(cam.id) || cam.pending;
  const sig = JSON.stringify([cam.enabled, busy, operator.busy.has(cam.id), cam.mode]);
  const cached = actionCache.get(cam.id);
  if (cached && cached.sig === sig) return cached.node;
  const id = cam.id;
  const toggle = h("button", {
    class: `btn small${cam.enabled ? " secondary" : ""}`, type: "button", disabled: busy,
    "aria-pressed": cam.enabled ? "true" : "false",
    onclick: () => toggleCamera(currentCamera(id)),
  }, cam.enabled ? "Nonaktifkan" : "Aktifkan");
  const pick = cam.mode === "foto"
    ? h("button", { class: "btn small secondary", type: "button", disabled: operator.busy.has(id), onclick: () => openGallery(currentCamera(id)) }, "Pilih foto")
    : null;
  const node = h("div", { class: "cam-actions" }, toggle, pick);
  actionCache.set(id, { sig, node });
  return node;
}

function renderCameras(cameras) {
  lastCameras = cameras;
  replace(els.grid, ...cameras.map((cam) => {
    const kind = cameraKind(cam);
    const sub = cam.sub_status && cam.online ? SUB_STATUS[cam.sub_status] || cam.sub_status : null;
    const dim = kind === "offline" || kind === "disabled";
    return h("article", { class: `cam-card${dim ? ` ${kind}` : ""}` },
      photo(kind === "disabled" ? null : cam.snapshot_url, `Gambar terbaru ${cam.id}`,
        kind === "disabled" ? "Kamera nonaktif" : cam.online ? "Belum ada gambar" : cameraNote(cam, kind)),
      h("div", { class: "cam-body" },
        h("div", { class: "cam-head" }, h("strong", { text: cam.id }), badge(kind)),
        h("span", { class: "muted", text: cam.name }),
        h("div", { class: "chips" },
          cam.mode === "foto" ? h("span", { class: "tag", text: "Mode foto (simulasi)" }) : null,
          cam.photo_shown && operator.active ? h("span", { class: "tag", text: `Foto: ${cam.photo_shown}` }) : null,
          sub ? h("span", { class: "tag", text: sub }) : null),
        cam.online
          ? h("span", { class: "cam-scores", text: `api ${num(cam.fire_score)} · asap ${num(cam.smoke_score)} · cek AI ${cam.last_llm_ts ? fmtTime(cam.last_llm_ts).slice(0, 5) : "-"}` })
          : h("span", { class: "small muted", text: cameraNote(cam, kind) }),
        cam.online && kind !== "normal" && cam.explanation ? h("span", { class: "small", text: cam.explanation }) : null,
        operator.notes[cam.id] ? h("span", { class: "small", role: "status", text: operator.notes[cam.id] }) : null,
        operatorActions(cam),
      ));
  }));
}

// --- operator --------------------------------------------------------------------------------

const opEls = {
  button: document.getElementById("operator-btn"),
  login: document.getElementById("login-dialog"),
  form: document.getElementById("login-form"),
  password: document.getElementById("login-password"),
  loginError: document.getElementById("login-error"),
  gallery: document.getElementById("gallery-dialog"),
  galleryGrid: document.getElementById("gallery-grid"),
  galleryTitle: document.getElementById("gallery-title"),
  galleryError: document.getElementById("gallery-error"),
};

function renderOperatorButton() {
  opEls.button.hidden = !operator.available;
  opEls.button.textContent = operator.active ? "Operator · Keluar" : "Masuk operator";
}

async function loadSession() {
  try {
    const data = await fetchJSON("/api/session");
    operator.available = data.available;
    operator.active = data.operator;
  } catch (err) {
    operator.available = false;
  }
  renderOperatorButton();
}

function sessionExpired() {
  operator.active = false;
  renderOperatorButton();
  refresh();
}

async function toggleCamera(cam) {
  const turnOff = cam.enabled;
  if (turnOff && cam.level !== "AMAN" && cam.online) {
    const incident = cam.level === "BAHAYA" ? " dan menutup insidennya" : "";
    const sure = window.confirm(`${cam.id} sedang ${STATUS[cameraKind(cam)].label}. Menonaktifkan akan me-reset status ke Normal${incident}. Lanjutkan?`);
    if (!sure) return;
  }
  operator.busy.add(cam.id);
  delete operator.notes[cam.id];
  renderCameras(lastCameras);
  try {
    await postJSON(`/api/cameras/${encodeURIComponent(cam.id)}/enabled`, { enabled: !turnOff });
  } catch (err) {
    if (err.status === 401) sessionExpired();
    else operator.notes[cam.id] = `Gagal mengubah ${cam.id}: ${err.message}`;
  } finally {
    operator.busy.delete(cam.id);
    refresh();
  }
}

async function openGallery(cam) {
  galleryCamera = cam;
  opEls.galleryTitle.textContent = `Pilih foto untuk ${cam.id}`;
  opEls.galleryError.textContent = "";
  replace(opEls.galleryGrid, h("p", { class: "small muted", text: "Memuat galeri…" }));
  opEls.gallery.showModal();
  try {
    const photos = await fetchJSON("/api/gallery");
    if (!photos.length) {
      replace(opEls.galleryGrid, h("p", { class: "small muted", text: "Galeri kosong. Isi folder GALLERY_DIR (default data/demo/bahan)." }));
      return;
    }
    replace(opEls.galleryGrid, ...photos.map((p) => h("button", {
      type: "button", "aria-current": cam.photo_shown === p.name ? "true" : "false",
      onclick: () => choosePhoto(p.name),
    }, h("img", { src: p.thumb_url, alt: "", loading: "lazy" }), p.name)));
  } catch (err) {
    opEls.galleryError.textContent = "Galeri tidak bisa dimuat. Coba masuk ulang sebagai operator.";
  }
}

async function choosePhoto(name) {
  const cam = galleryCamera;
  if (!cam) return;
  operator.busy.add(cam.id);
  try {
    await postJSON(`/api/cameras/${encodeURIComponent(cam.id)}/photo`, { name });
    opEls.gallery.close();
    operator.notes[cam.id] = cam.enabled
      ? `Foto ${name} dipilih; tampil dan dicek dalam beberapa detik.`
      : `Foto ${name} disiapkan. Aktifkan ${cam.id} untuk mulai memeriksa.`;
  } catch (err) {
    if (err.status === 401) { opEls.gallery.close(); sessionExpired(); }
    else opEls.galleryError.textContent = `Gagal: ${err.message}`;
  } finally {
    operator.busy.delete(cam.id);
    refresh();
  }
}

opEls.button.addEventListener("click", async () => {
  if (operator.active) {
    try { await postJSON("/api/logout"); } catch (err) { /* already logged out */ }
    operator.active = false;
    renderOperatorButton();
    refresh();
    return;
  }
  opEls.loginError.textContent = "";
  opEls.password.value = "";
  opEls.login.showModal();
  opEls.password.focus();
});

opEls.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  opEls.loginError.textContent = "";
  try {
    await postJSON("/api/login", { password: opEls.password.value });
    opEls.password.value = "";
    opEls.login.close();
    operator.active = true;
    renderOperatorButton();
    refresh();
  } catch (err) {
    opEls.loginError.textContent = err.message;
    opEls.password.select();
  }
});

document.getElementById("login-cancel").addEventListener("click", () => opEls.login.close());
document.getElementById("gallery-close").addEventListener("click", () => opEls.gallery.close());

function renderHistory(events, cameras) {
  if (!filterFilled) {
    for (const cam of cameras) els.historyFilter.append(h("option", { value: cam.id, text: cam.id }));
    filterFilled = true;
  }
  const changes = events.filter((e) => e.level_from !== e.level || e.llm || e.rule === "ON" || e.rule === "OFF");
  if (!changes.length) {
    replace(els.historyBody, h("tr", null, h("td", { colspan: 5, class: "muted", text: "Belum ada perubahan status atau cek AI dalam 30 menit terakhir." })));
    return;
  }
  replace(els.historyBody, ...changes.slice(0, 60).map((e) => {
    const from = e.level_from && e.level_from !== e.level ? `${STATUS[KIND_BY_LEVEL[e.level_from]].label} → ` : "";
    return h("tr", null,
      h("td", { class: "mono", text: fmtTime(e.ts) }),
      h("td", { text: e.camera_id }),
      h("td", { text: `${from}${e.label}` }),
      h("td", { class: "mono", text: e.rule }),
      h("td", { class: "muted", text: e.explanation || "" }));
  }));
}

async function refresh() {
  if (refreshing) { pending = true; return; }
  refreshing = true;
  try {
    const camera = els.historyFilter.value;
    const [status, events] = await Promise.all([
      fetchJSON("/api/status"),
      fetchJSON(`/api/events?minutes=30${camera ? `&camera=${encodeURIComponent(camera)}` : ""}`),
    ]);
    setHeaderPill(status);
    showMonitorBanner(status.monitor);
    renderRisk(status.risk);
    renderCounts(status.counts);
    renderCameras(status.cameras);
    renderHistory(events, status.cameras);
    mapView.update(status);
    await renderIncident(status);
  } catch (err) {
    document.getElementById("live-banner").hidden = false;
  } finally {
    refreshing = false;
    if (pending) { pending = false; refresh(); }
  }
}

async function loadHotspots() {
  try {
    mapView.setHotspots(await fetchJSON("/api/hotspots"), els.hotspotNote);
  } catch (err) {
    mapView.setHotspots(null, els.hotspotNote);
  }
}

els.historyFilter.addEventListener("change", refresh);
fetchJSON("/api/map").then((data) => mapView.setStatic(data)).catch(() => {});
startClock();
loadSession().then(refresh);
renderRiskHistory();
loadHotspots();
setInterval(renderRiskHistory, 600000);
setInterval(loadHotspots, 1800000);
connectLive(refresh);
