# MataKlabat v2: Spec Desain

| | |
|---|---|
| **Tanggal** | 26 Oktober 2026 |
| **Status** | Draf, menunggu review pemilik proyek |
| **Menggantikan** | Bagian yang bertentangan di `docs/PRD.md`, `docs/ARCHITECTURE.md`, `tasks/todo.md` (akan diperbarui setelah spec disetujui) |
| **Mockup** | [MataKlabat Web Mockup](https://claude.ai/artifact/3GxtXGNP8Sk3BeD9u8e93a) (dashboard desktop + pesan Telegram) |

---

## 1. Ringkasan

MataKlabat adalah sistem **pencegahan dan deteksi dini karhutla** kawasan Gunung Klabat. Sistem menggabungkan tiga lapis sinyal:

1. **Cuaca** → *Risiko Kebakaran Kawasan* (pencegahan), dihitung dengan Fire Weather Index (FWI).
2. **Kamera** → detektor lokal (warna + gerak) mencurigai api/asap.
3. **LLM vision** (via 9router) → *verifikasi*: menambah keyakinan dan memberi penjelasan. LLM tidak memutuskan sendiri; aturan R0–R6 yang memutuskan.

Hasilnya tampil di **website** (FastAPI + halaman web ringan) dan dikirim ke **Telegram** dengan foto, alasan, dan data yang dipakai. Saat kebakaran terdeteksi, **AI Agent** menyusun laporan insiden sebagai pesan kedua.

**Konteks pemakaian:** demo tugas kuliah di laptop, kode open source di GitHub, tetapi dibangun dengan **standar production** (§12).

---

## 2. Keputusan dari brainstorming

| # | Topik | Keputusan |
|---|---|---|
| D1 | Audiens & hosting | Demo di laptop; open source di GitHub; tidak di-hosting online |
| D2 | Kualitas | Standar production: andal, bisa diamati, aman, teruji, satu perintah start |
| D3 | Model status | **Dua status terpisah**: Risiko Kawasan (cuaca) dan Status Kamera (deteksi) |
| D4 | Telegram | **Bertingkat dan otomatis** (§8) |
| D5 | AI Agent | Dipertahankan sebagai **pesan kedua**; peringatan cepat tidak menunggu agent |
| D6 | Website | **FastAPI + HTML/CSS/JS biasa**, tanpa Node/build step; Streamlit dihapus |
| D7 | Indeks risiko | **Canadian FWI** (dasar FDRS Indonesia/BMKG), menggantikan FRI heuristik |
| D8 | LLM | **9router** (OpenAI-compatible) untuk vision dan agent; tanpa cadangan Gemini |
| D9 | Peta | Leaflet, 3 lapisan: **OpenTopoMap (default)**, Sentinel-2 cloudless (EOX), OpenStreetMap |
| D10 | Kamera demo | **Campuran**: CAM-01 webcam, CAM-02/03 video stok, CAM-04 **Kamera Foto** (folder) |
| D11 | Replay cuaca historis | **Tidak** dibuat |
| D12 | Data | Hanya gambar kamera yang simulasi; data lain asli (§15) |

---

## 3. Dua status

### 3.1 Risiko Kebakaran Kawasan (pencegahan)

Satu nilai untuk seluruh kawasan, dihitung dari cuaca di kaki Klabat (`weather_point`, Airmadidi). *(Revisi 27 Okt: semula Puncak Klabat, lihat Decision Log.)*

| Level | Arti untuk pengguna | Saran tindakan (template) |
|---|---|---|
| **Rendah** | Sulit terbakar | Pemantauan rutin |
| **Sedang** | Bisa terbakar jika ada sumber api | Waspadai pembakaran lahan dan sampah |
| **Tinggi** | Mudah terbakar dan menyebar | Larang pembakaran terbuka; tingkatkan patroli jalur pendakian |
| **Sangat Tinggi** | Sangat mudah terbakar, sulit dikendalikan | Siagakan regu pemadam; pertimbangkan penutupan jalur pendakian |

Ambang kelas: lihat §6.4.

### 3.2 Status Kamera (deteksi)

Label baru untuk level Decision Engine yang sudah ada (nama internal tetap, supaya kode T1–T6 tidak berubah makna):

| Internal (`Level`) | Label UI | Ikon (bentuk) | Warna |
|---|---|---|---|
| `AMAN` | **Normal** | lingkaran | `#1F7A4D` |
| `WASPADA` | **Perlu Dicek** | segitiga | `#B45309` |
| `BAHAYA` | **Kebakaran Terdeteksi** | segi delapan | `#B42318` |
| offline | **Offline** | lingkaran kosong | `#5B6560` |

Api kecil yang terkendali (api unggun, tungku masak, pembakaran tumpukan kecil yang dijaga) diberi `hazard_type = controlled_fire` dan menjadi **Perlu Dicek (potensi)**, bukan Kebakaran Terdeteksi *(revisi 27 Okt)*.

Sub-status tampil sebagai keterangan kecil: `unverified` → "belum terverifikasi AI", `POTENSI` → "potensi (faktor risiko terlihat)", `rejected_lookalike` → "AI menolak: mirip kabut/senja/lampu".

---

## 4. Arsitektur

```
python -m mataklabat up          (supervisor: start, restart otomatis, stop bersih)
├── monitor  (python -m mataklabat run)
│     CameraWorker ×N : kamera → detektor → [LLM verifier] → DecisionEngine
│     RiskService      : Open-Meteo → FWI harian + prakiraan 3 hari
│     AlertService     : kebijakan Telegram (§8) → tabel outbox
│     OutboxSender     : kirim Telegram dengan retry
│     IncidentAgent    : laporan insiden (pesan 2)
│     Heartbeat        : tulis kesehatan komponen tiap 5 dtk
│     → SQLite (WAL) + snapshot JPEG
└── web      (python -m mataklabat web)
      FastAPI read-only: /api/* + SSE + file statis → browser
```

Prinsip: monitor satu-satunya penulis DB; web hanya membaca. Salah satu crash tidak menghentikan yang lain.

### 4.1 Modul

| Modul | Status | Tanggung jawab |
|---|---|---|
| `config.py` | ubah | + kamera `mode: foto`, setelan web, Telegram, FWI, retensi |
| `camera.py` | ubah | + `FolderSource` (§5.2) |
| `detector.py` | tetap | mode tanpa gerak dipakai untuk kamera foto |
| `prompts.py`, `vision_llm.py` | tetap | sudah via 9router |
| `decision.py` | ubah kecil | ambang dinamis memakai kelas FWI (bukan FRI) |
| `risk.py` | **baru** | Open-Meteo, perhitungan FWI, kelas, prakiraan, cache, data basi |
| `fwi.py` | **baru** | rumus FWI murni (tanpa I/O), diuji dengan nilai referensi |
| `alerts.py` | **baru** | kebijakan kapan mengirim (§8.1), cooldown, ringkasan pagi |
| `messages.py` | **baru** | template pesan (Telegram + web), deterministik |
| `notifier.py` | **baru** | `TelegramClient`, `OutboxSender` (retry/backoff) |
| `agent.py`, `tools.py` | **baru** | AI Agent tool calling via 9router + laporan template cadangan |
| `storage.py` | **baru** | skema §11, query untuk web, retensi |
| `snapshots.py` | **baru** | simpan `latest.jpg` + arsip, gambar bbox |
| `pipeline.py` | ubah | sambungkan risk, storage, alerts, agent, heartbeat |
| `supervisor.py` | **baru** | perintah `up` |
| `web/app.py` | **baru** | FastAPI, endpoint §10.2, header keamanan |
| `web/static/` | **baru** | `index.html`, `incident.html`, `health.html`, `app.css`, `app.js`, `vendor/leaflet/` |
| `scripts/evaluate.py` | tetap (T12) | evaluasi test set |

---

## 5. Kamera

### 5.1 Jenis sumber

| `source` | Contoh | Perilaku |
|---|---|---|
| angka | `0` | Webcam |
| path file video | `data/videos/cam02.mp4` | Diputar berulang pada fps asli |
| URL | `rtsp://…` | Stream, sambung ulang otomatis |
| path folder + `mode: foto` | `data/demo/CAM-04/` | **Kamera Foto** (§5.2) |

### 5.2 Kamera Foto

- Menampilkan **file gambar terbaru** (berdasarkan waktu modifikasi) di folder; format `.jpg .jpeg .png .webp`.
- Folder dipindai tiap 1 detik. Saat foto berganti, kamera menerbitkan frame baru; selama foto sama, frame yang sama diterbitkan ulang supaya kamera tetap *online*.
- Detektor memakai `use_motion=False` (warna saja), karena foto diam tidak punya gerak.
- **Foto baru = kejadian baru:** LLM dipanggil segera untuk foto itu (prioritas setara T1, tanpa menunggu `RECHECK_S`), maksimal sekali per foto. Setelah itu trigger T2/T3 berlaku normal.
- Web menampilkan label **"Mode foto"** pada kamera ini.
- Folder kosong → kamera *offline* dengan pesan "folder belum berisi foto".

### 5.3 Susunan demo (D10)

| Kamera | Sumber | Lokasi (hipotetis, koordinat diverifikasi di peta) |
|---|---|---|
| CAM-01 | Webcam | Monumen Kaki Dian (Airmadidi) |
| CAM-02 | Video stok hutan | Jalur Pendakian Klabat, Pos 1 |
| CAM-03 | Video stok hutan | Desa Tatelu |
| CAM-04 | Kamera Foto | Matungkas–Laikit |

---

## 6. Risiko Kawasan: FWI

### 6.1 Data

Open-Meteo `forecast` untuk `weather_point` (Airmadidi, kaki Klabat), `timezone=Asia/Makassar`, `past_days` maksimum yang diizinkan API, `forecast_days=4`:
- per jam: `temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`, `wind_direction_10m`, `precipitation`.
- Nilai harian FWI memakai **pengamatan pukul 12:00 WITA** (suhu, RH, angin) dan **hujan 24 jam** sebelumnya (12:00 kemarin s/d 12:00 hari ini), sesuai konvensi FWI.

Ini data **model cuaca** (resolusi beberapa km), bukan stasiun BMKG; web menyebutkannya.

### 6.2 Perhitungan

`fwi.py` mengimplementasikan Van Wagner (1987): FFMC, DMC, DC → ISI, BUI → FWI.
- Rantai dimulai dari nilai awal standar (FFMC 85, DMC 6, DC 15) pada hari pertama data, lalu dihitung maju hari demi hari (*spin-up*). Hasil per hari disimpan di tabel `risk_daily`, jadi restart tidak memutus rantai.
- **Penyesuaian panjang hari** untuk DMC/DC: karena Klabat ±1,47° LU (dekat ekuator), gunakan faktor yang sesuai lintang ekuator seperti yang dipakai FDRS Indonesia. Implementasi wajib dicek terhadap sumber (paket `cffdrs` atau publikasi FDRS) sebelum dipakai.
- **Uji wajib:** hasil dicocokkan dengan nilai referensi yang dipublikasikan (data uji paket R `cffdrs` atau tabel Van Wagner & Pickett 1985), toleransi ±0,1.

### 6.3 Penyegaran dan data basi

- Diambil ulang tiap 60 menit; nilai hari ini dihitung ulang setelah 12:00 WITA.
- Gagal mengambil → pakai nilai terakhir, web menampilkan **"data cuaca terakhir HH:MM"**. Lebih dari 6 jam → level tampil abu-abu "tidak diketahui" dan Decision Engine memakai ambang default.

### 6.4 Kelas risiko

FDRS Indonesia tidak memberi kelas untuk angka FWI; kelasnya per indikator. Sumber: de Groot dkk. (2006), *Development of the Indonesian and Malaysian Fire Danger Rating Systems*, Mitig Adapt Strat Glob Change 12:165–180, tabel 1–3:

| Indikator | Arti | Rendah | Sedang | Tinggi | Sangat Tinggi (Extreme) |
|---|---|---|---|---|---|
| FFMC | potensi penyalaan | 0–72 | 73–77 | 78–82 | 83+ |
| DC | kekeringan / potensi asap | < 140 | 140–260 | 260–350 | > 350 |
| ISI | sulitnya pemadaman (padang rumput) | 0–1 | 2–3 | 4–5 | 6+ |

**Risiko Kawasan = kelas tertinggi di antara ketiganya**, dan web menampilkan indikator penentunya (misal "Tinggi karena potensi penyalaan"). Agregasi "kelas tertinggi" adalah keputusan tim (paper menampilkan ketiganya terpisah) dan dicatat di Decision Log. FWI tetap dihitung dan ditampilkan sebagai angka pendamping. Catatan: ambang DC dikalibrasi untuk kabut asap gambut; untuk Klabat (hutan pegunungan) dibaca sebagai indikator kekeringan.

Komponen yang ditampilkan dalam bahasa awam: *Kekeringan tanah* (DC), *Mudah menyala* (FFMC), *Angin*, *Hari tanpa hujan*.

### 6.5 Pengaruh ke deteksi

Ambang BAHAYA memakai `CONF_DANGER_HIGH_RISK` (0.60) jika risiko kawasan **Tinggi** atau **Sangat Tinggi**, selain itu `CONF_DANGER` (0.70). Trace mencatat `{"fwi": …, "category": …, "threshold_used": …}`.

---

## 7. Decision Engine

Tetap seperti T6 (`docs/ARCHITECTURE.md` §6 + Decision Log): rule R0–R6, konfirmasi 2/3 atau 1 cek ≥ 0.90, R6 menghitung verdict bersih, trace dan `explanation` deterministik. Perubahan hanya:
- input `fri` diganti `risk` (kelas FWI) untuk ambang (§6.5);
- trigger foto baru (§5.2).

---

## 8. Peringatan Telegram

### 8.1 Kebijakan

| Jenis | Kapan | Batas |
|---|---|---|
| **Kebakaran Terdeteksi** | Kamera berubah ke BAHAYA | Langsung. Satu insiden = satu peringatan; pembaruan berikutnya hanya jika insiden ditutup lalu dibuka lagi |
| **Perlu Dicek** | Kamera berubah ke WASPADA (termasuk POTENSI, unverified) | Maks 1 per kamera per `CHECK_ALERT_COOLDOWN_S` (default 900) |
| **Laporan AI** | ±1 menit setelah Kebakaran Terdeteksi | Satu per insiden; cadangan template jika agent gagal/timeout |
| **Risiko naik** | Kelas kawasan naik ke Tinggi atau Sangat Tinggi | Saat naik saja (bukan saat turun) |
| **Ringkasan pagi** | `MORNING_SUMMARY_AT` (default 07:00 WITA) | Sekali sehari |

`AUTO_SEND_ALERT=true` (default) mengirim otomatis. `false` = **mode kering**: pesan tetap dibuat dan tampil di web sebagai "tidak dikirim (mode kering)", tidak dikirim ke Telegram.

### 8.2 Format

- Pesan dengan foto: `sendPhoto`, foto snapshot dengan **bbox dan stempel waktu WITA**, caption **≤ 1.024 karakter** (dipotong rapi jika lebih).
- Isi selalu: **status → kenapa → data yang dipakai → tindakan**. Teks dari template `messages.py`; kutipan LLM diberi tanda petik dan dipotong ≤ 160 karakter.
- Laporan AI: `sendMessage` (≤ 4.096 karakter), label *"Dihasilkan AI, perlu verifikasi lapangan."*
- Link ke web hanya jika `PUBLIC_URL` diisi.
- Contoh lengkap: artboard "Pesan Telegram (HP)" di mockup.

### 8.3 Outbox

Setiap pesan masuk tabel `outbox` dulu (`pending`), lalu `OutboxSender` mengirim. Gagal → retry dengan backoff 5 s, 15 s, 60 s, 5 min (maks 10 percobaan) → `failed`. HTTP 429 menghormati `retry_after`. Status setiap pesan tampil di web. Token tidak pernah ditulis ke log.

---

## 9. AI Agent (pesan kedua)

- Dipicu saat insiden dibuka (BAHAYA), cooldown `AGENT_COOLDOWN_S` per kamera.
- Tool calling format OpenAI via 9router, **maks 6 langkah, timeout 60 dtk**. Tools: `get_weather`, `get_satellite_hotspots` (NASA FIRMS, opsional), `estimate_spread` (angin **dari** X° → sebaran **ke** X+180°), `find_nearest_resources`, `get_recent_events`.
- Agent **tidak** mengirim Telegram sendiri; laporannya disimpan di `incidents.report_md` dan dimasukkan ke outbox oleh `AlertService`.
- Laporan: Ringkasan, Bukti, Cuaca & Risiko, Arah Sebaran & Desa Terancam, Rekomendasi (≤ 5), Pihak yang Dihubungi. Data yang tidak dikembalikan tool ditulis "tidak tersedia".
- Gagal/timeout/model tanpa tool calling → **laporan template** dari hasil tool yang dihitung langsung oleh kode.

---

## 10. Website

### 10.1 Halaman

| Halaman | Isi |
|---|---|
| `/` Dashboard | Sesuai mockup: header + kesehatan sistem; kartu Risiko Kawasan dan Status Kamera; peta + insiden aktif ("Mengapa?"); grid kamera; riwayat 30 menit |
| `/incident/{id}` | Snapshot + arsip foto, timeline keputusan, laporan AI lengkap, status Telegram, trace JSON (expander) |
| `/health` | Status tiap komponen (kamera, LLM, Open-Meteo, Telegram, monitor heartbeat), versi, uptime, antrean outbox |

Data live lewat **Server-Sent Events** (`/api/stream`); jika putus, banner **"Data tidak live, mencoba menyambung…"** dan reconnect otomatis. Monitor tanpa heartbeat > 15 dtk → banner **"Monitor tidak merespons"**.

### 10.2 API (semua `GET`, JSON)

`/api/status` (ringkasan), `/api/risk`, `/api/cameras`, `/api/cameras/{id}/snapshot.jpg`, `/api/incidents?state=open|closed`, `/api/incidents/{id}`, `/api/events?camera=&minutes=30`, `/api/outbox?limit=`, `/api/health`, `/api/stream` (SSE).

### 10.3 Peta

Leaflet (disimpan lokal di `web/static/vendor/`, versi dikunci). Lapisan dengan atribusi wajib di kontrol peta:

| Lapisan | Lisensi / atribusi |
|---|---|
| OpenTopoMap (default) | CC-BY-SA; "Kartendaten: © OpenStreetMap-Mitwirkende, SRTM \| Kartendarstellung: © OpenTopoMap (CC-BY-SA)" |
| Sentinel-2 cloudless (EOX) | CC BY-NC-SA 4.0 (versi 2018+), non-komersial; string atribusi sesuai tahun layer, dengan tautan s2maps.eu |
| OpenStreetMap | ODbL; "© OpenStreetMap contributors" |

Overlay: marker kamera (bentuk + warna status), panah angin, perkiraan sektor sebaran (±45° searah angin), hotspot FIRMS, titik Puncak Klabat dan desa. Tanpa internet: latar kosong + pesan, overlay tetap tampil.

### 10.4 Aksesibilitas dan UX

Status = bentuk + warna + teks; kontras ≥ WCAG AA; target sentuh ≥ 44 px; responsif sampai lebar HP; teks Bahasa Indonesia sederhana; waktu dalam WITA; penjelasan selalu di dekat status.

### 10.5 Keamanan

- Teks dari LLM/DB dirender dengan `textContent`/`createElement`, **tidak pernah `innerHTML`**; ada test untuk `<script>` di `reasoning`.
- Header: `Content-Security-Policy` (tanpa inline script, `img-src` hanya self + domain tile), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- Web **read-only**; snapshot diakses lewat ID kamera yang divalidasi ke `cameras.yaml` (tanpa path dari pengguna).
- Default bind `127.0.0.1:8000`; `--host 0.0.0.0` menampilkan peringatan.
- Rahasia hanya di proses Python; `/api/health` tidak membocorkan token/URL ber-key.

---

## 11. Penyimpanan (SQLite WAL, `data/runtime/events.db`)

Tabel lama dipertahankan (`events`, `incidents`, `camera_status`) dengan tambahan kolom; tabel baru:

| Tabel | Isi utama |
|---|---|
| `events` | (tetap §9 ARCHITECTURE) + `risk_category` menggantikan makna `fri` |
| `incidents` | + `alert_outbox_id`, `report_outbox_id`, `report_source` (`agent`/`template`) |
| `camera_status` | + `mode` (`live`/`video`/`foto`), `sub_status`, `last_llm_ts` |
| `risk_daily` | `date`, `temp`, `rh`, `wind`, `rain24`, `ffmc`, `dmc`, `dc`, `isi`, `bui`, `fwi`, `category`, `source` (`observed`/`forecast`), `fetched_ts` |
| `outbox` | `id`, `kind`, `camera_id`, `incident_id`, `text`, `photo_path`, `status` (`pending`/`sent`/`failed`/`dry_run`), `attempts`, `next_attempt_ts`, `last_error`, `created_ts`, `sent_ts` |
| `component_health` | `component`, `ok`, `detail`, `ts` (di-upsert; termasuk heartbeat monitor) |

Retensi (tiap jam): `events` > 7 hari dihapus; arsip snapshot dibatasi `SNAPSHOT_ARCHIVE_MAX_MB` (default 500); `risk_daily` disimpan permanen.

---

## 12. Keandalan dan observabilitas

| Kegagalan | Perilaku |
|---|---|
| monitor/web crash | `up` restart dengan backoff (1, 2, 5, 10, 30 dtk); > 5 crash/5 menit → berhenti dengan pesan jelas |
| Kamera putus / video habis / folder kosong | Sambung ulang otomatis; status Offline di web |
| 9router/LLM gagal | R4: maksimal Perlu Dicek (belum terverifikasi) |
| Open-Meteo gagal | Data basi (§6.3) |
| Telegram gagal | Outbox retry (§8.3) |
| Monitor macet | Heartbeat > 15 dtk → banner di web |

Log: console ringkas (Bahasa Indonesia) + file JSON-lines `data/runtime/logs/*.log` dengan rotasi (5 × 5 MB). `python -m mataklabat check` tetap untuk pemeriksaan awal.

---

## 13. Pengujian

1. **Unit:** test yang ada (123) + FWI vs nilai referensi, kelas risiko, `FolderSource`, kebijakan alert (cooldown, ringkasan pagi), template pesan (≤ 1.024), outbox (retry, 429, dry run), storage & retensi, agent dengan LLM tiruan + fallback template, `estimate_spread` arah angin.
2. **API:** FastAPI `TestClient`: setiap endpoint, header keamanan, ID kamera tidak valid → 404, SSE mengirim event.
3. **Skenario demo otomatis:** pipeline penuh dengan video/foto uji dan LLM tiruan: api → Kebakaran Terdeteksi + 2 pesan outbox; kabut → R5, tanpa peringatan; foto pembakaran sampah → Perlu Dicek (POTENSI).
4. **Uji ketahanan (manual, dicatat):** 4 kamera 30 menit, memori dan CPU stabil, tanpa error.
5. **Evaluasi AI (T12):** precision/recall/false alarm per kelas, v1 vs v2, konsistensi `--repeat 3`, dengan 9router sungguhan.

---

## 14. Di luar lingkup

Hosting online, login/akun, HTTPS, rate limiting, aplikasi mobile, kamera fisik di lapangan, training YOLO, blur wajah otomatis, replay cuaca historis, sentiment analysis. (Catatan "jika ingin di-online-kan" masuk README.)

---

## 15. Data: asli vs simulasi

| Data | Sumber | Sifat |
|---|---|---|
| Cuaca, FWI, prakiraan | Open-Meteo | Asli, live (data model) |
| Hotspot | NASA FIRMS | Asli |
| Peta | OpenTopoMap, EOX, OSM | Asli |
| Gambar kamera | Webcam, video stok, foto dataset | **Simulasi** (tidak ada kamera fisik) |
| Deteksi, verdict, trace, riwayat | Sistem | Asli (hasil pemrosesan; tanpa riwayat karangan) |
| Lokasi kamera | `cameras.yaml` | Hipotetis, dicek di peta |
| Desa, posko | `resources.yaml` | Tempat asli; koordinat dari OSM, sumber dicatat |
| Nomor kontak | Sumber resmi | Tidak dikarang; "belum diisi" jika belum terverifikasi |
| Test set | Dataset publik | Asli, lisensi dicatat |

---

## 16. Persiapan demo

### 16.1 Alur demo (±10 menit)
1. Masalah nyata: kronologi karhutla Klabat + Fishbone.
2. Dashboard: risiko kawasan dari cuaca hari ini, 4 kamera Normal, peta topografi.
3. Seret **foto asap** ke folder CAM-04 → Perlu Dicek → Kebakaran Terdeteksi → Telegram masuk (foto + alasan), lalu laporan AI.
4. Buka "Mengapa?" dan jejak keputusan.
5. Seret **foto kabut** → AI menolak (R5) atau gagal (bahan analisis kegagalan).
6. Seret **foto pembakaran sampah** → Perlu Dicek (POTENSI): sisi pencegahan.
7. Opsional: **video api** di HP ke webcam CAM-01.
8. Hasil evaluasi + rekomendasi institusi.

### 16.2 Checklist

**H-7**
- [ ] Foto test set ≥ 10 per kelas (`fire`, `smoke`, `fog`, `sunset`, `lights`, `normal`) dari dataset publik; catat sumber & lisensi
- [ ] Foto demo untuk CAM-04: asap, api, kabut gunung, pembakaran sampah, senja
- [ ] 2 video stok hutan normal (`cam02.mp4`, `cam03.mp4`, < 20 MB, lisensi bebas)
- [ ] 1 video api untuk HP (opsional)
- [ ] 9router berjalan; pilih model yang mendukung gambar + tool calling; isi `.env`
- [ ] Bot Telegram (BotFather) + grup demo; isi token & chat id
- [ ] (Opsional) `FIRMS_MAP_KEY`
- [ ] Verifikasi koordinat kamera, desa, posko di peta
- [ ] Konfirmasi ke dosen: pemakaian 9router diperbolehkan

**H-1**
- [ ] `python -m mataklabat check` semua ✅
- [ ] Uji ketahanan 30 menit
- [ ] Latihan alur demo penuh 2×; rekam layar sebagai **video cadangan**
- [ ] Buka peta di area Klabat pada semua zoom yang dipakai (cache browser); siapkan hotspot HP sebagai internet cadangan
- [ ] Hasil `scripts/evaluate.py` masuk slide
- [ ] Laptop: charger, update Windows ditunda, mode jangan ganggu

**Hari H**
- [ ] `python -m mataklabat up` 15 menit sebelum mulai (FWI terhitung, kamera stabil)
- [ ] Tutup aplikasi yang memakai webcam (Zoom/Meet)
- [ ] Folder CAM-04 terbuka di File Explorer, foto demo siap diseret
- [ ] HP: grup Telegram terbuka; video api siap, kecerahan maksimum
- [ ] Halaman `/health` hijau semua

---

## 17. Risiko dan hal terbuka

| Risiko / pertanyaan | Penanganan |
|---|---|
| Ambang kelas FWI resmi BMKG tidak ditemukan | §6.4: turunkan dari literatur, tandai "perlu konfirmasi BMKG" |
| Faktor panjang hari DMC/DC untuk ekuator | Cek ke `cffdrs`/publikasi FDRS sebelum implementasi; uji referensi |
| Model di 9router tidak mendukung gambar atau tool calling | `check --llm-sample` + test agent nyata; fallback laporan template |
| Dosen keberatan dengan 9router | Ditanyakan H-7 |
| Internet kampus mati | Status tetap jalan lokal; Telegram tertunda di outbox; video cadangan |
| Kamera Foto dianggap "curang" | Label "Mode foto" di web; dijelaskan di presentasi sebagai simulasi kamera lapangan |

---

## 18. Langkah setelah spec disetujui

1. Perbarui `docs/PRD.md`, `docs/ARCHITECTURE.md` (+ Decision Log), `AGENTS.md` (izin FastAPI, aturan baru), `README.md`.
2. Susun ulang `tasks/plan.md` dan `tasks/todo.md` (skill *writing-plans*): T1–T6 tetap selesai; task baru untuk FWI, Kamera Foto, storage, alerts/outbox, agent, web, supervisor, evaluasi, polish.
3. Lanjut implementasi per task dengan test lebih dulu.

### Sumber

- FDRS Indonesia/FWI: [ASEAN Haze Portal](https://hazeportal.asean.org/?p=10687), [GOFC Fire-IT 2018](https://gofcgold.umd.edu/sites/default/files/fireit_meetings/GOFC_Fire_IT_2018/GWIS-GOFC_presentations/Monday_Afternoon/20181001.Field.pdf), [JMG BMKG](https://jmg.bmkg.go.id/jmg/index.php/jmg/article/view/37/32), [IJReSES BRIN](https://ejournal.brin.go.id/ijreses/article/view/13954)
- Lisensi EOX: [cloudless.eox.at/documentation/license](https://cloudless.eox.at/documentation/license), [Sentinel-2 cloudless 2024](https://eox.at/2025/03/sentinel-2-cloudless-2024/)
- OpenTopoMap: [OSM Wiki](https://wiki.openstreetmap.org/wiki/OpenTopoMap)
- 9router: [decolua/9router](https://docsearch.algolia.com/mcp/docs/repo/decolua/9router)
