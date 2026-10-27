"""Incident report: AI agent with tool calling, plus a template fallback (Spec §9).

The agent never sends anything itself. Its report is stored on the incident and
queued as the second Telegram message by `IncidentReporter`.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import openai

from mataklabat import messages
from mataklabat.config import CameraConfig, Settings
from mataklabat.decision import Decision
from mataklabat.storage import Storage
from mataklabat.tools import TOOL_SCHEMAS, IncidentTools

log = logging.getLogger(__name__)

AI_LABEL = "_Dihasilkan AI. Verifikasi lapangan diperlukan._"
TEMPLATE_LABEL = "_Laporan otomatis dari template"  # followed by the reason, e.g. "(AI nonaktif)"
SECTIONS = (
    "Ringkasan",
    "Bukti",
    "Kondisi Cuaca & Risiko",
    "Arah Sebaran & Desa Terancam",
    "Rekomendasi Tindakan",
    "Pihak yang Dihubungi",
)

SYSTEM_PROMPT = f"""Kamu adalah agen tanggap darurat karhutla Gunung Klabat, Minahasa Utara.
Sebuah kamera mendeteksi KEBAKARAN (status Kebakaran Terdeteksi).
Gunakan tools untuk: (1) cek cuaca dan risiko kawasan, (2) cek hotspot satelit, (3) perkirakan arah
sebaran dan desa terancam (angin DARI X derajat mendorong api KE X+180 derajat), (4) cari posko/damkar
terdekat, (5) lihat riwayat kamera.
Lalu tulis LAPORAN INSIDEN dalam Bahasa Indonesia, markdown, dengan tepat enam bagian berjudul
"## " berikut, berurutan: {", ".join(SECTIONS)}.
Rekomendasi maksimal 5 butir, urut prioritas. Jangan mengarang data yang tidak dikembalikan tools:
tulis "tidak tersedia" jika kosong. Kontak yang "belum diisi" ditulis apa adanya. Ringkas dan jelas."""


@dataclass
class Report:
    markdown: str
    source: str  # "agent" or "template"
    steps: list[dict[str, Any]] = field(default_factory=list)


class AgentError(Exception):
    pass


class IncidentAgent:
    def __init__(self, settings: Settings, tools: IncidentTools, client: Any = None):
        self.settings = settings
        self.tools = tools
        self.client = client or openai.OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "tanpa-key",
            timeout=settings.agent_timeout_s,
            max_retries=0,
        )

    def run(self, camera: CameraConfig, decision: Decision) -> Report:
        deadline = time.monotonic() + self.settings.agent_timeout_s
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": incident_brief(camera, decision)},
        ]
        steps: list[dict[str, Any]] = []
        for _ in range(self.settings.agent_max_steps + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AgentError("melewati batas waktu agent")
            resp = self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=msgs,
                tools=TOOL_SCHEMAS,
                timeout=remaining,
            )
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []
            if not calls:
                text = (msg.content or "").strip()
                if not text:
                    raise AgentError("agent tidak menulis laporan")
                return Report(f"{AI_LABEL}\n\n{text}", "agent", steps)
            if len(steps) >= self.settings.agent_max_steps:
                raise AgentError("agent melewati batas langkah")
            msgs.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in calls
                ],
            })
            for c in calls:
                result = self.tools.call(c.function.name, c.function.arguments)
                steps.append({"tool": c.function.name, "arguments": c.function.arguments, "result": result})
                msgs.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, ensure_ascii=False)})
        raise AgentError("agent melewati batas langkah")


def incident_brief(camera: CameraConfig, decision: Decision) -> str:
    v = decision.verdict
    lines = [
        f"Kamera: {camera.id} ({camera.name}), koordinat {camera.lat:.4f}, {camera.lon:.4f}, menghadap {camera.facing_deg:.0f}°.",
        f"Waktu: {messages.format_time(decision.ts)}.",
        f"Keputusan ({decision.rule}): {decision.explanation}",
    ]
    if v is not None and v.ok:
        lines.append(f"Verifikasi AI: {v.hazard_type}, keyakinan {v.confidence:.2f}, keparahan {v.severity}.")
        if v.evidence:
            lines.append("Bukti: " + "; ".join(v.evidence))
        if v.reasoning:
            lines.append(f"Alasan AI: {v.reasoning}")
    return "\n".join(lines)


def template_report(camera: CameraConfig, decision: Decision, tools: IncidentTools, reason: str = "AI nonaktif") -> Report:
    """Deterministic report from the same tools, used when the agent is unavailable."""
    steps: list[dict[str, Any]] = []

    def use(name: str, **args: Any) -> dict[str, Any]:
        result = tools.call(name, args)
        steps.append({"tool": name, "arguments": args, "result": result})
        return result

    weather = use("get_weather", lat=camera.lat, lon=camera.lon)
    hotspots = use("get_satellite_hotspots", lat=camera.lat, lon=camera.lon)
    resources = use("find_nearest_resources", lat=camera.lat, lon=camera.lon)
    wind_from, wind_kmh = weather.get("wind_from_deg"), weather.get("wind_kmh")
    spread = (
        use("estimate_spread", camera_id=camera.id, wind_dir_deg=wind_from, wind_kmh=wind_kmh)
        if wind_from is not None and wind_kmh is not None else None
    )

    v = decision.verdict
    evidence = [f"- {e}" for e in (v.evidence if v is not None and v.ok else ())] or ["- tidak tersedia"]
    if weather.get("status") == "unavailable":
        weather_lines = ["- tidak tersedia"]
    else:
        weather_lines = [
            f"- Suhu {weather['temperature_c']}°C, kelembapan {weather['humidity_pct']}%, "
            f"angin {weather['wind_kmh']} km/j dari {weather['wind_from']}",
            f"- Risiko kawasan {weather['area_risk_level']} (karena {weather['area_risk_driver']}), "
            f"FWI {weather['fwi']}, {weather['days_without_rain']} hari tanpa hujan",
        ]
    if spread is None:
        spread_lines = ["- tidak tersedia (data angin kosong)"]
    else:
        villages = ", ".join(f"{x['name']} ±{x['distance_km']} km" for x in spread["villages_in_path"]) or "tidak ada desa dalam 8 km"
        spread_lines = [f"- Cenderung ke {spread['spread_toward']}", f"- Desa di jalur angin: {villages}"]
        if spread.get("note"):
            spread_lines.append(f"- Catatan: {spread['note']}")
    if hotspots.get("status") == "ok":
        spread_lines.append(f"- Hotspot satelit 24 jam (≤ 10 km): {hotspots['count']}")
    else:
        spread_lines.append("- Hotspot satelit: tidak tersedia")
    contacts = [
        f"- {r['name']} ({r['kind']}, ±{r['distance_km']} km), kontak: {r['contact']}" for r in resources.get("resources", [])
    ] or ["- tidak tersedia"]
    toward = spread["spread_toward"] if spread else "arah angin"
    md = "\n".join([
        f"{TEMPLATE_LABEL} ({reason}). Verifikasi lapangan diperlukan._", "",
        "## Ringkasan",
        f"{camera.id} ({camera.name}) berstatus Kebakaran Terdeteksi sejak {messages.format_time(decision.ts)}. {decision.explanation}",
        "", "## Bukti", *evidence,
        "", "## Kondisi Cuaca & Risiko", *weather_lines,
        "", "## Arah Sebaran & Desa Terancam", *spread_lines,
        "", "## Rekomendasi Tindakan",
        "1. Kirim regu untuk verifikasi lapangan ke lokasi kamera.",
        f"2. Siagakan regu pemadam di sisi {toward} lokasi.",
        "3. Beri tahu aparat desa di jalur angin untuk bersiap.",
        "4. Pantau terus dashboard dan pesan berikutnya.",
        "", "## Pihak yang Dihubungi", *contacts,
    ])
    return Report(md, "template", steps)


class IncidentReporter:
    """Builds the report for each new incident in a background thread and queues
    it as the second Telegram message (Spec §8.1)."""

    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        tools: IncidentTools,
        enqueue_report: Callable[[int, CameraConfig, str], int],
        agent: IncidentAgent | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.settings = settings
        self.storage = storage
        self.tools = tools
        self.enqueue_report = enqueue_report
        self.agent = agent
        self._clock = clock
        self._last_agent_run: dict[str, float] = {}
        self._jobs: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def request(self, incident_id: int, decision: Decision, photo: Path | None = None) -> None:
        self._jobs.put((incident_id, decision))

    def start(self) -> IncidentReporter:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="incident-agent", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._jobs.put(None)
        if self._thread is not None:
            self._thread.join(timeout)

    def handle(self, incident_id: int, decision: Decision) -> Report:
        camera = self.settings.camera(decision.camera_id)
        report = self.build(camera, decision)
        self.storage.update_incident(
            incident_id,
            report_md=report.markdown,
            report_source=report.source,
            agent_steps_json=json.dumps(report.steps, ensure_ascii=False, default=str),
        )
        oid = self.enqueue_report(incident_id, camera, report.markdown)
        self.storage.update_incident(incident_id, report_outbox_id=oid)
        log.info("Laporan insiden #%d dibuat (%s).", incident_id, report.source)
        return report

    def build(self, camera: CameraConfig, decision: Decision) -> Report:
        now = self._clock()
        last = self._last_agent_run.get(camera.id)
        cooling = last is not None and now - last < self.settings.agent_cooldown_s
        reason = "AI nonaktif"
        if self.agent is not None and not cooling:
            self._last_agent_run[camera.id] = now
            try:
                return self.agent.run(camera, decision)
            except (AgentError, openai.APIError) as exc:
                log.warning("AI Agent gagal (%s), memakai laporan template.", exc)
                reason = "AI Agent gagal atau melewati batas waktu"
            except Exception:
                log.exception("AI Agent error tak terduga, memakai laporan template.")
                reason = "AI Agent error"
        elif cooling:
            minutes = round(self.settings.agent_cooldown_s / 60)
            log.info("%s: AI Agent dalam cooldown, memakai laporan template.", camera.id)
            reason = f"AI Agent sudah membuat laporan untuk kamera ini dalam {minutes} menit terakhir"
        return template_report(camera, decision, self.tools, reason)

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._jobs.get()
            if job is None:
                break
            try:
                self.handle(*job)
            except Exception:
                log.exception("Gagal membuat laporan insiden.")
