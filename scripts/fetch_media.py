"""Download the test set, demo photos and demo videos listed in data/MEDIA_SOURCES.md.

    python scripts/fetch_media.py            # skip files that already exist
    python scripts/fetch_media.py --force    # download again

Targets: `fire/x.jpg` -> data/test_set/fire/x.jpg, `demo/x.jpg` -> data/demo/bahan/x.jpg,
`videos/x.mp4` -> data/videos/x.mp4. Requests are paced (Wikimedia asks for a descriptive
User-Agent and modest request rates) and retried on HTTP 429/5xx.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "MEDIA_SOURCES.md"
USER_AGENT = "MataKlabat/0.2 (https://github.com/tmthyjw23/MataKlabat; student project) python-urllib"
PAUSE_S = 1.2
MAX_TRIES = 6
ROW = re.compile(r"^\|\s*\d+\s*\|\s*`([^`]+)`\s*\|\s*(https://\S+)\s*\|")


def target(name: str) -> Path:
    folder, _, filename = name.partition("/")
    if folder == "demo":
        return ROOT / "data" / "demo" / "bahan" / filename
    if folder == "videos":
        return ROOT / "data" / "videos" / filename
    return ROOT / "data" / "test_set" / folder / filename


def download(url: str, dest: Path) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, MAX_TRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                kind = resp.headers.get("Content-Type", "")
                if not kind.startswith(("image/", "video/")):
                    raise ValueError(f"bukan gambar/video: {kind}")
                data = resp.read()
            tmp = dest.with_suffix(dest.suffix + ".part")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            tmp.replace(dest)
            return len(data)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == MAX_TRIES:
                raise
            wait = float(exc.headers.get("Retry-After") or 0) or min(60, 5 * 2 ** (attempt - 1))
            print(f"    HTTP {exc.code}, coba lagi dalam {wait:.0f} dtk")
            time.sleep(wait)
    raise RuntimeError("tidak terunduh")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Unduh media dari data/MEDIA_SOURCES.md.")
    parser.add_argument("--force", action="store_true", help="Unduh ulang walau file sudah ada.")
    args = parser.parse_args()

    rows = [m.groups() for line in SOURCES.read_text(encoding="utf-8").splitlines() if (m := ROW.match(line))]
    print(f"{len(rows)} file di {SOURCES.relative_to(ROOT)}")
    done = skipped = 0
    failed: list[str] = []
    total = 0
    for i, (name, url) in enumerate(rows, start=1):
        dest = target(name)
        if dest.exists() and not args.force:
            skipped += 1
            continue
        try:
            size = download(url, dest)
        except Exception as exc:  # noqa: BLE001 - report and continue with the rest
            failed.append(f"{name}: {exc}")
            print(f"[{i}/{len(rows)}] GAGAL {name}: {exc}")
        else:
            done += 1
            total += size
            print(f"[{i}/{len(rows)}] {name} ({size / 1024:.0f} KB)")
        time.sleep(PAUSE_S)
    print(f"\nSelesai: {done} diunduh ({total / 1024 / 1024:.1f} MB), {skipped} sudah ada, {len(failed)} gagal.")
    for line in failed:
        print("  -", line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
