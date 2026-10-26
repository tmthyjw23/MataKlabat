import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from mataklabat import __main__ as cli
from mataklabat.camera import CameraSource
from mataklabat.config import CameraConfig

FPS = 10
N_FRAMES = 10  # 1 second of video


def make_video(path: Path) -> Path:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (64, 48))
    assert writer.isOpened(), "OpenCV cannot write MJPG/AVI on this machine"
    for i in range(N_FRAMES):
        writer.write(np.full((48, 64, 3), i * 20, dtype=np.uint8))
    writer.release()
    return path


def camera(source, cam_id: str = "CAM-T") -> CameraConfig:
    return CameraConfig(id=cam_id, name="Test", source=source, lat=1.4, lon=125.0)


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def video(tmp_path) -> Path:
    return make_video(tmp_path / "synthetic.avi")


def test_video_frames_are_published(video):
    with CameraSource(camera(str(video))) as src:
        assert wait_for(lambda: src.latest() is not None)
        frame = src.latest()
        assert frame.camera_id == "CAM-T"
        assert frame.image.shape == (48, 64, 3)
        assert frame.ts.tzinfo is not None and frame.ts.utcoffset().total_seconds() == 8 * 3600
        assert src.online


def test_video_loops_at_end_of_file(video):
    with CameraSource(camera(str(video))) as src:
        # Played at native speed, 1 s of video must wrap around within ~2.5 s.
        assert wait_for(lambda: (f := src.latest()) is not None and f.seq > N_FRAMES * 1.5)
        assert src.online
        assert src.last_error is None


def test_two_sources_read_concurrently(video, tmp_path):
    other = make_video(tmp_path / "other.avi")
    with CameraSource(camera(str(video), "A")) as a, CameraSource(camera(str(other), "B")) as b:
        assert wait_for(lambda: a.online and b.online)
        assert a.latest().camera_id == "A" and b.latest().camera_id == "B"


def test_missing_file_reports_offline(tmp_path):
    src = CameraSource(camera(str(tmp_path / "nope.mp4")), reconnect_delay_s=0.1).start()
    try:
        assert wait_for(lambda: src.last_error is not None)
        assert "tidak ditemukan" in src.last_error
        assert not src.online
        assert src.latest() is None
    finally:
        src.stop()


def test_goes_offline_when_frames_stop(video):
    now = [0.0]
    src = CameraSource(camera(str(video)), clock=lambda: now[0])
    src._publish(np.zeros((4, 4, 3), dtype=np.uint8))
    assert src.online and src.latest() is not None
    now[0] = 5.1
    assert not src.online
    assert src.latest() is None


def test_stop_terminates_thread(video):
    src = CameraSource(camera(str(video))).start()
    thread = src._thread
    src.stop()
    assert not thread.is_alive()


def test_check_cameras_reports_each_camera(video, tmp_path):
    from mataklabat.config import Resources, Settings

    settings = Settings(
        root=tmp_path,
        cameras=(camera(str(video), "OK-CAM"), camera(str(tmp_path / "missing.mp4"), "BAD-CAM")),
        resources=Resources(),
    )
    rows = {name: (ok, detail) for name, ok, detail in cli.check_cameras(settings, wait_s=3.0)}
    assert rows["OK-CAM"][0] is True and "64x48" in rows["OK-CAM"][1]
    assert rows["BAD-CAM"][0] is False and "tidak ditemukan" in rows["BAD-CAM"][1]


def test_check_open_meteo_parses_response(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"current": {"temperature_2m": 31.2, "relative_humidity_2m": 55, "wind_speed_10m": 12.0}}

    monkeypatch.setattr(cli.requests, "get", lambda *a, **k: FakeResponse())
    name, ok, detail = cli.check_open_meteo(1.4, 125.0)
    assert ok is True and "31.2" in detail and "55%" in detail


def test_check_open_meteo_reports_network_error(monkeypatch):
    def boom(*a, **k):
        raise cli.requests.ConnectionError("offline")

    monkeypatch.setattr(cli.requests, "get", boom)
    assert cli.check_open_meteo(1.4, 125.0)[1] is False


def test_check_telegram_hides_token_on_error(monkeypatch, tmp_path):
    from mataklabat.config import Resources, Settings

    def boom(url, **k):
        raise cli.requests.ConnectionError(f"failed {url}")

    monkeypatch.setattr(cli.requests, "get", boom)
    settings = Settings(
        root=tmp_path, cameras=(), resources=Resources(),
        telegram_bot_token="123:SECRET", telegram_chat_id="42",
    )
    name, ok, detail = cli.check_telegram(settings)
    assert ok is False and "SECRET" not in detail
