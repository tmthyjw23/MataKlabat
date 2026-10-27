"""Offline evaluation on a labelled image folder (failure analysis F1-F5, ARCHITECTURE §8).

Test set layout: <set>/<class>/<image>, classes fire, smoke (positive) and fog,
sunset, lights, normal (negative; the first three are lookalikes).

Variants:
- `local`: the local detector alone (color only, since images are still).
- `v1`, `v2`: one-shot decision from a single LLM verdict with that prompt.
"""

from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from mataklabat.camera import Frame, read_image
from mataklabat.config import Settings, now_local
from mataklabat.decision import POTENTIAL_RISKS
from mataklabat.detector import ColorMotionDetector
from mataklabat.prompts import PromptContext
from mataklabat.vision_llm import LLMVerdict

POSITIVE_CLASSES = ("fire", "smoke")
LOOKALIKE_CLASSES = ("fog", "sunset", "lights")
CLASSES = POSITIVE_CLASSES + LOOKALIKE_CLASSES + ("normal",)
LEVELS = ("AMAN", "WASPADA", "BAHAYA")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
MAX_CONSECUTIVE_ERRORS = 3


class LLMUnavailable(RuntimeError):
    """The LLM failed on several images in a row; results would be meaningless."""


@dataclass
class Prediction:
    variant: str
    file: str
    label: str
    level: str
    fire_score: float = 0.0
    smoke_score: float = 0.0
    hazard_type: str = ""
    lookalike: str = ""
    confidence: float | None = None
    reasoning: str = ""
    error: str | None = None
    repeats: list[tuple[str, float | None]] = field(default_factory=list)

    @property
    def positive_truth(self) -> bool:
        return self.label in POSITIVE_CLASSES

    @property
    def alarm(self) -> bool:
        return self.level == "BAHAYA"

    @property
    def correct(self) -> bool:
        return self.alarm == self.positive_truth


def list_images(test_set: Path, per_class: int | None = None) -> list[tuple[str, Path]]:
    """Images per class, sorted by name; `per_class` keeps only the first N of each class."""
    items = []
    for label in CLASSES:
        folder = test_set / label
        if folder.is_dir():
            files = [p for p in sorted(folder.iterdir()) if p.suffix.lower() in IMAGE_EXTENSIONS]
            items += [(label, p) for p in files[:per_class]]
    return items


def local_level(fire: float, smoke: float, settings: Settings) -> str:
    """Detector alone: a hit is at most WASPADA (rule R4); it can never confirm BAHAYA."""
    return "WASPADA" if fire >= settings.fire_trigger or smoke >= settings.smoke_trigger else "AMAN"


def one_shot_level(v: LLMVerdict, settings: Settings) -> str:
    """Single-verdict version of rules R1/R2/R3/R5 (no confirmation window, default threshold)."""
    if not v.ok:
        return "AMAN"
    real = v.positive and v.lookalike == "none"
    if real and v.confidence >= settings.conf_danger:
        return "BAHAYA"
    if real and v.confidence >= settings.conf_warn:
        return "WASPADA"
    if v.hazard_type == "uncertain" or any(r in POTENTIAL_RISKS for r in v.risk_factors):
        return "WASPADA"
    return "AMAN"


def evaluate(
    test_set: Path,
    settings: Settings,
    variants: list[str],
    verify: Callable[[np.ndarray, PromptContext, str], LLMVerdict] | None,
    repeat: int = 1,
    progress: Callable[[str], None] = lambda msg: None,
    per_class: int | None = None,
) -> list[Prediction]:
    detector = ColorMotionDetector(settings.fire_gain, settings.smoke_gain, use_motion=False)
    predictions: list[Prediction] = []
    images = list_images(test_set, per_class)
    consecutive_errors = 0
    for i, (label, path) in enumerate(images, start=1):
        image = read_image(path)
        if image is None:
            progress(f"lewati (tidak bisa dibaca): {path}")
            continue
        local = detector.detect(Frame("EVAL", now_local(), image, 0))
        name = f"{label}/{path.name}"
        if "local" in variants:
            predictions.append(Prediction("local", name, label, local_level(local.fire_score, local.smoke_score, settings),
                                          local.fire_score, local.smoke_score))
        for variant in (v for v in variants if v in ("v1", "v2")):
            if verify is None:
                raise RuntimeError("LLM tidak aktif: isi LLM_MODEL atau pakai --no-llm")
            ctx = PromptContext("Kamera evaluasi (test set)", 0.0, now_local(), local.fire_score, local.smoke_score)
            runs = [verify(image, ctx, variant) for _ in range(max(1, repeat))]
            if all(not r.ok for r in runs):
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    raise LLMUnavailable(
                        f"{consecutive_errors} gambar berturut-turut gagal dicek LLM ({runs[0].error}). "
                        "Pastikan 9router berjalan, lalu ulangi."
                    )
            else:
                consecutive_errors = 0
            first = runs[0]
            predictions.append(Prediction(
                variant, name, label, one_shot_level(first, settings), local.fire_score, local.smoke_score,
                first.hazard_type, first.lookalike, first.confidence if first.ok else None, first.reasoning, first.error,
                repeats=[(one_shot_level(r, settings), r.confidence if r.ok else None) for r in runs],
            ))
        progress(f"[{i}/{len(images)}] {name}")
    return predictions


def _ratio(n: int, d: int) -> float | None:
    return None if d == 0 else round(n / d, 3)


def metrics(predictions: list[Prediction]) -> list[dict[str, Any]]:
    rows = []
    by_variant: dict[str, list[Prediction]] = defaultdict(list)
    for p in predictions:
        by_variant[p.variant].append(p)
    for variant, all_preds in by_variant.items():
        # A failed LLM call says nothing about the image: leave it out, but report how many.
        preds = [p for p in all_preds if not p.error]
        tp = sum(p.alarm and p.positive_truth for p in preds)
        fp = sum(p.alarm and not p.positive_truth for p in preds)
        fn = sum(not p.alarm and p.positive_truth for p in preds)
        precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
        f1 = None if not precision or not recall else round(2 * precision * recall / (precision + recall), 3)
        # "Any alert" counts WASPADA too: what a person would be bothered with.
        alert_recall = _ratio(sum(p.level != "AMAN" and p.positive_truth for p in preds), sum(p.positive_truth for p in preds))
        row: dict[str, Any] = {
            "variant": variant, "n": len(preds), "errors": len(all_preds) - len(preds), "precision": precision, "recall": recall, "f1": f1,
            "recall_any_alert": alert_recall,
        }
        for cls in LOOKALIKE_CLASSES + ("normal",):
            subset = [p for p in preds if p.label == cls]
            row[f"false_alarm_{cls}"] = _ratio(sum(p.alarm for p in subset), len(subset))
        repeated = [p for p in preds if len(p.repeats) > 1]
        if repeated:
            row["consistency"] = _ratio(sum(len({lvl for lvl, _ in p.repeats}) == 1 for p in repeated), len(repeated))
            stds = [statistics.pstdev([c for _, c in p.repeats if c is not None]) for p in repeated
                    if sum(c is not None for _, c in p.repeats) > 1]
            row["confidence_std_mean"] = round(statistics.mean(stds), 3) if stds else None
        rows.append(row)
    return rows


def confusion(predictions: list[Prediction], variant: str) -> dict[str, Counter]:
    table: dict[str, Counter] = {cls: Counter() for cls in CLASSES}
    for p in predictions:
        if p.variant == variant:
            table[p.label][p.level] += 1
    return table


def failure_group(p: Prediction) -> str | None:
    if p.correct:
        return None
    if p.label == "fog":
        return "F1"
    if p.label in ("sunset", "lights"):
        return "F2"
    if p.positive_truth:
        return "F3"
    return "lainnya"


def write_outputs(predictions: list[Prediction], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"predictions": out_dir / "predictions.csv", "metrics": out_dir / "metrics.csv", "failures": out_dir / "failures.md"}

    with paths["predictions"].open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["variant", "file", "label", "level", "correct", "fire_score", "smoke_score", "hazard_type",
                    "lookalike", "confidence", "repeat_levels", "error", "reasoning"])
        for p in predictions:
            w.writerow([p.variant, p.file, p.label, p.level, int(p.correct), f"{p.fire_score:.3f}", f"{p.smoke_score:.3f}",
                        p.hazard_type, p.lookalike, "" if p.confidence is None else f"{p.confidence:.2f}",
                        "|".join(lvl for lvl, _ in p.repeats), p.error or "", p.reasoning])

    rows = metrics(predictions)
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k != "variant", k))
    with paths["metrics"].open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    for variant in sorted({p.variant for p in predictions}):
        png = out_dir / f"confusion_{variant}.png"
        _plot_confusion(confusion(predictions, variant), variant, png)
        paths[f"confusion_{variant}"] = png

    paths["failures"].write_text(failures_markdown(predictions, rows), encoding="utf-8")
    return paths


def _plot_confusion(table: dict[str, Counter], variant: str, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = np.array([[table[c][lvl] for lvl in LEVELS] for c in CLASSES])
    fig, ax = plt.subplots(figsize=(5, 4.2), dpi=120)
    ax.imshow(data, cmap="Oranges")
    ax.set_xticks(range(len(LEVELS)), ["Normal", "Perlu Dicek", "Kebakaran\nTerdeteksi"])
    ax.set_yticks(range(len(CLASSES)), CLASSES)
    ax.set_xlabel("Keputusan sistem")
    ax.set_ylabel("Label sebenarnya")
    ax.set_title(f"Confusion matrix · {variant}")
    for i in range(len(CLASSES)):
        for j in range(len(LEVELS)):
            ax.text(j, i, str(data[i, j]), ha="center", va="center",
                    color="white" if data[i, j] > data.max() / 2 else "black")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def failures_markdown(predictions: list[Prediction], rows: list[dict[str, Any]]) -> str:
    titles = {
        "F1": "F1 · Kabut/awan dikira asap (false positive)",
        "F2": "F2 · Senja/lampu dikira api (false positive)",
        "F3": "F3 · Api/asap tidak terdeteksi (false negative)",
        "lainnya": "Salah lainnya",
    }
    lines = ["# Analisis kegagalan", "", f"Dibuat {now_local():%d-%m-%Y %H:%M} WITA.", "", "## Ringkasan metrik", ""]
    if rows:
        keys = ["variant", "n", "errors", "precision", "recall", "f1", "recall_any_alert", "false_alarm_fog", "false_alarm_sunset",
                "false_alarm_lights", "false_alarm_normal", "consistency", "confidence_std_mean"]
        keys = [k for k in keys if any(k in r for r in rows)]
        lines += ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
        lines += ["| " + " | ".join("-" if r.get(k) is None else str(r.get(k)) for k in keys) + " |" for r in rows]
    for group, title in titles.items():
        items = [p for p in predictions if failure_group(p) == group]
        lines += ["", f"## {title}", ""]
        if not items:
            lines.append("Tidak ada contoh pada test set ini.")
            continue
        for p in items:
            detail = f"skor api {p.fire_score:.2f}, asap {p.smoke_score:.2f}"
            if p.variant != "local":
                detail += f"; AI: {p.hazard_type or '-'}, lookalike {p.lookalike or '-'}, keyakinan {p.confidence}"
            lines.append(f"- `{p.file}` [{p.variant}] → {p.level} ({detail})")
            if p.reasoning:
                lines.append(f"  - Alasan AI: {p.reasoning}")
    lines += ["", "## F4 · Inkonsistensi LLM (--repeat)", ""]
    unstable = [p for p in predictions if len({lvl for lvl, _ in p.repeats}) > 1]
    lines += [f"- `{p.file}` [{p.variant}]: {', '.join(lvl for lvl, _ in p.repeats)}" for p in unstable] or \
             ["Tidak ada (atau --repeat tidak dipakai)."]
    lines += ["", "## F5 · Pengaruh prompt (v1 vs v2)", ""]
    by_file: dict[str, dict[str, str]] = defaultdict(dict)
    for p in predictions:
        if p.variant in ("v1", "v2"):
            by_file[p.file][p.variant] = p.level
    diffs = [(f, lv) for f, lv in by_file.items() if len(lv) == 2 and lv["v1"] != lv["v2"]]
    lines += [f"- `{f}`: v1 {lv['v1']} · v2 {lv['v2']}" for f, lv in diffs] or ["Tidak ada perbedaan (atau hanya satu prompt diuji)."]
    return "\n".join(lines) + "\n"
