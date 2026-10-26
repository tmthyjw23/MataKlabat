"""Camera input: webcam index, looping video file, RTSP/HTTP stream, or a photo folder.

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
    still_id: str | None = None  # photo cameras: identifies the photo shown (name + mtime)


class FrameSource:
    """Shared plumbing: a reader thread publishes frames, consumers take the latest."""

    thread_prefix = "camera"

    def __init__(
        self,
        camera: CameraConfig,
        *,
        stale_after_s: float = STALE_AFTER_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.camera = camera
        self.stale_after_s = stale_after_s
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

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name=f"{self.thread_prefix}-{self.camera.id}", daemon=True
            )
            self._thread.start()
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _fail(self, message: str) -> None:
        if message != self.last_error:
            log.warning("Kamera %s: %s", self.camera.id, message)
        self.last_error = message

    def _run(self) -> None:
        raise NotImplementedError


class CameraSource(FrameSource):
    """Webcam index, looping video file, or stream URL."""

    def __init__(
        self,
        camera: CameraConfig,
        *,
        stale_after_s: float = STALE_AFTER_S,
        reconnect_delay_s: float = RECONNECT_DELAY_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(camera, stale_after_s=stale_after_s, clock=clock)
        self.reconnect_delay_s = reconnect_delay_s

    @property
    def is_file(self) -> bool:
        source = self.camera.source
        return isinstance(source, str) and "://" not in source

    def _open(self) -> cv2.VideoCapture | None:
        source = self.camera.source
        if self.is_file and not Path(source).is_file():
            self._fail(f"file video tidak ditemukan: {_short(source)}")
            return None
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            cap.release()
            self._fail(f"sumber tidak bisa dibuka: {_short(source)}")
            return None
        self.last_error = None
        log.info("Kamera %s terhubung (%s).", self.camera.id, source)
        return cap

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


PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
PHOTO_SCAN_S = 1.0


class FolderSource(FrameSource):
    """A "photo camera": always shows the newest image in a folder (Spec §5.2).

    Dropping a new photo into the folder makes it the next frame within about a
    second. The same photo is re-published every scan so the camera stays online.
    """

    thread_prefix = "photos"

    def __init__(
        self,
        camera: CameraConfig,
        *,
        scan_s: float = PHOTO_SCAN_S,
        stale_after_s: float = STALE_AFTER_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(camera, stale_after_s=stale_after_s, clock=clock)
        self.folder = Path(str(camera.source))
        self.scan_s = scan_s
        self._current_id: str | None = None
        self._current_image: np.ndarray | None = None

    def scan_once(self) -> None:
        newest = self._newest_photo()
        if newest is None:
            return
        path, photo_id = newest
        if photo_id != self._current_id:
            image = _read_image(path)
            if image is None:
                # Probably still being copied; try again on the next scan.
                log.debug("Kamera %s: %s belum bisa dibaca.", self.camera.id, path.name)
                if self._current_image is None:
                    return
            else:
                self._current_id, self._current_image = photo_id, image
                self.last_error = None
                log.info("Kamera %s: foto baru %s.", self.camera.id, path.name)
        with self._lock:
            self._seq += 1
            self._latest = Frame(self.camera.id, now_local(), self._current_image, self._seq, self._current_id)
            self._last_frame_at = self._clock()

    def _newest_photo(self) -> tuple[Path, str] | None:
        if not self.folder.is_dir():
            self._fail(f"folder foto tidak ditemukan: {_short(self.folder)}")
            return None
        photos = [p for p in self.folder.iterdir() if p.is_file() and p.suffix.lower() in PHOTO_EXTENSIONS]
        if not photos:
            self._fail(f"folder belum berisi foto: {_short(self.folder)}")
            return None
        newest = max(photos, key=lambda p: p.stat().st_mtime_ns)
        return newest, f"{newest.name}@{newest.stat().st_mtime_ns}"

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except OSError as exc:
                self._fail(f"gagal membaca folder foto: {exc}")
            self._stop.wait(self.scan_s)


def _read_image(path: Path) -> np.ndarray | None:
    # np.fromfile + imdecode also works for non-ASCII paths on Windows, unlike cv2.imread.
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _short(source: int | str | Path) -> str:
    """Last two path parts (e.g. videos/cam02.mp4), so messages stay readable on the web."""
    if isinstance(source, int) or "://" in str(source):
        return str(source)
    parts = Path(source).parts
    return "/".join(parts[-2:])


def open_source(camera: CameraConfig) -> CameraSource | FolderSource:
    return FolderSource(camera) if camera.is_photo else CameraSource(camera)
