"""When to send what (Spec §8.1). Messages go to the outbox; OutboxSender delivers them.

Tiers:
- Kebakaran Terdeteksi: at once, one per incident, with photo.
- Perlu Dicek: when a camera rises from Normal, at most once per camera per cooldown.
  Not while the AI is unavailable (R4, "unverified"): that stays on the dashboard, and
  the alert goes out only if the AI later confirms the check at the same camera.
- Area risk: when the level rises to Tinggi or Sangat Tinggi.
- Morning summary: once a day at MORNING_SUMMARY_AT.
- AI status: one notice when no AI endpoint has answered for AI_DOWN_NOTICE_S while
  cameras are on (camera checks are then held on the dashboard), one when it is back.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from mataklabat import messages
from mataklabat.config import Settings, now_local
from mataklabat.decision import SUB_REJECTED_LOOKALIKE, SUB_UNVERIFIED, Decision, Level
from mataklabat.fwi import LEVELS
from mataklabat.storage import OUTBOX_DRY_RUN, OUTBOX_PENDING, Storage, risk_to_dict

log = logging.getLogger(__name__)

HIGH_LEVELS = ("Tinggi", "Sangat Tinggi")
MORNING_CHECK_S = 30.0
MORNING_WINDOW = timedelta(hours=3)
MORNING_WAIT_FOR_WEATHER = timedelta(minutes=15)
AI_DOWN_NOTICE_S = 300.0

ReportRequester = Callable[[int, Decision, Path | None], None]


class AlertService:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        risk_provider: Callable[[], dict | None] = lambda: None,
        report_requester: ReportRequester | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = now_local,
    ):
        self.settings = settings
        self.storage = storage
        self.cameras = {c.id: c for c in settings.cameras}
        self.risk_provider = risk_provider
        self.report_requester = report_requester
        self._clock = clock
        self._wall = wall_clock
        self._last_check_alert: dict[str, float] = {}
        self._held_unverified: set[str] = set()
        self._ai_down_since: float | None = None
        self._ai_down_notified = False
        self._previous_risk: str | None = storage.current_risk_level()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def delivery_status(self) -> str:
        s = self.settings
        configured = bool(s.telegram_bot_token and s.telegram_chat_id)
        return OUTBOX_PENDING if s.auto_send_alert and configured else OUTBOX_DRY_RUN

    def _enqueue(self, kind: str, text: str, **kwargs: Any) -> int:
        status = self.delivery_status
        oid = self.storage.enqueue(kind, text, status=status, created=self._wall(), **kwargs)
        note = "" if status == OUTBOX_PENDING else " (mode kering, tidak dikirim)"
        log.info("Pesan %s #%d dibuat%s:\n%s", kind, oid, note, text)
        return oid

    # --- Recorder listener --------------------------------------------------------------

    def on_incident_opened(self, incident_id: int, decision: Decision, photo: Path | None) -> None:
        camera = self.cameras[decision.camera_id]
        text = messages.fire_alert(decision, camera, self.risk_provider(), self.settings.public_url, incident_id)
        oid = self._enqueue(
            "fire", text, camera_id=camera.id, incident_id=incident_id,
            photo_path=None if photo is None else str(photo),
        )
        self.storage.update_incident(incident_id, alert_outbox_id=oid)
        if self.report_requester is not None:
            self.report_requester(incident_id, decision, photo)

    def on_level_change(self, decision: Decision, photo: Path | None) -> None:
        self._held_unverified.discard(decision.camera_id)
        if not (decision.level == Level.WASPADA and decision.level_from == Level.AMAN):
            return
        if decision.sub_status == SUB_UNVERIFIED:
            # Without the AI the local detector alone is too noisy for the group chat.
            self._held_unverified.add(decision.camera_id)
            log.info("%s: Perlu Dicek (belum terverifikasi) hanya di dashboard, tidak ke Telegram.",
                     decision.camera_id)
            return
        self._send_check_alert(decision, photo)

    def on_sub_status_change(self, decision: Decision, photo: Path | None) -> None:
        """The AI came back and judged a camera that was held as unverified."""
        cam = decision.camera_id
        if cam not in self._held_unverified or decision.sub_status == SUB_UNVERIFIED:
            return
        self._held_unverified.discard(cam)
        if decision.level == Level.WASPADA and decision.sub_status != SUB_REJECTED_LOOKALIKE:
            self._send_check_alert(decision, photo)

    def _send_check_alert(self, decision: Decision, photo: Path | None) -> None:
        now = self._clock()
        last = self._last_check_alert.get(decision.camera_id)
        if last is not None and now - last < self.settings.check_alert_cooldown_s:
            log.info("%s: Perlu Dicek tidak dikirim ulang (cooldown).", decision.camera_id)
            return
        self._last_check_alert[decision.camera_id] = now
        camera = self.cameras[decision.camera_id]
        text = messages.check_alert(decision, camera, self.risk_provider(), self.settings.public_url)
        self._enqueue("check", text, camera_id=camera.id, photo_path=None if photo is None else str(photo))

    def enqueue_report(self, incident_id: int, camera, report_md: str) -> int:
        """Second message of an incident: the agent (or template) report."""
        return self._enqueue(
            "report", messages.report_message(camera, incident_id, report_md),
            camera_id=camera.id, incident_id=incident_id,
        )

    def on_camera_disabled(self, camera_id: str) -> None:
        """An operator reset: the next rise at this camera alerts again right away."""
        self._held_unverified.discard(camera_id)
        self._last_check_alert.pop(camera_id, None)

    def on_incident_closed(self, incident_id: int, decision: Decision) -> None:
        log.info("%s: insiden #%d selesai (kembali Normal).", decision.camera_id, incident_id)

    # --- AI status (Housekeeper) ----------------------------------------------------------

    def on_ai_status(self, failing: bool | None, detail: str) -> None:
        """failing=None: no camera is on, so nothing is known; the state is kept."""
        if failing is None:
            return
        now = self._clock()
        if failing:
            if self._ai_down_since is None:
                self._ai_down_since = now
            if not self._ai_down_notified and now - self._ai_down_since >= AI_DOWN_NOTICE_S:
                self._ai_down_notified = True
                self._enqueue("system", messages.ai_down_notice(detail, now - self._ai_down_since, self.settings.public_url))
            return
        if self._ai_down_notified:
            since = now if self._ai_down_since is None else self._ai_down_since
            self._enqueue("system", messages.ai_up_notice(detail, now - since))
        self._ai_down_since = None
        self._ai_down_notified = False

    # --- risk listener --------------------------------------------------------------------

    def on_risk(self, snapshot) -> None:
        level, previous = snapshot.level, self._previous_risk
        self._previous_risk = level
        # No alert for the very first value after a fresh install: there is nothing to rise from.
        if previous is not None and level in HIGH_LEVELS and LEVELS.index(level) > LEVELS.index(previous):
            self._enqueue("risk", messages.risk_rise_alert(risk_to_dict(snapshot), previous, self.settings.public_url))

    # --- morning summary --------------------------------------------------------------

    def maybe_send_morning_summary(self) -> bool:
        at = self.settings.morning_summary_at
        if not at:
            return False
        now = self._wall()
        hour, minute = (int(x) for x in at.split(":"))
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # Only inside a window after the scheduled time, so starting the monitor in the
        # evening does not send a "morning" summary.
        if not due <= now < due + MORNING_WINDOW:
            return False
        if self.storage.outbox_count_since("morning", due):
            return False
        risk = self.risk_provider()
        if risk is None and now < due + MORNING_WAIT_FOR_WEATHER:
            return False  # give the first weather download a moment
        cameras = self.storage.camera_rows()
        self._enqueue("morning", messages.morning_summary(risk, cameras, now, self.settings.public_url))
        return True

    def start(self) -> AlertService:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="alerts", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.maybe_send_morning_summary()
            except Exception:
                log.exception("Ringkasan pagi gagal.")
            self._stop.wait(MORNING_CHECK_S)
