"""Decision Engine: fuses evidence into AMAN / WASPADA / BAHAYA (ARCHITECTURE §6).

Rules are evaluated in order and the first match wins. Every decision carries a
trace whose `explanation` comes from a fixed template, never from the LLM.

Implemented so far (T4, local detector only): R4, R6, R0.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from mataklabat.config import Settings
from mataklabat.detector import LocalDetection


class Level(StrEnum):
    AMAN = "AMAN"
    WASPADA = "WASPADA"
    BAHAYA = "BAHAYA"

    @property
    def rank(self) -> int:
        return _RANK[self]

    def lower(self) -> Level:
        return _ORDER[max(0, self.rank - 1)]


_ORDER = (Level.AMAN, Level.WASPADA, Level.BAHAYA)
_RANK = {level: i for i, level in enumerate(_ORDER)}

SUB_UNVERIFIED = "unverified"


@dataclass(frozen=True)
class Decision:
    camera_id: str
    ts: datetime
    level: Level
    level_from: Level
    rule: str
    sub_status: str | None
    trace: dict[str, Any] = field(repr=False)

    @property
    def changed(self) -> bool:
        return self.level != self.level_from

    @property
    def explanation(self) -> str:
        return self.trace["explanation"]


class TriggerWindow:
    """T1: a local score above threshold on >= `min_hits` of the last `size` frames."""

    def __init__(self, size: int, min_hits: int, fire_threshold: float, smoke_threshold: float):
        self.min_hits = min_hits
        self.fire_threshold = fire_threshold
        self.smoke_threshold = smoke_threshold
        self._hits: deque[bool] = deque(maxlen=size)

    def push(self, local: LocalDetection) -> None:
        self._hits.append(
            local.fire_score >= self.fire_threshold or local.smoke_score >= self.smoke_threshold
        )

    @property
    def hits(self) -> int:
        return sum(self._hits)

    @property
    def active(self) -> bool:
        return self.hits >= self.min_hits

    def describe(self) -> str:
        return f"{self.hits}/{self._hits.maxlen}"


class DecisionEngine:
    """State machine for one camera."""

    def __init__(self, camera_id: str, settings: Settings):
        self.camera_id = camera_id
        self.settings = settings
        self.level = Level.AMAN
        self.sub_status: str | None = None
        self.t1 = TriggerWindow(
            settings.trigger_window,
            settings.trigger_min_hits,
            settings.fire_trigger,
            settings.smoke_trigger,
        )
        self._clear_steps = 0

    def update(self, local: LocalDetection, *, llm_available: bool) -> Decision:
        self.t1.push(local)
        level_from = self.level
        inputs = {
            "local": {
                "fire_score": round(local.fire_score, 3),
                "smoke_score": round(local.smoke_score, 3),
                "t1_hits": self.t1.describe(),
            },
            "llm": None if llm_available else "llm_unavailable",
            "confirm": None,
            "risk": None,
        }

        if self.t1.active and not llm_available:
            rule, explanation = "R4", self._explain_r4(local)
            self._raise_to(Level.WASPADA, SUB_UNVERIFIED)
        elif self.level != Level.AMAN:
            rule, explanation = "R6", self._step_clear(level_from)
            inputs["clear"] = f"{self._clear_steps}/{self.settings.clear_steps}"
        else:
            rule, explanation = "R0", "AMAN karena tidak ada bukti api atau asap dari detektor lokal."
            self.sub_status = None
            self._clear_steps = 0

        trace = {
            "rule": rule,
            "level_from": level_from.value,
            "level_to": self.level.value,
            "inputs": inputs,
            "explanation": explanation,
        }
        return Decision(
            camera_id=self.camera_id,
            ts=local.ts,
            level=self.level,
            level_from=level_from,
            rule=rule,
            sub_status=self.sub_status,
            trace=trace,
        )

    def _raise_to(self, level: Level, sub_status: str | None) -> None:
        """Evidence present: never lower the level (only R6 lowers), restart the clear count."""
        if level.rank >= self.level.rank:
            self.level = level
            self.sub_status = sub_status
        self._clear_steps = 0

    def _step_clear(self, level_from: Level) -> str:
        self._clear_steps += 1
        needed = self.settings.clear_steps
        if self._clear_steps < needed:
            return (
                f"Tetap {level_from.value}: tidak ada bukti baru, "
                f"menunggu {self._clear_steps}/{needed} langkah bersih sebelum turun level."
            )
        self.level = level_from.lower()
        self.sub_status = None
        self._clear_steps = 0
        return (
            f"Turun dari {level_from.value} ke {self.level.value} karena "
            f"{needed} langkah berturut-turut tanpa bukti api atau asap."
        )

    def _explain_r4(self, local: LocalDetection) -> str:
        s = self.settings
        return (
            f"WASPADA (belum terverifikasi) karena detektor lokal melihat tanda api/asap pada "
            f"{self.t1.describe()} frame terakhir (api {local.fire_score:.2f}, ambang {s.fire_trigger:.2f}; "
            f"asap {local.smoke_score:.2f}, ambang {s.smoke_trigger:.2f}) dan verifikasi LLM tidak tersedia."
        )
