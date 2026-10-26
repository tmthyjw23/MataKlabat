"""Command line entry point: `python -m mataklabat {run,check}`."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys

from mataklabat.config import PROMPT_VERSIONS, ConfigError, Settings, load_settings

log = logging.getLogger("mataklabat")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mataklabat",
        description="MataKlabat: sistem peringatan dini karhutla Gunung Klabat.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Tampilkan log debug.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{run,check}")

    run = sub.add_parser("run", help="Jalankan pemantauan kamera (monitor).")
    run.add_argument("--camera", metavar="ID", help="Hanya jalankan satu kamera, misalnya CAM-01.")
    run.add_argument("--no-llm", action="store_true", help="Hanya detektor lokal, tanpa Gemini.")
    run.add_argument("--prompt", choices=PROMPT_VERSIONS, help="Versi prompt verifikasi Gemini.")

    sub.add_parser("check", help="Cek konfigurasi, kamera, API key Gemini, dan koneksi cuaca.")
    return parser


def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    overrides: dict = {}
    if args.no_llm:
        overrides["llm_enabled"] = False
    if args.prompt:
        overrides["prompt_version"] = args.prompt
    if args.camera:
        overrides["cameras"] = (settings.camera(args.camera),)
    settings = dataclasses.replace(settings, **overrides)

    mode = f"Gemini {settings.gemini_model}, prompt {settings.prompt_version}" if settings.llm_enabled else "tanpa LLM"
    print(f"MataKlabat: {len(settings.cameras)} kamera, {mode}.")
    for cam in settings.cameras:
        print(f"  {cam.id}  {cam.name}  (sumber: {cam.source})")
    # TODO(T4): start one CameraWorker per camera here.
    print("Pipeline pemantauan belum tersedia (dikerjakan di T4).")
    return 0


def cmd_check(settings: Settings) -> int:
    rows = [
        ("Konfigurasi", True, f"{len(settings.cameras)} kamera, {len(settings.resources.villages)} desa"),
        (
            "Gemini API key",
            settings.llm_enabled,
            f"model {settings.gemini_model}" if settings.llm_enabled else "kosong, mode detektor lokal",
        ),
        (
            "Telegram",
            bool(settings.telegram_bot_token and settings.telegram_chat_id),
            "terkonfigurasi" if settings.telegram_bot_token else "tidak diisi (opsional)",
        ),
    ]
    # TODO(T2): add camera, Gemini call and Open-Meteo checks.
    for name, ok, detail in rows:
        print(f"{'✅' if ok else '❌'}  {name:<16} {detail}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        settings = load_settings()
        if args.command == "run":
            return cmd_run(settings, args)
        return cmd_check(settings)
    except ConfigError as exc:
        print(f"Konfigurasi tidak valid: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
