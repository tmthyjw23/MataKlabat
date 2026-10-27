"""LLM provider presets, fallbacks and failover (llm.py)."""

import json
from pathlib import Path

import pytest

from mataklabat import agent as agent_mod
from mataklabat.alerts import AI_DOWN_NOTICE_S, AlertService
from mataklabat.config import ConfigError, Resources, Settings, load_settings
from mataklabat.llm import PROVIDERS, LLMEndpoint, LLMPool
from mataklabat.monitor import llm_detail
from mataklabat.storage import ReadStore, Storage
from mataklabat.vision_llm import VisionVerifier
from tests.test_agent import FakeClient as AgentClient
from tests.test_agent import make_tools, reply
from tests.test_alerts import CAM, Clock, decision
from tests.test_vision_llm import CTX, FIRE, IMAGE, FakeClient, connection_error

ENV_KEYS = ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_FALLBACKS", "AISTUDIO_API_KEY",
            "OPENROUTER_API_KEY", "NINEROUTER_API_KEY", "CUSTOM_BASE_URL", "CUSTOM_API_KEY", "CAMERAS_FILE",
            "OPERATOR_PASSWORD")


@pytest.fixture
def root(tmp_path, monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "cameras.yaml").write_text(
        "cameras:\n  - {id: CAM-01, name: X, source: v.mp4, lat: 1.4, lon: 125.0}\n", encoding="utf-8")
    return tmp_path


def chain(root):
    return [(e.provider, e.base_url, e.model, e.api_key) for e in load_settings(root, env_file=None).llm_chain]


# --- config -----------------------------------------------------------------------------------


def test_old_settings_still_work(root, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "ag/x")
    monkeypatch.setenv("LLM_API_KEY", "k9")
    assert chain(root) == [("9router", "http://localhost:20128/v1", "ag/x", "k9")]
    monkeypatch.setenv("LLM_BASE_URL", "http://10.0.0.5:9000/v1/")
    assert chain(root) == [("custom", "http://10.0.0.5:9000/v1", "ag/x", "k9")]


def test_preset_wins_over_leftover_url_and_key(root, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "aistudio")
    monkeypatch.setenv("LLM_MODEL", "gemini-flash")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")  # left from Ollama
    monkeypatch.setenv("LLM_API_KEY", "old-9router-key")
    monkeypatch.setenv("AISTUDIO_API_KEY", "AIza-test")
    s = load_settings(root, env_file=None)
    assert chain(root) == [("aistudio", PROVIDERS["aistudio"][0].rstrip("/"), "gemini-flash", "AIza-test")]
    assert s.llm_base_url == PROVIDERS["aistudio"][0].rstrip("/") and "AIza" not in repr(s)


def test_fallbacks_parse_models_with_colons(root, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "aistudio")
    monkeypatch.setenv("LLM_MODEL", "gemini-flash")
    monkeypatch.setenv("AISTUDIO_API_KEY", "AIza-test")
    monkeypatch.setenv("NINEROUTER_API_KEY", "k9")
    monkeypatch.setenv("LLM_FALLBACKS", " ollama:gemma4:31b-cloud , 9router:ag/gemini-3.8-flash-high,")
    assert chain(root) == [
        ("aistudio", PROVIDERS["aistudio"][0].rstrip("/"), "gemini-flash", "AIza-test"),
        ("ollama", "http://127.0.0.1:11434/v1", "gemma4:31b-cloud", None),
        ("9router", "http://localhost:20128/v1", "ag/gemini-3.8-flash-high", "k9"),
    ]


@pytest.mark.parametrize("env, match", [
    ({"LLM_PROVIDER": "openia", "LLM_MODEL": "m"}, "tidak dikenal"),
    ({"LLM_PROVIDER": "custom", "LLM_MODEL": "m"}, "LLM_BASE_URL"),
    ({"LLM_MODEL": "m", "LLM_FALLBACKS": "ollama"}, "provider:model"),
    ({"LLM_MODEL": "m", "LLM_FALLBACKS": "mars:m"}, "tidak dikenal"),
    ({"LLM_FALLBACKS": "ollama:m"}, "LLM_MODEL kosong"),
])
def test_bad_llm_config_is_explained(root, monkeypatch, env, match):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ConfigError, match=match):
        load_settings(root, env_file=None)


# --- failover ---------------------------------------------------------------------------------

A = LLMEndpoint("9router", "http://a/v1", "model-a")
B = LLMEndpoint("ollama", "http://b/v1", "model-b")


def verifier(clients, clock=None):
    pool = LLMPool((A, B), 10.0, clients={A.label: clients[0], B.label: clients[1]},
                   **({"clock": clock} if clock else {}))
    s = Settings(root=Path("."), cameras=(), resources=Resources(), llm_model="model-a", llm_enabled=True,
                 llm_min_interval_s=0.0)
    return VisionVerifier(s, pool=pool), pool


def test_api_error_moves_to_next_endpoint_and_rests_the_first():
    clock = Clock()
    a = FakeClient(connection_error(), json.dumps(FIRE))
    b = FakeClient(json.dumps(FIRE), json.dumps(FIRE))
    v, pool = verifier((a, b), clock)

    first = v.verify(IMAGE, CTX, "v2")
    assert first.ok and first.model == "model-b" and b.calls[0]["model"] == "model-b"
    assert pool.status()["resting"] == {A.label: "api_error: APIConnectionError"}

    second = v.verify(IMAGE, CTX, "v2")  # A is resting: not asked
    assert second.model == "model-b" and len(a.calls) == 1

    clock.t = 301  # rest over: A is first again
    third = v.verify(IMAGE, CTX, "v2")
    assert third.model == "model-a" and pool.status()["resting"] == {}


def test_off_contract_answer_counts_as_failure():
    # e.g. "Gemini 3.5 Flash is no longer available..." with HTTP 200
    retired = "Model ini sudah tidak tersedia."
    v, pool = verifier((FakeClient(retired, retired), FakeClient(json.dumps(FIRE))))
    verdict = v.verify(IMAGE, CTX, "v2")
    assert verdict.ok and verdict.model == "model-b"
    assert pool.status()["resting"] == {A.label: "parse_failed"}


def test_all_endpoints_failing_returns_error_and_keeps_asking():
    clock = Clock()
    v, pool = verifier((FakeClient(connection_error(), connection_error()),
                        FakeClient(connection_error(), connection_error())), clock)
    verdict = v.verify(IMAGE, CTX, "v2")
    assert not verdict.ok and verdict.error.startswith("api_error")
    assert pool.status()["all_resting"]
    clock.t = 1
    assert [e.label for e in pool.candidates()] == [A.label]  # soonest-ready one is still tried
    assert "istirahat" in llm_detail(pool.status())


def test_agent_restarts_report_on_next_endpoint(tmp_path):
    s = Settings(root=tmp_path, cameras=(CAM,), resources=Resources(), llm_model="model-a", llm_enabled=True)
    a = AgentClient(connection_error())
    b = AgentClient(reply(content="## Laporan\nisi"))
    pool = LLMPool((A, B), 10.0, clients={A.label: a, B.label: b})
    report = agent_mod.IncidentAgent(s, make_tools(s), pool=pool).run(CAM, decision())
    assert report.source == "agent" and b.calls[0]["model"] == "model-b"
    assert A.label in pool.status()["resting"]


# --- AI down / up notice ----------------------------------------------------------------------


def test_ai_down_and_up_notices_once(tmp_path):
    s = Settings(root=tmp_path, cameras=(CAM,), resources=Resources(),
                 telegram_bot_token="123:abc", telegram_chat_id="-42", auto_send_alert=True)
    storage = Storage(s.db_path)
    clock = Clock()
    alerts = AlertService(s, storage, clock=clock)
    read = ReadStore(s.db_path)

    alerts.on_ai_status(True, "memakai 9router/x")
    clock.t = AI_DOWN_NOTICE_S - 1
    alerts.on_ai_status(True, "x")
    assert read.outbox() == []
    clock.t = AI_DOWN_NOTICE_S + 1
    alerts.on_ai_status(True, "istirahat: 9router/x (parse_failed)")
    alerts.on_ai_status(True, "x")
    alerts.on_ai_status(None, "kamera mati")  # unknown: keeps the state
    clock.t = 900
    alerts.on_ai_status(False, "memakai ollama/gemma4")
    alerts.on_ai_status(False, "memakai ollama/gemma4")
    texts = [o["text"] for o in reversed(read.outbox())]
    assert len(texts) == 2
    assert texts[0].startswith("⚙️ AI TIDAK TERSEDIA") and "bukan peringatan kebakaran" in texts[0]
    assert texts[1].startswith("✅ AI KEMBALI TERSEDIA") and "±15 menit" in texts[1]
    storage.close()


def test_short_outage_sends_nothing(tmp_path):
    s = Settings(root=tmp_path, cameras=(CAM,), resources=Resources())
    storage = Storage(s.db_path)
    clock = Clock()
    alerts = AlertService(s, storage, clock=clock)
    alerts.on_ai_status(True, "x")
    clock.t = 60
    alerts.on_ai_status(False, "ok")
    assert ReadStore(s.db_path).outbox() == []
    storage.close()


def test_check_flags_a_retired_model_that_still_answers():
    from mataklabat import __main__ as cli

    s = Settings(root=Path("."), cameras=(), resources=Resources(), llm_model="ag/old", llm_enabled=True)
    row = cli.check_llm(s, client=FakeClient("Gemini 3.5 Flash is no longer available. Please switch."))
    assert row[1] is False and "no longer available" in row[2]
