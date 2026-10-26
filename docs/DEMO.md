# Skenario Demo & Presentasi MataKlabat (±10 menit)

## Persiapan (H-1)

- [ ] `.env` terisi, dan `python -m mataklabat check` semua ✅
- [ ] `data/videos/cam02.mp4`, `cam03.mp4`, `cam04.mp4` tersedia (pemandangan hutan/gunung normal, durasi 1–3 menit, diputar berulang)
- [ ] Di HP atau monitor kedua: **video api**, **video asap**, **foto kabut di lereng gunung**, **foto matahari terbenam**
- [ ] Bot Telegram sudah di-*start* di grup demo, dan dosen/teman diundang ke grup
- [ ] Rekam **video cadangan** seluruh demo, untuk jaga-jaga jika internet mati
- [ ] Hasil `scripts/evaluate.py` (tabel dan grafik) sudah ada di slide

> 🔒 **Jangan menyalakan api, lilin, atau korek sungguhan di dalam ruangan.** Gunakan video di layar.

## Alur

| Menit | Adegan | Yang ditunjukkan | Poin rubrik |
|---|---|---|---|
| 0–2 | **Masalah nyata** | Kronologi karhutla Klabat Sep–Okt 2026 (60 → 651 ha, 21+ hari) dan Fishbone | RCA, Fishbone |
| 2–3 | **Kondisi normal** | Dashboard: 4 kamera AMAN, peta hijau, FRI dan cuaca live | Implementasi |
| 3–5 | **Api muncul** | Arahkan video api di HP ke webcam (CAM-01 Kaki Dian). Status naik ke WASPADA lalu BAHAYA dalam ≤ 30 detik. Buka panel **"Mengapa?"** | Integrasi LLM, XAI |
| 5–6 | **AI Agent bekerja** | Laporan insiden muncul: arah angin, desa terancam, rekomendasi. Tekan **Kirim ke Telegram**, pesan masuk ke HP | AI Agent, rekomendasi |
| 6–8 | **AI bisa salah** | (a) Foto kabut: detektor lokal terpicu, lalu lihat apakah LLM menolaknya sebagai `fog_cloud`. (b) Foto senja. (c) Asap kecil di kejauhan | Analisis kegagalan |
| 8–9 | **Evaluasi** | Tabel precision/recall, perbandingan prompt v1 dan v2, uji konsistensi | Analisis keputusan & prompt |
| 9–10 | **Rekomendasi institusi** | Rekomendasi untuk BPBD Minut, Dinas Kehutanan, dan desa (dari RCA §6) | Rekomendasi |

## Kalimat kunci saat presentasi

- *"Satelit buta saat berawan. Kamera darat tidak."*
- *"AI kami tidak memutuskan dari satu bukti. Detektor lokal mencurigai, LLM memverifikasi, aturan memutuskan, dan semua tercatat."*
- *"Kami sengaja menunjukkan kapan AI gagal, karena di dunia nyata false alarm dan kejadian yang terlewat sama-sama berbahaya."*
