# Task List: MataKlabat

Kerjakan berurutan. Centang `[x]` hanya setelah **Verification** lulus. Rujukan "§" mengacu ke `docs/ARCHITECTURE.md`.

---

## Fase 0: Fondasi

### T1: Scaffold proyek & config
**Description:** Buat struktur folder sesuai README, `pyproject`/`requirements.txt`, package `src/mataklabat`, `config.py` yang memuat `.env` + `config/cameras.yaml` + `config/resources.yaml` ke dataclass `Settings` (termasuk semua konstanta §4.3 dan §6.2, override-able via env).
**Acceptance criteria:**
- [x] `python -m mataklabat --help` menampilkan perintah `run` dan `check`
- [x] `Settings` gagal dengan pesan jelas jika `cameras.yaml` tidak valid
- [x] `LLM_MODEL` kosong tidak membuat crash, cukup peringatan dan `llm_enabled=False` *(awalnya `GEMINI_API_KEY`, diganti 9router)*

**Verification:** `pytest tests/test_config.py -q`
**Dependencies:** None · **Files:** `src/mataklabat/{__init__,__main__,config}.py`, `tests/test_config.py` · **Scope:** S

### T2: CameraSource + perintah `check`
**Description:** `CameraSource` mendukung int (webcam), path video (loop otomatis saat EOF), dan URL RTSP. Thread pembaca menyimpan frame terbaru. `latest()` mengembalikan `Frame | None`, dan `online` false jika > 5 dtk tanpa frame. `check` menguji setiap kamera, LLM (panggilan teks kecil ke 9router), dan Open-Meteo.
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

### T5: LLM Vision verifier via 9router (§5)
**Description:** `vision_llm.verify(frame, ctx, prompt_version) -> LLMVerdict` memakai SDK `openai` ke endpoint 9router (`LLM_BASE_URL`), JSON schema §5.1, resize ke JPEG ≤ 1024 px, retry parse 1x, timeout 20 dtk, dan rate limiter global. Prompt v1/v2 di `prompts.py`. **Cek dokumentasi resmi SDK terlebih dahulu.**
**Acceptance criteria:**
- [ ] Foto api memberi `fire_visible=true`. Foto hutan normal memberi `hazard_type="none"`
- [x] Output selalu tervalidasi ke dataclass, dan error menghasilkan `LLMVerdict(error=...)`, bukan exception
- [x] Dua panggilan beruntun menghormati `LLM_MIN_INTERVAL_S`

**Verification:** `pytest tests/test_vision_llm.py -q` (mock client) + 1 panggilan nyata `python -m mataklabat check --llm-sample data/test_set/fire/<file>.jpg`
**Dependencies:** T1 · **Files:** `vision_llm.py`, `prompts.py`, `tests/test_vision_llm.py` · **Scope:** M

### T6: Decision Engine lengkap (§6.2–6.5)
**Description:** Semua rule R0–R6, window konfirmasi, ambang dinamis berdasarkan FRI (sementara FRI di-mock), sub-status, dan `trace` dengan `explanation` dari template deterministik. Trigger T1–T3 di `CameraWorker`.
**Acceptance criteria:**
- [x] Unit test untuk setiap rule R0–R6 termasuk urutan prioritas
- [x] `lookalike="fog_cloud"` dengan confidence 0.95 **tidak** menghasilkan BAHAYA (R5)
- [x] 1 verdict dengan confidence 0.92 cukup untuk BAHAYA. Verdict 0.75 butuh 2/3

**Verification:** `pytest tests/test_decision.py -q`
**Dependencies:** T4, T5 · **Files:** `decision.py`, `pipeline.py`, `tests/test_decision.py` · **Scope:** M

> **v2 (26 Okt 2026):** task T7 dan seterusnya disusun ulang mengikuti `docs/superpowers/specs/2026-10-26-mataklabat-v2-design.md` (selanjutnya "Spec"). T1–T6 tetap berlaku.

### T7: Risiko Kawasan: FWI + FDRS (Spec §6)
**Description:** `fwi.py` (Van Wagner 1987, penyesuaian lintang ekuator seperti `cffdrs`), kelas FDRS Indonesia (de Groot dkk. 2006, tabel 1–3), `risk.py` (Open-Meteo, spin-up, cache, data basi, prakiraan 3 hari). Decision Engine memakai kelas risiko untuk ambang.
**Acceptance criteria:**
- [x] FFMC/DMC/DC/ISI/BUI/FWI cocok dengan nilai referensi Van Wagner & Pickett (±0,1)
- [x] Kelas FFMC/DC/ISI sesuai tabel FDRS; risiko kawasan = kelas tertinggi + indikator penentunya
- [x] Open-Meteo gagal → nilai terakhir + label basi; > 6 jam → "tidak diketahui"
**Verification:** `pytest tests/test_fwi.py tests/test_risk.py -q`

### T8: Kamera Foto (Spec §5.2)
**Description:** `FolderSource`: foto terbaru di folder, `mode: foto` di `cameras.yaml`, detektor tanpa gerak, foto baru memicu LLM sekali.
**Acceptance criteria:**
- [x] Menyalin foto baru ke folder → frame baru ≤ 2 dtk
- [x] Folder kosong → offline dengan pesan jelas
**Verification:** `pytest tests/test_camera.py tests/test_pipeline.py -q`

### T9: Storage, snapshot, kesehatan (Spec §11–12)
**Description:** `storage.py` (skema Spec §11, WAL, retensi), `snapshots.py` (latest + arsip + bbox), insiden buka/tutup, `component_health` + heartbeat monitor, log file berotasi.
**Acceptance criteria:**
- [x] BAHAYA membuka insiden; kembali AMAN menutupnya
- [x] DB bisa dibaca proses lain saat monitor menulis
- [x] Retensi menghapus event > 7 hari
**Verification:** `pytest tests/test_storage.py -q`

### T10: Pesan, kebijakan alert, outbox Telegram (Spec §8)
**Description:** `messages.py`, `alerts.py`, `notifier.py` (`TelegramClient`, `OutboxSender`).
**Acceptance criteria:**
- [ ] Kebijakan bertingkat + cooldown + ringkasan pagi + risiko naik
- [ ] Caption ≤ 1.024 karakter; retry/backoff; 429; mode kering
- [ ] Token tidak pernah muncul di log/DB
**Verification:** `pytest tests/test_messages.py tests/test_alerts.py tests/test_notifier.py -q`

### T11: AI Agent + tools (Spec §9)
**Description:** `tools.py`, `agent.py` (tool calling 9router, maks 6 langkah, 60 dtk), laporan template cadangan.
**Acceptance criteria:**
- [ ] Angin dari 270° → sebaran ke 90°
- [ ] Laporan 6 bagian + label AI; tanpa FIRMS → "tidak tersedia"
- [ ] Agent gagal/timeout → laporan template
**Verification:** `pytest tests/test_tools.py tests/test_agent.py -q`

### T12: Website (Spec §10)
**Description:** `web/app.py` (FastAPI read-only, SSE, header keamanan) + `web/static` (dashboard, insiden, kesehatan, Leaflet 3 lapisan).
**Acceptance criteria:**
- [ ] Semua endpoint Spec §10.2 teruji; ID kamera tidak valid → 404
- [ ] Teks LLM tidak pernah dirender sebagai HTML; CSP aktif
- [ ] Banner "data tidak live" dan "monitor tidak merespons"
**Verification:** `pytest tests/test_web.py -q` + manual di browser

### T13: Supervisor `up` + skenario demo (Spec §12–13)
**Acceptance criteria:**
- [ ] `up` menjalankan monitor + web, restart saat crash, Ctrl+C bersih
- [ ] Test skenario: api → Kebakaran Terdeteksi + 2 pesan; kabut → R5 tanpa peringatan; pembakaran sampah → POTENSI
**Verification:** `pytest tests/test_supervisor.py tests/test_scenarios.py -q`

### T14: `scripts/evaluate.py`
**Description:** (seperti T12 lama) metrics, confusion, `failures.md`, v1 vs v2, `--repeat`.
**Verification:** `python scripts/evaluate.py --set data/test_set --prompt v1,v2 --repeat 3` (butuh test set + 9router)

### T15: Dokumen & kesiapan demo
**Acceptance criteria:**
- [ ] PRD, ARCHITECTURE, AGENTS, README sesuai Spec; `docs/DEMO.md` berisi checklist Spec §16
- [ ] Clone bersih + Quick Start berjalan; tidak ada secret di git

## ✅ Checkpoint Akhir
- [ ] `pytest -q` hijau · [ ] `run --no-llm` dan `up` berjalan · [ ] Uji nyata 9router + Telegram (butuh `.env`) · [ ] Push ke GitHub (oleh pemilik)
