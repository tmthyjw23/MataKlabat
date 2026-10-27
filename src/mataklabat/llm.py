"""LLM providers: presets for OpenAI-compatible endpoints and an ordered failover pool.

Every provider here speaks the OpenAI chat-completions API (Google AI Studio and
Ollama ship such an endpoint), so one client type serves them all. The pool keeps
the order from .env: the primary first, then LLM_FALLBACKS. An endpoint that fails
(API error, or replies that are not the expected JSON) rests for a few minutes and
the next one is used; after the rest it is tried first again.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import openai

log = logging.getLogger(__name__)

# name -> (base URL, environment variable holding its API key)
PROVIDERS: dict[str, tuple[str | None, str | None]] = {
    "9router": ("http://localhost:20128/v1", "NINEROUTER_API_KEY"),
    "aistudio": ("https://generativelanguage.googleapis.com/v1beta/openai/", "AISTUDIO_API_KEY"),
    "ollama": ("http://127.0.0.1:11434/v1", None),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "custom": (None, "CUSTOM_API_KEY"),
}
REST_S = 300.0  # how long a failed endpoint is skipped


@dataclass(frozen=True)
class LLMEndpoint:
    provider: str
    base_url: str
    model: str
    api_key: str | None = field(default=None, repr=False)

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"


class LLMPool:
    """Ordered endpoints with a short rest for the ones that fail. Thread-safe."""

    def __init__(
        self,
        endpoints: tuple[LLMEndpoint, ...] | list[LLMEndpoint],
        timeout_s: float,
        rest_s: float = REST_S,
        clock: Callable[[], float] = time.monotonic,
        clients: dict[str, Any] | None = None,
    ):
        if not endpoints:
            raise ValueError("LLMPool butuh minimal satu endpoint")
        self.endpoints = tuple(endpoints)
        self.timeout_s = timeout_s
        self.rest_s = rest_s
        self._clock = clock
        self._clients: dict[str, Any] = dict(clients or {})
        self._resting: dict[str, tuple[float, str]] = {}  # label -> (until, reason)
        self._last_ok: str | None = None
        self._lock = threading.Lock()

    @property
    def primary(self) -> LLMEndpoint:
        return self.endpoints[0]

    def client(self, ep: LLMEndpoint) -> Any:
        with self._lock:
            if ep.label not in self._clients:
                self._clients[ep.label] = openai.OpenAI(
                    base_url=ep.base_url,
                    api_key=ep.api_key or "tanpa-key",
                    timeout=self.timeout_s,
                    max_retries=0,  # the pool and the decision engine retry on their own schedule
                )
            return self._clients[ep.label]

    def candidates(self) -> list[LLMEndpoint]:
        """Endpoints to try now, in order. When all are resting, the one that is ready
        soonest is tried anyway, so the system never stops asking altogether."""
        now = self._clock()
        with self._lock:
            ready = [ep for ep in self.endpoints if self._resting.get(ep.label, (0.0, ""))[0] <= now]
            if ready:
                return ready
            return [min(self.endpoints, key=lambda ep: self._resting[ep.label][0])]

    def mark_failed(self, ep: LLMEndpoint, reason: str) -> None:
        with self._lock:
            first = ep.label not in self._resting
            self._resting[ep.label] = (self._clock() + self.rest_s, reason)
        if first and len(self.endpoints) > 1:
            log.warning("LLM %s gagal (%s); memakai cadangan selama %.0f menit.", ep.label, reason, self.rest_s / 60)

    def mark_ok(self, ep: LLMEndpoint) -> None:
        with self._lock:
            recovered = self._resting.pop(ep.label, None) is not None
            switched = self._last_ok not in (None, ep.label)
            self._last_ok = ep.label
        if recovered:
            log.info("LLM %s kembali menjawab.", ep.label)
        elif switched:
            log.info("LLM sekarang memakai %s.", ep.label)

    def status(self) -> dict[str, Any]:
        """For the health page: which endpoint answers and which are resting."""
        now = self._clock()
        with self._lock:
            resting = {k: v for k, v in self._resting.items() if v[0] > now}
            last = self._last_ok
        return {
            "active": last,
            "resting": {label: reason for label, (_, reason) in resting.items()},
            "all_resting": len(resting) == len(self.endpoints),
            "order": [ep.label for ep in self.endpoints],
        }


def pool_from_settings(settings, timeout_s: float, client: Any = None) -> LLMPool:
    """The pool for these settings. `client` (tests) serves the primary endpoint."""
    endpoints = settings.llm_chain
    clients = {endpoints[0].label: client} if client is not None else None
    return LLMPool(endpoints, timeout_s, clients=clients)
