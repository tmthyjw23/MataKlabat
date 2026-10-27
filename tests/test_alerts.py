from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from mataklabat import messages
from mataklabat.alerts import AlertService
from mataklabat.config import CameraConfig, Resources, Settings, now_local
from mataklabat.decision import DecisionEngine, Level
from mataklabat.detector import LocalDetection
from mataklabat.fwi import DailyWeather, FwiCodes
from mataklabat.notifier import OutboxSender, TelegramClient, TelegramError
from mataklabat.risk import DayRisk, RiskSnapshot
from mataklabat.storage import ReadStore, Storage, risk_to_dict
from mataklabat.vision_llm import LLMVerdict

TZ = ZoneInfo("Asia/Makassar")
CAM = CameraConfig("CAM-01", "Monumen Kaki Dian (Airmadidi)", 0, 1.42, 124.98)
SMOKE = LLMVerdict(
    smoke_visible=True, hazard_type="smoke", confidence=0.95, prompt_version="v2",
    reasoning="Kolom asap abu-abu naik dari satu titik di lereng kiri. " * 6,
)


def snapshot(level="Tinggi", fetched=None) -> RiskSnapshot:
    codes = FwiCodes(ffmc=80.0, dmc=20.0, dc=315.4, isi=3.0, bui=30.0, fwi=8.2)
    day = DayRisk(date(2026, 10, 26), level, "dc", {"ffmc": "Tinggi", "dc": level, "isi": "Sedang"}, codes,
                  DailyWeather(31, 50, 18, 0, 10), True)
    fc = DayRisk(date(2026, 10, 27), level, "dc", day.indicator_levels, codes, day.weather, False)
    return RiskSnapshot(fetched or now_local(), day, (fc,), 12, 31.0, 50.0, 18.0, 270.0, (day,))


RISK = risk_to_dict(snapshot())
WEAK = LLMVerdict(smoke_visible=True, hazard_type="smoke", confidence=0.5, prompt_version="v2", reasoning="Asap samar.")
FOG = LLMVerdict(smoke_visible=True, hazard_type="smoke", confidence=0.9, prompt_version="v2",
                 lookalike="fog_cloud", reasoning="Kabut.")


def decision(verdict=SMOKE, scores=(0.31, 0.44), times=1, llm=True):
    engine = DecisionEngine("CAM-01", Settings(root=Path("."), cameras=(CAM,), resources=Resources()))
    d = None
    for _ in range(times):
        d = engine.update(LocalDetection("CAM-01", datetime(2026, 10, 26, 14, 32, tzinfo=TZ), *scores),
                          verdict=verdict, llm_available=llm)
    return d


# --- messages ---------------------------------------------------------------------------


def test_fire_alert_has_status_why_data_action():
    text = messages.fire_alert(decision(), CAM, RISK, public_url="http://192.168.1.5:8000", incident_id=7)
    assert text.startswith("🔴 KEBAKARAN TERDETEKSI — CAM-01 Monumen Kaki Dian")
    assert "26 Okt 2026, 14:32 WITA" in text
    assert "Kenapa:" in text and "Data yang dipakai:" in text and "Tindakan:" in text
    assert "keyakinan 0.95, bukan kabut/awan atau cahaya" in text
    assert "Aturan R1:" in text
    assert "Risiko kawasan: TINGGI (karena kekeringan" in text or "Risiko kawasan: TINGGI" in text
    assert "Angin 18 km/j dari barat → api cenderung ke timur" in text
    assert "Detail: http://192.168.1.5:8000/incident/7" in text
    assert len(text) <= messages.CAPTION_LIMIT
    quote = next(line for line in text.splitlines() if line.strip().startswith('"'))
    assert len(quote.strip()) <= messages.QUOTE_LIMIT + 2


def test_check_alert_unverified_says_not_certain():
    d = decision(verdict=None, scores=(0.4, 0.0), times=3, llm=False)
    assert d.level == Level.WASPADA and d.sub_status == "unverified"
    text = messages.check_alert(d, CAM, None)
    assert text.startswith("🟡 PERLU DICEK") and "belum terverifikasi AI" in text
    assert "Belum pasti, mohon dicek." in text
    assert "Verifikasi AI: tidak tersedia" in text
    assert "Risiko kawasan: tidak diketahui" in text
    assert "Detail:" not in text  # no PUBLIC_URL


def test_captions_are_cut_to_limit():
    long_cam = CameraConfig("CAM-01", "X" * 2000, 0, 1.4, 125.0)
    assert len(messages.fire_alert(decision(), long_cam, RISK)) <= messages.CAPTION_LIMIT


def test_risk_and_morning_messages():
    text = messages.risk_rise_alert(RISK, "Sedang")
    assert "naik dari Sedang menjadi TINGGI" in text and "Kekeringan tanah (DC 315): Tinggi" in text
    assert "Saran:" in text and "Prakiraan: 10-27 Tinggi" in text
    cams = [{"camera_id": "CAM-01", "name": "Kaki Dian", "level": "AMAN", "online": 1},
            {"camera_id": "CAM-02", "name": "Pos 1", "level": "AMAN", "online": 0}]
    summary = messages.morning_summary(RISK, cams, datetime(2026, 10, 27, 7, 0, tzinfo=TZ))
    assert "RINGKASAN PAGI" in summary and "CAM-01 Kaki Dian: Normal" in summary and "CAM-02 Pos 1: Offline" in summary


# --- alert policy ----------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def setup(tmp_path):
    def make(**overrides):
        values = dict(root=tmp_path, cameras=(CAM,), resources=Resources(),
                      telegram_bot_token="123:abc", telegram_chat_id="42", auto_send_alert=True)
        values.update(overrides)
        settings = Settings(**values)
        storage = Storage(settings.db_path)
        clock, wall = Clock(), [datetime(2026, 10, 27, 6, 0, tzinfo=TZ)]
        reports = []
        alerts = AlertService(settings, storage, risk_provider=lambda: RISK,
                              report_requester=lambda *a: reports.append(a), clock=clock,
                              wall_clock=lambda: wall[0])
        return alerts, storage, ReadStore(settings.db_path), clock, wall, reports
    return make


def test_fire_alert_enqueued_and_report_requested(setup, tmp_path):
    alerts, storage, read, _, _, reports = setup()
    d = decision()
    incident_id = storage.open_incident("CAM-01", d.ts, "BAHAYA", None)
    photo = tmp_path / "p.jpg"
    alerts.on_incident_opened(incident_id, d, photo)
    [item] = read.outbox()
    assert item["kind"] == "fire" and item["status"] == "pending" and item["photo_path"] == str(photo)
    assert read.incident(incident_id)["alert_outbox_id"] == item["id"]
    assert reports and reports[0][0] == incident_id


def check_decision():
    d = decision(verdict=WEAK, scores=(0.4, 0.0))
    assert (d.level, d.level_from, d.rule) == (Level.WASPADA, Level.AMAN, "R2")
    return d


def unverified_then(verdict):
    """A camera held as R4 'unverified', then the AI answers again."""
    engine = DecisionEngine("CAM-01", Settings(root=Path("."), cameras=(CAM,), resources=Resources()))
    ts = datetime(2026, 10, 26, 14, 32, tzinfo=TZ)
    for _ in range(3):
        held = engine.update(LocalDetection("CAM-01", ts, 0.4, 0.0), verdict=None, llm_available=False)
    after = engine.update(LocalDetection("CAM-01", ts, 0.4, 0.0), verdict=verdict, llm_available=True)
    return held, after


def test_check_alert_cooldown(setup):
    alerts, _, read, clock, _, _ = setup()
    d = check_decision()
    alerts.on_level_change(d, None)
    clock.t = 600
    alerts.on_level_change(d, None)
    assert len(read.outbox()) == 1
    clock.t = 901
    alerts.on_level_change(d, None)
    assert [o["kind"] for o in read.outbox()] == ["check", "check"]


def test_no_check_alert_when_falling_from_bahaya(setup):
    alerts, _, read, _, _, _ = setup()
    d = decision()
    falling = SimpleNamespace(level=Level.WASPADA, level_from=Level.BAHAYA, camera_id="CAM-01")
    alerts.on_level_change(falling, None)
    alerts.on_level_change(d, None)  # BAHAYA itself is handled by on_incident_opened
    assert read.outbox() == []


def test_unverified_check_stays_on_dashboard(setup):
    alerts, _, read, _, _, _ = setup()
    held, _ = unverified_then(None)
    assert held.rule == "R4" and held.sub_status == "unverified"
    alerts.on_level_change(held, None)
    assert read.outbox() == []


def test_unverified_check_sent_once_ai_confirms(setup):
    alerts, _, read, _, _, _ = setup()
    held, after = unverified_then(WEAK)
    assert (after.level, after.changed, after.sub_status) == (Level.WASPADA, False, None)
    alerts.on_level_change(held, None)
    alerts.on_sub_status_change(after, None)
    alerts.on_sub_status_change(after, None)  # only once
    [item] = read.outbox()
    assert item["kind"] == "check" and "belum terverifikasi" not in item["text"]


def test_unverified_check_dropped_when_ai_rejects(setup):
    alerts, _, read, _, _, _ = setup()
    held, after = unverified_then(FOG)
    assert after.sub_status == "rejected_lookalike"
    alerts.on_level_change(held, None)
    alerts.on_sub_status_change(after, None)
    assert read.outbox() == []


def test_sub_status_change_without_hold_sends_nothing(setup):
    alerts, _, read, _, _, _ = setup()
    _, after = unverified_then(WEAK)
    alerts.on_sub_status_change(after, None)
    assert read.outbox() == []


def test_dry_run_without_telegram_or_auto_send(setup):
    for overrides in ({"auto_send_alert": False}, {"telegram_bot_token": None}):
        alerts, storage, read, _, _, _ = setup(**overrides)
        alerts.on_level_change(check_decision(), None)
        assert read.outbox()[0]["status"] == "dry_run"
        storage.close()


def test_risk_rise_alerts_only_when_rising_to_high(setup):
    alerts, _, read, _, _, _ = setup()
    alerts.on_risk(snapshot("Sedang"))  # first value after install: no alert
    alerts.on_risk(snapshot("Tinggi"))
    alerts.on_risk(snapshot("Tinggi"))
    alerts.on_risk(snapshot("Sedang"))
    alerts.on_risk(snapshot("Sangat Tinggi"))
    assert [o["kind"] for o in read.outbox()] == ["risk", "risk"]


def test_morning_summary_once_per_day(setup):
    alerts, storage, read, _, wall, _ = setup()
    storage.upsert_camera_status("CAM-01", name="Kaki Dian", level="AMAN", online=1)
    assert alerts.maybe_send_morning_summary() is False  # 06:00, too early
    wall[0] = datetime(2026, 10, 27, 7, 5, tzinfo=TZ)
    assert alerts.maybe_send_morning_summary() is True
    assert alerts.maybe_send_morning_summary() is False
    wall[0] += timedelta(days=1)
    assert alerts.maybe_send_morning_summary() is True
    assert [o["kind"] for o in read.outbox()] == ["morning", "morning"]


# --- Telegram + outbox -------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_telegram_client_photo_and_text(tmp_path):
    photo = tmp_path / "x.jpg"
    photo.write_bytes(b"\xff\xd8jpeg")
    session = FakeSession(FakeResponse(200, {"ok": True}), FakeResponse(200, {"ok": True}))
    client = TelegramClient("123:SECRET", "42", session=session)
    client.send("halo", str(photo))
    client.send("teks saja", str(tmp_path / "missing.jpg"))
    assert session.calls[0][0].endswith("/sendPhoto") and session.calls[0][1]["data"]["caption"] == "halo"
    assert session.calls[1][0].endswith("/sendMessage")


@pytest.mark.parametrize(
    ("response", "permanent", "retry_after"),
    [
        (FakeResponse(429, {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 7}}), False, 7),
        (FakeResponse(400, {"ok": False, "description": "Bad Request: chat not found"}), True, None),
        (FakeResponse(502, {}), False, None),
    ],
)
def test_telegram_errors_are_classified(response, permanent, retry_after):
    client = TelegramClient("123:SECRET", "42", session=FakeSession(response))
    with pytest.raises(TelegramError) as exc:
        client.send("x")
    assert exc.value.permanent is permanent and exc.value.retry_after == retry_after


def test_network_error_never_shows_token():
    import requests

    client = TelegramClient("123:SECRET", "42", session=FakeSession(requests.ConnectionError("https://api.telegram.org/bot123:SECRET/x")))
    with pytest.raises(TelegramError) as exc:
        client.send("x")
    assert "SECRET" not in str(exc.value)


def test_outbox_sender_retries_then_sends(tmp_path):
    settings = Settings(root=tmp_path, cameras=(CAM,), resources=Resources())
    storage = Storage(settings.db_path)
    now = [now_local()]
    session = FakeSession(FakeResponse(502, {}), FakeResponse(200, {"ok": True}))
    sender = OutboxSender(storage, TelegramClient("123:SECRET", "42", session=session), clock=lambda: now[0])
    incident = storage.open_incident("CAM-01", now[0], "BAHAYA", None)
    oid = storage.enqueue("fire", "pesan", incident_id=incident)
    assert sender.send_due() == 0
    item = storage.outbox_item(oid)
    assert item["status"] == "pending" and item["attempts"] == 1 and "502" in item["last_error"]
    assert sender.send_due() == 0  # backoff not over yet
    now[0] += timedelta(seconds=6)
    assert sender.send_due() == 1
    assert storage.outbox_item(oid)["status"] == "sent"
    assert storage.incident(incident)["alert_sent"] == 1
    health = {h["component"]: h for h in ReadStore(settings.db_path).health()}
    assert health["telegram"]["ok"] == 1
    assert all("SECRET" not in str(v) for row in ReadStore(settings.db_path).outbox() for v in row.values())


def test_outbox_sender_gives_up_on_permanent_error(tmp_path):
    settings = Settings(root=tmp_path, cameras=(CAM,), resources=Resources())
    storage = Storage(settings.db_path)
    sender = OutboxSender(storage, TelegramClient("t", "c", session=FakeSession(FakeResponse(403, {"description": "Forbidden"}))))
    oid = storage.enqueue("check", "x")
    sender.send_due()
    assert storage.outbox_item(oid)["status"] == "failed"


def test_dry_run_items_are_never_sent(tmp_path):
    settings = Settings(root=tmp_path, cameras=(CAM,), resources=Resources())
    storage = Storage(settings.db_path)
    session = FakeSession()
    storage.enqueue("check", "x", status="dry_run")
    assert OutboxSender(storage, TelegramClient("t", "c", session=session)).send_due() == 0
    assert session.calls == []


def test_morning_summary_window_and_weather_wait(tmp_path):
    settings = Settings(root=tmp_path, cameras=(CAM,), resources=Resources())
    storage = Storage(settings.db_path)
    wall = [datetime(2026, 10, 27, 23, 0, tzinfo=TZ)]
    risk = [None]
    alerts = AlertService(settings, storage, risk_provider=lambda: risk[0], wall_clock=lambda: wall[0])
    assert alerts.maybe_send_morning_summary() is False  # evening start: outside the window
    wall[0] = datetime(2026, 10, 28, 7, 5, tzinfo=TZ)
    assert alerts.maybe_send_morning_summary() is False  # waiting for the first weather data
    risk[0] = RISK
    assert alerts.maybe_send_morning_summary() is True
