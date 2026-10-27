"""Assembles the monitor process: cameras, risk, storage, alerts, housekeeping."""

from __future__ import annotations

import logging
import threading
from typing import Any

from mataklabat.agent import IncidentAgent, IncidentReporter
from mataklabat.alerts import AlertService
from mataklabat.config import Settings, now_local
from mataklabat.control import CameraControl, ControlWatcher
from mataklabat.llm import LLMPool
from mataklabat.notifier import OutboxSender, TelegramClient
from mataklabat.pipeline import ConsoleSink, Monitor
from mataklabat.recorder import Recorder
from mataklabat.risk import RiskService
from mataklabat.snapshots import SnapshotStore
from mataklabat.storage import Storage, risk_to_dict
from mataklabat.tools import IncidentTools
from mataklabat.vision_llm import VisionVerifier

log = logging.getLogger(__name__)

HEARTBEAT_S = 5.0
PRUNE_EVERY_S = 3600.0


class Housekeeper:
    """Writes the monitor heartbeat and component health every few seconds,
    and prunes old events and snapshots every hour (Spec §11-12)."""

    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        snapshots: SnapshotStore,
        monitor_ref: dict[str, Any],
        risk: RiskService | None,
        interval_s: float = HEARTBEAT_S,
        alerts=None,
    ):
        self.settings = settings
        self.storage = storage
        self.snapshots = snapshots
        self.monitor_ref = monitor_ref
        self.risk = risk
        self.alerts = alerts
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at = now_local()
        self._last_prune: float = -PRUNE_EVERY_S

    def start(self) -> Housekeeper:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="housekeeper", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self.storage.set_health("monitor", False, "monitor dihentikan")

    def beat(self) -> None:
        uptime = int((now_local() - self._started_at).total_seconds())
        self.storage.set_health("monitor", True, f"berjalan {uptime // 60} menit")

        if self.risk is not None:
            snap = self.risk.snapshot()
            fresh = self.risk.current() is not None
            if snap is None:
                detail = self.risk.last_error or "menunggu data cuaca pertama"
            else:
                age_min = int((self.risk.age_s() or 0) // 60)
                detail = f"risiko {snap.level}, data {age_min} menit lalu"
                if self.risk.last_error:
                    detail += f" (gagal terakhir: {self.risk.last_error})"
            self.storage.set_health("weather", fresh, detail)

        monitor = self.monitor_ref.get("monitor")
        if monitor is not None:
            if monitor.verifier is None:
                self.storage.set_health("llm", None, "AI nonaktif (LLM_MODEL kosong atau --no-llm), memakai detektor lokal")
            else:
                active = [w for w in monitor.workers if w.active]
                failing = [w.camera.id for w in active if w._llm_failed]
                detail = llm_detail(monitor.verifier.pool.status())
                if failing:
                    detail += f"; tidak ada AI yang menjawab untuk {', '.join(failing)}"
                self.storage.set_health("llm", not failing, detail)
                if self.alerts is not None:
                    # None = no camera is asking the AI, so nothing is known about it.
                    self.alerts.on_ai_status(bool(failing) if active else None, detail)

    def prune(self) -> None:
        removed = self.storage.prune(now_local(), self.settings.event_keep_days)
        files = self.snapshots.prune_archive()
        if removed or files:
            log.info("Retensi: %d event dan %d foto arsip dihapus.", removed, files)

    def _run(self) -> None:
        elapsed = PRUNE_EVERY_S
        while not self._stop.is_set():
            try:
                self.beat()
                if elapsed >= PRUNE_EVERY_S:
                    self.prune()
                    elapsed = 0.0
            except Exception:
                log.exception("Housekeeping gagal.")
            self._stop.wait(self.interval_s)
            elapsed += self.interval_s


def llm_detail(status: dict[str, Any]) -> str:
    """One line for the health page: which endpoint answers, which ones rest."""
    order = status["order"]
    active = status["active"] or order[0]
    text = f"memakai {active}"
    if len(order) > 1:
        text += f" (urutan: {' → '.join(order)})"
    if status["resting"]:
        text += "; istirahat: " + ", ".join(f"{k} ({v})" for k, v in status["resting"].items())
    return text


def build_monitor(settings: Settings, with_weather: bool = True, verifier=None) -> Monitor:
    storage = Storage(settings.db_path)
    snapshots = SnapshotStore(settings.snapshot_dir, settings.snapshot_archive_max_mb)

    risk = RiskService(*settings.risk_point, listeners=[storage.save_risk]) if with_weather else None

    def risk_provider() -> dict | None:
        snap = risk.current() if risk is not None else None
        return None if snap is None else risk_to_dict(snap)

    alerts = AlertService(settings, storage, risk_provider=risk_provider)
    tools = IncidentTools(settings, risk_provider, recent_events=storage.recent_events)
    # One pool for vision and agent: an endpoint found dead by one is skipped by both.
    pool = LLMPool(settings.llm_chain, settings.llm_timeout_s) if settings.llm_enabled else None
    if verifier is None and pool is not None:
        verifier = VisionVerifier(settings, pool=pool)
    agent = IncidentAgent(settings, tools, pool=pool) if pool is not None else None
    reporter = IncidentReporter(settings, storage, tools, alerts.enqueue_report, agent)
    alerts.report_requester = reporter.request
    if risk is not None:
        risk.listeners.append(alerts.on_risk)
    telegram = None
    if settings.telegram_bot_token and settings.telegram_chat_id:
        telegram = TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id)
    services: list[Any] = [alerts, reporter, OutboxSender(storage, telegram)]

    recorder = Recorder(storage, snapshots, settings.cameras, listeners=[alerts, reporter])
    control = ControlWatcher(CameraControl(settings.control_db_path, settings.cameras))
    monitor_ref: dict[str, Any] = {}
    services += [control, Housekeeper(settings, storage, snapshots, monitor_ref, risk, alerts=alerts)]
    monitor = Monitor(
        settings, sinks=[ConsoleSink(), recorder], verifier=verifier, risk=risk, services=services,
        is_enabled=control.enabled,
    )
    monitor_ref["monitor"] = monitor
    monitor.storage = storage
    return monitor
