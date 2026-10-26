"""Command line entry point: `python -m mataklabat {up,run,web,check}`."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
import time
from pathlib import Path

import requests

from mataklabat.camera import open_source
from mataklabat.config import PROMPT_VERSIONS, TIMEZONE, ConfigError, Settings, load_settings, now_local
from mataklabat.logs import setup_logging
from mataklabat.monitor import build_monitor
from mataklabat.prompts import PromptContext
from mataklabat.vision_llm import VisionVerifier

log = logging.getLogger("mataklabat")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mataklabat",
        description="MataKlabat: sistem peringatan dini karhutla Gunung Klabat.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Tampilkan log debug.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{up,run,web,check}")

    run = sub.add_parser("run", help="Jalankan pemantauan kamera (monitor).")
    run.add_argument("--camera", metavar="ID", help="Hanya jalankan satu kamera, misalnya CAM-01.")
    run.add_argument("--no-llm", action="store_true", help="Hanya detektor lokal, tanpa LLM.")
    run.add_argument("--prompt", choices=PROMPT_VERSIONS, help="Versi prompt verifikasi LLM.")
    run.add_argument(
        "--duration", type=float, metavar="DETIK", help="Berhenti otomatis setelah sekian detik."
    )

    web = sub.add_parser("web", help="Jalankan website dashboard (hanya-baca).")
    web.add_argument("--host", help="Alamat bind (default 127.0.0.1; 0.0.0.0 = bisa dibuka dari HP di jaringan yang sama).")
    web.add_argument("--port", type=int, help="Port (default 8000).")

    check = sub.add_parser("check", help="Cek konfigurasi, kamera, LLM (9router), dan koneksi cuaca.")
    check.add_argument(
        "--llm-sample", type=Path, metavar="GAMBAR",
        help="Kirim satu gambar ke LLM vision dan tampilkan verdict JSON-nya.",
    )
    check.add_argument("--prompt", choices=PROMPT_VERSIONS, help="Versi prompt untuk --llm-sample.")
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

    mode = f"LLM {settings.llm_model}, prompt {settings.prompt_version}" if settings.llm_enabled else "tanpa LLM"
    print(f"MataKlabat: {len(settings.cameras)} kamera, {mode}.")
    for cam in settings.cameras:
        print(f"  {cam.id}  {cam.name}  (sumber: {cam.source})")
    setup_logging(settings, "monitor", args.verbose)
    build_monitor(settings).run_forever(duration_s=args.duration)
    return 0


# A check row: (component, ok, detail). ok=None means optional and not configured.
CheckRow = tuple[str, bool | None, str]

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
TELEGRAM_API = "https://api.telegram.org"


def check_cameras(settings: Settings, wait_s: float = 6.0) -> list[CheckRow]:
    """Open every camera at the same time and wait for a first frame from each."""
    sources = [open_source(cam).start() for cam in settings.cameras]
    try:
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline and not all(s.online for s in sources):
            time.sleep(0.1)
        rows: list[CheckRow] = []
        for src in sources:
            frame = src.latest()
            if frame is not None:
                h, w = frame.image.shape[:2]
                rows.append((src.camera_id, True, f"{w}x{h}, {src.camera.name}"))
            else:
                reason = src.last_error or f"tidak ada frame dalam {wait_s:.0f} detik"
                rows.append((src.camera_id, False, reason))
        return rows
    finally:
        for src in sources:
            src.stop()


def check_llm(settings: Settings, client=None) -> CheckRow:
    if not settings.llm_enabled:
        return ("LLM", False, "LLM_MODEL kosong, sistem hanya memakai detektor lokal")
    try:
        client = client or VisionVerifier(settings).client
        reply = client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": "Jawab hanya dengan satu kata: OK"}],
        )
        text = (reply.choices[0].message.content or "").strip()
        return ("LLM", True, f"{settings.llm_model} @ {settings.llm_base_url} menjawab {text[:20]!r}")
    except Exception as exc:  # noqa: BLE001 - any SDK/network error is reported, not raised
        return ("LLM", False, f"{settings.llm_model} @ {settings.llm_base_url}: {_short_error(exc)}")


def cmd_llm_sample(settings: Settings, image_path: Path, prompt_version: str | None) -> int:
    """Send one image through the real vision verifier and print the verdict."""
    import cv2

    image = cv2.imread(str(image_path))
    if image is None:
        print(f"❌ Gambar tidak bisa dibaca: {image_path}", file=sys.stderr)
        return 1
    cam = settings.cameras[0]
    ctx = PromptContext(camera_name=cam.name, facing_deg=cam.facing_deg, local_time=now_local())
    verdict = VisionVerifier(settings).verify(image, ctx, prompt_version)
    print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
    return 0 if verdict.ok else 1


def check_open_meteo(lat: float, lon: float) -> CheckRow:
    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
                "timezone": TIMEZONE,
            },
            timeout=10,
        )
        resp.raise_for_status()
        cur = resp.json()["current"]
        detail = (
            f"suhu {cur['temperature_2m']}°C, kelembapan {cur['relative_humidity_2m']}%, "
            f"angin {cur['wind_speed_10m']} km/j"
        )
        return ("Open-Meteo", True, detail)
    except Exception as exc:  # noqa: BLE001
        return ("Open-Meteo", False, _short_error(exc))


def check_telegram(settings: Settings) -> CheckRow:
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return ("Telegram", None, "tidak diisi (opsional)")
    try:
        resp = requests.get(f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/getMe", timeout=10)
        data = resp.json()
        if not data.get("ok"):
            return ("Telegram", False, data.get("description", "token ditolak"))
        return ("Telegram", True, f"bot @{data['result'].get('username', '?')}")
    except Exception as exc:  # noqa: BLE001
        # The request URL contains the token, so never print the exception text.
        return ("Telegram", False, type(exc).__name__)


def _short_error(exc: Exception, limit: int = 120) -> str:
    text = f"{type(exc).__name__}: {exc}".splitlines()[0]
    return text if len(text) <= limit else text[: limit - 1] + "…"


def cmd_check(settings: Settings) -> int:
    print(f"Konfigurasi OK: {len(settings.cameras)} kamera, {len(settings.resources.villages)} desa.")
    print("Menguji kamera...")
    rows = check_cameras(settings)
    first = settings.cameras[0]
    rows += [check_llm(settings), check_open_meteo(first.lat, first.lon), check_telegram(settings)]

    symbols = {True: "✅", False: "❌", None: "➖"}
    for name, ok, detail in rows:
        print(f"{symbols[ok]}  {name:<12} {detail}")
    return 1 if any(ok is False for _, ok, _ in rows) else 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    setup_logging(None, args.command, args.verbose)
    try:
        settings = load_settings()
        if args.command == "run":
            return cmd_run(settings, args)
        if args.command == "web":
            setup_logging(settings, "web", args.verbose)
            from mataklabat.web.app import run_web

            run_web(settings, args.host, args.port)
            return 0
        if args.llm_sample:
            return cmd_llm_sample(settings, args.llm_sample, args.prompt)
        return cmd_check(settings)
    except ConfigError as exc:
        print(f"Konfigurasi tidak valid: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
