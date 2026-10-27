import json
import sqlite3
import threading
from datetime import timedelta

import numpy as np
import pytest

from mataklabat.camera import Frame
from mataklabat.config import CameraConfig, Resources, Settings, now_local
from mataklabat.decision import DecisionEngine, Level
from mataklabat.detector import Box, LocalDetection
from mataklabat.monitor import Housekeeper
from mataklabat.recorder import Recorder
from mataklabat.snapshots import SnapshotStore, annotate
from mataklabat.storage import ReadStore, Storage
from mataklabat.vision_llm import LLMVerdict

CAM = CameraConfig("CAM-01", "Kaki Dian", 0, 1.42, 124.98)
IMG = np.full((480, 640, 3), (40, 110, 30), dtype=np.uint8)
FIRE = LLMVerdict(
    fire_visible=True, smoke_visible=True, hazard_type="smoke_and_flame", confidence=0.95,
    reasoning="Api dan asap terlihat jelas.", prompt_version="v2",
)
CLEAN = LLMVerdict(hazard_type="none", confidence=0.9, prompt_version="v2")


@pytest.fixture
def env(tmp_path):
    settings = Settings(root=tmp_path, cameras=(CAM,), resources=Resources())
    storage = Storage(settings.db_path)
    snaps = SnapshotStore(settings.snapshot_dir)
    yield settings, storage, snaps
    storage.close()


class Listener:
    def __init__(self):
        self.calls = []

    def on_level_change(self, decision, photo):
        self.calls.append(("change", decision.level, photo))

    def on_incident_opened(self, incident_id, decision, photo):
        self.calls.append(("opened", incident_id, photo))

    def on_incident_closed(self, incident_id, decision):
        self.calls.append(("closed", incident_id))

    def on_sub_status_change(self, decision, photo):
        self.calls.append(("sub", decision.sub_status))


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def drive(engine, recorder, clock, verdict, steps=1):
    out = []
    for _ in range(steps):
        clock.t += 0.5
        ts = now_local()
        local = LocalDetection("CAM-01", ts, 0.4, 0.3, (Box(100, 100, 80, 60, "fire"),))
        d = engine.update(local, verdict=verdict, llm_available=True)
        recorder.on_decision(d, local, Frame("CAM-01", ts, IMG, 1))
        out.append(d)
    return out


def test_incident_opens_on_bahaya_and_closes_on_aman(env):
    settings, storage, snaps = env
    listener, clock = Listener(), Clock()
    recorder = Recorder(storage, snaps, settings.cameras, listeners=[listener], clock=clock)
    engine = DecisionEngine("CAM-01", settings)

    drive(engine, recorder, clock, FIRE)
    read = ReadStore(settings.db_path)
    [incident] = read.incidents("open")
    assert incident["camera_id"] == "CAM-01" and incident["peak_level"] == "BAHAYA"
    opened = [c for c in listener.calls if c[0] == "opened"]
    assert opened and opened[0][2].is_file() and "archive" in opened[0][2].as_posix()

    for _ in range(8):  # 4 clean verdicts per level step
        drive(engine, recorder, clock, CLEAN)
    assert engine.level == Level.AMAN
    assert read.incidents("open") == []
    assert read.incident(incident["id"])["closed_ts"] is not None
    assert ("closed", incident["id"]) in listener.calls

    status = read.camera_status("CAM-01")
    assert status["level"] == "AMAN" and status["online"] == 1
    assert (settings.snapshot_dir / status["last_snapshot"]).is_file()


def test_sub_status_change_at_same_level_is_notified(env):
    settings, storage, snaps = env
    listener, clock = Listener(), Clock()
    recorder = Recorder(storage, snaps, settings.cameras, listeners=[listener], clock=clock)
    engine = DecisionEngine("CAM-01", settings)
    for _ in range(3):  # AI down: R4 "unverified"
        clock.t += 0.5
        local = LocalDetection("CAM-01", now_local(), 0.4, 0.3)
        d = engine.update(local, verdict=None, llm_available=False)
        recorder.on_decision(d, local, Frame("CAM-01", d.ts, IMG, 1))
    weak = LLMVerdict(smoke_visible=True, hazard_type="smoke", confidence=0.5, prompt_version="v2")
    drive(engine, recorder, clock, weak, steps=2)
    assert listener.calls == [("change", Level.WASPADA, listener.calls[0][2]), ("sub", None)]


def test_events_written_on_change_verdict_and_heartbeat(env):
    settings, storage, snaps = env
    clock = Clock()
    recorder = Recorder(storage, snaps, settings.cameras, clock=clock)
    engine = DecisionEngine("CAM-01", settings)
    drive(engine, recorder, clock, None, steps=6)  # 3 s, no verdict, no change
    read = ReadStore(settings.db_path)
    since = (now_local() - timedelta(minutes=5)).isoformat(timespec="seconds")
    assert len(read.events(None, since)) == 1  # first step only
    clock.t += 10
    drive(engine, recorder, clock, None)
    drive(engine, recorder, clock, FIRE)
    events = read.events("CAM-01", since)
    assert len(events) == 3
    newest = events[0]
    assert newest["level"] == "BAHAYA" and json.loads(newest["llm_json"])["confidence"] == 0.95
    assert json.loads(newest["trace_json"])["rule"] == "R1"


def test_offline_status(env):
    settings, storage, snaps = env
    recorder = Recorder(storage, snaps, settings.cameras)
    read = ReadStore(settings.db_path)
    assert read.camera_status("CAM-01")["offline_reason"] == "menunggu frame pertama"
    recorder.on_offline("CAM-01", "file video tidak ditemukan")
    status = read.camera_status("CAM-01")
    assert status["online"] == 0 and "tidak ditemukan" in status["offline_reason"]


def test_reader_works_while_writer_writes(env):
    settings, storage, _ = env
    read = ReadStore(settings.db_path)
    errors = []

    def reader():
        for _ in range(50):
            try:
                read.camera_statuses()
                read.health()
            except sqlite3.Error as exc:
                errors.append(exc)

    t = threading.Thread(target=reader)
    t.start()
    for i in range(50):
        storage.set_health("monitor", True, f"beat {i}")
        storage.upsert_camera_status("CAM-01", level="AMAN", online=1)
    t.join()
    assert errors == []
    assert read.health()[0]["detail"] == "beat 49"


def test_read_store_without_database(tmp_path):
    read = ReadStore(tmp_path / "missing.db")
    assert read.camera_statuses() == [] and read.risk() is None and read.latest_event_id() == 0


def _event(storage, ts, level, rule):
    trace = {"rule": rule, "explanation": "x", "inputs": {}}
    return storage.insert_event(
        ts=ts, camera_id="CAM-01", level=level, sub_status=None, fire_score=0, smoke_score=0, llm=None,
        risk_level=None, fwi=None, rule=rule, trace=trace, snapshot_path=None,
    )


def test_prune_keeps_incident_trigger_events(env):
    settings, storage, _ = env
    old = now_local() - timedelta(days=10)
    kept = _event(storage, old, "BAHAYA", "R1")
    _event(storage, old, "AMAN", "R0")
    storage.open_incident("CAM-01", old, "BAHAYA", kept)
    assert storage.prune(now_local(), keep_days=7) == 1
    since = (old - timedelta(days=1)).isoformat()
    assert [e["id"] for e in ReadStore(settings.db_path).events(None, since)] == [kept]


def test_outbox_lifecycle(env):
    _, storage, _ = env
    oid = storage.enqueue("fire", "pesan", camera_id="CAM-01")
    now = now_local()
    assert [r["id"] for r in storage.due_outbox(now)] == [oid]
    storage.mark_retry(oid, "timeout", now + timedelta(seconds=30), give_up=False)
    assert storage.due_outbox(now) == []
    assert [r["id"] for r in storage.due_outbox(now + timedelta(seconds=31))] == [oid]
    storage.mark_sent(oid)
    item = storage.outbox_item(oid)
    assert item["status"] == "sent" and item["attempts"] == 2


def test_snapshot_annotation_and_archive_limit(tmp_path):
    out = annotate(np.zeros((1080, 1920, 3), np.uint8), (Box(10, 10, 200, 100, "smoke"),), now_local(), {"smoke": 0.4})
    assert out.shape[1] == 960 and out.any()
    store = SnapshotStore(tmp_path, archive_max_mb=0.0001)
    rng = np.random.default_rng(0)
    for _ in range(3):
        store.archive("CAM-01", rng.integers(0, 255, (200, 200, 3), np.uint8), now_local())
    assert store.prune_archive() >= 2


def test_housekeeper_reports_health(env):
    settings, storage, snaps = env
    keeper = Housekeeper(settings, storage, snaps, {}, risk=None)
    keeper.beat()
    health = {h["component"]: h for h in ReadStore(settings.db_path).health()}
    assert health["monitor"]["ok"] == 1
