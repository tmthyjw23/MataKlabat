// Incident detail page: photos, decision timeline, AI report, Telegram status, trace.
"use strict";

const main = document.getElementById("incident-main");
const incidentId = Number(location.pathname.split("/").filter(Boolean).pop());

function outboxStatus(m) {
  if (m.status === "sent") return `terkirim ${fmtTime(m.sent_ts)}`;
  if (m.status === "dry_run") return "tidak dikirim (mode kering)";
  if (m.status === "failed") return `gagal permanen: ${m.last_error || "-"}`;
  return m.attempts ? `menunggu kirim ulang, percobaan ${m.attempts}: ${m.last_error || ""}` : "dalam antrean";
}

function render(d) {
  document.title = `MataKlabat · Insiden #${d.id}`;
  const open = !d.closed_ts;
  const photos = d.events.filter((e) => e.snapshot_url);
  const changes = d.events.filter((e) => e.level_from !== e.level || e.llm);
  const steps = d.agent_steps || [];

  replace(main,
    h("section", { class: "card stack" },
      h("div", { class: "chips" }, open ? badge("fire") : h("span", { class: "tag", text: "Selesai" }),
        h("span", { class: "small muted", text: `Insiden #${d.id}` })),
      h("h1", { text: `${d.camera_id} · ${d.camera_name}` }),
      h("p", { class: "muted", text: `Dibuka ${fmtDateTime(d.opened_ts)}${d.closed_ts ? ` · ditutup ${fmtDateTime(d.closed_ts)}` : " · masih berlangsung"}` }),
      photos.length
        ? h("div", { class: "thumbs" }, ...photos.slice(-8).map((e) =>
            h("figure", null, h("img", { src: e.snapshot_url, alt: `Foto ${fmtTime(e.ts)} (${e.label})`, loading: "lazy" }),
              h("figcaption", { class: "small muted", text: `${fmtTime(e.ts)} · ${e.label}` }))))
        : h("p", { class: "muted", text: "Tidak ada foto arsip." }),
    ),

    h("section", { class: "row" },
      h("article", { class: "card wide stack" },
        h("h2", { text: "Laporan insiden" }),
        d.report_md
          ? renderMarkdown(d.report_md)
          : h("p", { class: "muted", text: "Laporan sedang disusun (biasanya ±1 menit)…" }),
        d.report_source ? h("p", { class: "small muted", text: d.report_source === "agent" ? "Sumber: AI Agent (tool calling)." : "Sumber: template otomatis (AI tidak tersedia)." }) : null,
        steps.length ? h("details", null, h("summary", { text: `Langkah agent (${steps.length} tool)` }),
          h("pre", { text: JSON.stringify(steps, null, 2) })) : null,
      ),
      h("article", { class: "card narrow stack" },
        h("h2", { text: "Pesan Telegram" }),
        d.messages.length
          ? h("ul", { class: "timeline" }, ...d.messages.map((m) => h("li", null,
              h("div", { class: "stack" },
                h("strong", { text: m.kind === "fire" ? "Peringatan kebakaran" : m.kind === "report" ? "Laporan AI" : m.kind }),
                h("span", { class: "small muted", text: outboxStatus(m) }),
                h("details", null, h("summary", { text: "Isi pesan" }), h("pre", { text: m.text }))))))
          : h("p", { class: "muted", text: "Belum ada pesan." }),
      ),
    ),

    h("section", { class: "card stack" },
      h("h2", { text: "Jejak keputusan" }),
      h("ul", { class: "timeline" }, ...changes.map((e) => {
        const kind = KIND_BY_LEVEL[e.level];
        return h("li", null, statusIcon(kind, 18),
          h("div", { class: "stack" },
            h("div", null, h("span", { class: "mono", text: `${fmtTime(e.ts)} ` }), h("strong", { text: e.label }), h("span", { class: "mono muted", text: ` · ${e.rule}` })),
            h("span", { text: e.explanation || "" }),
            e.llm && e.llm.reasoning ? h("span", { class: "small quote", text: `AI: “${e.llm.reasoning}”` }) : null,
            h("details", null, h("summary", { text: "Trace JSON" }), h("pre", { text: JSON.stringify(e.trace, null, 2) }))));
      })),
    ),
  );
}

async function load() {
  if (!Number.isInteger(incidentId)) {
    replace(main, h("p", { text: "Nomor insiden tidak valid." }));
    return;
  }
  try {
    render(await fetchJSON(`/api/incidents/${incidentId}`));
  } catch (err) {
    replace(main, h("section", { class: "card" }, h("h1", { text: "Insiden tidak ditemukan" }), h("a", { href: "/", text: "Kembali ke dashboard" })));
  }
}

startClock();
load();
connectLive(load);
