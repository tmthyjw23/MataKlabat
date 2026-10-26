"""Monitor orchestration: one CameraWorker thread per camera (ARCHITECTURE §2-3)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Protocol

from mataklabat.camera import CameraSource, Frame
from mataklabat.config import CameraConfig, Settings
from mataklabat.decision import Decision, DecisionEngine, Level
from mataklabat.detector import Detector, LocalDetection, create_detector

log = logging.getLogger(__name__)

STATUS_LOG_INTERVAL_S = 1.0


class DecisionSink(Protocol):
    """Receives every decision a worker makes (console, storage, ...)."""

    def on_decision(self, decision: Decision, local: LocalDetection, frame: Frame) -> None: ...

    def on_offline(self, camera_id: str, reason: str | None) -> None: ...


class ConsoleSink:
    """Prints one status line per camera about once a second, and every level change at once."""

    def __init__(self, interval_s: float = STATUS_LOG_INTERVAL_S):
        self.interval_s = interval_s
        self._last_print: dict[str, float] = {}
        self._offline: set[str] = set()

    def on_decision(self, decision: Decision, local: LocalDetection, frame: Frame) -> None:
        cam = decision.camera_id
        if cam in self._offline:
            self._offline.discard(cam)
            log.info("%s kembali online.", cam)
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
        detector_factory: Callable[[Settings], Detector] = create_detector,
    ):
        super().__init__(name=f"worker-{camera.id}", daemon=True)
        self.camera = camera
        self.settings = settings
        self.sinks = sinks
        self.stop_event = stop_event
        self.source = CameraSource(camera)
        self.detector = detector_factory(settings)
        self.engine = DecisionEngine(camera.id, settings)
        self.last_decision: Decision | None = None

    @property
    def level(self) -> Level:
        return self.engine.level

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
            self.source.stop()

    def step(self, frame: Frame) -> Decision:
        local = self.detector.detect(frame)
        # TODO(T5/T6): call Gemini on triggers T1-T3; until then the LLM is unavailable.
        decision = self.engine.update(local, llm_available=False)
        self.last_decision = decision
        for sink in self.sinks:
            try:
                sink.on_decision(decision, local, frame)
            except Exception:
                log.exception("%s: sink %s gagal.", self.camera.id, type(sink).__name__)
        return decision

    def _emit_offline(self) -> None:
        for sink in self.sinks:
            sink.on_offline(self.camera.id, self.source.last_error)


class Monitor:
    """Starts every camera worker and stops them all cleanly on Ctrl+C."""

    def __init__(self, settings: Settings, sinks: list[DecisionSink] | None = None):
        self.settings = settings
        self.stop_event = threading.Event()
        self.sinks = sinks if sinks is not None else [ConsoleSink()]
        self.workers = [
            CameraWorker(cam, settings, self.sinks, self.stop_event) for cam in settings.cameras
        ]

    def start(self) -> None:
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
