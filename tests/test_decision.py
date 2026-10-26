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
    assert "menunggu" in held[0].explanation
    assert dropped.level == Level.AMAN and dropped.changed and dropped.sub_status is None
    assert "Turun dari WASPADA ke AMAN" in dropped.explanation
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
