import _thread
import logging
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from mataklabat.config import CameraConfig, Resources, Settings
from mataklabat.decision import Level
from mataklabat.pipeline import CameraWorker, ConsoleSink, Monitor

FPS = 20
FOREST = (40, 110, 30)
FLAMES = ((0, 120, 230), (0, 160, 255), (60, 200, 255))  # gray levels ~140 / ~170 / ~200


def make_fire_then_forest_video(path: Path, fire_s: float = 1.5, forest_s: float = 2.5) -> Path:
    """Flicker must be irregular, like real flames: a periodic A/B flicker sampled at
    PROCESS_FPS can alias to the same color every time and show no motion at all."""
    rng = np.random.default_rng(7)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (160, 120))
    for i in range(int((fire_s + forest_s) * FPS)):
        img = np.full((120, 160, 3), FOREST, dtype=np.uint8)
        if i < fire_s * FPS:
            top = int(rng.integers(30, 60))  # flame height changes every frame
            img[top:90, 60:100] = FLAMES[int(rng.integers(len(FLAMES)))]
        writer.write(img)
    writer.release()
    return path


class RecordingSink:
    def __init__(self):
        self.decisions = []
        self.offline = []

    def on_decision(self, decision, local, frame):
        self.decisions.append(decision)

    def on_offline(self, camera_id, reason):
        self.offline.append((camera_id, reason))


def settings_for(tmp_path, *cameras, **overrides) -> Settings:
    return Settings(root=tmp_path, cameras=cameras, resources=Resources(), **overrides)


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_worker_raises_waspada_then_clears(tmp_path):
    video = make_fire_then_forest_video(tmp_path / "fire.avi")
    cam = CameraConfig("CAM-T", "Test", str(video), 1.4, 125.0)
    settings = settings_for(tmp_path, cam, process_fps=10.0)
    sink, stop = RecordingSink(), threading.Event()
    worker = CameraWorker(cam, settings, [sink], stop)
    worker.start()
    try:

        def saw_waspada_then_aman():
            levels = [d.level for d in sink.decisions]
            if Level.WASPADA not in levels:
                return False
            return Level.AMAN in levels[levels.index(Level.WASPADA):]

        assert wait_for(saw_waspada_then_aman), [d.rule for d in sink.decisions]
    finally:
        stop.set()
        worker.join(3)
    assert not worker.is_alive()
    raised = next(d for d in sink.decisions if d.changed and d.level == Level.WASPADA)
    assert raised.rule == "R4" and raised.sub_status == "unverified"
    cleared = next(d for d in sink.decisions if d.changed and d.level == Level.AMAN)
    assert cleared.rule == "R6"


def test_worker_reports_offline_camera(tmp_path):
    cam = CameraConfig("CAM-X", "Missing", str(tmp_path / "none.mp4"), 1.4, 125.0)
    sink, stop = RecordingSink(), threading.Event()
    worker = CameraWorker(cam, settings_for(tmp_path, cam), [sink], stop)
    worker.start()
    try:
        assert wait_for(lambda: sink.offline, timeout=5)
    finally:
        stop.set()
        worker.join(3)
    assert sink.offline[0][0] == "CAM-X" and "tidak ditemukan" in sink.offline[0][1]
    assert sink.decisions == []


def test_monitor_runs_for_duration_and_stops_all_workers(tmp_path):
    video = make_fire_then_forest_video(tmp_path / "v.avi")
    cams = [CameraConfig(f"CAM-{i}", "Test", str(video), 1.4, 125.0) for i in range(4)]
    sink = RecordingSink()
    monitor = Monitor(settings_for(tmp_path, *cams), sinks=[sink])
    started = time.monotonic()
    monitor.run_forever(duration_s=2.0)
    assert time.monotonic() - started < 6
    assert all(not w.is_alive() for w in monitor.workers)
    assert {d.camera_id for d in sink.decisions} == {c.id for c in cams}


def test_console_sink_logs_level_change(tmp_path, caplog):
    video = make_fire_then_forest_video(tmp_path / "fire.avi")
    cam = CameraConfig("CAM-T", "Test", str(video), 1.4, 125.0)
    stop = threading.Event()
    worker = CameraWorker(cam, settings_for(tmp_path, cam, process_fps=10.0), [ConsoleSink()], stop)
    with caplog.at_level(logging.INFO, logger="mataklabat.pipeline"):
        worker.start()
        try:
            assert wait_for(lambda: "AMAN -> WASPADA" in caplog.text)
        finally:
            stop.set()
            worker.join(3)
    assert "api=" in caplog.text and "T1=" in caplog.text


def test_ctrl_c_stops_all_workers(tmp_path):
    video = make_fire_then_forest_video(tmp_path / "v.avi")
    cams = [CameraConfig(f"CAM-{i}", "Test", str(video), 1.4, 125.0) for i in range(2)]
    monitor = Monitor(settings_for(tmp_path, *cams), sinks=[RecordingSink()])
    # Deliver a real KeyboardInterrupt to the main thread, exactly like Ctrl+C.
    timer = threading.Timer(1.0, _thread.interrupt_main)
    timer.start()
    started = time.monotonic()
    try:
        monitor.run_forever(duration_s=15)  # backstop so a bug cannot hang the suite
    finally:
        timer.cancel()
    assert time.monotonic() - started < 8
    assert monitor.stop_event.is_set()
    assert all(not w.is_alive() for w in monitor.workers)
