"""Stage 2: vision LLM verification (ARCHITECTURE §5).

Talks to any OpenAI-compatible chat endpoint (9router by default). The model
must answer with the JSON contract of §5.1; anything else becomes an
`LLMVerdict` with `error` set, never an exception.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

import cv2
import numpy as np
import openai

from mataklabat.camera import Frame
from mataklabat.config import Settings
from mataklabat.prompts import PromptContext, build_prompt

log = logging.getLogger(__name__)

TIMEOUT_S = 20.0
MAX_IMAGE_SIDE = 1024
JPEG_QUALITY = 85
MAX_EVIDENCE = 4
MAX_REASONING_WORDS = 60
MAX_ACTION_WORDS = 25

HAZARD_TYPES = ("none", "smoke", "flame", "smoke_and_flame", "haze", "uncertain")
LOOKALIKES = ("none", "fog_cloud", "sunset_glare", "artificial_light", "dust", "steam", "other")
SEVERITIES = ("none", "low", "medium", "high")
RISK_FACTORS = (
    "dry_vegetation", "campfire", "people_burning", "trash_burning", "strong_wind_signs", "none",
)

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fire_visible": {"type": "boolean"},
        "smoke_visible": {"type": "boolean"},
        "hazard_type": {"type": "string", "enum": list(HAZARD_TYPES)},
        "lookalike": {"type": "string", "enum": list(LOOKALIKES)},
        "confidence": {"type": "number"},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "risk_factors": {"type": "array", "items": {"type": "string", "enum": list(RISK_FACTORS)}},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
        "recommended_action": {"type": "string"},
    },
    "required": [
        "fire_visible", "smoke_visible", "hazard_type", "lookalike", "confidence",
        "severity", "risk_factors", "evidence", "reasoning", "recommended_action",
    ],
    "additionalProperties": False,
}

# Not every provider behind the router honours `response_format`, so the
# contract is also stated in the system message.
SYSTEM_PROMPT = (
    "Jawab HANYA dengan satu objek JSON yang valid, tanpa teks lain dan tanpa markdown, "
    "mengikuti JSON Schema ini: " + json.dumps(VERDICT_SCHEMA, separators=(",", ":")) + ". "
    f"confidence adalah angka 0 sampai 1. evidence maksimal {MAX_EVIDENCE} butir. "
    f"reasoning maksimal {MAX_REASONING_WORDS} kata, recommended_action maksimal {MAX_ACTION_WORDS} kata."
)


class VerdictParseError(ValueError):
    pass


@dataclass(frozen=True)
class LLMVerdict:
    fire_visible: bool = False
    smoke_visible: bool = False
    hazard_type: str = "none"
    lookalike: str = "none"
    confidence: float = 0.0
    severity: str = "none"
    risk_factors: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    reasoning: str = ""
    recommended_action: str = ""
    prompt_version: str = ""
    model: str = ""
    latency_s: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def positive(self) -> bool:
        return self.ok and (self.fire_visible or self.smoke_visible)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_factors"] = list(self.risk_factors)
        data["evidence"] = list(self.evidence)
        return data

    @classmethod
    def failed(cls, error: str, prompt_version: str = "", model: str = "", latency_s: float = 0.0) -> LLMVerdict:
        return cls(prompt_version=prompt_version, model=model, latency_s=latency_s, error=error)


def parse_verdict(text: str) -> dict[str, Any]:
    """Validate a model reply against §5.1 and return clean `LLMVerdict` fields."""
    match = re.search(r"\{.*\}", text or "", flags=re.DOTALL)  # tolerate ```json fences
    if match is None:
        raise VerdictParseError("tidak ada objek JSON di jawaban")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise VerdictParseError(f"JSON tidak valid: {exc}") from None
    if not isinstance(data, dict):
        raise VerdictParseError("jawaban bukan objek JSON")

    def boolean(key: str) -> bool:
        value = data.get(key)
        if not isinstance(value, bool):
            raise VerdictParseError(f"{key} harus boolean, bukan {value!r}")
        return value

    def enum(key: str, allowed: tuple[str, ...]) -> str:
        value = str(data.get(key, "")).strip().lower()
        if value not in allowed:
            raise VerdictParseError(f"{key}={data.get(key)!r} tidak dikenal")
        return value

    def strings(key: str) -> list[str]:
        value = data.get(key, [])
        if not isinstance(value, list):
            raise VerdictParseError(f"{key} harus berupa daftar")
        return [str(v).strip() for v in value if str(v).strip()]

    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise VerdictParseError(f"confidence harus angka, bukan {confidence!r}")
    if 1.0 < confidence <= 100.0:  # some models answer in percent
        confidence /= 100.0

    # "none" is the schema's way to say "no risk"; store that as an empty tuple.
    risks = [r.lower() for r in strings("risk_factors") if r.lower() in RISK_FACTORS and r.lower() != "none"]

    return {
        "fire_visible": boolean("fire_visible"),
        "smoke_visible": boolean("smoke_visible"),
        "hazard_type": enum("hazard_type", HAZARD_TYPES),
        "lookalike": enum("lookalike", LOOKALIKES),
        "confidence": min(1.0, max(0.0, float(confidence))),
        "severity": enum("severity", SEVERITIES),
        "risk_factors": tuple(dict.fromkeys(risks)),
        "evidence": tuple(strings("evidence")[:MAX_EVIDENCE]),
        "reasoning": _limit_words(str(data.get("reasoning", "")), MAX_REASONING_WORDS),
        "recommended_action": _limit_words(str(data.get("recommended_action", "")), MAX_ACTION_WORDS),
    }


class RateLimiter:
    """Global gate: at most one LLM call per `min_interval_s`, shared by all cameras."""

    def __init__(
        self,
        min_interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.min_interval_s = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: float | None = None

    def seconds_until_ready(self) -> float:
        with self._lock:
            if self._last is None:
                return 0.0
            return max(0.0, self._last + self.min_interval_s - self._clock())

    def try_acquire(self) -> bool:
        with self._lock:
            now = self._clock()
            if self._last is not None and now - self._last < self.min_interval_s:
                return False
            self._last = now
            return True

    def acquire(self) -> None:
        while not self.try_acquire():
            self._sleep(max(0.01, self.seconds_until_ready()))


def encode_jpeg(image: np.ndarray, max_side: int = MAX_IMAGE_SIDE, quality: int = JPEG_QUALITY) -> bytes:
    h, w = image.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1.0:
        image = cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("gagal meng-encode JPEG")
    return buf.tobytes()


class VisionVerifier:
    def __init__(self, settings: Settings, client: Any = None, limiter: RateLimiter | None = None):
        self.settings = settings
        self.model = settings.llm_model or ""
        self.client = client or openai.OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "tanpa-key",
            timeout=TIMEOUT_S,
            max_retries=0,  # the decision engine retries on its own schedule
        )
        self.limiter = limiter or RateLimiter(settings.llm_min_interval_s)
        self._structured_output = True

    def verify(
        self,
        frame: Frame | np.ndarray,
        ctx: PromptContext,
        prompt_version: str | None = None,
        *,
        block: bool = True,
        limit: bool = True,
    ) -> LLMVerdict:
        """Ask the LLM about one image.

        `block=False` returns `rate_limited` instead of waiting. `limit=False` skips the
        limiter for callers that already acquired it (the pipeline's LLMScheduler).
        """
        version = prompt_version or self.settings.prompt_version
        if not self.settings.llm_enabled:
            return LLMVerdict.failed("llm_disabled", version, self.model)
        if limit and block:
            self.limiter.acquire()
        elif limit and not self.limiter.try_acquire():
            return LLMVerdict.failed("rate_limited", version, self.model)

        image = frame.image if isinstance(frame, Frame) else frame
        image_url = "data:image/jpeg;base64," + base64.b64encode(encode_jpeg(image)).decode("ascii")
        prompt = build_prompt(version, ctx)
        started = time.monotonic()

        for attempt in (1, 2):  # §5.1: one retry when the reply cannot be parsed
            try:
                text = self._complete(prompt, image_url)
            except openai.APIError as exc:
                log.warning("LLM gagal (%s): %s", self.model, exc)
                return LLMVerdict.failed(
                    f"api_error: {type(exc).__name__}", version, self.model, time.monotonic() - started
                )
            try:
                fields = parse_verdict(text)
            except VerdictParseError as exc:
                log.warning("Jawaban LLM tidak sesuai skema (percobaan %d): %s", attempt, exc)
                continue
            return LLMVerdict(
                **fields,
                prompt_version=version,
                model=self.model,
                latency_s=round(time.monotonic() - started, 2),
            )
        return LLMVerdict.failed("parse_failed", version, self.model, time.monotonic() - started)

    def _complete(self, prompt: str, image_url: str) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]
        if self._structured_output:
            try:
                return self._create(
                    messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": "llm_verdict", "strict": True, "schema": VERDICT_SCHEMA},
                    },
                )
            except openai.BadRequestError as exc:
                # Some providers reject json_schema; fall back to the system-prompt contract.
                log.warning("Endpoint menolak response_format (%s); lanjut tanpa structured output.", exc)
                self._structured_output = False
        return self._create(messages)

    def _create(self, messages: list[dict], **kwargs: Any) -> str:
        resp = self.client.chat.completions.create(model=self.model, messages=messages, **kwargs)
        return resp.choices[0].message.content or ""


def _limit_words(text: str, limit: int) -> str:
    words = text.split()
    return text.strip() if len(words) <= limit else " ".join(words[:limit]) + "…"
