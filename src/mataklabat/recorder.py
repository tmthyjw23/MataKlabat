"""Persists decisions (Spec §11): events, camera status, snapshots and incidents.

Listeners (the alert service) are told about level changes and incidents after
the data is stored, so they can refer to rows and photos that already exist.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Protocol

from mataklabat.camera import Frame
from mataklabat.config import CameraConfig
from mataklabat.decision import Decision, Level
from mataklabat.detector import LocalDetection
from mataklabat.snapshots import SnapshotStore, annotate
from mataklabat.storage import Storage

log = logging.getLogger(__name__)

EVENT_HEARTBEAT_S = 10.0
STATUS_INTERVAL_S = 1.0


class RecorderListener(Protocol):
    def on_level_change(self, decision: Decision, photo: Path | None) -> None: ...

    def on_sub_status_change(self, decision: Decision, photo: Path | None) -> None: ...

    def on_incident_opened(self, incident_id: int, decision: Decision, photo: Path | None) -> None: ...

    def on_incident_closed(self, incident_id: int, decision: Decision) -> None: ...


class Recorder:
    def __init__(
        self,
        storage: Storage,
        snapshots: SnapshotStore,
        cameras: tuple[CameraConfig, ...],
        listeners: list[Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.storage = storage
        self.snapshots = snapshots
        self.cameras = {c.id: c for c in cameras}
        self.listeners = listeners or []
        self._clock = clock
        self._last_event_at: dict[str, float] = {}
        self._last_status_at: dict[str, float] = {}
        self._offline: set[str] = set()
        self._sub_status: dict[str, str | None] = {}
        for cam in cameras:
            self.storage.upsert_camera_status(
                cam.id, name=cam.name, mode=cam.mode, level=Level.AMAN.value,
                online=0, offline_reason="menunggu frame pertama",
            )

    def relative(self, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return path.relative_to(self.snapshots.root).as_posix()
        except ValueError:
            return path.as_posix()

    def on_decision(self, decision: Decision, local: LocalDetection, frame: Frame) -> None:
        cam = decision.camera_id
        now = self._clock()
        # Same level, different sub-status (e.g. "unverified" → verified by the AI).
        sub_changed = not decision.changed and decision.sub_status != self._sub_status.get(cam)
        self._sub_status[cam] = decision.sub_status
        need_event = (
            decision.changed
            or sub_changed
            or decision.verdict is not None
            or now - self._last_event_at.get(cam, -1e9) >= EVENT_HEARTBEAT_S
        )
        status_due = need_event or cam in self._offline or now - self._last_status_at.get(cam, -1e9) >= STATUS_INTERVAL_S
        if not status_due:
            return

        scores = {"fire": local.fire_score, "smoke": local.smoke_score}
        image = annotate(frame.image, local.boxes, frame.ts, scores)
        latest = self.snapshots.save_latest(cam, image)
        archived = None
        if need_event and decision.level != Level.AMAN:
            archived = self.snapshots.archive(cam, image, frame.ts)
        photo = archived or latest

        event_id = None
        if need_event:
            self._last_event_at[cam] = now
            v = decision.verdict
            event_id = self.storage.insert_event(
                ts=decision.ts,
                camera_id=cam,
                level=decision.level.value,
                sub_status=decision.sub_status,
                fire_score=local.fire_score,
                smoke_score=local.smoke_score,
                llm=None if v is None else v.to_dict(),
                risk_level=decision.risk_level,
                fwi=decision.trace["inputs"]["risk"]["fwi"] if decision.trace["inputs"].get("risk") else None,
                rule=decision.rule,
                trace=decision.trace,
                snapshot_path=self.relative(archived),
            )

        status: dict[str, Any] = {
            "ts": decision.ts,
            "level": decision.level.value,
            "sub_status": decision.sub_status,
            "rule": decision.rule,
            "explanation": decision.explanation,
            "fire_score": local.fire_score,
            "smoke_score": local.smoke_score,
            "risk_level": decision.risk_level,
            "online": 1,
            "offline_reason": None,
        }
        if latest is not None:
            status["last_snapshot"] = self.relative(latest)
        v = decision.verdict
        if v is not None and v.ok:
            status["last_reasoning"] = v.reasoning
            status["last_llm_ts"] = decision.ts.isoformat(timespec="seconds")
        self.storage.upsert_camera_status(cam, **status)
        self._last_status_at[cam] = now
        self._offline.discard(cam)

        if decision.changed:
            self._handle_change(decision, event_id, photo)
        elif sub_changed:
            self._notify("on_sub_status_change", decision, photo)

    def _handle_change(self, decision: Decision, event_id: int | None, photo: Path | None) -> None:
        cam = decision.camera_id
        incident_id = self.storage.open_incident_id(cam)
        if decision.level == Level.BAHAYA and incident_id is None:
            incident_id = self.storage.open_incident(cam, decision.ts, decision.level.value, event_id)
            log.warning("%s: insiden #%d dibuka.", cam, incident_id)
            self._notify("on_incident_opened", incident_id, decision, photo)
        elif decision.level == Level.AMAN and incident_id is not None:
            self.storage.close_incident(incident_id, decision.ts)
            log.info("%s: insiden #%d ditutup.", cam, incident_id)
            self._notify("on_incident_closed", incident_id, decision)
        self._notify("on_level_change", decision, photo)

    def on_offline(self, camera_id: str, reason: str | None) -> None:
        if camera_id in self._offline:
            return
        self._offline.add(camera_id)
        self.storage.upsert_camera_status(camera_id, online=0, offline_reason=reason or "tidak ada frame")

    def _notify(self, method: str, *args: Any) -> None:
        for listener in self.listeners:
            handler = getattr(listener, method, None)
            if handler is None:
                continue
            try:
                handler(*args)
            except Exception:
                log.exception("Listener %s.%s gagal.", type(listener).__name__, method)
