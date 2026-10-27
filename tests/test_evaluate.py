import csv

import cv2
import numpy as np
import pytest

from mataklabat.config import Resources, Settings
from mataklabat.evaluation import evaluate, failure_group, metrics, one_shot_level, write_outputs
from mataklabat.vision_llm import LLMVerdict

# One color per class so the fake LLM can "recognise" the class from pixels.
COLORS = {"fire": (0, 150, 245), "smoke": (160, 162, 162), "fog": (205, 208, 208), "sunset": (40, 120, 230),
          "lights": (200, 240, 250), "normal": (50, 120, 40)}
ANSWERS = {
    "fire": LLMVerdict(fire_visible=True, hazard_type="flame", confidence=0.9, prompt_version="v2"),
    "smoke": LLMVerdict(smoke_visible=True, hazard_type="smoke", confidence=0.5, prompt_version="v2"),  # missed: below 0.70
    "fog": LLMVerdict(smoke_visible=True, hazard_type="smoke", confidence=0.8, prompt_version="v2", reasoning="kabut tebal"),  # F1
    "sunset": LLMVerdict(fire_visible=True, hazard_type="flame", lookalike="sunset_glare", confidence=0.8, prompt_version="v2"),
    "lights": LLMVerdict(hazard_type="none", confidence=0.9, prompt_version="v2"),
    "normal": LLMVerdict(hazard_type="none", confidence=0.9, prompt_version="v2"),
}


@pytest.fixture
def test_set(tmp_path):
    root = tmp_path / "set"
    for cls, color in COLORS.items():
        (root / cls).mkdir(parents=True)
        for i in range(2):
            img = np.full((120, 160, 3), (40, 90, 40), np.uint8)
            img[20:100, 30:130] = color
            cv2.imwrite(str(root / cls / f"{i}.png"), img)
    (root / "fire" / "notes.txt").write_text("bukan gambar")
    return root


def fake_verify(image, ctx, version):
    center = tuple(int(v) for v in image[60, 80])
    cls = min(COLORS, key=lambda c: sum(abs(a - b) for a, b in zip(COLORS[c], center)))
    return ANSWERS[cls] if version == "v2" else LLMVerdict(smoke_visible=True, hazard_type="smoke", confidence=0.95, prompt_version="v1")


def test_one_shot_level():
    s = Settings(root=".", cameras=(), resources=Resources())
    assert one_shot_level(ANSWERS["fire"], s) == "BAHAYA"
    assert one_shot_level(ANSWERS["smoke"], s) == "WASPADA"
    assert one_shot_level(ANSWERS["sunset"], s) == "AMAN"
    assert one_shot_level(LLMVerdict(hazard_type="none", risk_factors=("campfire",)), s) == "WASPADA"
    assert one_shot_level(LLMVerdict.failed("api_error"), s) == "AMAN"


def test_evaluate_metrics_and_outputs(test_set, tmp_path):
    settings = Settings(root=".", cameras=(), resources=Resources())
    preds = evaluate(test_set, settings, ["local", "v1", "v2"], fake_verify, repeat=2)
    assert len(preds) == 12 * 3
    rows = {r["variant"]: r for r in metrics(preds)}
    v2 = rows["v2"]
    assert v2["recall"] == 0.5 and v2["precision"] == 0.5  # fire caught, smoke missed, fog false alarm
    assert v2["recall_any_alert"] == 1.0  # smoke still raised Perlu Dicek
    assert v2["false_alarm_fog"] == 1.0 and v2["false_alarm_sunset"] == 0.0 and v2["false_alarm_normal"] == 0.0
    assert v2["consistency"] == 1.0
    assert rows["v1"]["false_alarm_normal"] == 1.0  # v1 says "smoke" everywhere
    assert rows["local"]["precision"] is None  # the detector alone never reaches BAHAYA

    paths = write_outputs(preds, tmp_path / "results")
    with paths["predictions"].open(encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 36
    assert paths["confusion_v2"].stat().st_size > 1000
    md = paths["failures"].read_text(encoding="utf-8")
    assert "## F1" in md and "fog/0.png" in md and "kabut tebal" in md
    assert "## F3" in md and "smoke/0.png" in md
    assert "## F5" in md and "v1 BAHAYA · v2 AMAN" in md


def test_failure_groups():
    from mataklabat.evaluation import Prediction

    assert failure_group(Prediction("v2", "f", "fog", "BAHAYA")) == "F1"
    assert failure_group(Prediction("v2", "f", "lights", "BAHAYA")) == "F2"
    assert failure_group(Prediction("v2", "f", "smoke", "AMAN")) == "F3"
    assert failure_group(Prediction("v2", "f", "normal", "AMAN")) is None


def test_per_class_limit(test_set):
    settings = Settings(root=".", cameras=(), resources=Resources())
    preds = evaluate(test_set, settings, ["local"], None, per_class=1)
    assert len(preds) == 6 and {p.file.split("/")[1] for p in preds} == {"0.png"}


def test_failed_call_is_retried_once(test_set):
    settings = Settings(root=".", cameras=(), resources=Resources())
    calls = {"n": 0}

    def flaky(image, ctx, version):
        calls["n"] += 1
        return LLMVerdict.failed("api_error: APITimeoutError", "v2") if calls["n"] == 2 else fake_verify(image, ctx, "v2")

    waits = []
    preds = evaluate(test_set, settings, ["v2"], flaky, sleep=waits.append)
    assert len(preds) == 12 and all(p.error is None for p in preds)
    assert waits == [10.0] and calls["n"] == 13


def test_outage_stops_with_partial_results_and_resume_continues(test_set, tmp_path):
    from mataklabat.evaluation import LLMUnavailable, load_predictions, write_outputs

    settings = Settings(root=".", cameras=(), resources=Resources())
    calls = {"n": 0}

    def dies_after_four(image, ctx, version):
        calls["n"] += 1
        return fake_verify(image, ctx, version) if calls["n"] <= 4 else LLMVerdict.failed("api_error: APITimeoutError", "v2")

    with pytest.raises(LLMUnavailable, match="--resume") as exc:
        evaluate(test_set, settings, ["v2"], dies_after_four, sleep=lambda s: None)
    partial = exc.value.predictions
    assert len(partial) == 4 and all(p.error is None for p in partial)

    write_outputs(partial, tmp_path)
    previous = load_predictions(tmp_path / "predictions.csv")
    assert [(p.variant, p.file, p.level) for p in previous] == [(p.variant, p.file, p.level) for p in partial]
    seen = []

    def recording(image, ctx, version):
        seen.append(1)
        return fake_verify(image, ctx, version)

    full = evaluate(test_set, settings, ["v2"], recording, previous=previous)
    assert len(full) == 12 and len(seen) == 8  # only the 8 images not done before


def test_cli_script_compiles():
    import py_compile
    from pathlib import Path

    py_compile.compile(str(Path(__file__).resolve().parents[1] / "scripts" / "evaluate.py"), doraise=True)
    py_compile.compile(str(Path(__file__).resolve().parents[1] / "scripts" / "fetch_media.py"), doraise=True)
