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


# --- T6: triggers and LLM scheduling --------------------------------------------

from mataklabat.pipeline import LLMScheduler, Trigger  # noqa: E402
from mataklabat.vision_llm import LLMVerdict, RateLimiter  # noqa: E402

SMOKE_095 = LLMVerdict(smoke_visible=True, hazard_type="smoke", confidence=0.95, prompt_version="v2")


class FakeVerifier:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = 0
        self.limiter = RateLimiter(0.0)

    def verify(self, frame, ctx, prompt_version=None, *, block=True, limit=True):
        assert limit is False  # the scheduler already took the rate-limit slot
        self.calls += 1
        return self.verdict


def llm_settings(tmp_path, *cams, **overrides):
    values = dict(llm_enabled=True, llm_model="test/vision", process_fps=10.0, recheck_s=0.5)
    values.update(overrides)
    return settings_for(tmp_path, *cams, **values)


def test_scheduler_prefers_higher_priority():
    now = [0.0]
    scheduler = LLMScheduler(RateLimiter(10.0, clock=lambda: now[0]))
    assert scheduler.request("C", Trigger.T1)  # takes the slot at t=0
    now[0] = 5
    assert not scheduler.request("B", Trigger.T2)  # rate limited, now waiting with T2
    now[0] = 11
    assert not scheduler.request("A", Trigger.T3)  # B outranks A
    assert scheduler.request("B", Trigger.T2)
    now[0] = 22
    assert scheduler.request("A", Trigger.T3)


def test_scheduler_withdraw_releases_priority():
    scheduler = LLMScheduler(RateLimiter(0.0))
    scheduler._waiting["B"] = Trigger.T2
    assert not scheduler.request("A", Trigger.T1)
    scheduler.withdraw("B")
    assert scheduler.request("A", Trigger.T1)


def test_due_trigger_order(tmp_path):
    now = [100.0]
    cam = CameraConfig("CAM-T", "Test", str(tmp_path / "none.mp4"), 1.4, 125.0)
    worker = CameraWorker(
        cam, llm_settings(tmp_path, cam, recheck_s=15, heartbeat_s=120), [], threading.Event(),
        verifier=FakeVerifier(SMOKE_095), scheduler=LLMScheduler(RateLimiter(0.0)), clock=lambda: now[0],
    )
    assert worker.due_trigger() == Trigger.T3  # never checked: heartbeat is due
    worker._last_llm_at = 100.0
    now[0] = 110
    assert worker.due_trigger() is None
    for _ in range(3):
        worker.engine.t1._hits.append(True)
    assert worker.due_trigger() is None  # T1 active but checked 10 s ago
    now[0] = 116
    assert worker.due_trigger() == Trigger.T1
    worker.engine.level = Level.WASPADA
    assert worker.due_trigger() == Trigger.T2


def test_no_heartbeat_when_disabled(tmp_path):
    cam = CameraConfig("CAM-T", "Test", str(tmp_path / "none.mp4"), 1.4, 125.0)
    worker = CameraWorker(
        cam, llm_settings(tmp_path, cam, heartbeat_s=0), [], threading.Event(),
        verifier=FakeVerifier(SMOKE_095), scheduler=LLMScheduler(RateLimiter(0.0)),
    )
    assert worker.due_trigger() is None


def run_worker_until(tmp_path, verifier, predicate, **overrides):
    video = make_fire_then_forest_video(tmp_path / "fire.avi", fire_s=3.0, forest_s=1.0)
    cam = CameraConfig("CAM-T", "Test", str(video), 1.4, 125.0)
    sink, stop = RecordingSink(), threading.Event()
    worker = CameraWorker(
        cam, llm_settings(tmp_path, cam, heartbeat_s=0, **overrides), [sink], stop,
        verifier=verifier, scheduler=LLMScheduler(verifier.limiter),
    )
    worker.start()
    try:
        assert wait_for(lambda: predicate(sink.decisions)), [(d.level, d.rule) for d in sink.decisions]
    finally:
        stop.set()
        worker.join(3)
    return sink.decisions


def test_worker_reaches_bahaya_with_llm(tmp_path):
    verifier = FakeVerifier(SMOKE_095)
    decisions = run_worker_until(
        tmp_path, verifier, lambda ds: any(d.level == Level.BAHAYA for d in ds)
    )
    bahaya = next(d for d in decisions if d.level == Level.BAHAYA)
    assert bahaya.rule == "R1" and bahaya.verdict is SMOKE_095
    assert verifier.calls >= 1


def test_worker_falls_back_to_r4_when_llm_fails(tmp_path):
    verifier = FakeVerifier(LLMVerdict.failed("api_error: APIConnectionError", "v2"))
    decisions = run_worker_until(
        tmp_path, verifier, lambda ds: any(d.rule == "R4" for d in ds)
    )
    r4 = next(d for d in decisions if d.rule == "R4")
    assert r4.level == Level.WASPADA and r4.sub_status == "unverified"
