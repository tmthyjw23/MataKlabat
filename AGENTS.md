# AGENTS.md: Instruksi untuk AI Coding Agent

Kamu membangun **MataKlabat**, sistem pencegahan dan deteksi dini karhutla Gunung Klabat (Python). Demo di laptop dengan **standar production** (andal, bisa diamati, aman, teruji).

## Baca dulu (urutan wajib)

1. `docs/PRD.md`: apa dan untuk siapa
2. `docs/ARCHITECTURE.md`: **kontrak teknis** (modul, skema JSON, aturan keputusan, DB)
   dan `docs/superpowers/specs/2026-10-26-mataklabat-v2-design.md`: spec v2 (dua status, Telegram, web)
3. `tasks/plan.md` lalu `tasks/todo.md`: urutan kerja. Kerjakan task **berurutan** dan centang `[x]` setelah verifikasi lulus

## Aturan kerja

- **Ikuti ARCHITECTURE.md.** Nama modul, field JSON, nama rule (R0–R6), dan nama tabel tidak boleh diubah. Jika harus menyimpang, tambahkan baris di *Decision Log* (§12) beserta alasannya.
- **Vertical slice.** Setiap task meninggalkan sistem dalam keadaan bisa dijalankan. Jangan membangun semua modul dulu baru menyambungkannya di akhir.
- **Paling sederhana yang bekerja.** Gunakan standard library, OpenCV, FastAPI (web read-only) dan HTML/JS biasa tanpa build step. Jangan menambah framework lain (React, Celery, Redis, Docker) tanpa diminta.
- **Jangan pernah commit secret.** API key hanya di `.env` (gitignored). `.env.example` berisi placeholder.
- **Jangan mengarang data dunia nyata.** Nomor telepon, koordinat pasti, dan statistik yang tidak ada di docs ditulis `ISI_SENDIRI` atau ditandai "perkiraan".
- **Bahasa:** kode, nama variabel, dan docstring dalam English. Teks UI, laporan agent, dan pesan log untuk pengguna dalam Bahasa Indonesia. Label status untuk pengguna: Normal / Perlu Dicek / Kebakaran Terdeteksi (nilai internal tetap AMAN/WASPADA/BAHAYA).
- **Keamanan web:** teks dari API/LLM hanya dirender sebagai teks (tanpa `innerHTML`), tanpa inline script/style; web tidak pernah menulis ke DB atau menampilkan secret.
- **Zona waktu:** `Asia/Makassar` untuk semua timestamp yang tampil.
- Jika ada blocker lebih dari 20 menit (misalnya API berubah), pilih jalan paling sederhana, catat di Decision Log, lalu lanjut.

## Stack

- Python 3.11+, `opencv-python`, `numpy`, `openai` (klien untuk endpoint OpenAI-compatible **9router**, bukan API OpenAI langsung), `fastapi`, `uvicorn`, `matplotlib` (evaluasi), `pyyaml`, `python-dotenv`, `requests`, `pytest`; Leaflet 1.9.4 disimpan di `web/static/vendor/`
- Opsional: `ultralytics` (hanya jika `YOLO_WEIGHTS` diisi; import secara lazy)
- LLM: env `LLM_BASE_URL` (default `http://localhost:20128/v1`), `LLM_API_KEY`, `LLM_MODEL` (wajib, model vision + tool calling dari dashboard 9router). Jangan hardcode nama model di kode.

## Perintah

```bash
pip install -e .
python -m mataklabat check [--llm-sample FOTO]
python -m mataklabat up [--no-llm] [--host 0.0.0.0]      # monitor + web, restart otomatis
python -m mataklabat run [--camera CAM-01] [--no-llm] [--prompt v1|v2] [--duration DETIK]
python -m mataklabat web [--host 127.0.0.1] [--port 8000]
python scripts/evaluate.py --set data/test_set --prompt v2 [--repeat 3] [--no-llm]
pytest -q
```

## Definition of Done (setiap task)

- [ ] Acceptance criteria di `tasks/todo.md` terpenuhi
- [ ] `pytest -q` hijau
- [ ] `python -m mataklabat run --no-llm` masih berjalan tanpa error
- [ ] Tidak ada secret, file `data/runtime/*`, atau video besar (> 20 MB) yang ter-commit
- [ ] Commit kecil dengan pesan jelas, contoh `feat(detector): color+motion fire/smoke scoring`

## Yang TIDAK boleh dilakukan

- Menambah sentiment analysis (dikesampingkan dosen)
- Menulis `explanation` di decision trace memakai LLM. Wajib template deterministik
- Mengirim Telegram saat `AUTO_SEND_ALERT=false` (mode kering) atau di luar tabel `outbox`
- Memanggil LLM di setiap frame. Patuhi trigger T1–T3 dan `LLM_MIN_INTERVAL_S`
- Menghapus test yang gagal atau melonggarkan ambang hanya supaya test lulus
