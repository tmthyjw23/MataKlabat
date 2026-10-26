import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import openai
import pytest

from mataklabat import __main__ as cli
from mataklabat.config import Resources, Settings
from mataklabat.prompts import PROMPT_V1, PromptContext, build_prompt, facing_description
from mataklabat.vision_llm import (
    RateLimiter,
    VerdictParseError,
    VisionVerifier,
    encode_jpeg,
    parse_verdict,
)

SPEC_EXAMPLE = {  # ARCHITECTURE §5.1
    "fire_visible": False,
    "smoke_visible": True,
    "hazard_type": "smoke",
    "lookalike": "none",
    "confidence": 0.82,
    "severity": "medium",
    "risk_factors": ["dry_vegetation"],
    "evidence": ["kolom asap abu-abu naik dari lereng kiri", "pangkal asap menyatu dengan vegetasi"],
    "reasoning": "Asap berbentuk kolom yang naik dan bergulung dari satu titik di permukaan tanah.",
    "recommended_action": "Verifikasi lapangan ke sektor barat laut kamera.",
}
FIRE = {**SPEC_EXAMPLE, "fire_visible": True, "hazard_type": "smoke_and_flame", "confidence": 0.93}
FOREST = {
    **SPEC_EXAMPLE, "smoke_visible": False, "hazard_type": "none", "confidence": 0.9,
    "severity": "none", "risk_factors": ["none"], "evidence": ["hutan hijau tanpa asap"],
}

CTX = PromptContext(
    camera_name="Monumen Kaki Dian (Airmadidi)",
    facing_deg=60,
    local_time=datetime(2026, 10, 26, 14, 32, tzinfo=ZoneInfo("Asia/Makassar")),
    fire_score=0.31,
    smoke_score=0.44,
)
IMAGE = np.full((480, 640, 3), (40, 110, 30), dtype=np.uint8)


def _response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class FakeClient:
    """Mimics `client.chat.completions.create`; replies are strings or exceptions."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _response(reply)


def settings(tmp_path=Path("."), **overrides) -> Settings:
    values = dict(
        root=tmp_path, cameras=(), resources=Resources(),
        llm_model="test/vision-model", llm_enabled=True, llm_min_interval_s=0.0,
    )
    values.update(overrides)
    return Settings(**values)


def bad_request(message="response_format json_schema is not supported"):
    request = openai._base_client.httpx2.Request("POST", "http://localhost:20128/v1/chat/completions")
    response = openai._base_client.httpx2.Response(400, request=request)
    return openai.BadRequestError(message, response=response, body=None)


def connection_error():
    request = openai._base_client.httpx2.Request("POST", "http://localhost:20128/v1/chat/completions")
    return openai.APIConnectionError(request=request)


# --- parse_verdict ---------------------------------------------------------


def test_parse_spec_example():
    fields = parse_verdict(json.dumps(SPEC_EXAMPLE))
    assert fields["smoke_visible"] is True and fields["hazard_type"] == "smoke"
    assert fields["confidence"] == 0.82
    assert fields["risk_factors"] == ("dry_vegetation",)
    assert len(fields["evidence"]) == 2


def test_parse_tolerates_markdown_fence_and_case():
    text = "```json\n" + json.dumps({**SPEC_EXAMPLE, "hazard_type": "Smoke"}) + "\n```"
    assert parse_verdict(text)["hazard_type"] == "smoke"


@pytest.mark.parametrize(("raw", "expected"), [(82, 0.82), (1.5, 0.015), (-0.2, 0.0), (250, 1.0)])
def test_parse_normalises_confidence(raw, expected):
    assert parse_verdict(json.dumps({**SPEC_EXAMPLE, "confidence": raw}))["confidence"] == pytest.approx(expected)


def test_parse_cleans_lists_and_text():
    data = {
        **SPEC_EXAMPLE,
        "risk_factors": ["none", "campfire", "aliens", "campfire"],
        "evidence": [f"bukti {i}" for i in range(7)],
        "reasoning": " ".join(["kata"] * 80),
    }
    fields = parse_verdict(json.dumps(data))
    assert fields["risk_factors"] == ("campfire",)
    assert len(fields["evidence"]) == 4
    assert len(fields["reasoning"].split()) == 60


@pytest.mark.parametrize(
    "text",
    [
        "Saya melihat asap.",
        "{not json}",
        json.dumps([SPEC_EXAMPLE]).replace("[", "", 1).replace("]", "", 1)[:20],
        json.dumps({**SPEC_EXAMPLE, "hazard_type": "volcano"}),
        json.dumps({**SPEC_EXAMPLE, "lookalike": "ghost"}),
        json.dumps({**SPEC_EXAMPLE, "fire_visible": "yes"}),
        json.dumps({**SPEC_EXAMPLE, "confidence": "tinggi"}),
        json.dumps({k: v for k, v in SPEC_EXAMPLE.items() if k != "smoke_visible"}),
    ],
)
def test_parse_rejects_invalid(text):
    with pytest.raises(VerdictParseError):
        parse_verdict(text)


# --- VisionVerifier ----------------------------------------------------------


def test_verify_fire_image():
    client = FakeClient(json.dumps(FIRE))
    verdict = VisionVerifier(settings(), client=client).verify(IMAGE, CTX, "v2")
    assert verdict.ok and verdict.positive and verdict.fire_visible
    assert (verdict.prompt_version, verdict.model) == ("v2", "test/vision-model")

    call = client.calls[0]
    assert call["model"] == "test/vision-model"
    assert call["response_format"]["type"] == "json_schema"
    text_part, image_part = call["messages"][1]["content"]
    assert "Monumen Kaki Dian" in text_part["text"] and "0.31" in text_part["text"]
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_verify_forest_image_is_not_positive():
    verdict = VisionVerifier(settings(), client=FakeClient(json.dumps(FOREST))).verify(IMAGE, CTX)
    assert verdict.ok and not verdict.positive
    assert verdict.hazard_type == "none" and verdict.risk_factors == ()


def test_verify_retries_parse_once():
    client = FakeClient("maaf, saya tidak yakin", json.dumps(FIRE))
    verdict = VisionVerifier(settings(), client=client).verify(IMAGE, CTX)
    assert verdict.ok and len(client.calls) == 2


def test_verify_parse_failure_returns_error_verdict():
    client = FakeClient("bukan json", "masih bukan json")
    verdict = VisionVerifier(settings(), client=client).verify(IMAGE, CTX)
    assert verdict.error == "parse_failed" and not verdict.positive
    assert len(client.calls) == 2


def test_verify_api_error_returns_error_verdict():
    verdict = VisionVerifier(settings(), client=FakeClient(connection_error())).verify(IMAGE, CTX)
    assert verdict.error == "api_error: APIConnectionError"


def test_verify_falls_back_when_response_format_rejected():
    client = FakeClient(bad_request(), json.dumps(FIRE), json.dumps(FOREST))
    verifier = VisionVerifier(settings(), client=client)
    assert verifier.verify(IMAGE, CTX).ok
    assert "response_format" in client.calls[0] and "response_format" not in client.calls[1]
    verifier.verify(IMAGE, CTX)
    assert "response_format" not in client.calls[2]  # remembered for later calls


def test_verify_disabled_makes_no_call():
    client = FakeClient()
    verdict = VisionVerifier(settings(llm_enabled=False), client=client).verify(IMAGE, CTX)
    assert verdict.error == "llm_disabled" and client.calls == []


def test_verify_v1_uses_plain_prompt():
    client = FakeClient(json.dumps(FOREST))
    VisionVerifier(settings(), client=client).verify(IMAGE, CTX, "v1")
    assert client.calls[0]["messages"][1]["content"][0]["text"] == PROMPT_V1


# --- rate limiting -----------------------------------------------------------


class FakeTime:
    def __init__(self):
        self.now = 100.0
        self.slept = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept += seconds
        self.now += seconds


def test_non_blocking_calls_respect_min_interval():
    t = FakeTime()
    limiter = RateLimiter(8.0, clock=t.clock, sleep=t.sleep)
    client = FakeClient(json.dumps(FIRE), json.dumps(FIRE))
    verifier = VisionVerifier(settings(), client=client, limiter=limiter)
    assert verifier.verify(IMAGE, CTX, block=False).ok
    t.now += 3
    assert verifier.verify(IMAGE, CTX, block=False).error == "rate_limited"
    t.now += 5
    assert verifier.verify(IMAGE, CTX, block=False).ok
    assert len(client.calls) == 2


def test_blocking_calls_wait_for_min_interval():
    t = FakeTime()
    limiter = RateLimiter(8.0, clock=t.clock, sleep=t.sleep)
    verifier = VisionVerifier(settings(), client=FakeClient(json.dumps(FIRE), json.dumps(FIRE)), limiter=limiter)
    verifier.verify(IMAGE, CTX)
    verifier.verify(IMAGE, CTX)
    assert t.slept == pytest.approx(8.0)


# --- helpers -----------------------------------------------------------------


def test_encode_jpeg_limits_size():
    big = np.zeros((1000, 2000, 3), dtype=np.uint8)
    decoded = cv2.imdecode(np.frombuffer(encode_jpeg(big), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (512, 1024)
    small = cv2.imdecode(np.frombuffer(encode_jpeg(IMAGE), np.uint8), cv2.IMREAD_COLOR)
    assert small.shape[:2] == (480, 640)


def test_prompt_v2_context():
    text = build_prompt("v2", CTX)
    assert '"Monumen Kaki Dian (Airmadidi)"' in text
    assert "timur laut (60°)" in text and "14:32" in text
    assert "api 0.31 dan asap 0.44" in text
    assert "Cuaca: tidak tersedia." in text
    weather = PromptContext(**{**CTX.__dict__, "temp_c": 31.6, "rh_pct": 48, "wind_kmh": 18.2})
    assert "suhu 32°C, kelembapan 48%, angin 18 km/j" in build_prompt("v2", weather)


def test_facing_description():
    assert facing_description(0) == "arah utara (0°)"
    assert facing_description(270) == "arah barat (270°)"
    assert facing_description(350) == "arah utara (350°)"


def test_check_llm_reports_reply_and_errors():
    ok = cli.check_llm(settings(), client=FakeClient("OK"))
    assert ok[1] is True and "'OK'" in ok[2]
    failed = cli.check_llm(settings(), client=FakeClient(connection_error()))
    assert failed[1] is False and "APIConnectionError" in failed[2]
    assert cli.check_llm(settings(llm_enabled=False))[1] is False
