"""Camera input: webcam index, looping video file, or RTSP/HTTP stream.

A background thread keeps only the most recent frame, so slow consumers never
fall behind the live feed.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from mataklabat.config import CameraConfig, now_local

log = logging.getLogger(__name__)

STALE_AFTER_S = 5.0
RECONNECT_DELAY_S = 2.0
DEFAULT_VIDEO_FPS = 25.0


@dataclass(frozen=True)
class Frame:
    camera_id: str
    ts: datetime  # aware, Asia/Makassar
    image: np.ndarray  # BGR
    seq: int  # increases by one for every frame read


class CameraSource:
    def __init__(
        self,
        camera: CameraConfig,
        *,
        stale_after_s: float = STALE_AFTER_S,
        reconnect_delay_s: float = RECONNECT_DELAY_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.camera = camera
        self.stale_after_s = stale_after_s
        self.reconnect_delay_s = reconnect_delay_s
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: Frame | None = None
        self._last_frame_at: float | None = None
        self._seq = 0
        self.last_error: str | None = None

    @property
    def camera_id(self) -> str:
        return self.camera.id

    @property
    def is_file(self) -> bool:
        source = self.camera.source
        return isinstance(source, str) and "://" not in source

    @property
    def online(self) -> bool:
        with self._lock:
            last = self._last_frame_at
        return last is not None and self._clock() - last <= self.stale_after_s

    def latest(self) -> Frame | None:
        """Most recent frame, or None if nothing has been read or the feed went stale."""
        if not self.online:
            return None
        with self._lock:
            return self._latest

    def start(self) -> CameraSource:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name=f"camera-{self.camera.id}", daemon=True
            )
            self._thread.start()
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def __enter__(self) -> CameraSource:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _open(self) -> cv2.VideoCapture | None:
        source = self.camera.source
        if self.is_file and not Path(source).is_file():
            self._fail(f"file video tidak ditemukan: {source}")
            return None
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            cap.release()
            self._fail(f"sumber tidak bisa dibuka: {source}")
            return None
        self.last_error = None
        log.info("Kamera %s terhubung (%s).", self.camera.id, source)
        return cap

    def _fail(self, message: str) -> None:
        if message != self.last_error:
            log.warning("Kamera %s: %s", self.camera.id, message)
        self.last_error = message

    def _run(self) -> None:
        cap: cv2.VideoCapture | None = None
        try:
            while not self._stop.is_set():
                if cap is None:
                    cap = self._open()
                    if cap is None:
                        self._stop.wait(self.reconnect_delay_s)
                        continue
                    fps = cap.get(cv2.CAP_PROP_FPS) if self.is_file else 0.0
                    frame_interval = 1.0 / (fps if 1.0 <= fps <= 120.0 else DEFAULT_VIDEO_FPS)

                started = time.monotonic()
                ok, image = cap.read()
                if not ok or image is None:
                    if self.is_file:
                        # End of file: rewind so the video behaves like a live camera.
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ok, image = cap.read()
                    if not ok or image is None:
                        self._fail("gagal membaca frame, mencoba menyambung ulang")
                        cap.release()
                        cap = None
                        self._stop.wait(self.reconnect_delay_s)
                        continue

                self._publish(image)
                if self.is_file:
                    # Play files at their native speed instead of as fast as possible.
                    self._stop.wait(max(0.0, frame_interval - (time.monotonic() - started)))
        finally:
            if cap is not None:
                cap.release()

    def _publish(self, image: np.ndarray) -> None:
        with self._lock:
            self._seq += 1
            self._latest = Frame(self.camera.id, now_local(), image, self._seq)
            self._last_frame_at = self._clock()
