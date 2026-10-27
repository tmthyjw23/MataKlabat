"""Evaluate detection on a labelled test set.

    python scripts/evaluate.py --set data/test_set --prompt v1,v2 --repeat 3
    python scripts/evaluate.py --set data/test_set --no-llm

Writes results/predictions.csv, metrics.csv, confusion_<variant>.png, failures.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mataklabat.config import ConfigError, load_settings
from mataklabat.evaluation import CLASSES, evaluate, list_images, metrics, write_outputs
from mataklabat.vision_llm import RateLimiter, VisionVerifier


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Evaluasi MataKlabat pada test set berlabel.")
    parser.add_argument("--set", type=Path, default=Path("data/test_set"), help="Folder test set.")
    parser.add_argument("--prompt", default="v2", help="Versi prompt, misal v2 atau v1,v2.")
    parser.add_argument("--repeat", type=int, default=1, help="Ulangi panggilan LLM per gambar (uji konsistensi).")
    parser.add_argument("--no-llm", action="store_true", help="Hanya detektor lokal.")
    parser.add_argument("--interval", type=float, help="Jeda minimum antar panggilan LLM (default LLM_MIN_INTERVAL_S).")
    parser.add_argument("--per-class", type=int, help="Hanya N gambar pertama per kelas (misal untuk uji konsistensi).")
    parser.add_argument("--out", type=Path, default=Path("results"), help="Folder hasil.")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Konfigurasi tidak valid: {exc}", file=sys.stderr)
        return 2

    images = list_images(args.set, args.per_class)
    if not images:
        print(f"Tidak ada gambar di {args.set}/<kelas>/ (kelas: {', '.join(CLASSES)}).", file=sys.stderr)
        return 1
    variants = ["local"]
    verify = None
    if not args.no_llm:
        if not settings.llm_enabled:
            print("LLM_MODEL kosong. Isi .env atau jalankan dengan --no-llm.", file=sys.stderr)
            return 1
        variants += [v.strip() for v in args.prompt.split(",") if v.strip()]
        limiter = RateLimiter(settings.llm_min_interval_s if args.interval is None else args.interval)
        verifier = VisionVerifier(settings, limiter=limiter)
        verify = lambda image, ctx, version: verifier.verify(image, ctx, version)  # noqa: E731

    counts = {c: sum(1 for label, _ in images if label == c) for c in CLASSES}
    print(f"{len(images)} gambar: " + ", ".join(f"{c} {n}" for c, n in counts.items()))
    small = [c for c, n in counts.items() if n < 10]
    if small:
        print(f"Peringatan: kurang dari 10 gambar untuk {', '.join(small)}.")
    predictions = evaluate(args.set, settings, variants, verify, args.repeat, progress=print, per_class=args.per_class)
    paths = write_outputs(predictions, args.out)
    print()
    for row in metrics(predictions):
        print(row)
    print("\nHasil:", ", ".join(str(p) for p in paths.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
