"""Operator control of cameras: on/off and the demo photo gallery.

The choices live in their own small database (control.db). The web process is
its only writer; the monitor only reads it, so events.db keeps a single writer.
A camera without a row follows `enabled:` in cameras.yaml.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import cv2

from mataklabat.camera import PHOTO_EXTENSIONS, read_image
from mataklabat.config import CameraConfig, Settings, now_local
from mataklabat.storage import _connect, iso

log = logging.getLogger(__name__)

CONTROL_SCHEMA = """
CREATE TABLE IF NOT EXISTS camera_control (
  camera_id TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL,
  updated_ts TEXT NOT NULL,
  updated_by TEXT
);
"""
POLL_S = 1.0
DEMO_PREFIX = "_demo_"  # photos the web copies into a photo camera's folder


class CameraControl:
    """Reads (and, for the web, writes) the operator's on/off choice per camera."""

    def __init__(self, path: Path, cameras: tuple[CameraConfig, ...], writable: bool = False):
        self.path = Path(path)
        self.defaults = {c.id: c.enabled for c in cameras}
        self.writable = writable
        self._lock = threading.Lock()
        if writable:
            with self._write() as c:
                c.executescript(CONTROL_SCHEMA)

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        conn = _connect(self.path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rows(self) -> dict[str, dict[str, Any]]:
        """Stored choices by camera id; empty when nothing was chosen yet."""
        if not self.path.is_file():
            return {}
        try:
            conn = _connect(self.path, readonly=True)
        except sqlite3.Error:
            return {}
        try:
            return {r["camera_id"]: dict(r) for r in conn.execute("SELECT * FROM camera_control")}
        except sqlite3.OperationalError:
            return {}  # table not created yet
        finally:
            conn.close()

    def states(self) -> dict[str, bool]:
        stored = self.rows()
        return {
            cam_id: bool(stored[cam_id]["enabled"]) if cam_id in stored else default
            for cam_id, default in self.defaults.items()
        }

    def set_enabled(self, camera_id: str, enabled: bool, by: str = "operator") -> None:
        if not self.writable:
            raise PermissionError("CameraControl ini hanya-baca")
        if camera_id not in self.defaults:
            raise KeyError(camera_id)
        with self._lock, self._write() as c:
            c.execute(
                "INSERT INTO camera_control (camera_id, enabled, updated_ts, updated_by) VALUES (?,?,?,?)"
                " ON CONFLICT(camera_id) DO UPDATE SET enabled=excluded.enabled,"
                " updated_ts=excluded.updated_ts, updated_by=excluded.updated_by",
                (camera_id, int(enabled), iso(), by),
            )
        log.info("%s %s oleh %s.", camera_id, "diaktifkan" if enabled else "dinonaktifkan", by)


class ControlWatcher:
    """Monitor side: polls control.db about once a second so workers can ask cheaply."""

    def __init__(self, control: CameraControl, interval_s: float = POLL_S):
        self.control = control
        self.interval_s = interval_s
        self._states = dict(control.defaults)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.refresh()

    def refresh(self) -> None:
        try:
            self._states = self.control.states()
        except Exception:
            log.exception("Gagal membaca pilihan operator; memakai keadaan terakhir.")

    def enabled(self, camera_id: str) -> bool:
        return self._states.get(camera_id, True)

    def start(self) -> ControlWatcher:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="control", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.refresh()


# --- demo photo gallery --------------------------------------------------------------------


def gallery_photos(settings: Settings) -> list[Path]:
    """Photos an operator may show on a photo camera, sorted by name."""
    folder = settings.gallery_dir
    if folder is None or not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in PHOTO_EXTENSIONS),
        key=lambda p: p.name.lower(),
    )


def gallery_photo(settings: Settings, name: str) -> Path | None:
    """The gallery photo with exactly this file name; never a path from the request."""
    for path in gallery_photos(settings):
        if path.name == name:
            return path
    return None


THUMB_WIDTH = 320
_thumbs: dict[tuple[str, int], bytes] = {}


def thumbnail(photo: Path) -> bytes | None:
    """Small JPEG of a gallery photo, so the gallery loads quickly on a phone."""
    key = (str(photo), photo.stat().st_mtime_ns)
    if key not in _thumbs:
        image = read_image(photo)
        if image is None:
            return None
        h, w = image.shape[:2]
        if w > THUMB_WIDTH:
            image = cv2.resize(image, (THUMB_WIDTH, max(1, round(h * THUMB_WIDTH / w))), interpolation=cv2.INTER_AREA)
        ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return None
        _thumbs[key] = data.tobytes()
    return _thumbs[key]


def show_photo(camera: CameraConfig, photo: Path) -> Path:
    """Make `photo` the newest image in a photo camera's folder.

    Written to a temporary name and renamed, so the camera never reads half a file.
    Earlier demo copies are removed; the folder's own photos stay.
    """
    if not camera.is_photo:
        raise ValueError(f"{camera.id} bukan kamera mode foto")
    folder = Path(str(camera.source))
    folder.mkdir(parents=True, exist_ok=True)
    stamp = now_local().strftime("%Y%m%d-%H%M%S")
    target = folder / f"{DEMO_PREFIX}{stamp}_{photo.name}"
    tmp = folder / f".{target.name}.tmp"
    shutil.copyfile(photo, tmp)
    now = time.time()
    os.utime(tmp, (now, now))
    os.replace(tmp, target)
    for old in folder.glob(f"{DEMO_PREFIX}*"):
        if old != target:
            try:
                old.unlink()
            except OSError:
                log.warning("Foto demo lama tidak bisa dihapus: %s", old.name)
    return target


def shown_photo(camera: CameraConfig) -> str | None:
    """Gallery name of the demo photo a photo camera shows now, if any."""
    folder = Path(str(camera.source))
    if not camera.is_photo or not folder.is_dir():
        return None
    copies = sorted(folder.glob(f"{DEMO_PREFIX}*"), key=lambda p: p.stat().st_mtime_ns)
    if not copies:
        return None
    # _demo_YYYYMMDD-HHMMSS_<name>
    return copies[-1].name.split("_", 3)[-1]
