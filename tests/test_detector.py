import sys
import time
from pathlib import Path

import numpy as np
import pytest

from mataklabat.camera import Frame
from mataklabat.config import Resources, Settings, now_local
from mataklabat.detector import (
    ColorMotionDetector,
    YoloDetector,
    create_detector,
    fire_mask,
    smoke_mask,
)

H, W = 480, 640
# BGR colors
FOREST = (40, 110, 30)  # dark green
FLAME_A = (0, 160, 255)  # orange
FLAME_B = (60, 200, 255)  # yellow-orange, ~30 gray levels brighter than FLAME_A
SMOKE = (165, 170, 170)  # light gray, low saturation
DUSK = (40, 120, 230)  # orange sky


def frame(image: np.ndarray, camera_id: str = "CAM-T") -> Frame:
    return Frame(camera_id, now_local(), image, 0)


def scene(color=FOREST, h=H, w=W) -> np.ndarray:
    return np.full((h, w, 3), color, dtype=np.uint8)


def flame_scene(flame_color, h=H, w=W) -> np.ndarray:
    img = scene(h=h, w=w)
    img[h // 2 : h // 2 + h // 4, w // 3 : w // 3 + w // 6] = flame_color  # ~4% of the frame
    return img


def run(detector, images, camera_id="CAM-T"):
    return [detector.detect(frame(img, camera_id)) for img in images]


def test_color_masks():
    assert fire_mask(scene(FLAME_A)).all()
    assert fire_mask(scene(FLAME_B)).all()
    assert not fire_mask(scene(FOREST)).any()
    assert not fire_mask(scene(SMOKE)).any()
    assert smoke_mask(scene(SMOKE)).all()
    assert not smoke_mask(scene(FOREST)).any()


def test_flickering_orange_scores_as_fire():
    det = ColorMotionDetector()
    results = run(det, [flame_scene(FLAME_A), flame_scene(FLAME_B)] * 3)
    assert results[0].fire_score == 0.0  # first frame has no motion reference
    assert all(r.fire_score > 0.15 for r in results[1:])
    assert any(b.label == "fire" for b in results[-1].boxes)


def test_static_green_scores_low():
    det = ColorMotionDetector()
    results = run(det, [scene(FOREST)] * 5)
    assert all(r.fire_score < 0.05 and r.smoke_score < 0.05 for r in results)


def test_static_orange_scores_low():
    """A still orange object (or sunset sky) does not move, so it is not fire."""
    det = ColorMotionDetector()
    for img in (flame_scene(FLAME_A), scene(DUSK)):
        det.reset()
        results = run(det, [img] * 5)
        assert all(r.fire_score < 0.05 for r in results)


def test_moving_gray_plume_scores_as_smoke():
    """A billowing plume: textured gray (S = 0, V 110-210) that changes every frame."""
    det = ColorMotionDetector()
    rng = np.random.default_rng(1)
    images = []
    for shift in range(0, 100, 20):
        img = scene()
        blocks = rng.integers(110, 211, (25, 25), dtype=np.uint8)
        texture = np.kron(blocks, np.ones((8, 8), dtype=np.uint8))  # 200x200, 8 px puffs
        img[150 - shift : 350 - shift, 200:400] = texture[..., None]
        images.append(img)
    results = run(det, images)
    assert results[-1].smoke_score > 0.20
    assert results[-1].fire_score < 0.05
    assert results[-1].boxes and results[-1].boxes[0].label == "smoke"


def test_boxes_are_in_original_resolution_and_capped():
    det = ColorMotionDetector()
    big_h, big_w = 720, 1280
    a, b = scene(h=big_h, w=big_w), scene(h=big_h, w=big_w)
    for i in range(7):  # seven separate flickering patches
        x = 40 + i * 170
        a[300:400, x : x + 80] = FLAME_A
        b[300:400, x : x + 80] = FLAME_B
    result = run(det, [a, b])[-1]
    assert 1 <= len(result.boxes) <= 5
    for box in result.boxes:
        assert 0 <= box.x and box.x + box.w <= big_w
        assert 0 <= box.y and box.y + box.h <= big_h
        assert box.w >= 70  # scaled back up from 640 px (patch is 80 px wide)


def test_motion_state_is_per_camera():
    det = ColorMotionDetector()
    det.detect(frame(flame_scene(FLAME_A), "CAM-A"))
    # First frame of another camera must not be compared against CAM-A.
    first_b = det.detect(frame(flame_scene(FLAME_B), "CAM-B"))
    assert first_b.fire_score == 0.0


def test_static_mode_scores_still_images():
    det = ColorMotionDetector(use_motion=False)
    result = det.detect(frame(flame_scene(FLAME_A)))
    assert result.fire_score > 0.15


def test_gains_scale_scores():
    imgs = [flame_scene(FLAME_A), flame_scene(FLAME_B)]
    low = run(ColorMotionDetector(fire_gain=1.0), imgs)[-1].fire_score
    high = run(ColorMotionDetector(fire_gain=10.0), imgs)[-1].fire_score
    assert high == pytest.approx(min(1.0, low * 10), rel=1e-6)


def test_speed_at_least_15_fps():
    det = ColorMotionDetector()
    rng = np.random.default_rng(0)
    images = [rng.integers(0, 256, (H, W, 3), dtype=np.uint8) for _ in range(10)]
    det.detect(frame(images[0]))
    n = 60
    start = time.perf_counter()
    for i in range(n):
        det.detect(frame(images[i % len(images)]))
    fps = n / (time.perf_counter() - start)
    assert fps >= 15, f"only {fps:.1f} FPS"


def test_create_detector_defaults_to_color_motion(tmp_path):
    settings = Settings(root=tmp_path, cameras=(), resources=Resources(), fire_gain=30.0)
    det = create_detector(settings)
    assert isinstance(det, ColorMotionDetector) and det.fire_gain == 30.0


def test_yolo_without_ultralytics_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "ultralytics", None)  # makes the import fail
    with pytest.raises(RuntimeError, match="pip install ultralytics"):
        YoloDetector(Path(tmp_path / "best.pt"))
