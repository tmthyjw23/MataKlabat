import json
import re
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mataklabat.camera import Frame
from mataklabat.config import CameraConfig, Place, Resources, Settings, now_local
from mataklabat.decision import DecisionEngine
from mataklabat.detector import Box, LocalDetection
from mataklabat.recorder import Recorder
from mataklabat.snapshots import SnapshotStore
from mataklabat.storage import Storage
from mataklabat.vision_llm import LLMVerdict
from mataklabat.web.app import STATIC_DIR, create_app
from tests.test_alerts import snapshot

CAMS = (
    CameraConfig("CAM-01", "Kaki Dian", 0, 1.42, 124.98),
    CameraConfig("CAM-04", "Matungkas", "data/demo/CAM-04", 1.47, 124.95, mode="foto"),
)
XSS = "<img src=x onerror=alert(1)><script>alert('x')</script>"
FIRE = LLMVerdict(smoke_visible=True, hazard_type="smoke", confidence=0.95, prompt_version="v2",
                  reasoning=XSS, evidence=("kolom asap",))


@pytest.fixture
def env(tmp_path):
    settings = Settings(root=tmp_path, cameras=CAMS,
                        resources=Resources((Place("Klabat", 1.43, 124.99),), (), (Place("Puncak Klabat", 1.4667, 125.0333),)),
                        telegram_bot_token="123:SECRET-TOKEN", telegram_chat_id="42", llm_api_key="sk-SECRET")
    storage = Storage(settings.db_path)
    recorder = Recorder(storage, SnapshotStore(settings.snapshot_dir), settings.cameras)
    storage.set_health("monitor", True, "berjalan")
    storage.save_risk(snapshot())
    engine = DecisionEngine("CAM-01", settings)
    ts = now_local()
    local = LocalDetection("CAM-01", ts, 0.3, 0.4, (Box(10, 10, 50, 50, "smoke"),))
    decision = engine.update(local, verdict=FIRE, llm_available=True)
    recorder.on_decision(decision, local, Frame("CAM-01", ts, np.zeros((120, 160, 3), np.uint8), 1))
    incident = storage.open_incident_id("CAM-01")
    storage.enqueue("fire", "🔴 KEBAKARAN", camera_id="CAM-01", incident_id=incident)
    client = TestClient(create_app(settings))
    yield settings, storage, client, incident
    storage.close()


def test_status_summarises_cameras_risk_and_incidents(env):
    _, _, client, incident = env
    data = client.get("/api/status").json()
    assert data["monitor"]["alive"] is True
    assert data["counts"] == {"normal": 0, "check": 0, "fire": 1, "offline": 1}
    cam1 = data["cameras"][0]
    assert cam1["label"] == "Kebakaran Terdeteksi" and cam1["snapshot_url"].startswith("/api/cameras/CAM-01/snapshot.jpg")
    assert data["cameras"][1]["mode"] == "foto" and data["cameras"][1]["online"] is False
    assert data["risk"]["level"] == "Tinggi" and data["risk"]["stale"] is False
    assert [i["id"] for i in data["open_incidents"]] == [incident]


def test_snapshots_by_id_only(env):
    _, _, client, _ = env
    resp = client.get("/api/cameras/CAM-01/snapshot.jpg")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/jpeg"
    assert client.get("/api/cameras/CAM-04/snapshot.jpg").status_code == 404  # no frame yet
    assert client.get("/api/cameras/..%2F..%2Fevents.db/snapshot.jpg").status_code == 404
    assert client.get("/api/cameras/CAM-99/snapshot.jpg").json() == {"error": "kamera tidak dikenal"}
    events = client.get("/api/events").json()
    assert client.get(events[0]["snapshot_url"]).status_code == 200


def test_events_and_validation(env):
    _, _, client, _ = env
    [event] = client.get("/api/events?camera=CAM-01&minutes=30").json()
    assert event["rule"] == "R1" and event["label"] == "Kebakaran Terdeteksi" and event["level_from"] == "AMAN"
    assert event["llm"]["reasoning"] == XSS  # raw text, rendered as text by the page
    assert client.get("/api/events?camera=CAM-99").status_code == 404
    assert client.get("/api/events?minutes=0").status_code == 422


def test_incident_detail(env):
    _, _, client, incident = env
    data = client.get(f"/api/incidents/{incident}").json()
    assert data["camera_name"] == "Kaki Dian" and data["agent_steps"] == []
    assert data["events"][0]["rule"] == "R1"
    assert data["messages"][0]["kind"] == "fire"
    assert client.get("/api/incidents/999").status_code == 404
    assert client.get("/api/incidents?state=open").json()[0]["id"] == incident
    assert client.get("/api/incidents?state=bogus").status_code == 422


def test_risk_map_outbox_hotspots(env):
    _, _, client, _ = env
    risk = client.get("/api/risk").json()
    assert risk["current"]["driver"] == "dc" and len(risk["daily"]) >= 1
    m = client.get("/api/map").json()
    assert m["center"] == [1.4667, 125.0333] and m["villages"][0]["name"] == "Klabat"
    assert client.get("/api/outbox").json()[0]["status"] == "pending"
    assert client.get("/api/hotspots").json()["status"] == "unavailable"


def test_no_secrets_anywhere(env):
    _, _, client, _ = env
    for url in ("/api/status", "/api/health", "/api/outbox", "/api/map", "/api/risk", "/api/events"):
        body = client.get(url).text
        assert "SECRET" not in body, url
    health = client.get("/api/health").json()
    assert health["config"]["telegram_configured"] is True


def test_security_headers_on_pages_and_api(env):
    _, _, client, _ = env
    for url in ("/", "/api/status", "/incident/1", "/health", "/static/app.css"):
        resp = client.get(url)
        assert resp.status_code == 200, url
        csp = resp.headers["content-security-policy"]
        assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
    assert client.get("/api/status").headers["cache-control"] == "no-store"


def test_static_pages_have_no_inline_script_or_style():
    for page in STATIC_DIR.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), page.name
        assert "style=" not in html and "<style" not in html, page.name
        assert re.search(r"\son[a-z]+=", html) is None, page.name


def test_frontend_never_uses_innerhtml():
    for script in STATIC_DIR.glob("*.js"):
        code = script.read_text(encoding="utf-8")
        assert "innerHTML" not in code and "insertAdjacentHTML" not in code and "document.write" not in code, script.name


def test_stream_sends_update(env):
    _, _, client, _ = env
    # The SSE generator polls forever; read just the first chunks.
    with client.stream("GET", "/api/stream") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        chunks = []
        for line in resp.iter_lines():
            chunks.append(line)
            if line.startswith("data:"):
                break
    assert "event: update" in chunks and json.loads(chunks[-1][5:])["ts"]


def test_empty_database_still_serves(tmp_path):
    settings = Settings(root=tmp_path, cameras=CAMS, resources=Resources())
    client = TestClient(create_app(settings))
    data = client.get("/api/status").json()
    assert data["monitor"]["alive"] is False and data["risk"] is None
    assert all(not c["online"] for c in data["cameras"])
    assert client.get("/").status_code == 200
