# Skenario Demo & Persiapan MataKlabat (±10 menit)

Susunan kamera demo (Spec §5.3): **CAM-01 webcam**, **CAM-02 dan CAM-03 video stok**, **CAM-04 Kamera Foto** (folder `data/demo/CAM-04`). Tidak perlu ke lapangan: semua bahan bisa dari internet.

> 🔒 **Jangan menyalakan api, lilin, atau korek sungguhan di dalam ruangan.** Pakai foto atau video.

---

## Alur presentasi

| Menit | Adegan | Yang dilakukan / ditunjukkan | Poin rubrik |
|---|---|---|---|
| 0–2 | **Masalah nyata** | Kronologi karhutla Klabat Sep–Okt 2026 (60 → 651 ha, 21+ hari), Fishbone (`docs/RCA.md`) | RCA |
| 2–3 | **Pencegahan** | Dashboard: Risiko Kawasan dari cuaca hari ini, penentunya (kekeringan / mudah menyala / sulit dipadamkan), prakiraan 3 hari, riwayat 30 hari | Data & analisis |
| 3–5 | **Api muncul** | Seret **foto asap/api** ke folder CAM-04 → Perlu Dicek → Kebakaran Terdeteksi. Pesan Telegram masuk ke HP (foto + alasan + data). Buka panel **"Mengapa?"** | LLM, XAI |
| 5–6 | **AI Agent** | Laporan insiden masuk sebagai pesan kedua: arah sebaran, desa terancam, rekomendasi. Buka halaman detail insiden + jejak keputusan | AI Agent |
| 6–8 | **AI bisa salah** | (a) Seret **foto kabut gunung**: AI menolak sebagai lookalike (R5) atau tertipu (F1). (b) **Foto senja**. (c) **Foto orang membakar sampah** → Perlu Dicek (potensi): sisi pencegahan | Analisis kegagalan |
| 8–9 | **Evaluasi** | Tabel `results/metrics.csv`, confusion matrix, v1 vs v2, konsistensi (`results/failures.md`) | Evaluasi & prompt |
| 9–10 | **Rekomendasi** | Rekomendasi untuk BPBD Minut, Dinas Kehutanan, desa (RCA §6); keterbatasan dan roadmap | Rekomendasi |

Opsional: arahkan **video** api di HP ke webcam CAM-01 untuk menunjukkan kamera live. Pakai video, bukan foto: foto yang dipegang tangan menghasilkan gerak acak yang tidak bisa diandalkan.

### Kalimat kunci
- *"Satelit buta saat berawan. Kamera darat tidak."*
- *"Dua pertanyaan berbeda: seberapa mudah terbakar hari ini, dan apakah ada api sekarang."*
- *"AI kami tidak memutuskan dari satu bukti. Detektor mencurigai, LLM memverifikasi, aturan memutuskan, dan semua tercatat."*
- *"Kami sengaja menunjukkan kapan AI gagal, karena false alarm dan kejadian terlewat sama-sama berbahaya."*

---

## Checklist persiapan

### H-7: bahan dan akun
- [x] **Test set** 12 foto per kelas + foto demo + video: `python scripts/fetch_media.py` (sumber dan lisensi di `data/MEDIA_SOURCES.md`)
- [ ] **Foto demo** untuk CAM-04 (simpan di folder lain, misalnya `data/demo/bahan/`): asap di lereng, api, kabut gunung, pembakaran sampah, senja
- [ ] **2 video stok** hutan normal → `data/videos/cam02.mp4`, `cam03.mp4` (< 20 MB, lisensi bebas)
- [ ] (Opsional) 1 video api untuk diputar di HP
- [ ] **9router** terpasang dan berjalan; pilih model yang mendukung **gambar + tool calling**; isi `LLM_MODEL` dan `LLM_API_KEY` di `.env`
- [ ] Uji model: `python -m mataklabat check --llm-sample data/test_set/fire/<foto>.jpg` → `fire_visible`/`smoke_visible` true
- [ ] **Bot Telegram** via @BotFather + grup demo; masukkan bot ke grup; isi `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- [ ] (Opsional) `FIRMS_MAP_KEY` dari NASA FIRMS
- [ ] Verifikasi koordinat kamera, desa, dan posko di peta; nomor kontak hanya dari sumber resmi
- [ ] **Konfirmasi ke dosen** bahwa pemakaian 9router (bukan Gemini) diperbolehkan

### H-3: uji sistem
- [ ] `python -m mataklabat check` → semua ✅
- [ ] `python scripts/evaluate.py --set data/test_set --prompt v1,v2 --repeat 3` → salin tabel ke slide
- [ ] **Uji ketahanan**: `python -m mataklabat up` selama 30 menit dengan 4 kamera; cek `/health` tetap hijau dan memori stabil (Task Manager)
- [ ] Latihan alur demo penuh 2×, dengan Telegram sungguhan

### H-1: cadangan
- [ ] **Rekam layar** seluruh demo sebagai video cadangan (jika internet mati)
- [ ] Buka dashboard dan geser peta di area Klabat pada zoom yang dipakai, di ketiga lapisan, supaya tile tersimpan di cache browser
- [ ] Siapkan **hotspot HP** sebagai internet cadangan
- [ ] Hapus data latihan agar demo mulai bersih: hentikan `up`, lalu hapus folder `data/runtime/`
- [ ] Kosongkan `data/demo/CAM-04/`, sisakan satu foto hutan normal
- [ ] Laptop: charger, update Windows ditunda, mode jangan ganggu

### Hari H
- [ ] `python -m mataklabat up` **15 menit** sebelum mulai (data cuaca terambil, kamera stabil)
- [ ] Tutup aplikasi yang memakai webcam (Zoom, Meet, Teams)
- [ ] Buka `http://127.0.0.1:8000` (layar presentasi) dan `/health` → semua hijau
- [ ] File Explorer: folder `data/demo/CAM-04` dan folder bahan foto terbuka berdampingan
- [ ] HP: grup Telegram terbuka; video api siap (kecerahan maksimum)
- [ ] Jika ingin penonton membuka dashboard dari HP: `python -m mataklabat up --host 0.0.0.0` dan beri alamat IP laptop (hanya-baca)

### Jika ada masalah saat demo
| Masalah | Tindakan |
|---|---|
| Banner "Monitor tidak merespons" | Supervisor biasanya menyalakan ulang sendiri dalam beberapa detik; cek terminal `up` |
| 9router/internet mati | Status tetap jalan (maksimal Perlu Dicek, belum terverifikasi); jelaskan sebagai degradasi anggun; lanjut dengan video cadangan |
| Telegram tidak masuk | Pesan tetap di antrean dan dikirim ulang; tunjukkan status di halaman insiden / `/health` |
| Peta kosong | Internet putus; marker dan status tetap tampil; jelaskan |
| Webcam tidak terbaca | Tutup aplikasi lain; demo tetap jalan dengan CAM-04 (foto) |
