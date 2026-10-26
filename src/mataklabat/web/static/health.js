// System health page (Spec §10.1, §12).
"use strict";

const COMPONENT_NAMES = { monitor: "Monitor", weather: "Cuaca (Open-Meteo)", llm: "AI vision (9router)", telegram: "Telegram" };

function okCell(ok) {
  if (ok === null) {
    return h("td", null, h("span", { class: "badge offline" }, statusIcon("offline", 12, "#fff"), "Nonaktif"));
  }
  return h("td", null, h("span", { class: `badge ${ok ? "normal" : "fire"}` }, statusIcon(ok ? "normal" : "fire", 12, "#fff"), ok ? "OK" : "Bermasalah"));
}

async function load() {
  let data, outbox;
  try {
    [data, outbox] = await Promise.all([fetchJSON("/api/health"), fetchJSON("/api/outbox?limit=30")]);
  } catch (err) {
    document.getElementById("live-banner").hidden = false;
    return;
  }
  showMonitorBanner(data.monitor);
  const rows = data.components.map((c) => {
    const ok = c.component === "monitor" ? data.monitor.alive : c.ok === -1 ? null : Boolean(c.ok);
    return h("tr", null, h("td", { text: COMPONENT_NAMES[c.component] || c.component }), okCell(ok),
      h("td", { text: c.detail || "" }), h("td", { class: "mono", text: fmtTime(c.ts) }));
  });
  replace(document.getElementById("components"), ...(rows.length ? rows : [h("tr", null, h("td", { colspan: 4, class: "muted", text: "Monitor belum pernah berjalan." }))]));

  replace(document.getElementById("cameras"), ...data.cameras.map((cam) => {
    const kind = cameraKind(cam);
    return h("tr", null, h("td", { text: `${cam.id} · ${cam.name}` }),
      h("td", { text: cam.mode === "foto" ? "Kamera foto (folder)" : "Webcam / video / stream" }),
      h("td", null, badge(kind)),
      h("td", { class: "muted", text: cam.online ? `frame terakhir ${fmtTime(cam.ts)}` : (cam.offline_reason || "") }));
  }));

  const cfg = data.config;
  document.getElementById("config").textContent = [
    cfg.telegram_configured ? "Telegram terkonfigurasi" : "Telegram belum diisi (mode kering)",
    cfg.auto_send_alert ? "kirim otomatis aktif" : "kirim otomatis mati (mode kering)",
    cfg.llm_enabled ? `AI: ${cfg.llm_model}, prompt ${cfg.prompt_version}` : "AI nonaktif",
    cfg.firms_configured ? "NASA FIRMS aktif" : "NASA FIRMS belum diisi",
    `${data.outbox_pending} pesan menunggu`,
  ].join(" · ");

  replace(document.getElementById("outbox"), ...(outbox.length ? outbox.map((m) => h("tr", null,
    h("td", { class: "mono", text: m.id }), h("td", { text: m.kind }), h("td", { text: m.status }),
    h("td", { class: "mono", text: fmtTime(m.created_ts) }),
    h("td", { class: "muted", text: m.last_error || (m.sent_ts ? `terkirim ${fmtTime(m.sent_ts)}` : "") }))) :
    [h("tr", null, h("td", { colspan: 5, class: "muted", text: "Belum ada pesan." }))]));
}

startClock();
load();
connectLive(load);
