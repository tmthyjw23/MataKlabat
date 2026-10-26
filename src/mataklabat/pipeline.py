"""Monitor orchestration: one CameraWorker thread per camera (ARCHITECTURE §2-4)."""

from __future__ import annotations

import logging
import threading
import time
from enum import IntEnum
from typing import Callable, Protocol

from mataklabat.camera import Frame, open_source
from mataklabat.config import CameraConfig, Settings
from mataklabat.decision import Decision, DecisionEngine, Level
from mataklabat.detector import Detector, LocalDetection, create_detector
from mataklabat.prompts import PromptContext
from mataklabat.risk import RiskService
from mataklabat.vision_llm import RateLimiter, VisionVerifier

log = logging.getLogger(__name__)

STATUS_LOG_INTERVAL_S = 1.0


class Trigger(IntEnum):
    """Reasons to call the vision LLM (§4.3). Higher value = higher priority."""

    T3 = 1  # heartbeat
    T1 = 2  # persistent local signal
    T2 = 3  # recheck while WASPADA/BAHAYA


class LLMScheduler:
    """Global LLM queue: one shared rate limit, and a camera only gets a slot
    when no other camera is waiting with a higher-priority trigger."""

    def __init__(self, limiter: RateLimiter):
        self.limiter = limiter
        self._lock = threading.Lock()
        self._waiting: dict[str, Trigger] = {}

    def request(self, camera_id: str, trigger: Trigger) -> bool:
        with self._lock:
            self._waiting[camera_id] = trigger
            if trigger < max(self._waiting.values()):
                return False
            if not self.limiter.try_acquire():
                return False
            del self._waiting[camera_id]
            return True

    def withdraw(self, camera_id: str) -> None:
        with self._lock:
            self._waiting.pop(camera_id, None)


class DecisionSink(Protocol):
    """Receives every decision a worker makes (console, storage, ...)."""

    def on_decision(self, decision: Decision, local: LocalDetection, frame: Frame) -> None: ...

    def on_offline(self, camera_id: str, reason: str | None) -> None: ...


class ConsoleSink:
    """Prints one status line per camera about once a second, and every level change
    and LLM verdict at once."""

    def __init__(self, interval_s: float = STATUS_LOG_INTERVAL_S):
        self.interval_s = interval_s
        self._last_print: dict[str, float] = {}
        self._offline: set[str] = set()

    def on_decision(self, decision: Decision, local: LocalDetection, frame: Frame) -> None:
        cam = decision.camera_id
        if cam in self._offline:
            self._offline.discard(cam)
            log.info("%s kembali online.", cam)
        v = decision.verdict
        if v is not None:
            if v.ok:
                log.info(
                    "%s LLM: %s keyakinan=%.2f lookalike=%s risiko=%s (%s, %.1f dtk)",
                    cam, v.hazard_type, v.confidence, v.lookalike,
                    ",".join(v.risk_factors) or "-", v.prompt_version, v.latency_s,
                )
            else:
                log.warning("%s LLM gagal: %s", cam, v.error)
        if decision.changed:
            log.warning(
                "%s %s -> %s [%s] %s",
                cam, decision.level_from, decision.level, decision.rule, decision.explanation,
            )
        now = time.monotonic()
        if decision.changed or now - self._last_print.get(cam, 0.0) >= self.interval_s:
            self._last_print[cam] = now
            sub = f" ({decision.sub_status})" if decision.sub_status else ""
            log.info(
                "%s %-7s%s api=%.2f asap=%.2f T1=%s rule=%s",
                cam, decision.level, sub, local.fire_score, local.smoke_score,
                decision.trace["inputs"]["local"]["t1_hits"], decision.rule,
            )

    def on_offline(self, camera_id: str, reason: str | None) -> None:
        if camera_id not in self._offline:
            self._offline.add(camera_id)
            log.error("%s OFFLINE: %s", camera_id, reason or "tidak ada frame")


class CameraWorker(threading.Thread):
    def __init__(
        self,
        camera: CameraConfig,
        settings: Settings,
        sinks: list[DecisionSink],
        stop_event: threading.Event,
        detector_factory: Callable[..., Detector] = create_detector,
        verifier: VisionVerifier | None = None,
        scheduler: LLMScheduler | None = None,
        clock: Callable[[], float] = time.monotonic,
        risk: RiskService | None = None,
    ):
        super().__init__(name=f"worker-{camera.id}", daemon=True)
        self.camera = camera
        self.settings = settings
        self.sinks = sinks
        self.stop_event = stop_event
        self.source = open_source(camera)
        self.detector = detector_factory(settings, camera)
        self.engine = DecisionEngine(camera.id, settings)
        self.verifier = verifier if settings.llm_enabled else None
        self.scheduler = scheduler
        self.risk = risk
        self._clock = clock
        self._last_llm_at: float | None = None
        self._llm_failed = False
        self._last_still_checked: str | None = None
        self.last_decision: Decision | None = None

    @property
    def level(self) -> Level:
        return self.engine.level

    @property
    def llm_available(self) -> bool:
        return self.verifier is not None and self.scheduler is not None and not self._llm_failed

    def run(self) -> None:
        interval = 1.0 / self.settings.process_fps
        last_seq = -1
        self.source.start()
        try:
            while not self.stop_event.is_set():
                started = time.monotonic()
                frame = self.source.latest()
                if frame is None:
                    if not self.source.online and self.source.last_error is not None:
                        self._emit_offline()
                elif frame.seq != last_seq:
                    last_seq = frame.seq
                    self.step(frame)
                self.stop_event.wait(max(0.0, interval - (time.monotonic() - started)))
        except Exception:
            log.exception("%s: worker berhenti karena error.", self.camera.id)
            raise
        finally:
            if self.scheduler is not None:
                self.scheduler.withdraw(self.camera.id)
            self.source.stop()

    def step(self, frame: Frame) -> Decision:
        local = self.detector.detect(frame)
        self.engine.observe(local)
        snapshot = self.risk.current() if self.risk is not None else None
        verdict = self._maybe_verify(frame, local, snapshot)
        decision = self.engine.update(
            local,
            verdict=verdict,
            llm_available=self.llm_available,
            risk_level=snapshot.level if snapshot else None,
            fwi=snapshot.fwi if snapshot else None,
        )
        self.last_decision = decision
        for sink in self.sinks:
            try:
                sink.on_decision(decision, local, frame)
            except Exception:
                log.exception("%s: sink %s gagal.", self.camera.id, type(sink).__name__)
        return decision

    def due_trigger(self, frame: Frame | None = None) -> Trigger | None:
        """Highest-priority trigger that is due for this camera (§4.3).

        On a photo camera a photo that has not been checked yet counts as T1 right away
        (Spec §5.2), without waiting for RECHECK_S.
        """
        s = self.settings
        new_photo = frame is not None and frame.still_id is not None and frame.still_id != self._last_still_checked
        since = None if self._last_llm_at is None else self._clock() - self._last_llm_at
        recheck_due = since is None or since >= s.recheck_s
        if self.engine.level != Level.AMAN and recheck_due:
            return Trigger.T2
        if new_photo or (self.engine.t1.active and recheck_due):
            return Trigger.T1
        if s.heartbeat_s > 0 and (since is None or since >= s.heartbeat_s):
            return Trigger.T3
        return None

    def _maybe_verify(self, frame: Frame, local: LocalDetection, snapshot=None):
        if self.verifier is None or self.scheduler is None:
            return None
        trigger = self.due_trigger(frame)
        if trigger is None:
            self.scheduler.withdraw(self.camera.id)
            return None
        if not self.scheduler.request(self.camera.id, trigger):
            return None
        if frame.still_id is not None:
            self._last_still_checked = frame.still_id
        ctx = PromptContext(
            camera_name=self.camera.name,
            facing_deg=self.camera.facing_deg,
            local_time=frame.ts,
            fire_score=local.fire_score,
            smoke_score=local.smoke_score,
            temp_c=snapshot.now_temp_c if snapshot else None,
            rh_pct=snapshot.now_rh_pct if snapshot else None,
            wind_kmh=snapshot.now_wind_kmh if snapshot else None,
        )
        verdict = self.verifier.verify(frame, ctx, limit=False)
        self._last_llm_at = self._clock()
        self._llm_failed = not verdict.ok
        log.debug("%s memanggil LLM karena %s.", self.camera.id, trigger.name)
        return verdict

    def _emit_offline(self) -> None:
        for sink in self.sinks:
            sink.on_offline(self.camera.id, self.source.last_error)


class Monitor:
    """Starts every camera worker and stops them all cleanly on Ctrl+C.

    `services` are background helpers with start()/stop() (risk refresh, outbox
    sender, housekeeping); they start before the cameras and stop after them.
    """

    def __init__(
        self,
        settings: Settings,
        sinks: list[DecisionSink] | None = None,
        verifier: VisionVerifier | None = None,
        risk: RiskService | None = None,
        services: list | None = None,
    ):
        self.settings = settings
        self.risk = risk
        self.services = ([risk] if risk is not None else []) + list(services or [])
        self.stop_event = threading.Event()
        self.sinks = sinks if sinks is not None else [ConsoleSink()]
        if settings.llm_enabled and verifier is None:
            verifier = VisionVerifier(settings)
        self.verifier = verifier
        scheduler = LLMScheduler(verifier.limiter) if verifier is not None else None
        self.workers = [
            CameraWorker(
                cam, settings, self.sinks, self.stop_event,
                verifier=verifier, scheduler=scheduler, risk=risk,
            )
            for cam in settings.cameras
        ]

    def start(self) -> None:
        for service in self.services:
            service.start()
        for worker in self.workers:
            worker.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        deadline = time.monotonic() + timeout
        for worker in self.workers:
            worker.join(max(0.0, deadline - time.monotonic()))
        alive = [w.camera.id for w in self.workers if w.is_alive()]
        if alive:
            log.warning("Worker belum berhenti: %s", ", ".join(alive))
        for service in reversed(self.services):
            try:
                service.stop()
            except Exception:
                log.exception("Gagal menghentikan %s.", type(service).__name__)

    def run_forever(self, duration_s: float | None = None) -> None:
        """Block until Ctrl+C, or until `duration_s` seconds have passed."""
        self.start()
        log.info("Pemantauan berjalan untuk %d kamera. Tekan Ctrl+C untuk berhenti.", len(self.workers))
        deadline = time.monotonic() + duration_s if duration_s else None
        try:
            # Short waits keep the main thread responsive to Ctrl+C on Windows.
            while not self.stop_event.wait(0.5):
                if not any(w.is_alive() for w in self.workers):
                    log.error("Semua worker berhenti.")
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    log.info("Durasi %.0f detik tercapai.", duration_s)
                    break
        except KeyboardInterrupt:
            log.info("Ctrl+C diterima, menghentikan semua kamera...")
        finally:
            self.stop()
            log.info("Pemantauan berhenti.")
