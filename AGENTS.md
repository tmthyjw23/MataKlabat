# AGENTS.md: Instruksi untuk AI Coding Agent

Kamu membangun **MataKlabat**, sistem peringatan dini karhutla Gunung Klabat (Python). Target: **selesai dan bisa didemokan dalam 1 hari kerja (±8 jam agent)**.

## Baca dulu (urutan wajib)

1. `docs/PRD.md`: apa dan untuk siapa
2. `docs/ARCHITECTURE.md`: **kontrak teknis** (modul, skema JSON, aturan keputusan, DB)
3. `tasks/plan.md` lalu `tasks/todo.md`: urutan kerja. Kerjakan task **berurutan** dan centang `[x]` setelah verifikasi lulus

## Aturan kerja

- **Ikuti ARCHITECTURE.md.** Nama modul, field JSON, nama rule (R0–R6), dan nama tabel tidak boleh diubah. Jika harus menyimpang, tambahkan baris di *Decision Log* (§12) beserta alasannya.
- **Vertical slice.** Setiap task meninggalkan sistem dalam keadaan bisa dijalankan. Jangan membangun semua modul dulu baru menyambungkannya di akhir.
- **Paling sederhana yang bekerja.** Gunakan standard library, OpenCV, dan Streamlit. Jangan menambah framework (FastAPI, Celery, Redis, Docker) tanpa diminta.
- **Jangan pernah commit secret.** API key hanya di `.env` (gitignored). `.env.example` berisi placeholder.
- **Jangan mengarang data dunia nyata.** Nomor telepon, koordinat pasti, dan statistik yang tidak ada di docs ditulis `ISI_SENDIRI` atau ditandai "perkiraan".
- **Bahasa:** kode, nama variabel, dan docstring dalam English. Teks UI, laporan agent, dan pesan log untuk pengguna dalam Bahasa Indonesia.
- **Zona waktu:** `Asia/Makassar` untuk semua timestamp yang tampil.
- Jika ada blocker lebih dari 20 menit (misalnya API berubah), pilih jalan paling sederhana, catat di Decision Log, lalu lanjut.

## Stack

- Python 3.11+, `opencv-python`, `numpy`, `openai` (klien untuk endpoint OpenAI-compatible **9router**, bukan API OpenAI langsung), `streamlit`, `streamlit-folium`, `folium`, `plotly`, `pandas`, `pyyaml`, `python-dotenv`, `requests`, `pytest`
- Opsional: `ultralytics` (hanya jika `YOLO_WEIGHTS` diisi; import secara lazy)
- LLM: env `LLM_BASE_URL` (default `http://localhost:20128/v1`), `LLM_API_KEY`, `LLM_MODEL` (wajib, model vision + tool calling dari dashboard 9router). Jangan hardcode nama model di kode.

## Perintah

```bash
pip install -e .
python -m mataklabat check
python -m mataklabat run [--camera CAM-01] [--no-llm] [--prompt v1|v2]
streamlit run app.py
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
- Membiarkan agent mengirim Telegram otomatis saat `AUTO_SEND_ALERT=false`
- Memanggil LLM di setiap frame. Patuhi trigger T1–T3 dan `LLM_MIN_INTERVAL_S`
- Menghapus test yang gagal atau melonggarkan ambang hanya supaya test lulus
