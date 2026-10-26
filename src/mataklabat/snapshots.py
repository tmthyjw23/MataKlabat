"""Snapshot JPEGs: the latest frame per camera (overwritten) and an archive for WASPADA+."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from mataklabat.detector import Box

log = logging.getLogger(__name__)

MAX_WIDTH = 960
JPEG_QUALITY = 82
BOX_COLORS = {"fire": (40, 60, 230), "smoke": (22, 115, 249)}  # BGR: red-ish / orange


def annotate(image: np.ndarray, boxes: tuple[Box, ...], ts: datetime, scores: dict[str, float] | None = None) -> np.ndarray:
    """Copy of the frame with detection boxes and a WITA timestamp, resized to <= MAX_WIDTH."""
    out = image.copy()
    for box in boxes:
        color = BOX_COLORS.get(box.label, (0, 200, 255))
        cv2.rectangle(out, (box.x, box.y), (box.x + box.w, box.y + box.h), color, 3)
        label = "api" if box.label == "fire" else "asap"
        if scores and box.label in scores:
            label = f"{label} {scores[box.label]:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        y = max(th + 6, box.y)
        cv2.rectangle(out, (box.x, y - th - 6), (box.x + tw + 8, y), color, -1)
        cv2.putText(out, label, (box.x + 4, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2, cv2.LINE_AA)

    h, w = out.shape[:2]
    if w > MAX_WIDTH:
        out = cv2.resize(out, (MAX_WIDTH, round(h * MAX_WIDTH / w)), interpolation=cv2.INTER_AREA)
        h, w = out.shape[:2]
    stamp = ts.strftime("%d-%m-%Y %H:%M:%S WITA")
    (tw, th), _ = cv2.getTextSize(stamp, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    cv2.rectangle(out, (w - tw - 16, h - th - 14), (w, h), (20, 20, 20), -1)
    cv2.putText(out, stamp, (w - tw - 8, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1, cv2.LINE_AA)
    return out


class SnapshotStore:
    def __init__(self, root: Path, archive_max_mb: float = 500.0):
        self.root = Path(root)
        self.archive_max_bytes = int(archive_max_mb * 1024 * 1024)

    def latest_path(self, camera_id: str) -> Path:
        return self.root / camera_id / "latest.jpg"

    def save_latest(self, camera_id: str, image: np.ndarray) -> Path | None:
        path = self.latest_path(camera_id)
        return path if self._write(path, image) else None

    def archive(self, camera_id: str, image: np.ndarray, ts: datetime) -> Path | None:
        path = self.root / camera_id / "archive" / f"{ts.strftime('%Y%m%d-%H%M%S-%f')}.jpg"
        return path if self._write(path, image) else None

    def prune_archive(self) -> int:
        """Delete the oldest archived snapshots until the archive fits the size limit."""
        files = sorted(self.root.glob("*/archive/*.jpg"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        removed = 0
        for path in files:
            if total <= self.archive_max_bytes:
                break
            size = path.stat().st_size
            try:
                path.unlink()
            except OSError:
                continue
            total -= size
            removed += 1
        return removed

    def _write(self, path: Path, image: np.ndarray) -> bool:
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_bytes(buf.tobytes())
            # Atomic replace, so the web never serves half a file. On Windows this can
            # fail while a reader holds the file; the next frame simply tries again.
            os.replace(tmp, path)
            return True
        except OSError as exc:
            log.debug("Snapshot %s belum bisa ditulis: %s", path, exc)
            return False
