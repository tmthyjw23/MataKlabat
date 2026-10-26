"""Vision LLM prompts (ARCHITECTURE §5.2).

`v1` is the bare baseline and `v2` the lookalike-aware Klabat prompt. Both are
kept so `scripts/evaluate.py` can compare them (failure case F5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

PROMPT_V1 = "Lihat gambar ini. Apakah ada api atau asap kebakaran? Jawab dalam JSON sesuai skema."

PROMPT_V2 = """\
Kamu adalah analis pemantau kebakaran hutan untuk kawasan Gunung Klabat, Minahasa Utara.
Gambar berasal dari kamera "{camera_name}" yang menghadap {facing_desc}.
Waktu lokal: {local_time}. {weather_line}
Detektor lokal memberi skor api {fire_score:.2f} dan asap {smoke_score:.2f} (sensitif, sering salah).

Tugas:
1. Tentukan apakah ada API atau ASAP KEBAKARAN yang nyata.
2. Waspadai LOOKALIKE yang umum di Klabat: kabut/awan yang menyelimuti lereng (menyebar rata,
   putih, tanpa titik sumber), cahaya matahari terbit/terbenam, lampu kendaraan/rumah, debu, uap.
   Asap kebakaran biasanya: berbentuk kolom/gumpalan, bersumber dari satu titik di permukaan,
   berwarna abu-abu hingga coklat/kehitaman, bergerak naik.
3. Catat FAKTOR RISIKO yang terlihat walau belum ada api (api unggun, orang membakar, sampah dibakar,
   vegetasi sangat kering).
4. Jika ragu, gunakan hazard_type "uncertain" dan confidence rendah. Jangan menebak.
Jawab HANYA dalam JSON sesuai skema. reasoning dan evidence dalam Bahasa Indonesia."""

_COMPASS = (
    "utara", "timur laut", "timur", "tenggara", "selatan", "barat daya", "barat", "barat laut",
)


@dataclass(frozen=True)
class PromptContext:
    camera_name: str
    facing_deg: float
    local_time: datetime
    fire_score: float = 0.0
    smoke_score: float = 0.0
    temp_c: float | None = None
    rh_pct: float | None = None
    wind_kmh: float | None = None


def compass_name(deg: float) -> str:
    return _COMPASS[round((deg % 360) / 45) % 8]


def facing_description(deg: float) -> str:
    return f"arah {compass_name(deg)} ({deg:.0f}°)"


def weather_line(ctx: PromptContext) -> str:
    if ctx.temp_c is None or ctx.rh_pct is None or ctx.wind_kmh is None:
        return "Cuaca: tidak tersedia."
    return f"Cuaca: suhu {ctx.temp_c:.0f}°C, kelembapan {ctx.rh_pct:.0f}%, angin {ctx.wind_kmh:.0f} km/j."


def build_prompt(version: str, ctx: PromptContext) -> str:
    if version == "v1":
        return PROMPT_V1
    if version == "v2":
        return PROMPT_V2.format(
            camera_name=ctx.camera_name,
            facing_desc=facing_description(ctx.facing_deg),
            local_time=ctx.local_time.strftime("%H:%M (%d-%m-%Y)"),
            weather_line=weather_line(ctx),
            fire_score=ctx.fire_score,
            smoke_score=ctx.smoke_score,
        )
    raise ValueError(f"unknown prompt version: {version!r}")
