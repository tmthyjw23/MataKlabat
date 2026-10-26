"""Decision Engine: fuses evidence into AMAN / WASPADA / BAHAYA (ARCHITECTURE §6).

Rules R1-R6 are evaluated in order and the first match wins; R0 is the default.
Every decision carries a trace whose `explanation` comes from a fixed template,
never from the LLM, so it always matches the rule that actually fired.

A "step" is one processed frame. Clearing (R6) counts clean steps:
- with the LLM available, only steps that bring a new verdict count;
- without the LLM, every frame where trigger T1 is inactive counts.
Steps that bring no new information keep the last rule and its explanation.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from mataklabat.config import Settings
from mataklabat.detector import LocalDetection
from mataklabat.vision_llm import LLMVerdict


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

SUB_POTENSI = "POTENSI"
SUB_UNVERIFIED = "unverified"
SUB_REJECTED_LOOKALIKE = "rejected_lookalike"

POTENTIAL_RISKS = ("campfire", "people_burning", "trash_burning")

_RISK_NAMES = {
    "campfire": "api unggun",
    "people_burning": "orang membakar",
    "trash_burning": "pembakaran sampah",
    "dry_vegetation": "vegetasi kering",
    "strong_wind_signs": "tanda angin kencang",
}
_LOOKALIKE_NAMES = {
    "fog_cloud": "kabut/awan",
    "sunset_glare": "cahaya matahari terbit/terbenam",
    "artificial_light": "lampu buatan",
    "dust": "debu",
    "steam": "uap",
    "other": "objek lain",
}


def fri_category(fri: int | None) -> str | None:
    """FRI category (§6.1): < 30 RENDAH, 30-59 SEDANG, >= 60 TINGGI."""
    if fri is None:
        return None
    return "RENDAH" if fri < 30 else "SEDANG" if fri < 60 else "TINGGI"


@dataclass(frozen=True)
class Decision:
    camera_id: str
    ts: datetime
    level: Level
    level_from: Level
    rule: str
    sub_status: str | None
    trace: dict[str, Any] = field(repr=False)
    verdict: LLMVerdict | None = field(default=None, repr=False)
    fri: int | None = None

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
        self.verdicts: deque[LLMVerdict] = deque(maxlen=settings.confirm_window)
        self._clear_steps = 0
        self._last_observed: LocalDetection | None = None
        self._last_rule = "R0"
        self._last_explanation = "AMAN karena belum ada bukti api atau asap."

    def danger_threshold(self, fri: int | None) -> float:
        s = self.settings
        return s.conf_danger_high_risk if fri is not None and fri >= s.fri_high else s.conf_danger

    def observe(self, local: LocalDetection) -> None:
        """Feed the T1 window. `update` calls this itself unless it was already done."""
        if local is not self._last_observed:
            self.t1.push(local)
            self._last_observed = local

    def update(
        self,
        local: LocalDetection,
        *,
        verdict: LLMVerdict | None = None,
        llm_available: bool,
        fri: int | None = None,
    ) -> Decision:
        self.observe(local)
        level_from = self.level
        threshold = self.danger_threshold(fri)
        new_verdict = verdict if verdict is not None and verdict.ok else None
        if new_verdict is not None:
            self.verdicts.append(new_verdict)
        confirmations = self._confirmations(threshold) if new_verdict is not None else 0

        inputs: dict[str, Any] = {
            "local": {
                "fire_score": round(local.fire_score, 3),
                "smoke_score": round(local.smoke_score, 3),
                "t1_hits": self.t1.describe(),
            },
            "llm": _llm_input(verdict) if verdict is not None else (None if llm_available else "llm_unavailable"),
            "confirm": f"{confirmations}/{self.settings.confirm_window}" if new_verdict else None,
            "risk": None if fri is None else {
                "fri": fri, "category": fri_category(fri), "threshold_used": threshold,
            },
        }

        rule, explanation = self._evaluate(new_verdict, llm_available, threshold, confirmations, fri)
        if rule == "R6":
            inputs["clear"] = f"{self._clear_steps}/{self.settings.clear_steps}"

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
            verdict=verdict,
            fri=fri,
        )

    # --- rules ------------------------------------------------------------------

    def _evaluate(
        self,
        v: LLMVerdict | None,
        llm_available: bool,
        threshold: float,
        confirmations: int,
        fri: int | None,
    ) -> tuple[str, str]:
        s = self.settings
        clean_step = False

        if v is not None:
            real = v.positive and v.lookalike == "none"
            confirmed = confirmations >= s.confirm_min or v.confidence >= s.conf_single_confirm
            potential = [r for r in v.risk_factors if r in POTENTIAL_RISKS]

            if real and v.confidence >= threshold and confirmed:
                self._raise_to(Level.BAHAYA, None)
                return self._remember("R1", self._explain_r1(v, threshold, confirmations, fri))
            if real and v.confidence >= s.conf_warn:
                self._raise_to(Level.WASPADA, None)
                return self._remember("R2", self._explain_r2(v, threshold, confirmations))
            if v.hazard_type == "uncertain" and self.t1.active:
                self._raise_to(Level.WASPADA, None)
                return self._remember(
                    "R2",
                    f"WASPADA karena LLM ragu (uncertain, keyakinan {v.confidence:.2f}) sementara "
                    f"detektor lokal aktif pada {self.t1.describe()} frame terakhir.",
                )
            if potential:
                self._raise_to(Level.WASPADA, SUB_POTENSI)
                names = ", ".join(_RISK_NAMES[r] for r in potential)
                return self._remember(
                    "R3",
                    f"WASPADA (POTENSI) karena LLM melihat faktor risiko: {names}. "
                    "Belum ada api atau asap kebakaran.",
                )
            if v.positive and v.lookalike != "none":
                self.sub_status = SUB_REJECTED_LOOKALIKE
                what = _hazard_words(v)
                lookalike = _LOOKALIKE_NAMES.get(v.lookalike, v.lookalike)
                return self._remember(
                    "R5",
                    f"Tetap {self.level.value}: LLM melihat {what} (keyakinan {v.confidence:.2f}) "
                    f"tetapi menilainya sebagai lookalike ({lookalike}), sehingga ditolak.",
                )
            clean_step = True
        elif not llm_available:
            if self.t1.active:
                self._raise_to(Level.WASPADA, SUB_UNVERIFIED)
                return self._remember("R4", self._explain_r4())
            clean_step = True
        # else: LLM available but no verdict this step, so nothing new is known.

        if not clean_step:
            if self.level == Level.AMAN:
                waiting = " T1 aktif, menunggu verifikasi LLM." if self.t1.active else ""
                return "R0", f"AMAN karena belum ada verdict LLM yang menunjukkan bahaya.{waiting}"
            return self._last_rule, f"Masih berlaku: {self._last_explanation}"

        if self.level != Level.AMAN:
            return self._remember("R6", self._step_clear(llm_available))
        self.sub_status = None
        self._clear_steps = 0
        source = "verdict LLM" if llm_available else "detektor lokal"
        return self._remember("R0", f"AMAN karena tidak ada bukti api atau asap dari {source}.")

    def _confirmations(self, threshold: float) -> int:
        return sum(
            1 for v in self.verdicts
            if v.positive and v.lookalike == "none" and v.confidence >= threshold
        )

    def _raise_to(self, level: Level, sub_status: str | None) -> None:
        """Evidence present: never lower the level (only R6 lowers), restart the clear count."""
        if level.rank >= self.level.rank:
            self.level = level
            self.sub_status = sub_status
        self._clear_steps = 0

    def _step_clear(self, llm_available: bool) -> str:
        level_from = self.level
        self._clear_steps += 1
        needed = self.settings.clear_steps
        unit = "verdict LLM bersih" if llm_available else "langkah bersih"
        if self._clear_steps < needed:
            return (
                f"Tetap {level_from.value}: tidak ada bukti baru, "
                f"{self._clear_steps}/{needed} {unit} sebelum turun level."
            )
        self.level = level_from.lower()
        self.sub_status = None
        self._clear_steps = 0
        return (
            f"Turun dari {level_from.value} ke {self.level.value} karena "
            f"{needed} {unit} berturut-turut tanpa bukti api atau asap."
        )

    def _remember(self, rule: str, explanation: str) -> tuple[str, str]:
        self._last_rule, self._last_explanation = rule, explanation
        return rule, explanation

    # --- explanation templates -----------------------------------------------------

    def _explain_r1(self, v: LLMVerdict, threshold: float, confirmations: int, fri: int | None) -> str:
        s = self.settings
        lowered = f", ambang diturunkan karena FRI {fri}" if threshold < s.conf_danger else ""
        if confirmations >= s.confirm_min:
            confirm = f"terkonfirmasi {confirmations} dari {s.confirm_window} cek"
        else:
            confirm = f"cukup 1 cek karena keyakinan ≥ {s.conf_single_confirm:.2f}"
        return (
            f"BAHAYA karena LLM melihat {_hazard_words(v)} ({v.confidence:.2f} ≥ {threshold:.2f}"
            f"{lowered}), bukan lookalike, {confirm}."
        )

    def _explain_r2(self, v: LLMVerdict, threshold: float, confirmations: int) -> str:
        s = self.settings
        if v.confidence < threshold:
            reason = f"di bawah ambang BAHAYA {threshold:.2f}"
        else:
            reason = f"baru {confirmations} dari {s.confirm_min} konfirmasi yang dibutuhkan"
        return f"WASPADA karena LLM melihat {_hazard_words(v)} dengan keyakinan {v.confidence:.2f} ({reason})."

    def _explain_r4(self) -> str:
        s = self.settings
        local = self._last_observed
        return (
            f"WASPADA (belum terverifikasi) karena detektor lokal melihat tanda api/asap pada "
            f"{self.t1.describe()} frame terakhir (api {local.fire_score:.2f}, ambang {s.fire_trigger:.2f}; "
            f"asap {local.smoke_score:.2f}, ambang {s.smoke_trigger:.2f}) dan verifikasi LLM tidak tersedia."
        )


def _hazard_words(v: LLMVerdict) -> str:
    if v.fire_visible and v.smoke_visible:
        return "api dan asap"
    return "api" if v.fire_visible else "asap"


def _llm_input(v: LLMVerdict) -> dict[str, Any]:
    if not v.ok:
        return {"error": v.error, "prompt": v.prompt_version}
    return {
        "hazard_type": v.hazard_type,
        "confidence": v.confidence,
        "lookalike": v.lookalike,
        "prompt": v.prompt_version,
    }
