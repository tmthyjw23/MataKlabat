# Panduan Setup MataKlabat untuk Tim

Ikuti urutan ini dari laptop yang akan dipakai demo. Total waktu ±45 menit pertama kali (sebagian besar menunggu unduhan). Semua perintah dijalankan di **PowerShell** atau **Git Bash** dari folder proyek, kecuali yang ditandai **[WSL]**.

> Yang dibagikan **secara pribadi** (bukan lewat git/grup publik): token bot Telegram dan API key 9router. File `.env` tidak pernah di-commit.

---

## 0. Siapa mengerjakan apa (isi bersama)

| Tugas | Penanggung jawab |
|---|---|
| Laptop demo + setup langkah 1–6 | |
| Bot & grup Telegram (langkah 4) | |
| Slide + latihan presentasi | |
| Video cadangan demo | |

---

## 1. Prasyarat (sekali saja)

| Perlu | Cek | Unduh |
|---|---|---|
| Python **3.11+** | `python --version` | [python.org](https://www.python.org/downloads/) (centang *Add to PATH*) |
| Git | `git --version` | [git-scm.com](https://git-scm.com/) |
| Node.js 20+ (untuk 9router) | `node --version` | [nodejs.org](https://nodejs.org/) (di WSL atau Windows) |
| Webcam | – | bawaan laptop cukup |
| Telegram di HP | – | – |

Ruang disk: ±1,5 GB (paket Python ±1 GB, foto/video ±45 MB).

## 2. Ambil kode dan pasang

```bash
git clone https://github.com/tmthyjw23/MataKlabat.git
cd MataKlabat
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e .
```

Cek: `python -m mataklabat --help` menampilkan `{up,run,web,check}`.

Sudah pernah memasang sebelum 28 Okt 2026? OpenCV diganti ke versi headless; sekali saja jalankan `pip uninstall -y opencv-python` lalu `pip install -e .` lagi.

Unduh foto test set, foto demo, dan video (sumber + lisensi di `data/MEDIA_SOURCES.md`):

```bash
python scripts/fetch_media.py
```

Hasil yang benar: `Selesai: 92 diunduh … 0 gagal` (jika ada yang gagal, jalankan ulang; file yang sudah ada dilewati).

## 3. 9router (LLM vision + AI Agent)

MataKlabat memanggil AI lewat [9router](https://github.com/decolua/9router), gateway lokal yang kompatibel dengan OpenAI.

1. **[WSL atau terminal]** pasang dan jalankan sesuai README 9router (umumnya `npm install -g 9router`, lalu `9router`).
2. Buka dashboard `http://localhost:20128` di browser Windows.
3. Hubungkan provider (akun milik sendiri) dan pilih **model yang mendukung gambar dan tool calling**. Model yang sudah teruji: `ag/gemini-3.8-flash-high`.
4. Salin **API key** dan **nama model** dari dashboard.
5. **Biarkan terminal 9router tetap terbuka** selama evaluasi dan demo. Jika terminal WSL ditutup, 9router ikut mati (gejala: `check` menampilkan ❌ LLM "Connection error").

## 4. Bot Telegram

1. Di Telegram, chat **@BotFather** → `/newbot` → beri nama → salin **token** (bentuk `123456:ABC…`).
2. Buat **grup demo**, masukkan bot ke grup, lalu kirim satu pesan apa saja di grup.
3. Cari **chat ID** grup: buka di browser `https://api.telegram.org/bot<TOKEN>/getUpdates` (ganti `<TOKEN>`), cari `"chat":{"id":-100…}`. Angka negatif itu chat ID-nya.
   - Jangan bagikan URL ini: berisi token.
4. Undang dosen/penguji ke grup demo jika ingin mereka melihat pesan masuk.

## 5. Isi `.env`

```bash
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

Buka `.env` di editor dan isi:

| Variabel | Isi |
|---|---|
| `LLM_MODEL` | nama model dari 9router, misal `ag/gemini-3.8-flash-high` |
| `LLM_API_KEY` | API key dari dashboard 9router |
| `TELEGRAM_BOT_TOKEN` | token dari BotFather |
| `TELEGRAM_CHAT_ID` | chat ID grup (angka negatif) |
| `FIRMS_MAP_KEY` | opsional, hotspot satelit dari [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/api/map_key) |

Biarkan variabel lain sesuai default.

## 6. Cek sistem

```bash
python -m mataklabat check
```

Yang diharapkan:

```
✅  CAM-01  640x480 …            (webcam)
✅  CAM-02  1280x720 …           (video)
✅  CAM-03  1280x720 …           (video)
✅  CAM-04  … Matungkas - Laikit (kamera foto; perlu minimal 1 foto di data/demo/CAM-04)
✅  LLM     … menjawab 'OK'
✅  Open-Meteo …
✅  Telegram bot @…
```

Jika CAM-04 ❌ "folder belum berisi foto": salin satu foto normal, misal
`copy data\demo\bahan\klabat.jpg data\demo\CAM-04\00_klabat_normal.jpg`.

Uji AI dengan satu foto (±15 detik):

```bash
python -m mataklabat check --llm-sample data/test_set/fire/fire_03.jpg
```

Harus muncul `"fire_visible": true` dan alasan dalam Bahasa Indonesia.

## 6b. Mode operator (kamera aktif/nonaktif)

Isi `OPERATOR_PASSWORD` di `.env` (minimal 10 karakter). Di dashboard muncul tombol **Masuk operator**; setelah masuk, setiap kartu kamera punya tombol **Aktifkan/Nonaktifkan**, dan Kamera Foto punya **Pilih foto** (galeri dari `data/demo/bahan`). Kamera nonaktif tidak memakai AI dan tidak mengirim Telegram; menonaktifkan kamera me-reset statusnya ke Normal. Tanpa `OPERATOR_PASSWORD`, website hanya-baca seperti sebelumnya dan kamera mengikuti `enabled:` di file kamera.

Untuk VPS/server: [`DEPLOY.md`](DEPLOY.md).

## 7. Jalankan

```bash
python -m mataklabat up
```

Buka **http://127.0.0.1:8000**. Halaman **Kesehatan sistem** (`/health`) harus hijau semua. Ctrl+C menghentikan semuanya.

Untuk membuka dashboard dari HP di Wi-Fi yang sama: `python -m mataklabat up --host 0.0.0.0`, lalu buka `http://<IP-laptop>:8000` (cek IP dengan `ipconfig`). Dashboard hanya-baca; matikan setelah demo.

## 8. Latihan demo

Ikuti alur dan checklist di [`docs/DEMO.md`](DEMO.md). Ringkas:

1. **Kabut** → seret `data\demo\bahan\kabut_gunung.jpg` ke `data\demo\CAM-04\` → tetap **Normal**, AI menulis "mirip kabut/awan".
2. **Pencegahan** → `potensi_01.jpg` (api unggun) → **Perlu Dicek (potensi)** + Telegram "belum pasti".
3. **Kebakaran** → `asap_kolom.jpg` → **Kebakaran Terdeteksi** dalam ±35 dtk → Telegram (foto + alasan), lalu laporan AI Agent ±1 menit kemudian.

Tunggu ±30 detik setelah tiap foto (satu cek AI ±15 detik). Setelah Kebakaran Terdeteksi, kamera butuh ±4–5 menit untuk kembali Normal, jadi letakkan adegan api terakhir.

**Mulai bersih sebelum demo:** hentikan `up`, hapus folder `data\runtime\`, kosongkan `data\demo\CAM-04\` kecuali satu foto normal.

## 9. Evaluasi (opsional, untuk slide)

Hasil sudah ada di `results/`. Untuk mengulang (±40 menit, 9router harus berjalan):

```bash
python scripts/evaluate.py --set data/test_set --prompt v1,v2
python scripts/evaluate.py --set data/test_set --prompt v2 --per-class 2 --repeat 3 --out results/consistency
```

Jika berhenti di tengah (9router mati/timeout), jalankan ulang dengan `--resume`.

## 10. Masalah umum

| Gejala | Penyebab | Solusi |
|---|---|---|
| ❌ LLM "Connection error" | 9router tidak berjalan | jalankan lagi 9router, cek `http://localhost:20128` |
| LLM "Request timed out" | provider lambat | tunggu, ulangi; naikkan `LLM_TIMEOUT_S` di `.env` |
| LLM 429/503 "quota" / "reset after …" | kuota model di 9router habis (evaluasi penuh ±600 panggilan bisa menghabiskannya) | ganti `LLM_MODEL` ke model atau akun lain di 9router; jangan jalankan evaluasi penuh menjelang demo |
| ❌ CAM-01 | webcam dipakai aplikasi lain | tutup Zoom/Meet/Teams |
| ❌ CAM-02/03 "file video tidak ditemukan" | media belum diunduh | `python scripts/fetch_media.py` |
| Telegram tidak masuk | token/chat ID salah, bot belum di grup | ulangi langkah 4; status pesan terlihat di `/health` |
| Pesan "mode kering" | `TELEGRAM_*` kosong atau `AUTO_SEND_ALERT=false` | isi `.env`, jalankan ulang `up` |
| Peta kosong | tidak ada internet | marker & status tetap jalan; pakai hotspot HP |
| Banner "Monitor tidak merespons" | monitor crash | supervisor menyalakan ulang otomatis; cek terminal |
| `pip install` gagal | versi Python < 3.11 | pasang Python 3.11+ |

Masih bermasalah: jalankan `python -m mataklabat check` dan kirim hasilnya (tanpa isi `.env`) ke grup tim.
