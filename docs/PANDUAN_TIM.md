# Panduan Tim MataKlabat

**Untuk siapa:** semua anggota tim Dragon Apple, termasuk yang belum paham AI atau pemrograman.
**Isi:** apa itu MataKlabat, cara membaca website dan pesan Telegram, pembagian peran, dan langkah demo di kelas.

Yang dipakai saat demo hanya dua:

| Alat | Alamat | Dipakai untuk |
|---|---|---|
| Website | **https://mataklabat.timotation.biz.id** | Melihat status, dan (khusus operator) menyalakan kamera serta memilih foto |
| Grup Telegram | grup **MataKlabat** (bot `@MataKlabatBot`) | Menerima peringatan otomatis |

Tidak perlu memasang apa pun. Cukup browser (Chrome di HP/laptop) dan aplikasi Telegram.

---

## 1. MataKlabat dalam satu menit

Bayangkan **satpam yang menjaga Gunung Klabat 24 jam** lewat kamera.

1. **Satpam junior** (detektor lokal) melihat setiap gambar kamera. Ia cepat dan tidak pernah lelah, tapi gampang kaget: awan, kabut, atau matahari sore pun bisa ia kira asap atau api.
2. Kalau satpam junior curiga, ia memanggil **satpam senior** (AI vision). Satpam senior melihat fotonya dengan teliti dan menjawab: "Ini asap sungguhan" atau "Itu cuma kabut", lengkap dengan alasannya.
3. Lalu **buku aturan** (aturan keputusan) yang menentukan statusnya. Contohnya: kalau satpam senior sangat yakin itu asap, status menjadi **Kebakaran Terdeteksi**.
4. Kalau statusnya penting, **grup Telegram** langsung diberi tahu. Sekitar satu menit kemudian datang laporan lengkap: arah angin, desa yang mungkin terancam, dan pos pemadam terdekat.

Selain itu, setiap hari MataKlabat menghitung **seberapa rawan kawasan terbakar** dari data cuaca (kering atau tidak, angin kencang atau tidak). Ini mirip ramalan cuaca, tapi untuk risiko kebakaran.

> Kalimat kunci untuk diingat: **"Detektor mencurigai, AI memverifikasi, aturan memutuskan, dan semuanya tercatat."**

---

## 2. Kamus singkat

| Istilah | Artinya dalam bahasa sehari-hari |
|---|---|
| **AI vision** | Program AI yang bisa "melihat" foto dan menjelaskan isinya |
| **Detektor lokal** | Penyaring cepat yang mencari warna api/asap dan gerakan di gambar; murah, tapi sering salah |
| **Lookalike** | Hal yang *mirip* api/asap tapi bukan: kabut, awan, matahari terbenam, lampu |
| **Risiko Kebakaran Kawasan** | Seberapa mudah kawasan terbakar hari ini, dari cuaca: Rendah, Sedang, Tinggi, Sangat Tinggi |
| **Status Kamera** | Apa yang dilihat kamera sekarang: Normal, Perlu Dicek, Kebakaran Terdeteksi |
| **Kamera Foto** | Kamera simulasi (CAM-04) yang menampilkan foto pilihan operator; dipakai untuk demo |
| **Operator** | Anggota tim yang memegang password untuk menyalakan/mematikan kamera dan memilih foto |
| **Insiden** | Catatan satu kejadian kebakaran, dengan foto, urutan keputusan, dan laporan AI |
| **AI Agent** | AI yang menulis laporan lengkap sendiri (cek cuaca, arah sebaran, sumber air terdekat) |
| **Provider AI** | "Penyedia" otak AI-nya (misalnya Google atau Ollama). Kalau satu habis kuota, sistem pindah ke cadangan |

---

## 3. Dua pertanyaan, dua status

MataKlabat sengaja memisahkan dua hal supaya tidak membingungkan:

**A. Pencegahan: "Seberapa rawan hari ini?"** → **Risiko Kebakaran Kawasan** (kotak besar kiri atas di website)

| Tingkat | Artinya |
|---|---|
| Rendah | Aman, kecil kemungkinan terbakar |
| Sedang | Perlu waspada |
| Tinggi | Mudah terbakar; perketat patroli |
| Sangat Tinggi | Sangat mudah terbakar; siagakan regu pemadam, pertimbangkan menutup jalur pendakian |

**B. Deteksi: "Apakah ada api/asap sekarang?"** → **Status Kamera** (kartu tiap kamera)

| Ikon | Status | Artinya |
|---|---|---|
| ● lingkaran hijau | **Normal** | Tidak ada api atau asap |
| ▲ segitiga oranye | **Perlu Dicek** | Ada tanda mencurigakan, belum pasti; mohon dicek |
| ▲ + "potensi" | **Perlu Dicek (potensi)** | Ada api kecil yang terkendali (api unggun, bakar sampah); bisa membesar |
| ▲ + "belum terverifikasi" | **Perlu Dicek (belum terverifikasi)** | Detektor curiga, tapi AI sedang tidak bisa dihubungi. **Tidak dikirim ke Telegram** supaya grup tidak kebanjiran alarm palsu |
| ⬣ segi delapan merah | **Kebakaran Terdeteksi** | AI yakin ada kebakaran; insiden dibuka dan Telegram berbunyi |
| ❚❚ abu-abu | **Nonaktif** | Kamera sengaja dimatikan operator; tidak memeriksa apa-apa |
| ○ lingkaran kosong | **Offline** | Kamera bermasalah (rusak/tidak ada gambar) |

Bentuk ikonnya berbeda-beda, jadi tetap terbaca oleh orang yang buta warna.

Contoh: risiko **Sangat Tinggi** tapi semua kamera **Normal** artinya belum ada api, tapi kawasan sedang sangat kering.

---

## 4. Membaca website

Buka **https://mataklabat.timotation.biz.id**. Halaman ini bisa dibuka siapa saja dan **hanya untuk melihat**. Isinya dari atas ke bawah:

1. **Baris atas:** jam (WITA), status sistem ("Monitor aktif · 1/1 kamera online · 3 nonaktif · AI aktif"), tautan **Kesehatan sistem**, dan tombol **Masuk operator**.
2. **Risiko kebakaran kawasan:** tingkat hari ini, penyebab utamanya (misalnya "kekeringan"), angin, suhu, dan prakiraan beberapa hari.
3. **Status kamera:** jumlah kamera per status.
4. **Peta:** posisi kamera, desa, dan pos. Saat ada api, muncul kipas berwarna yang menunjukkan **perkiraan arah sebaran** menurut angin.
5. **Panel insiden** (kanan peta): kalau ada kebakaran, muncul foto, bagian **"Mengapa?"** (alasan keputusan dan alasan AI), status pesan Telegram, dan tombol **Buka laporan lengkap**.
6. **Kartu kamera:** foto terbaru tiap kamera dan statusnya.
7. **Riwayat 30 menit terakhir:** setiap perubahan status beserta alasannya.

Halaman **Kesehatan sistem** (`/health`) menunjukkan apakah setiap bagian berjalan: Monitor, Cuaca, AI, dan Telegram. Kalau ada yang merah, lihat bagian 9.

Website memperbarui dirinya sendiri, jadi tidak perlu di-refresh.

---

## 5. Pesan di grup Telegram

Bot **@MataKlabatBot** mengirim pesan **otomatis**. Tidak ada yang perlu dibalas.

| Pesan | Kapan muncul | Isi |
|---|---|---|
| 🔴 **KEBAKARAN TERDETEKSI** | Langsung saat AI yakin ada kebakaran | Foto, kamera mana, kenapa, data cuaca, arah sebaran, tindakan |
| 📋 **LAPORAN INSIDEN** (AI Agent) | ±1 menit setelah pesan merah | Desa terancam, pos damkar dan sumber air terdekat, langkah yang disarankan |
| 🟡 **PERLU DICEK** | Saat kamera naik dari Normal (yang sudah dicek AI) | "Belum pasti, mohon dicek", dengan alasan. Paling sering 1× per kamera tiap 15 menit |
| 🟠 **RISIKO KEBAKARAN KAWASAN** naik | Saat Risiko Kawasan naik ke Tinggi/Sangat Tinggi | Tingkat baru dan saran |
| ☀️ **Ringkasan pagi** | Setiap pagi pukul 07.00 WITA | Risiko hari ini dan status semua kamera |
| ⚙️ **AI TIDAK TERSEDIA** | AI tidak bisa dihubungi ±5 menit saat ada kamera aktif | Pemberitahuan teknis, **bukan** peringatan kebakaran |
| ✅ **AI KEMBALI TERSEDIA** | AI sudah bisa dihubungi lagi | Pemberitahuan teknis |

Yang **tidak** dikirim ke Telegram: status "Perlu Dicek (belum terverifikasi)", karena tanpa AI sistem tidak bisa membedakan asap dari awan.

Setiap pesan peringatan meminta **verifikasi lapangan**. MataKlabat membantu manusia, bukan menggantikan.

---

## 6. Pembagian peran saat demo di kelas

| Peran | Siapa | Tugas |
|---|---|---|
| **Presenter A–D** | [isi nama] | Membawakan slide (lihat [`SKRIP_PRESENTASI.md`](SKRIP_PRESENTASI.md)) |
| **Operator** | [isi nama] | Memegang laptop demo: masuk operator, menyalakan kamera, memilih foto, mematikan kamera |
| **Pemegang HP Telegram** | [isi nama] | Membuka grup MataKlabat dan menunjukkan pesan yang masuk ke kelas (bisa lewat kamera dokumen atau mirroring) |
| **Penjaga waktu** | [isi nama] | Memberi tanda kalau waktu tinggal 2 menit |

Password operator **hanya** dipegang operator dan ketua tim. Minta langsung ke ketua; jangan dikirim ke grup, jangan ditulis di slide.

---

## 7. Persiapan

### H-1 (sehari sebelum)

- [ ] Semua anggota sudah masuk grup Telegram **MataKlabat**.
- [ ] Operator sudah mencoba **Masuk operator** di website dan berhasil.
- [ ] Gladi sekali penuh (bagian 8), termasuk pesan Telegram masuk. Setelah gladi, **nonaktifkan kamera**.
- [ ] Rekam layar saat gladi berhasil, sebagai cadangan kalau internet di kelas bermasalah.
- [ ] Slide sudah diunduh (PPTX/PDF) dan nama anggota sudah diisi.

### 30 menit sebelum tampil

- [ ] Buka **https://mataklabat.timotation.biz.id/health**. Monitor, Cuaca, AI, dan Telegram harus **OK** (hijau).
- [ ] Di dashboard, semua kamera **Nonaktif** (abu-abu). Kalau ada yang aktif dari gladi, nonaktifkan.
- [ ] Laptop operator: dashboard terbuka di tab sendiri, sudah **Masuk operator**.
- [ ] HP Telegram: grup MataKlabat terbuka, notifikasi suara **nyala**, baterai cukup.
- [ ] Siapkan hotspot HP kalau Wi-Fi kampus lambat.
- [ ] (Opsional) Tulis alamat website di papan atau slide supaya teman-teman bisa ikut membuka dari HP.

---

## 8. Langkah demo di kelas (±4 menit)

Kolom "Yang dikatakan" hanya contoh; lihat juga skrip slide 14.

| # | Operator melakukan | Yang terlihat | Presenter mengatakan |
|---|---|---|---|
| 1 | Tunjukkan dashboard. Semua kamera **Nonaktif** | Kartu abu-abu, risiko kawasan tampil | "Saat tidak dipakai, kamera dimatikan supaya hemat. Risiko kawasan tetap dihitung dari cuaca." |
| 2 | Kartu **CAM-04** → klik **Aktifkan** | Dalam ±5 detik muncul foto Gunung Klabat, status **Normal** | "Kita nyalakan kamera di Matungkas." |
| 3 | **Pilih foto** → `kabut_gunung.jpg` | Detektor sempat curiga, lalu AI menilai **kabut** → tetap **Normal**. Klik riwayat atau lihat alasan | "Detektor sederhana mengira ini asap, tapi AI tahu ini kabut. Jadi tidak ada alarm palsu." |
| 4 | **Pilih foto** → `potensi_01.jpg` (api unggun) | **Perlu Dicek (potensi)**. Di Telegram masuk 🟡 PERLU DICEK | "Ada api kecil yang terkendali. Belum kebakaran, tapi perlu dicek supaya tidak membesar." |
| 5 | **Pilih foto** → `asap_kolom.jpg` | Dalam ±5–35 detik: **Kebakaran Terdeteksi**, panel insiden muncul, kipas sebaran di peta | "Kolom asap besar. AI yakin, aturan memutuskan: kebakaran." |
| 6 | Pemegang HP menunjukkan Telegram | Pesan 🔴 dengan foto, lalu ±1 menit kemudian 📋 laporan AI Agent | "Grup langsung diberi tahu: di mana, kenapa, dan apa yang harus dilakukan." |
| 7 | Klik **Buka laporan lengkap** | Halaman insiden: foto, urutan keputusan, laporan AI | "Semua keputusan tercatat dan bisa diperiksa ulang." |
| 8 | Kembali ke dashboard → CAM-04 **Nonaktifkan** → **OK** | Status kembali **Normal**, kartu abu-abu, insiden ditutup | "Selesai demo, kamera dimatikan dan sistem siap diulang." |

Tips untuk operator:

- Setelah memilih foto, **tunggu 5–10 detik**. Jangan klik berkali-kali.
- Klik **Aktifkan** dulu, baru pilih foto. Foto juga bisa dipilih saat kamera nonaktif; foto itu langsung diperiksa begitu kamera diaktifkan.
- Kalau tampilan HP kecil, putar layar ke mode mendatar.

---

## 9. Kalau ada masalah saat demo

| Yang terjadi | Kemungkinan penyebab | Yang dilakukan |
|---|---|---|
| Status berhenti di **Perlu Dicek (belum terverifikasi)**, Telegram diam | AI sedang tidak bisa dihubungi (kuota habis atau provider gangguan) | Tenang. Jelaskan: "Tanpa AI, sistem sengaja tidak mengirim alarm supaya tidak ada alarm palsu." Lalu putar rekaman gladi. Sistem otomatis mencoba AI cadangan |
| Website tidak terbuka | Internet kelas bermasalah | Pindah ke hotspot HP. Kalau tetap gagal, putar rekaman gladi |
| Banner merah "Monitor tidak merespons" | Server sedang restart | Tunggu 10–20 detik; sistem menyalakan diri sendiri |
| Tombol **Aktifkan** tidak ada | Belum masuk operator, atau sesi habis | Klik **Masuk operator** lagi |
| "Terlalu banyak percobaan" saat login | Password salah berkali-kali | Tunggu 10 menit, atau minta ketua memastikan password |
| Telegram tidak masuk, padahal status sudah Kebakaran | Internet HP lambat | Tunjukkan panel insiden di website (ada keterangan "terkirim" atau "dalam antrean"). Pesan yang tertunda dikirim ulang otomatis |
| Status tidak berubah setelah pilih foto | AI sedang memeriksa | Tunggu sampai 30 detik |
| Teman di kelas membuka website dan melihat status berubah | Memang begitu, website ini live | Bagus, ajak mereka melihat |

Kalau ragu, buka halaman **Kesehatan sistem**: yang merah adalah sumber masalahnya.

---

## 10. Pertanyaan yang mungkin muncul

Jawaban lengkapnya ada di [`SKRIP_PRESENTASI.md`](SKRIP_PRESENTASI.md) bagian "Persiapan tanya jawab". Ringkasnya:

- **"Akurasinya 100%?"** → Pada 72 foto uji, ya. Tapi fotonya kebakaran besar yang jelas; asap tipis dan malam hari belum diuji. Kami jujur menyebut ini keterbatasan.
- **"Kalau AI mati?"** → Detektor tetap jalan. Sistem tidak mengirim alarm yang belum pasti, pindah otomatis ke AI cadangan, dan memberi tahu grup kalau AI benar-benar tidak tersedia.
- **"Kenapa tidak pakai satelit?"** → Satelit buta saat berawan; kamera darat tidak. Keduanya sebaiknya digabung.
- **"Bisa salah?"** → Bisa. Karena itu keputusan tidak diambil dari satu bukti, semua tercatat, dan pesan selalu meminta verifikasi lapangan.
- **"Biayanya?"** → Server kecil (2 CPU, 2 GB RAM). Biaya terbesar di lapangan adalah kamera, listrik, dan jaringan.

---

## 11. Aturan keamanan

- Jangan membagikan **password operator**, **token bot**, atau isi file `.env` ke grup atau slide.
- Penonton boleh membuka website; mereka **tidak bisa** mengubah apa pun tanpa password.
- Kalau password operator mungkin bocor, minta ketua menggantinya (`OPERATOR_PASSWORD` di server, lalu restart).
- Grup Telegram sebaiknya hanya berisi tim dan dosen, karena pesannya berisi foto dan lokasi.

---

## 12. Untuk yang ingin tahu lebih dalam

| Dokumen | Isi |
|---|---|
| [`README.md`](../README.md) | Gambaran teknis dan hasil evaluasi |
| [`SKRIP_PRESENTASI.md`](SKRIP_PRESENTASI.md) | Skrip per slide dan persiapan tanya jawab |
| [`DEMO.md`](DEMO.md) | Catatan demo versi laptop |
| [`SETUP.md`](SETUP.md) | Memasang di laptop sendiri |
| [`DEPLOY.md`](DEPLOY.md) | Memasang di server, memilih provider AI |
| [`RCA.md`](RCA.md) | Analisis akar masalah (Fishbone, 5 Whys) |
