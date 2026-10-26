# PRD: MataKlabat

| | |
|---|---|
| **Produk** | MataKlabat: Sistem Peringatan Dini Karhutla Gunung Klabat |
| **Konteks** | Tugas mata kuliah Artificial Intelligence (Lecture 20: Decision Making in AI), FILKOM UNKLAB |
| **Versi** | 0.1 (prototipe demo) |
| **Tanggal** | 26 Oktober 2026 |

## 1. Masalah

Karhutla di kaki Gunung Klabat yang dimulai **19 September 2026** meluas dari 60 ha menjadi ±651 ha (termasuk ±131,59 ha hutan lindung). Api belum padam lebih dari 21 hari, dan status tanggap darurat diperpanjang hingga 21 Oktober 2026. Pemantauan saat ini bergantung pada **laporan warga** dan **satelit yang terhalang awan**. Akibatnya titik api baru (Matungkas, Laikit) baru diketahui setelah membesar. Lihat [`RCA.md`](RCA.md).

**Problem statement:** *Bagaimana kita bisa mengetahui titik api atau asap di kawasan Gunung Klabat dalam hitungan menit, bukan jam, dan langsung tahu harus berbuat apa?*

## 2. Pengguna

| Persona | Kebutuhan | Yang didapat dari MataKlabat |
|---|---|---|
| **Operator Posko BPBD Minut** | Tahu titik api secepatnya dan menentukan prioritas pengerahan | Dashboard status kamera, peta, laporan insiden agent |
| **Manggala Agni / Damkar** | Arah sebaran dan akses | Arah angin, desa terancam, sumber daya terdekat |
| **Hukum Tua / aparat desa** (Tatelu, Matungkas, Laikit, Airmadidi) | Peringatan untuk warga dan membangun sekat api | Notifikasi Telegram |
| **Pengelola jalur pendakian Klabat** | Mencegah api unggun dan pembakaran oleh pengunjung | Status WASPADA–POTENSI (faktor risiko terlihat) |
| **Dosen / penguji** | Melihat cara AI mengambil keputusan | Decision trace, evaluasi, analisis kegagalan |

## 3. Tujuan & Metrik Keberhasilan (demo)

| Tujuan | Metrik | Target |
|---|---|---|
| Deteksi cepat | Waktu dari api/asap muncul di kamera sampai status BAHAYA | ≤ 30 detik |
| Sedikit false alarm | False alarm rate pada kelas `fog`, `sunset`, `lights` (test set) | ≤ 20% (setelah Tahap 2) |
| Tidak melewatkan kejadian | Recall kelas `fire` + `smoke` | ≥ 80% |
| Keputusan bisa dijelaskan | Event dengan trace lengkap | 100% |
| Tindak lanjut otomatis | Insiden BAHAYA yang punya laporan agent | 100% (jika online) |
| Hemat kuota | Panggilan LLM per kamera per jam saat kondisi tenang | ≤ 30 |

## 4. Kebutuhan Fungsional

| ID | Kebutuhan | Prioritas |
|---|---|---|
| F1 | Membaca ≥ 1 webcam dan ≥ 2 video file sebagai kamera virtual secara bersamaan | Must |
| F2 | Detektor lokal menghasilkan `fire_score`, `smoke_score`, dan bbox per frame | Must |
| F3 | Verifikasi LLM Vision (via 9router) dengan output JSON terstruktur (ARCHITECTURE §5) | Must |
| F4 | Decision Engine dengan aturan R0–R6 dan state machine (ARCHITECTURE §6) | Must |
| F5 | Decision trace tersimpan untuk setiap event | Must |
| F6 | Dashboard: grid kamera, peta, panel "Mengapa?", log insiden | Must |
| F7 | Fire Risk Index dari Open-Meteo | Should |
| F8 | AI Agent dengan function calling dan laporan insiden | Should |
| F9 | Notifikasi Telegram (manual dan opsional otomatis) | Could |
| F10 | Hotspot NASA FIRMS di peta dan sebagai tool agent | Could |
| F11 | Script evaluasi: metrics, perbandingan prompt v1/v2, uji konsistensi | Must (untuk laporan) |
| F12 | Mode `--no-llm` (offline) | Should |

## 5. Kebutuhan Non-Fungsional

- Berjalan di laptop mahasiswa (CPU, tanpa GPU), minimal 2 FPS proses per kamera untuk 4 kamera.
- Monitor tetap berjalan jika dashboard ditutup, dan sebaliknya.
- Tidak ada API key di repo (`.env` di-gitignore).
- Bahasa UI dan laporan: Bahasa Indonesia.

## 6. Bukan Lingkup (Not Doing)

| Tidak dikerjakan | Alasan |
|---|---|
| Hardware kamera lapangan, panel surya, jaringan LoRa/4G | Di luar waktu 1 hari. Disimulasikan dengan webcam dan video |
| Training model YOLO sendiri | Butuh dataset dan GPU. `YoloDetector` disiapkan sebagai slot opsional |
| Sentiment analysis opini warga | Diarahkan dosen untuk dikesampingkan |
| Login/akun pengguna | Tidak dibutuhkan untuk demo |
| Aplikasi mobile | Notifikasi Telegram sudah cukup |
| Lokalisasi titik api presisi (triangulasi) | Butuh ≥ 2 kamera nyata yang dikalibrasi. Masuk roadmap |
| Klaim akurasi untuk penggunaan operasional | Prototipe akademik |

## 7. Asumsi & Risiko

| Asumsi / Risiko | Dampak | Mitigasi |
|---|---|---|
| 9router berjalan dan kuota model di belakangnya cukup untuk demo | Tinggi | Rate limit, trigger lokal, mode `--no-llm` |
| Detektor warna terlalu sensitif terhadap kabut | Sedang | Memang diserahkan ke Tahap 2. Dibahas sebagai F1 |
| Internet kampus tidak stabil saat demo | Tinggi | Rekam video cadangan demo. Degradasi ke WASPADA `unverified` |
| Koordinat desa/posko tidak akurat | Rendah | Diberi label "perkiraan", verifikasi sebelum demo |
| Video api untuk demo kurang realistis | Sedang | Siapkan beberapa video (api, asap, kabut) di HP/monitor kedua |
