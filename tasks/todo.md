# Task List: MataKlabat

Kerjakan berurutan. Centang `[x]` hanya setelah **Verification** lulus. Rujukan "§" mengacu ke `docs/ARCHITECTURE.md`.

---

## Fase 0: Fondasi

### T1: Scaffold proyek & config
**Description:** Buat struktur folder sesuai README, `pyproject`/`requirements.txt`, package `src/mataklabat`, `config.py` yang memuat `.env` + `config/cameras.yaml` + `config/resources.yaml` ke dataclass `Settings` (termasuk semua konstanta §4.3 dan §6.2, override-able via env).
**Acceptance criteria:**
- [x] `python -m mataklabat --help` menampilkan perintah `run` dan `check`
- [x] `Settings` gagal dengan pesan jelas jika `cameras.yaml` tidak valid
- [x] `GEMINI_API_KEY` kosong tidak membuat crash, cukup peringatan dan `llm_enabled=False`

**Verification:** `pytest tests/test_config.py -q`
**Dependencies:** None · **Files:** `src/mataklabat/{__init__,__main__,config}.py`, `tests/test_config.py` · **Scope:** S

### T2: CameraSource + perintah `check`
**Description:** `CameraSource` mendukung int (webcam), path video (loop otomatis saat EOF), dan URL RTSP. Thread pembaca menyimpan frame terbaru. `latest()` mengembalikan `Frame | None`, dan `online` false jika > 5 dtk tanpa frame. `check` menguji setiap kamera, API key (panggilan teks kecil ke Gemini), dan Open-Meteo.
**Acceptance criteria:**
- [x] Webcam dan 1 video bisa dibaca bersamaan
- [x] Video berulang tanpa error saat habis
- [x] `check` mencetak tabel ✅/❌ per komponen

**Verification:** `python -m mataklabat check` · `pytest tests/test_camera.py -q` (memakai video sintetis 1 dtk yang dibuat di test)
**Dependencies:** T1 · **Files:** `camera.py`, `__main__.py`, `tests/test_camera.py` · **Scope:** S

---

## Fase 1: Deteksi Lokal

### T3: ColorMotionDetector (§4.1)
**Description:** Implementasi mask api, asap, dan gerak, `fire_score`, `smoke_score`, serta `boxes`. Interface `Detector.detect(frame) -> LocalDetection`. Slot `YoloDetector` dengan lazy import.
**Acceptance criteria:**
- [x] Gambar sintetis oranye berkedip memberi `fire_score` > 0.15. Gambar hijau statis memberi < 0.05
- [x] Gambar oranye **statis** (tanpa gerak) memberi `fire_score` < 0.05
- [x] ≥ 15 FPS pada frame 640 px di CPU laptop

**Verification:** `pytest tests/test_detector.py -q`
**Dependencies:** T1 · **Files:** `detector.py`, `tests/test_detector.py` · **Scope:** S

### T4: Pipeline headless + Decision Engine versi lokal
**Description:** `CameraWorker` per kamera (thread): ambil frame, deteksi, lalu `DecisionEngine` (sementara hanya R4/R6/R0, karena LLM belum ada), lalu log ke console. `run --no-llm` menjalankan semua kamera.
**Acceptance criteria:**
- [x] Console menampilkan per kamera: level, fire/smoke score, tiap ~1 dtk
- [ ] Video api di HP di depan webcam memicu **WASPADA (unverified)**, dan kembali AMAN setelah dijauhkan (R6) *(sudah lulus dengan video sintetis di `tests/test_pipeline.py`; uji HP manual belum)*
- [x] Ctrl+C menghentikan semua thread dengan bersih

**Verification:** manual + `pytest tests/test_decision.py -q` (R4, R6, R0)
**Dependencies:** T2, T3 · **Files:** `pipeline.py`, `decision.py`, `tests/test_decision.py` · **Scope:** M

## ✅ Checkpoint A
- [ ] `pytest -q` hijau · [ ] `run --no-llm` stabil 5 menit dengan 4 kamera · [ ] Commit

---

## Fase 2: LLM + Keputusan Lengkap

### T5: Gemini Vision verifier (§5)
**Description:** `vision_llm.verify(frame, ctx, prompt_version) -> LLMVerdict` memakai SDK `google-genai`, JSON schema §5.1, resize ke JPEG ≤ 1024 px, retry parse 1x, timeout 20 dtk, dan rate limiter global. Prompt v1/v2 di `prompts.py`. **Cek dokumentasi resmi SDK terlebih dahulu.**
**Acceptance criteria:**
- [ ] Foto api memberi `fire_visible=true`. Foto hutan normal memberi `hazard_type="none"`
- [ ] Output selalu tervalidasi ke dataclass, dan error menghasilkan `LLMVerdict(error=...)`, bukan exception
- [ ] Dua panggilan beruntun menghormati `LLM_MIN_INTERVAL_S`

**Verification:** `pytest tests/test_vision_llm.py -q` (mock client) + 1 panggilan nyata `python -m mataklabat check --llm-sample data/test_set/fire/<file>.jpg`
**Dependencies:** T1 · **Files:** `vision_llm.py`, `prompts.py`, `tests/test_vision_llm.py` · **Scope:** M

### T6: Decision Engine lengkap (§6.2–6.5)
**Description:** Semua rule R0–R6, window konfirmasi, ambang dinamis berdasarkan FRI (sementara FRI di-mock), sub-status, dan `trace` dengan `explanation` dari template deterministik. Trigger T1–T3 di `CameraWorker`.
**Acceptance criteria:**
- [ ] Unit test untuk setiap rule R0–R6 termasuk urutan prioritas
- [ ] `lookalike="fog_cloud"` dengan confidence 0.95 **tidak** menghasilkan BAHAYA (R5)
- [ ] 1 verdict dengan confidence 0.92 cukup untuk BAHAYA. Verdict 0.75 butuh 2/3

**Verification:** `pytest tests/test_decision.py -q`
**Dependencies:** T4, T5 · **Files:** `decision.py`, `pipeline.py`, `tests/test_decision.py` · **Scope:** M

### T7: Storage SQLite + snapshot (§9)
**Description:** `storage.py`: init schema, `insert_event`, `upsert_camera_status`, `open_incident`, `close_incident`, `update_incident_report`, query untuk dashboard. WAL mode. Snapshot `latest.jpg` per kamera, plus arsip saat ≥ WASPADA. Bbox digambar di snapshot.
**Acceptance criteria:**
- [ ] Masuk BAHAYA membuka incident. Turun ke AMAN menutupnya (`closed_ts`)
- [ ] DB bisa dibaca proses lain saat monitor menulis (uji 2 koneksi)

**Verification:** `pytest tests/test_storage.py -q` + manual: `sqlite3 data/runtime/events.db "select level, rule from events order by id desc limit 5"`
**Dependencies:** T6 · **Files:** `storage.py`, `pipeline.py`, `tests/test_storage.py` · **Scope:** S

## ✅ Checkpoint B
- [ ] Video api ke webcam: BAHAYA ≤ 30 dtk, dengan trace di DB · [ ] Foto kabut: dicatat (BAHAYA atau tidak, catat untuk analisis F1) · [ ] Commit

---

## Fase 3: Risiko + Agent

### T8: RiskService + FRI (§6.1)
**Description:** Open-Meteo (`current` + `daily precipitation_sum`, `past_days=14`, `timezone=Asia/Makassar`), cache 15 menit, hitung FRI dan kategori. Jika gagal, pakai nilai terakhir atau `None` (ambang default).
**Acceptance criteria:**
- [ ] Unit test formula FRI dengan input tetap (contoh: RH 40, T 32, W 20, 10 hari kering memberi nilai yang dihitung manual)
- [ ] Decision Engine memakai FRI nyata

**Verification:** `pytest tests/test_risk.py -q`
**Dependencies:** T6 · **Files:** `risk.py`, `tests/test_risk.py` · **Scope:** S

### T9: IncidentAgent + tools + notifier (§7)
**Description:** Tools §7.2 (`estimate_spread` dengan konversi arah angin yang benar), loop function calling Gemini maks 6 langkah dan timeout 60 dtk, laporan markdown disimpan ke `incidents.report_md`, jejak tool ke `agent_steps_json`. `ConsoleNotifier` dan `TelegramNotifier` (mengikuti `AUTO_SEND_ALERT`). Cooldown 10 menit.
**Acceptance criteria:**
- [ ] Angin **dari** 270° (barat) memberi sebaran **ke** timur (90°). Ada unit test
- [ ] Laporan memiliki 6 bagian §7.3 dan label "Dihasilkan AI. Verifikasi lapangan diperlukan."
- [ ] Tanpa `FIRMS_MAP_KEY`, laporan menulis "tidak tersedia", bukan data karangan

**Verification:** `pytest tests/test_tools.py tests/test_agent.py -q` (agent dengan mock LLM) + 1 insiden nyata
**Dependencies:** T7, T8 · **Files:** `tools.py`, `agent.py`, `notifier.py`, tests · **Scope:** M

---

## Fase 4: Dashboard

### T10: Dashboard inti (§10)
**Description:** `app.py`: header status kawasan (level tertinggi semua kamera) + FRI, grid kamera 2×2 dari `latest.jpg` dengan badge warna, peta folium (marker per kamera berwarna, panah arah angin, titik referensi Puncak Klabat), dan panel **"Mengapa?"** untuk kamera terpilih (explanation, reasoning LLM, evidence, JSON trace dalam expander). Refresh 1 dtk via `st.fragment(run_every=1)`.
**Acceptance criteria:**
- [ ] Perubahan level di monitor terlihat di dashboard ≤ 2 dtk
- [ ] Dashboard tidak crash jika DB kosong atau kamera offline (tampil abu-abu)

**Verification:** manual: jalankan monitor + dashboard, picu api
**Dependencies:** T7 · **Files:** `app.py`, `src/mataklabat/ui_helpers.py` · **Scope:** M

### T11: Panel insiden & riwayat
**Description:** Daftar insiden terbuka dan tertutup, render `report_md`, tombol **Kirim ke Telegram** (menandai `alert_sent`), grafik plotly fire/smoke score + level per kamera 30 menit terakhir, tabel event yang bisa difilter.
**Acceptance criteria:**
- [ ] Tombol kirim berfungsi (atau menampilkan pesan jelas jika Telegram belum dikonfigurasi)
- [ ] Grafik menampilkan perubahan level sebagai garis bertingkat

**Verification:** manual
**Dependencies:** T9, T10 · **Files:** `app.py` · **Scope:** S

## ✅ Checkpoint C
- [ ] Jalankan `docs/DEMO.md` menit 2–6 tanpa intervensi kode · [ ] Commit

---

## Fase 5: Evaluasi

### T12: `scripts/evaluate.py`
**Description:** Untuk folder `data/test_set/{fire,smoke,fog,sunset,lights,normal}`: jalankan detektor lokal (gambar statis: pakai 2 salinan dengan jitter kecil agar mask gerak bekerja, atau abaikan gerak dengan flag `--static`), LLM (prompt v1 dan/atau v2), dan keputusan gabungan "satu-shot" (R1 tanpa window). Output `results/predictions.csv` (file, label, scores, verdict, reasoning, benar/salah), `results/metrics.csv` (precision, recall, F1 positif = fire∪smoke, false alarm rate per kelas lookalike), `results/confusion_<variant>.png`, `results/failures.md` (daftar salah klasifikasi + reasoning LLM, dikelompokkan F1–F5). `--repeat N` untuk konsistensi.
**Acceptance criteria:**
- [ ] Berjalan pada ≥ 10 gambar per kelas
- [ ] `failures.md` memuat minimal 1 contoh untuk F1, F2, dan F3 (jika ada)
- [ ] Tabel perbandingan v1 dan v2 tersedia

**Verification:** `python scripts/evaluate.py --set data/test_set --prompt v1,v2 --repeat 3`
**Dependencies:** T5, T6 · **Files:** `scripts/evaluate.py`, `results/` · **Scope:** M

---

## Fase 6: Polish

### T13: README & demo readiness
**Description:** Screenshot dashboard ke `docs/assets/` dan tautkan di README. Isi tabel hasil evaluasi di README. Uji ulang `DEMO.md` dari awal. Pastikan `.gitignore` benar.
**Acceptance criteria:**
- [ ] Clone bersih + ikuti Quick Start memberi sistem yang berjalan
- [ ] Tidak ada secret atau data runtime di git (`git status` bersih, `git log -p | grep -i api_key` kosong)

**Verification:** manual
**Dependencies:** semua · **Scope:** S

## ✅ Checkpoint D: Selesai
- [ ] Semua DoD di `AGENTS.md` · [ ] Push ke GitHub
