"""Stage 1: cheap per-frame fire/smoke scoring (ARCHITECTURE §4).

`ColorMotionDetector` is deliberately sensitive: fog and dust also trigger the
smoke mask. Stage 2 (vision LLM) is responsible for rejecting those lookalikes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

import cv2
import numpy as np

from mataklabat.camera import Frame
from mataklabat.config import Settings

log = logging.getLogger(__name__)

PROCESS_WIDTH = 640

# §4.1 color thresholds (OpenCV HSV: H 0-179, S/V 0-255)
FIRE_HSV_LOW = np.array([0, 120, 180], dtype=np.uint8)
FIRE_HSV_HIGH = np.array([35, 255, 255], dtype=np.uint8)
FIRE_MIN_RED = 190
SMOKE_HSV_LOW = np.array([0, 0, 90], dtype=np.uint8)
SMOKE_HSV_HIGH = np.array([179, 60, 220], dtype=np.uint8)
MOTION_THRESHOLD = 20
MAX_BOXES = 5
MIN_BOX_AREA_FRAC = 0.002

_BLUR_KSIZE = (5, 5)
_DILATE_KERNEL = np.ones((5, 5), dtype=np.uint8)


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int
    label: Literal["fire", "smoke"]


@dataclass(frozen=True)
class LocalDetection:
    camera_id: str
    ts: datetime
    fire_score: float
    smoke_score: float
    boxes: tuple[Box, ...] = ()
    detector: str = "color_motion"


class Detector(Protocol):
    def detect(self, frame: Frame) -> LocalDetection: ...


class ColorMotionDetector:
    """HSV color masks gated by frame-to-frame motion (§4.1).

    Keeps the previous grayscale frame per camera, so one instance can serve
    several cameras. With `use_motion=False` the motion gate is skipped, which
    is only meant for scoring still images in offline evaluation.
    """

    name = "color_motion"

    def __init__(self, fire_gain: float = 25.0, smoke_gain: float = 8.0, use_motion: bool = True):
        self.fire_gain = fire_gain
        self.smoke_gain = smoke_gain
        self.use_motion = use_motion
        self._prev_gray: dict[str, np.ndarray] = {}

    def reset(self, camera_id: str | None = None) -> None:
        if camera_id is None:
            self._prev_gray.clear()
        else:
            self._prev_gray.pop(camera_id, None)

    def detect(self, frame: Frame) -> LocalDetection:
        image, scale = _resize_to_width(frame.image, PROCESS_WIDTH)
        fire = fire_mask(image)
        smoke = smoke_mask(image)

        if self.use_motion:
            motion = self._motion_mask(frame.camera_id, image)
            if motion is None:  # first frame of this camera: nothing to compare with
                return LocalDetection(frame.camera_id, frame.ts, 0.0, 0.0, (), self.name)
            fire = cv2.bitwise_and(fire, motion)
            smoke = cv2.bitwise_and(smoke, motion)

        total = float(fire.size)
        fire_score = _clip01(cv2.countNonZero(fire) / total * self.fire_gain)
        smoke_score = _clip01(cv2.countNonZero(smoke) / total * self.smoke_gain)
        boxes = _boxes(fire, smoke, scale)
        return LocalDetection(frame.camera_id, frame.ts, fire_score, smoke_score, boxes, self.name)

    def _motion_mask(self, camera_id: str, image: np.ndarray) -> np.ndarray | None:
        gray = cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), _BLUR_KSIZE, 0)
        prev = self._prev_gray.get(camera_id)
        self._prev_gray[camera_id] = gray
        if prev is None or prev.shape != gray.shape:
            return None
        diff = cv2.absdiff(gray, prev)
        _, motion = cv2.threshold(diff, MOTION_THRESHOLD, 255, cv2.THRESH_BINARY)
        return cv2.dilate(motion, _DILATE_KERNEL, iterations=2)


class YoloDetector:
    """Optional fire/smoke YOLO model (§4.2). Same interface as ColorMotionDetector."""

    name = "yolo"

    def __init__(self, weights: Path, min_conf: float = 0.10):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "YOLO_WEIGHTS diisi tetapi paket ultralytics belum terpasang. "
                "Jalankan `pip install ultralytics` atau kosongkan YOLO_WEIGHTS."
            ) from exc
        if not Path(weights).is_file():
            raise RuntimeError(f"File bobot YOLO tidak ditemukan: {weights}")
        self.model = YOLO(str(weights))
        self.min_conf = min_conf

    def detect(self, frame: Frame) -> LocalDetection:
        result = self.model(frame.image, verbose=False)[0]
        scores = {"fire": 0.0, "smoke": 0.0}
        boxes: list[tuple[float, Box]] = []
        for xyxy, conf, cls in zip(
            result.boxes.xyxy.tolist(), result.boxes.conf.tolist(), result.boxes.cls.tolist()
        ):
            label = _yolo_label(self.model.names[int(cls)])
            if label is None or conf < self.min_conf:
                continue
            scores[label] = max(scores[label], float(conf))
            x1, y1, x2, y2 = (int(v) for v in xyxy)
            boxes.append((conf, Box(x1, y1, x2 - x1, y2 - y1, label)))
        boxes.sort(key=lambda item: item[0], reverse=True)
        return LocalDetection(
            frame.camera_id,
            frame.ts,
            scores["fire"],
            scores["smoke"],
            tuple(b for _, b in boxes[:MAX_BOXES]),
            self.name,
        )


def create_detector(settings: Settings) -> Detector:
    if settings.yolo_weights is not None:
        log.info("Memakai YoloDetector (%s).", settings.yolo_weights)
        return YoloDetector(settings.yolo_weights)
    return ColorMotionDetector(settings.fire_gain, settings.smoke_gain)


def fire_mask(image: np.ndarray) -> np.ndarray:
    """Flame-colored pixels: HSV orange/yellow range plus R > G > B and bright red."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, FIRE_HSV_LOW, FIRE_HSV_HIGH)
    b, g, r = cv2.split(image)
    rgb_rule = (r > g) & (g > b) & (r >= FIRE_MIN_RED)
    return cv2.bitwise_and(mask, rgb_rule.astype(np.uint8) * 255)


def smoke_mask(image: np.ndarray) -> np.ndarray:
    """Light-to-medium gray pixels (low saturation)."""
    return cv2.inRange(cv2.cvtColor(image, cv2.COLOR_BGR2HSV), SMOKE_HSV_LOW, SMOKE_HSV_HIGH)


def _resize_to_width(image: np.ndarray, width: int) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    if w == width:
        return image, 1.0
    scale = width / w
    resized = cv2.resize(image, (width, max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    return resized, scale


def _boxes(fire: np.ndarray, smoke: np.ndarray, scale: float) -> tuple[Box, ...]:
    combined = cv2.bitwise_or(fire, smoke)
    # Connected components instead of findContours: one pass over the mask, so a
    # noisy frame with thousands of specks stays fast.
    _, _, stats, _ = cv2.connectedComponentsWithStats(combined, connectivity=8)
    stats = stats[1:]  # row 0 is the background
    areas = stats[:, cv2.CC_STAT_AREA]
    keep = np.flatnonzero(areas >= MIN_BOX_AREA_FRAC * combined.size)
    largest = keep[np.argsort(areas[keep])[::-1][:MAX_BOXES]]
    boxes = []
    for i in largest:
        x, y, w, h = (int(v) for v in stats[i, :4])
        n_fire = cv2.countNonZero(fire[y : y + h, x : x + w])
        n_smoke = cv2.countNonZero(smoke[y : y + h, x : x + w])
        boxes.append(
            Box(
                x=round(x / scale),
                y=round(y / scale),
                w=round(w / scale),
                h=round(h / scale),
                label="fire" if n_fire >= n_smoke else "smoke",
            )
        )
    return tuple(boxes)


def _yolo_label(class_name: str) -> Literal["fire", "smoke"] | None:
    name = class_name.lower()
    if "fire" in name or "flame" in name:
        return "fire"
    if "smoke" in name:
        return "smoke"
    return None


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, value))
