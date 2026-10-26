"""Demo scenarios end to end (Spec §13.3): photo camera -> detector -> (fake) vision LLM
-> decision -> storage -> alerts/outbox -> incident report. Only the LLM is faked."""

import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from mataklabat.config import CameraConfig, Place, Resource, Resources, Settings
from mataklabat.monitor import build_monitor
from mataklabat.storage import ReadStore
from mataklabat.vision_llm import LLMVerdict, RateLimiter

VERDICTS = {
    "api": LLMVerdict(smoke_visible=True, fire_visible=True, hazard_type="smoke_and_flame", confidence=0.95,
                      evidence=("api dan asap di lereng",), reasoning="Api terlihat jelas.", prompt_version="v2"),
    "kabut": LLMVerdict(smoke_visible=True, hazard_type="smoke", lookalike="fog_cloud", confidence=0.95,
                        reasoning="Kabut menyebar rata di lereng.", prompt_version="v2"),
    "sampah": LLMVerdict(hazard_type="none", confidence=0.8, risk_factors=("trash_burning",),
                         reasoning="Ada orang membakar sampah.", prompt_version="v2"),
    "normal": LLMVerdict(hazard_type="none", confidence=0.9, prompt_version="v2"),
}


class PhotoVerifier:
    """Answers by photo file name, like a perfectly predictable LLM."""

    def __init__(self):
        self.limiter = RateLimiter(0.0)
        self.calls = []

    def verify(self, frame, ctx, prompt_version=None, *, block=True, limit=True):
        name = (frame.still_id or "normal").split(".")[0]
        self.calls.append(name)
        return VERDICTS.get(name, VERDICTS["normal"])


def write_photo(folder: Path, name: str, kind: str) -> None:
    img = np.full((360, 480, 3), (60, 120, 50), np.uint8)
    if kind == "fire":
        img[120:300, 180:320] = (0, 150, 245)
    elif kind == "gray":
        img[60:300, 80:400] = (165, 168, 168)
    ok, buf = cv2.imencode(".jpg", img)
    path = folder / name
    path.write_bytes(buf.tobytes())
    t = time.time()
    os.utime(path, (t, t))


def wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def demo(tmp_path):
    folder = tmp_path / "data" / "demo" / "CAM-04"
    folder.mkdir(parents=True)
    cam = CameraConfig("CAM-04", "Matungkas - Laikit", str(folder), 1.475, 124.95, 90, mode="foto")
    settings = Settings(
        root=tmp_path, cameras=(cam,),
        resources=Resources((Place("Laikit", 1.47, 124.96),), (Resource("Posko", "posko", 1.42, 124.98),), ()),
        llm_enabled=True, llm_model="test/vision", llm_base_url="http://127.0.0.1:9/v1",
        process_fps=10.0, recheck_s=0.5, heartbeat_s=0, agent_timeout_s=5,
        morning_summary_at="",
    )
    verifier = PhotoVerifier()
    monitor = build_monitor(settings, with_weather=False, verifier=verifier)
    thread = threading.Thread(target=monitor.run_forever, kwargs={"duration_s": 60}, daemon=True)
    thread.start()
    yield folder, ReadStore(settings.db_path), verifier
    monitor.stop_event.set()
    thread.join(10)


def kinds(read):
    return sorted(o["kind"] for o in read.outbox())


def test_fire_photo_opens_incident_with_two_messages(demo):
    folder, read, verifier = demo
    write_photo(folder, "normal.jpg", "none")
    assert wait_for(lambda: (read.camera_status("CAM-04") or {}).get("online") == 1)
    write_photo(folder, "api.jpg", "fire")
    assert wait_for(lambda: read.incidents("open"))
    status = read.camera_status("CAM-04")
    assert status["level"] == "BAHAYA" and status["rule"] == "R1"
    # Message 1 at once, message 2 (report) after the agent fails over to the template.
    assert wait_for(lambda: kinds(read) == ["fire", "report"], timeout=30), kinds(read)
    incident = read.incidents("open")[0]
    full = read.incident(incident["id"])
    assert full["report_source"] == "template" and "## Rekomendasi Tindakan" in full["report_md"]
    assert all(o["status"] == "dry_run" for o in read.outbox())  # Telegram not configured
    fire = next(o for o in read.outbox() if o["kind"] == "fire")
    assert fire["text"].startswith("🔴 KEBAKARAN TERDETEKSI — CAM-04")


def test_fog_photo_is_rejected_without_alerts(demo):
    folder, read, verifier = demo
    write_photo(folder, "kabut.jpg", "gray")
    assert wait_for(lambda: "kabut" in verifier.calls)
    assert wait_for(lambda: (read.camera_status("CAM-04") or {}).get("rule") == "R5")
    status = read.camera_status("CAM-04")
    assert status["level"] == "AMAN" and status["sub_status"] == "rejected_lookalike"
    time.sleep(1)
    assert read.outbox() == [] and read.incidents() == []


def test_trash_burning_photo_is_a_potential_risk(demo):
    folder, read, verifier = demo
    write_photo(folder, "sampah.jpg", "none")
    assert wait_for(lambda: (read.camera_status("CAM-04") or {}).get("level") == "WASPADA")
    status = read.camera_status("CAM-04")
    assert status["rule"] == "R3" and status["sub_status"] == "POTENSI"
    assert wait_for(lambda: kinds(read) == ["check"])
    assert "pembakaran sampah" in read.outbox()[0]["text"]
    assert read.incidents() == []
