"""Operator control: camera on/off, login, demo photo gallery (control.py, web)."""

import sqlite3
import threading
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from mataklabat.config import CameraConfig, ConfigError, Resources, Settings, load_settings, now_local
from mataklabat.control import DEMO_PREFIX, CameraControl, ControlWatcher, show_photo, shown_photo
from mataklabat.decision import Level
from mataklabat.messages import morning_summary
from mataklabat.pipeline import CameraWorker
from mataklabat.recorder import Recorder
from mataklabat.snapshots import SnapshotStore
from mataklabat.storage import ReadStore, Storage
from mataklabat.web.app import LOGIN_MAX_FAILURES, SESSION_COOKIE, OperatorAuth, create_app
from tests.test_pipeline import RecordingSink, wait_for

PASSWORD = "uji-operator-123"
WRITE = {"X-MataKlabat": "1"}


def write_photo(path: Path, color=(40, 110, 30)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.full((60, 80, 3), color, np.uint8))
    return path


@pytest.fixture
def env(tmp_path):
    folder = tmp_path / "cam04"
    write_photo(folder / "00_normal.jpg")
    gallery = tmp_path / "bahan"
    write_photo(gallery / "asap.jpg", (200, 200, 200))
    write_photo(gallery / "kabut.jpg", (220, 220, 220))
    (gallery / "catatan.txt").write_text("bukan foto")
    cams = (
        CameraConfig("CAM-02", "Pos 1", str(tmp_path / "v.mp4"), 1.44, 125.0),
        CameraConfig("CAM-04", "Matungkas", str(folder), 1.48, 124.97, mode="foto", enabled=False),
    )
    settings = Settings(root=tmp_path, cameras=cams, resources=Resources(),
                        operator_password=PASSWORD, gallery_dir=gallery)
    return settings


def client_for(settings, **kwargs):
    return TestClient(create_app(settings, **kwargs))


def login(client, password=PASSWORD):
    return client.post("/api/login", json={"password": password}, headers=WRITE)


# --- control store ---------------------------------------------------------------------------


def test_control_defaults_follow_config_then_operator(env):
    reader = CameraControl(env.control_db_path, env.cameras)
    assert reader.states() == {"CAM-02": True, "CAM-04": False}  # no control.db yet
    writer = CameraControl(env.control_db_path, env.cameras, writable=True)
    writer.set_enabled("CAM-04", True)
    writer.set_enabled("CAM-02", False)
    assert reader.states() == {"CAM-02": False, "CAM-04": True}
    with pytest.raises(PermissionError):
        reader.set_enabled("CAM-02", True)
    with pytest.raises(KeyError):
        writer.set_enabled("CAM-99", True)


def test_watcher_keeps_last_state_and_refreshes(env):
    writer = CameraControl(env.control_db_path, env.cameras, writable=True)
    watcher = ControlWatcher(CameraControl(env.control_db_path, env.cameras))
    assert watcher.enabled("CAM-04") is False
    writer.set_enabled("CAM-04", True)
    watcher.refresh()
    assert watcher.enabled("CAM-04") is True


def test_show_photo_replaces_previous_demo_copy(env):
    cam = env.cameras[1]
    gallery = env.gallery_dir
    first = show_photo(cam, gallery / "kabut.jpg")
    second = show_photo(cam, gallery / "asap.jpg")
    folder = Path(cam.source)
    assert not first.exists() and second.exists()
    assert sorted(p.name for p in folder.iterdir()) == ["00_normal.jpg", second.name]
    assert second.name.startswith(DEMO_PREFIX) and shown_photo(cam) == "asap.jpg"
    newest = max(folder.iterdir(), key=lambda p: p.stat().st_mtime_ns)
    assert newest == second
    with pytest.raises(ValueError):
        show_photo(env.cameras[0], gallery / "asap.jpg")


# --- monitor side ------------------------------------------------------------------------------


class OnOffSink(RecordingSink):
    def __init__(self):
        super().__init__()
        self.calls = []

    def on_camera_enabled(self, camera_id):
        self.calls.append(("on", camera_id))

    def on_camera_disabled(self, camera_id, level_before, at_start):
        self.calls.append(("off", camera_id, at_start))


def test_worker_follows_operator_switch(env):
    cam = env.cameras[1]
    state = {"CAM-04": False}
    sink, stop = OnOffSink(), threading.Event()
    settings = Settings(root=env.root, cameras=(cam,), resources=Resources(), process_fps=10.0)
    worker = CameraWorker(cam, settings, [sink], stop, is_enabled=lambda cid: state[cid])
    worker.start()
    try:
        assert wait_for(lambda: sink.calls == [("off", "CAM-04", True)], 3)
        assert sink.decisions == []  # disabled: no frames, no AI
        state["CAM-04"] = True
        assert wait_for(lambda: sink.decisions, 5)
        assert ("on", "CAM-04") in sink.calls
        state["CAM-04"] = False
        assert wait_for(lambda: sink.calls[-1] == ("off", "CAM-04", False), 3)
        count = len(sink.decisions)
        assert wait_for(lambda: False, 0.5) is False
        assert len(sink.decisions) == count  # stopped
        assert worker.active is False and worker.engine.level == Level.AMAN
    finally:
        stop.set()
        worker.join(3)
    assert not worker.is_alive()


def test_recorder_disable_resets_status_and_closes_incident(env):
    storage = Storage(env.db_path)
    listener_calls = []

    class Listener:
        def on_camera_disabled(self, camera_id):
            listener_calls.append(camera_id)

    recorder = Recorder(storage, SnapshotStore(env.snapshot_dir), env.cameras, listeners=[Listener()])
    incident = storage.open_incident("CAM-02", now_local(), "BAHAYA", None)
    storage.upsert_camera_status("CAM-02", level="BAHAYA", online=1)
    recorder.on_camera_disabled("CAM-02", Level.BAHAYA, at_start=False)

    read = ReadStore(env.db_path)
    row = read.camera_status("CAM-02")
    assert (row["level"], row["enabled"], row["online"], row["rule"]) == ("AMAN", 0, 0, "OFF")
    closed = read.incident(incident)
    assert closed["closed_ts"] and closed["close_reason"] == "kamera dinonaktifkan operator"
    [event] = read.events("CAM-02", "2000")
    assert event["rule"] == "OFF" and "Kebakaran Terdeteksi di-reset ke Normal" in event["trace_json"]
    assert listener_calls == ["CAM-02"]

    recorder.on_camera_enabled("CAM-02")
    row = read.camera_status("CAM-02")
    assert (row["enabled"], row["offline_reason"]) == (1, "menyalakan kamera")
    storage.close()


def test_disabled_at_start_writes_no_event(env):
    storage = Storage(env.db_path)
    recorder = Recorder(storage, SnapshotStore(env.snapshot_dir), env.cameras)
    recorder.on_camera_disabled("CAM-04", Level.AMAN, at_start=True)
    assert ReadStore(env.db_path).events(None, "2000") == []
    assert ReadStore(env.db_path).camera_status("CAM-04")["enabled"] == 0
    storage.close()


def test_old_database_gets_new_columns(tmp_path):
    path = tmp_path / "events.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE camera_status (camera_id TEXT PRIMARY KEY, ts TEXT NOT NULL, level TEXT)")
    conn.execute("CREATE TABLE incidents (id INTEGER PRIMARY KEY, opened_ts TEXT, closed_ts TEXT,"
                 " camera_id TEXT, peak_level TEXT)")
    conn.commit()
    conn.close()
    Storage(path).close()
    conn = sqlite3.connect(path)
    assert "enabled" in {r[1] for r in conn.execute("PRAGMA table_info(camera_status)")}
    assert "close_reason" in {r[1] for r in conn.execute("PRAGMA table_info(incidents)")}
    conn.close()


def test_morning_summary_names_disabled_cameras():
    cams = [{"camera_id": "CAM-04", "name": "Matungkas", "level": "AMAN", "online": 0, "enabled": 0}]
    text = morning_summary(None, cams, now_local())
    assert "CAM-04 Matungkas: Nonaktif (pilihan operator)" in text


# --- web --------------------------------------------------------------------------------------


def test_viewer_sees_state_but_cannot_change_it(env):
    client = client_for(env)
    status = client.get("/api/status").json()
    cams = {c["id"]: c for c in status["cameras"]}
    assert cams["CAM-04"]["enabled"] is False and cams["CAM-02"]["enabled"] is True
    assert status["counts"]["disabled"] == 1
    assert client.get("/api/session").json() == {"operator": False, "available": True}
    assert client.post("/api/cameras/CAM-04/enabled", json={"enabled": True}, headers=WRITE).status_code == 401
    assert client.get("/api/gallery").status_code == 401
    assert client.get("/api/gallery/asap.jpg").status_code == 401


def test_operator_switches_camera_and_picks_photo(env):
    client = client_for(env)
    resp = login(client)
    assert resp.status_code == 200
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/session").json()["operator"] is True

    assert client.post("/api/cameras/CAM-04/enabled", json={"enabled": True}, headers=WRITE).json() == \
        {"id": "CAM-04", "enabled": True}
    assert CameraControl(env.control_db_path, env.cameras).states()["CAM-04"] is True
    assert client.post("/api/cameras/CAM-04/enabled", json={"enabled": "ya"}, headers=WRITE).status_code == 422
    assert client.post("/api/cameras/CAM-99/enabled", json={"enabled": True}, headers=WRITE).status_code == 404

    names = [p["name"] for p in client.get("/api/gallery").json()]
    assert names == ["asap.jpg", "kabut.jpg"]  # no .txt
    assert client.get("/api/gallery/asap.jpg").status_code == 200
    thumb = client.get("/api/gallery/asap.jpg?thumb=1")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    assert client.post("/api/cameras/CAM-04/photo", json={"name": "asap.jpg"}, headers=WRITE).status_code == 200
    cams = {c["id"]: c for c in client.get("/api/cameras").json()}
    assert cams["CAM-04"]["photo_shown"] == "asap.jpg"
    assert cams["CAM-04"]["control_ts"] and cams["CAM-02"]["control_ts"] is None
    assert client.post("/api/cameras/CAM-02/photo", json={"name": "asap.jpg"}, headers=WRITE).status_code == 400

    client.post("/api/logout", headers=WRITE)
    assert client.get("/api/session").json()["operator"] is False


@pytest.mark.parametrize("name", ["../cam04/00_normal.jpg", "..\\x.jpg", "/etc/passwd", "catatan.txt", "", "ASAP.JPG"])
def test_gallery_only_serves_exact_names(env, name):
    client = client_for(env)
    login(client)
    assert client.post("/api/cameras/CAM-04/photo", json={"name": name}, headers=WRITE).status_code == 404
    if name:  # "/api/gallery/" is just the listing
        assert client.get(f"/api/gallery/{name}").status_code in (404, 405)


def test_writes_need_csrf_header_and_same_origin(env):
    client = client_for(env)
    login(client)
    assert client.post("/api/cameras/CAM-04/enabled", json={"enabled": True}).status_code == 403
    evil = {**WRITE, "Origin": "https://jahat.example"}
    assert client.post("/api/cameras/CAM-04/enabled", json={"enabled": True}, headers=evil).status_code == 403
    same = {**WRITE, "Origin": "http://testserver"}
    assert client.post("/api/cameras/CAM-04/enabled", json={"enabled": True}, headers=same).status_code == 200
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 403


def test_wrong_passwords_lock_login(env):
    clock = [0.0]
    client = client_for(env, auth=OperatorAuth(PASSWORD, clock=lambda: clock[0]))
    for _ in range(LOGIN_MAX_FAILURES):
        assert login(client, "salah-salah-salah").status_code == 401
    assert login(client).status_code == 429  # even the right password, while locked
    clock[0] = 601.0
    assert login(client).status_code == 200


def test_session_expires_and_is_not_guessable(env):
    clock = [0.0]
    auth = OperatorAuth(PASSWORD, clock=lambda: clock[0])
    token = auth.login(PASSWORD)
    assert auth.valid(token) and not auth.valid("tebakan") and not auth.valid(None)
    clock[0] = 13 * 3600
    assert not auth.valid(token)


def test_no_password_means_no_operator(env):
    import dataclasses
    client = client_for(dataclasses.replace(env, operator_password=None))
    assert client.get("/api/session").json() == {"operator": False, "available": False}
    assert login(client).status_code == 404


def test_session_cookie_secure_behind_https_proxy(env):
    client = client_for(env)
    resp = client.post("/api/login", json={"password": PASSWORD}, headers={**WRITE, "X-Forwarded-Proto": "https"})
    assert "secure" in resp.headers["set-cookie"].lower()
    assert SESSION_COOKIE in resp.headers["set-cookie"]


# --- config -----------------------------------------------------------------------------------


def test_cameras_file_and_enabled_flag(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "cameras.vps.yaml").write_text(
        "cameras:\n  - {id: CAM-02, name: X, source: v.mp4, lat: 1.4, lon: 125.0, enabled: false}\n",
        encoding="utf-8")
    monkeypatch.setenv("CAMERAS_FILE", "config/cameras.vps.yaml")
    monkeypatch.setenv("OPERATOR_PASSWORD", PASSWORD)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    settings = load_settings(tmp_path, env_file=None)
    assert settings.cameras[0].enabled is False
    assert settings.operator_password == PASSWORD and "uji-operator" not in repr(settings)
    assert settings.gallery_dir == tmp_path / "data" / "demo" / "bahan"

    (tmp_path / "config" / "cameras.vps.yaml").write_text(
        "cameras:\n  - {id: CAM-02, name: X, source: v.mp4, lat: 1.4, lon: 125.0, enabled: 'ya'}\n",
        encoding="utf-8")
    with pytest.raises(ConfigError, match="enabled"):
        load_settings(tmp_path, env_file=None)


def test_short_operator_password_rejected(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "cameras.yaml").write_text(
        "cameras:\n  - {id: CAM-02, name: X, source: v.mp4, lat: 1.4, lon: 125.0}\n", encoding="utf-8")
    monkeypatch.delenv("CAMERAS_FILE", raising=False)
    monkeypatch.setenv("OPERATOR_PASSWORD", "pendek")
    with pytest.raises(ConfigError, match="OPERATOR_PASSWORD"):
        load_settings(tmp_path, env_file=None)
