import json
from pathlib import Path

import pytest

from mataklabat.config import Resources, Settings, now_local
from mataklabat.decision import DecisionEngine, Level
from mataklabat.detector import LocalDetection

HIT = (0.40, 0.0)  # fire score above FIRE_TRIGGER (0.15)
SMOKE_HIT = (0.0, 0.30)  # smoke score above SMOKE_TRIGGER (0.20)
CLEAN = (0.0, 0.05)


@pytest.fixture
def engine() -> DecisionEngine:
    settings = Settings(root=Path("."), cameras=(), resources=Resources())
    return DecisionEngine("CAM-01", settings)


def feed(engine, scores, *, llm_available=False, times=1):
    decisions = []
    for _ in range(times):
        local = LocalDetection("CAM-01", now_local(), *scores)
        decisions.append(engine.update(local, llm_available=llm_available))
    return decisions


def raise_to_waspada(engine):
    feed(engine, HIT, times=3)
    assert engine.level == Level.WASPADA


def test_r0_default_is_aman(engine):
    d = feed(engine, CLEAN)[0]
    assert (d.level, d.rule, d.sub_status) == (Level.AMAN, "R0", None)
    assert not d.changed


def test_r4_needs_three_of_five_hits(engine):
    first_two = feed(engine, HIT, times=2)
    assert all(d.level == Level.AMAN and d.rule == "R0" for d in first_two)
    d = feed(engine, HIT)[0]
    assert (d.level, d.rule, d.sub_status) == (Level.WASPADA, "R4", "unverified")
    assert d.changed and d.level_from == Level.AMAN
    assert "3/5" in d.explanation and "tidak tersedia" in d.explanation


def test_r4_counts_smoke_and_non_consecutive_hits(engine):
    for scores in (SMOKE_HIT, CLEAN, SMOKE_HIT, CLEAN):
        feed(engine, scores)
    assert engine.level == Level.AMAN
    d = feed(engine, SMOKE_HIT)[0]  # 3 hits within the last 5 frames
    assert d.rule == "R4" and d.level == Level.WASPADA


def test_r4_does_not_fire_when_llm_available(engine):
    decisions = feed(engine, HIT, times=5, llm_available=True)
    assert all(d.level == Level.AMAN for d in decisions)


def test_r6_steps_down_after_clear_steps(engine):
    raise_to_waspada(engine)
    decisions = feed(engine, CLEAN, times=10)
    rules = [d.rule for d in decisions]
    # The 3-of-5 window keeps T1 active for two more frames, then R6 counts 4 clean steps.
    assert rules[:2] == ["R4", "R4"]
    assert rules[2:6] == ["R6"] * 4
    held, dropped = decisions[2:5], decisions[5]
    assert all(d.level == Level.WASPADA and d.sub_status == "unverified" for d in held)
    assert "1/4 langkah bersih" in held[0].explanation
    assert dropped.level == Level.AMAN and dropped.changed and dropped.sub_status is None
    assert "Turun dari Perlu Dicek ke Normal" in dropped.explanation
    assert rules[6:] == ["R0"] * 4


def test_new_evidence_resets_clear_count(engine):
    raise_to_waspada(engine)
    feed(engine, CLEAN, times=5)  # T1 inactive, 3 clean steps counted
    feed(engine, HIT, times=3)  # evidence again
    decisions = feed(engine, CLEAN, times=5)
    assert all(d.level == Level.WASPADA for d in decisions)


def test_r6_lowers_one_level_at_a_time(engine):
    engine.level = Level.BAHAYA
    decisions = feed(engine, CLEAN, times=8)
    levels = [d.level for d in decisions]
    assert levels[:3] == [Level.BAHAYA] * 3
    assert levels[3:7] == [Level.WASPADA] * 4
    assert levels[7] == Level.AMAN


def test_r4_never_lowers_bahaya(engine):
    engine.level = Level.BAHAYA
    decisions = feed(engine, HIT, times=4)
    assert decisions[-1].rule == "R4"
    assert all(d.level == Level.BAHAYA for d in decisions)


def test_trace_matches_contract(engine):
    feed(engine, HIT, times=2)
    d = feed(engine, HIT)[0]
    trace = json.loads(json.dumps(d.trace))  # must be JSON-serializable for SQLite
    assert set(trace) == {"rule", "level_from", "level_to", "inputs", "explanation"}
    assert trace["rule"] == "R4"
    assert (trace["level_from"], trace["level_to"]) == ("AMAN", "WASPADA")
    assert trace["inputs"]["local"] == {"fire_score": 0.4, "smoke_score": 0.0, "t1_hits": "3/5"}
    assert trace["inputs"]["llm"] == "llm_unavailable"


def test_level_lower():
    assert Level.BAHAYA.lower() == Level.WASPADA
    assert Level.WASPADA.lower() == Level.AMAN
    assert Level.AMAN.lower() == Level.AMAN


# --- T6: rules with LLM verdicts ---------------------------------------------------

from mataklabat.vision_llm import LLMVerdict  # noqa: E402


def v(conf=0.8, *, smoke=True, fire=False, hazard=None, lookalike="none", risks=(), error=None):
    if hazard is None:
        hazard = "smoke_and_flame" if fire and smoke else "flame" if fire else "smoke" if smoke else "none"
    return LLMVerdict(
        fire_visible=fire, smoke_visible=smoke, hazard_type=hazard, lookalike=lookalike,
        confidence=conf, risk_factors=tuple(risks), prompt_version="v2", error=error,
    )


CLEAN_V = v(0.9, smoke=False)


def step(engine, verdict=None, scores=CLEAN, risk=None, llm_available=True):
    local = LocalDetection("CAM-01", now_local(), *scores)
    return engine.update(local, verdict=verdict, llm_available=llm_available, risk_level=risk, fwi=24.0 if risk else None)


def test_r1_single_verdict_above_090_is_enough(engine):
    d = step(engine, v(0.92))
    assert (d.level, d.rule, d.sub_status) == (Level.BAHAYA, "R1", None)
    assert "cukup 1 cek" in d.explanation and "0.92 ≥ 0.70" in d.explanation


def test_r1_verdict_075_needs_two_of_three(engine):
    first = step(engine, v(0.75))
    assert (first.level, first.rule) == (Level.WASPADA, "R2")
    assert "baru 1 dari 2" in first.explanation
    second = step(engine, v(0.75))
    assert (second.level, second.rule) == (Level.BAHAYA, "R1")
    assert "terkonfirmasi 2 dari 3" in second.explanation
    assert second.trace["inputs"]["confirm"] == "2/3"


def test_r1_confirmation_window_slides(engine):
    for verdict in (v(0.75), CLEAN_V, CLEAN_V):
        step(engine, verdict)
    d = step(engine, v(0.75))  # window = [clean, clean, 0.75] -> 1/3
    assert d.level == Level.WASPADA and d.rule == "R2"


def test_r2_confidence_between_warn_and_danger(engine):
    d = step(engine, v(0.55))
    assert (d.level, d.rule) == (Level.WASPADA, "R2")
    assert "di bawah ambang kebakaran 0.70" in d.explanation


def test_positive_below_conf_warn_is_not_evidence(engine):
    d = step(engine, v(0.30))
    assert (d.level, d.rule) == (Level.AMAN, "R0")


def test_r2_uncertain_only_with_active_t1(engine):
    calm = step(engine, v(0.3, smoke=False, hazard="uncertain"))
    assert calm.level == Level.AMAN
    feed(engine, HIT, times=2, llm_available=True)
    d = step(engine, v(0.3, smoke=False, hazard="uncertain"), scores=HIT)
    assert (d.level, d.rule) == (Level.WASPADA, "R2") and "ragu" in d.explanation


def test_r3_potential_risk_factor(engine):
    d = step(engine, v(0.8, smoke=False, risks=["campfire", "dry_vegetation"]))
    assert (d.level, d.rule, d.sub_status) == (Level.WASPADA, "R3", "POTENSI")
    assert "api unggun" in d.explanation


def test_dry_vegetation_alone_is_not_r3(engine):
    assert step(engine, v(0.8, smoke=False, risks=["dry_vegetation"])).level == Level.AMAN


def test_r5_fog_with_high_confidence_is_never_bahaya(engine):
    d = step(engine, v(0.95, lookalike="fog_cloud"))
    assert (d.level, d.rule, d.sub_status) == (Level.AMAN, "R5", "rejected_lookalike")
    assert "kabut/awan" in d.explanation
    for _ in range(3):
        assert step(engine, v(0.95, lookalike="fog_cloud")).level == Level.AMAN


def test_r5_keeps_current_level(engine):
    step(engine, v(0.55))  # WASPADA via R2
    d = step(engine, v(0.95, lookalike="sunset_glare"))
    assert (d.level, d.rule) == (Level.WASPADA, "R5")


@pytest.mark.parametrize(
    ("verdict", "rule"),
    [
        (v(0.95, risks=["campfire"]), "R1"),  # R1 beats R3
        (v(0.55, risks=["campfire"]), "R2"),  # R2 beats R3
        (v(0.95, lookalike="fog_cloud", risks=["campfire"]), "R3"),  # R3 beats R5
    ],
)
def test_rule_priority(engine, verdict, rule):
    assert step(engine, verdict).rule == rule


@pytest.mark.parametrize("level", ["Tinggi", "Sangat Tinggi"])
def test_high_area_risk_lowers_danger_threshold(engine, level):
    step(engine, v(0.65), risk=level)
    d = step(engine, v(0.65), risk=level)
    assert (d.level, d.rule) == (Level.BAHAYA, "R1")
    assert f"ambang diturunkan karena risiko kawasan {level}" in d.explanation
    assert d.trace["inputs"]["risk"] == {"level": level, "fwi": 24.0, "threshold_used": 0.6}
    assert d.risk_level == level


@pytest.mark.parametrize("level", ["Rendah", "Sedang", None])
def test_low_or_unknown_area_risk_keeps_default_threshold(engine, level):
    step(engine, v(0.65), risk=level)
    d = step(engine, v(0.65), risk=level)
    assert (d.level, d.rule) == (Level.WASPADA, "R2")


def test_steps_without_verdict_keep_last_rule(engine):
    step(engine, v(0.92))
    d = step(engine, None, scores=HIT)
    assert (d.level, d.rule) == (Level.BAHAYA, "R1")
    assert d.explanation.startswith("Masih berlaku: Kebakaran Terdeteksi")


def test_r6_with_llm_counts_clean_verdicts_only(engine):
    step(engine, v(0.92))
    for _ in range(3):
        step(engine, CLEAN_V)
        for _ in range(5):
            step(engine, None)  # frames between verdicts do not count
    assert engine.level == Level.BAHAYA
    d = step(engine, CLEAN_V)
    assert (d.level, d.rule) == (Level.WASPADA, "R6")
    assert "4 verifikasi AI bersih" in d.explanation


def test_failed_verdict_is_ignored(engine):
    d = step(engine, v(0.95, error="api_error: APITimeoutError"))
    assert d.level == Level.AMAN
    assert d.trace["inputs"]["llm"] == {"error": "api_error: APITimeoutError", "prompt": "v2"}
    assert len(engine.verdicts) == 0


def test_trace_includes_llm_inputs(engine):
    d = step(engine, v(0.86))
    assert d.trace["inputs"]["llm"] == {
        "hazard_type": "smoke", "confidence": 0.86, "lookalike": "none", "prompt": "v2",
    }
    assert d.verdict is not None and d.verdict.confidence == 0.86


def test_clean_verdict_with_lookalike_is_explained(engine):
    fog = v(0.95, smoke=False, hazard="none", lookalike="fog_cloud")
    d = step(engine, fog)
    assert d.rule == "R0" and "mirip kabut/awan" in d.explanation
    later = step(engine, None, scores=HIT)  # frames without a new verdict keep the AI's reason
    assert later.explanation == d.explanation


def test_r6_hold_steps_are_not_prefixed_twice(engine):
    step(engine, v(0.95))
    step(engine, v(0.9, smoke=False, hazard="none", lookalike="fog_cloud"))
    d = step(engine, None)
    assert d.rule == "R6" and not d.explanation.startswith("Masih berlaku")
    assert "1/4 verifikasi AI bersih" in d.explanation and "mirip kabut/awan" in d.explanation
