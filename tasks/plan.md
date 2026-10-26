> **v2 (26 Okt 2026):** rencana ini digantikan oleh spec `docs/superpowers/specs/2026-10-26-mataklabat-v2-design.md` dan task T7–T15 di `tasks/todo.md`. Isi di bawah adalah rencana awal (v1).

# Implementation Plan: MataKlabat (build 1 hari)

## Overview
Membangun prototipe peringatan dini karhutla Gunung Klabat. Kamera (webcam + video) masuk ke detektor lokal, lalu LLM Vision (via 9router) memverifikasi, Decision Engine menetapkan AMAN/WASPADA/BAHAYA beserta trace, AI Agent menyusun laporan insiden, dan hasilnya tampil di dashboard Streamlit dengan peta. Ditutup dengan script evaluasi untuk analisis kegagalan. Task detail ada di `tasks/todo.md`.

## Architecture Decisions
- **Python + Streamlit**: rubrik meminta `.py`, dan Streamlit adalah UI tercepat.
- **Dua proses (monitor + dashboard) dengan SQLite WAL**: sederhana dan saling independen.
- **Deteksi 2 tahap**: detektor lokal murah menyaring, LLM memverifikasi dan menjelaskan, sehingga kuota hemat.
- **Rule-based fusion (R0–R6)**: keputusan transparan dan bisa diuji unit, bukan "LLM yang memutuskan semuanya".
- **Detail lengkap**: `docs/ARCHITECTURE.md`.

## Jadwal (±8 jam)

| Fase | Jam | Task | Hasil yang bisa dilihat |
|---|---|---|---|
| 0. Fondasi | 0:00–0:45 | T1, T2 | `check` jalan, webcam terbaca |
| 1. Deteksi lokal | 0:45–2:00 | T3, T4 | Terminal mencetak skor api/asap live, status AMAN/WASPADA |
| ✅ Checkpoint A | | | Video api di HP memicu WASPADA tanpa LLM |
| 2. LLM + keputusan | 2:00–3:45 | T5, T6, T7 | BAHAYA dengan trace, tersimpan di DB |
| ✅ Checkpoint B | | | End-to-end headless: api → BAHAYA ≤ 30 dtk, kabut → bukan BAHAYA (idealnya) |
| 3. Risiko + Agent | 3:45–5:00 | T8, T9 | FRI live, laporan insiden agent |
| 4. Dashboard | 5:00–6:45 | T10, T11 | Grid, peta, panel "Mengapa?", insiden, Telegram |
| ✅ Checkpoint C | | | Demo DEMO.md menit 2–6 berjalan |
| 5. Evaluasi | 6:45–7:30 | T12 | `results/metrics.csv`, perbandingan v1/v2, konsistensi |
| 6. Polish | 7:30–8:00 | T13 | Screenshot README, rehearsal demo |
| ✅ Checkpoint D | | | Semua DoD, siap push |

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Provider di belakang 9router tidak mendukung gambar/`response_format`/tool calling | High | Kontrak JSON juga di system message, fallback tanpa `response_format`, uji model dengan `check --llm-sample`; wrapper tipis di `vision_llm.py` |
| Rate limit / kuota provider di 9router habis | High | `LLM_MIN_INTERVAL_S`, trigger T1–T3, `--no-llm`, cache verdict per hash frame (opsional) |
| Streamlit + loop kamera saling mengunci | Med | Kamera hanya di proses monitor. Dashboard hanya membaca snapshot dan DB |
| Webcam dipakai aplikasi lain (Zoom) | Med | `check` melaporkan dengan jelas, dan bisa memakai video sebagai CAM-01 |
| Detektor warna terlalu banyak false positive | Med | Memang diserahkan ke LLM. Tuning `FIRE_GAIN`/`SMOKE_GAIN` di config |
| Test set kurang | Med | Minimal 10 gambar per kelas dari dataset publik (D-Fire, dll.) dan foto kabut Klabat sendiri |

## Open Questions (untuk tim)
- Siapa anggota tim lain, dan siapa yang memegang laporan PDF dan slide?
- ~~Apakah dosen mewajibkan Gemini?~~ Diputuskan memakai 9router (lihat Decision Log). Pastikan dosen tidak keberatan.
- Video untuk CAM-02..04: rekam sendiri di Klabat atau pakai stok video bebas lisensi?
