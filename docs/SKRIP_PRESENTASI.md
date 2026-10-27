# Skrip Presentasi dan Demo MataKlabat

Untuk tim Dragon Apple. Deck: slide 1–18 (link di grup). Total ±16 menit + tanya jawab.
Teks yang sama ada di *speaker notes* tiap slide (ikut terbawa saat deck diunduh sebagai PPTX).

Isi nama di tanda `[...]`. Teks di dalam `[OP: ...]` adalah aksi operator laptop, bukan untuk dibaca.

## Pembagian peran

| Kode | Nama | Bagian | Durasi |
|---|---|---|---|
| A | [Nama pembicara A] | Masalah dan RCA (slide 1-6) | ±4 menit |
| B | [Nama pembicara B] | Solusi, cara AI memutuskan, peringatan (slide 7-11) | ±4 menit |
| C | [Nama pembicara C] | Website, mode operator, demo langsung (slide 12-14) | ±5 menit |
| D | [Nama pembicara D] | Evaluasi, kegagalan, rekomendasi, penutup (slide 15-18) | ±3 menit |
| OP | [Nama operator laptop] | Menjalankan dashboard saat demo (login, aktifkan kamera, pilih foto) | selama demo |

## Persiapan sebelum tampil (H-30 menit)

- [ ] Dashboard terbuka di laptop presentasi; semua kamera **Nonaktif**; operator **belum** login.
- [ ] `python -m mataklabat check --llm-sample data/demo/bahan/asap_kolom.jpg` berhasil (AI dan kuota aman).
- [ ] Grup Telegram terbuka di HP yang akan ditunjukkan.
- [ ] Rekaman gladi siap diputar sebagai cadangan.
- [ ] Hotspot HP siap kalau Wi-Fi kampus bermasalah.
- [ ] Kalau demo online (VPS): link dashboard / QR siap ditampilkan di slide 13.

## Skrip per slide

### 1. MataKlabat — Pembicara A ([Nama pembicara A]), 30 dtk

Selamat pagi/siang, Bapak/Ibu dosen dan teman-teman. Kami dari tim Dragon Apple. Bulan lalu, kebakaran di kaki Gunung Klabat terus meluas selama lebih dari tiga minggu. Kami membuat MataKlabat, prototipe yang menjawab dua pertanyaan: seberapa rawan kawasan terbakar hari ini, dan apakah ada api atau asap sekarang. Saya [nama A], bersama [nama B], [nama C], dan [nama D].

> Catatan tim: Sebut nama semua anggota. Jangan membaca judul slide.

### 2. Masalah — Pembicara A ([Nama pembicara A]), 45 dtk

Dalam sekitar tiga minggu, lahan yang terbakar naik dari 60 hektare menjadi sekitar 651 hektare menurut estimasi Dishut Sulut, 131 hektare di antaranya hutan lindung. Tanggap darurat diperpanjang sampai 21 Oktober. Yang paling penting buat kami: titik api baru di Matungkas dan Laikit baru diketahui setelah membesar. Kepala Dinas Kehutanan sendiri bilang, kalau berawan, alat pemantau tidak bisa melacak.

> Catatan tim: Kalau ditanya angka: sumber berbeda, Bupati menyebut ±400 ha (9 Okt), Dishut ±651 ha (3 Okt). Kita pakai estimasi tertinggi.

### 3. Kronologi — Pembicara A ([Nama pembicara A]), 30 dtk

Kalau kita lihat kronologinya, polanya sama terus: api muncul, menyebar, baru penanganan diperkuat. Dari Kaki Dian tanggal 19 September, masuk hutan lindung awal Oktober, sampai titik api baru di Matungkas dan Laikit tanggal 11 Oktober. Api selalu selangkah di depan.

> Catatan tim: Jangan membaca semua baris tabel; sebut 3 tanggal saja.

### 4. Fishbone Diagram — Pembicara A ([Nama pembicara A]), 45 dtk

Kami menganalisis penyebabnya dengan Fishbone. Ada enam kategori: lingkungan dan alam, pemantauan dan teknologi, medan dan akses, manusia, metode, dan sumber daya. Teks tegak adalah fakta dari pemberitaan, teks miring adalah analisis kami yang masih perlu diverifikasi. Kategori yang paling bisa dijawab teknologi adalah pemantauan: satelit buta saat berawan, titik api baru terlambat diketahui, dan tidak ada kamera darat 24 jam.

> Catatan tim: Tunjuk kategori Pemantauan & Teknologi di diagram.

### 5. 5 Whys — Pembicara A ([Nama pembicara A]), 45 dtk

Lalu kami turun dengan 5 Whys. Kenapa api meluas? Karena menyebar lebih cepat dari kemampuan memadamkan. Kenapa? Titik api baru tidak segera diketahui. Kenapa? Pemantauan tidak kontinu. Kenapa? Belum ada deteksi dini darat yang terhubung ke posko. Dan kenapa? Karena penanganannya masih reaktif, dan belum ada solusi pemantauan yang murah di tingkat kabupaten atau desa.

> Catatan tim: Ritme: tanya 'kenapa?' lalu jawab, lima kali.

### 6. Akar masalah — Pembicara A ([Nama pembicara A]), 30 dtk

Jadi akar masalahnya: tidak ada pemantauan darat yang kontinu dan terhubung ke posko. Faktor alam seperti kemarau dan angin tidak bisa kita hilangkan, dan hal seperti armada atau akses air di luar lingkup sistem. Yang bisa kita kendalikan adalah: api diketahui lebih cepat, dan arah sebarannya diketahui lebih awal. [Nama B] akan menjelaskan solusinya.

> Catatan tim: Serah terima ke pembicara B.

### 7. Solusi — Pembicara B ([Nama pembicara B]), 45 dtk

Terima kasih. MataKlabat memisahkan dua pertanyaan menjadi dua status. Pertama, pencegahan: Risiko Kebakaran Kawasan, dihitung dari cuaca, dari Rendah sampai Sangat Tinggi. Kedua, deteksi: Status Kamera, yaitu Normal, Perlu Dicek, atau Kebakaran Terdeteksi. Kami pisahkan supaya orang tidak bingung: waspada karena cuaca kering, atau karena memang ada asap. Status juga dibedakan dengan bentuk ikon, bukan hanya warna. Satelit buta saat berawan, kamera darat tidak.

### 8. Arsitektur — Pembicara B ([Nama pembicara B]), 45 dtk

Prinsip arsitekturnya: murah dulu, mahal belakangan. Dari kiri: empat kamera dan data cuaca. Di tengah, detektor lokal berbasis warna dan gerak memeriksa setiap frame, gratis. AI vision lewat 9router hanya dipanggil kalau ada tanda, jawabannya JSON lengkap dengan alasan. Lalu aturan R0 sampai R6 yang memutuskan. Keluarannya: website, Telegram, dan jejak keputusan di database. Monitor dan website proses terpisah, jadi kalau website mati, pemantauan tetap jalan.

### 9. Cara AI memutuskan — Pembicara B ([Nama pembicara B]), 60 dtk

Ini inti Explainable AI kami: tidak ada keputusan dari satu bukti. Detektor mencurigai, AI memverifikasi, aturan memutuskan. Kebakaran Terdeteksi hanya kalau AI yakin minimal 0,70, bukan lookalike, dan terkonfirmasi. Api unggun atau pembakaran kecil menjadi Perlu Dicek potensi. Kalau AI menilai itu kabut, senja, atau lampu, ditolak. Dan kalau AI tidak tersedia, statusnya Perlu Dicek belum terverifikasi: tampil di dashboard, tapi tidak dikirim ke Telegram, supaya grup tidak dibanjiri alarm palsu. Penjelasan di dashboard ditulis dari template tetap, bukan dikarang LLM.

> Catatan tim: Kalau waktu mepet, cukup jelaskan R1, R5, R4.

### 10. Risiko Kawasan — Pembicara B ([Nama pembicara B]), 45 dtk

Untuk pencegahan kami tidak mengarang indeks. Kami memakai Fire Weather Index Kanada, dasar FDRS yang dipakai BMKG, dengan ambang kelas dari penelitian FDRS Indonesia. Risiko kawasan adalah kelas tertinggi dari tiga indikator: mudah menyala, kekeringan, dan sulit dipadamkan. Saat risiko Tinggi, ambang AI untuk Kebakaran Terdeteksi turun ke 0,60. Satu temuan dari gladi: kalau cuaca diambil di puncak, risikonya tampak Sedang. Kami pindahkan ke kaki gunung, tempat api bermula.

> Catatan tim: Angka di slide adalah data 27 Okt; risiko hari H bisa berbeda, sebut yang tampil di dashboard.

### 11. Peringatan Telegram — Pembicara B ([Nama pembicara B]), 45 dtk

Peringatan dikirim ke grup Telegram dalam dua pesan. Pesan pertama langsung: foto, status, alasan, data, dan tindakan, bisa dibaca dalam lima detik. Pesan kedua sekitar satu menit kemudian: laporan AI Agent yang memanggil alat sendiri, cuaca, perkiraan arah sebaran, desa terancam, pos damkar dan sumber air terdekat. Kalau agent gagal, laporan template tetap terkirim dan menyebut alasannya. Pesan disimpan di antrean dan dikirim ulang kalau internet putus. [Nama C] akan menunjukkan sistemnya langsung.

> Catatan tim: Serah terima ke pembicara C.

### 12. Website — Pembicara C ([Nama pembicara C]), 30 dtk

Ini website MataKlabat. Di atas, risiko kawasan; di bawahnya peta dengan kamera, arah angin, dan perkiraan sebaran; lalu kartu tiap kamera. Setiap status punya panel Mengapa yang menjelaskan rule dan data yang dipakai. Setiap insiden punya halaman sendiri dengan foto, linimasa keputusan, dan laporan AI Agent.

> Catatan tim: OP: buka dashboard di tab browser, belum login.

### 13. Mode operator — Pembicara C ([Nama pembicara C]), 45 dtk

Kamera yang selalu aktif membuang kuota AI dan bisa memicu peringatan yang tidak perlu. Jadi operator bisa menyalakan kamera hanya saat dibutuhkan. Kamera nonaktif tidak membaca gambar, tidak memanggil AI, dan tidak mengirim Telegram. Mematikan kamera me-reset statusnya ke Normal, jadi demo bisa diulang. Hanya operator yang login yang bisa mengubah; teman-teman bisa membuka dashboard yang sama di HP dan hanya melihat.

> Catatan tim: Kalau sudah online di VPS: tampilkan link/QR dashboard supaya penonton ikut membuka.

### 14. Demo langsung — Pembicara C ([Nama pembicara C]), 3-4 menit

Sekarang demo. [OP login sebagai operator. Semua kamera tampil Nonaktif.] Kami aktifkan CAM-04, kamera foto di Matungkas. [OP: Aktifkan CAM-04.] Pertama foto kabut di gunung. [OP: Pilih foto, kabut_gunung.jpg.] Detektor lokal curiga karena warnanya mirip asap, tapi AI menilainya kabut, jadi status tetap Normal. Buka panel Mengapa. Kedua, api unggun. [OP: Pilih foto, potensi_01.jpg.] Ini Perlu Dicek potensi: ada api, tapi kecil dan terkendali. Ketiga, kolom asap. [OP: Pilih foto, asap_kolom.jpg.] Dalam sekitar 35 detik status menjadi Kebakaran Terdeteksi, insiden dibuka, dan pesan masuk ke Telegram. [Tunjukkan HP.] Sekitar satu menit kemudian laporan AI Agent menyusul. [OP: buka halaman insiden.] Terakhir, kami nonaktifkan kamera: status kembali Normal dan insiden ditutup. [OP: Nonaktifkan CAM-04.] [Nama D] akan menjelaskan hasil evaluasinya.

> Catatan tim: Rencana cadangan: kalau AI habis kuota, status jadi 'belum terverifikasi' tanpa Telegram; jelaskan sebagai perilaku aman, lalu putar rekaman gladi. Kalau internet mati: pakai hotspot HP.

### 15. Evaluasi — Pembicara D ([Nama pembicara D]), 45 dtk

Kami menguji 72 foto berlisensi dalam enam kelas: api, asap, kabut, senja, lampu, dan normal. Detektor lokal saja menangkap semua kebakaran, tapi hampir semua kabut, senja, dan foto normal ikut memicu: precision hanya 0,35. Dengan verifikasi AI, semua false alarm itu hilang tanpa kehilangan satu kebakaran pun. Hasilnya juga konsisten: 12 foto diulang 3 kali, keputusannya 100 persen sama. Untuk api unggun, 7 dari 8 menjadi Perlu Dicek potensi.

### 16. Kegagalan dan keterbatasan — Pembicara D ([Nama pembicara D]), 45 dtk

Tapi skor sempurna belum berarti siap lapangan. Test set kami mudah: kebakarannya besar dan jelas. Malam hari, asap tipis di kejauhan, dan kabut asap belum teruji. Kami juga belajar bahwa kuota AI bisa habis: evaluasi sekitar 600 panggilan menghabiskannya. Saat itu terjadi, sistem tidak diam, tapi turun ke status belum terverifikasi supaya manusia tetap mengecek. Cuacanya juga dari model, bukan stasiun di lokasi.

> Catatan tim: Bagian ini penting untuk kejujuran; jangan dilewati.

### 17. Rekomendasi — Pembicara D ([Nama pembicara D]), 45 dtk

Teknologi hanya separuh jawaban. Rekomendasi kami: BPBD memasang tiga sampai empat kamera di titik pandang tinggi yang terhubung ke posko. Dinas Kehutanan menggabungkan satelit dengan kamera darat. Desa membangun sekat api sebelum kemarau. Pengelola jalur pendakian melarang api unggun saat risiko tinggi. Dan yang paling murah: UNKLAB menguji satu kamera di kampus yang menghadap Klabat.

### 18. Penutup — Pembicara D ([Nama pembicara D]), 30 dtk

Jadi MataKlabat: detektor mencurigai, AI memverifikasi, aturan memutuskan, dan semuanya tercatat. Langkah berikutnya: menambah kasus sulit ke test set, menyiapkan model AI cadangan, dan uji lapangan. Kode dan dokumentasinya terbuka di GitHub. Terima kasih, kami siap menerima pertanyaan.

> Catatan tim: Semua anggota maju untuk tanya jawab.

## Alur demo untuk operator (slide 14)

| Langkah | Aksi operator | Yang terlihat | Waktu |
|---|---|---|---|
| 1 | **Masuk operator** (password dari ketua tim) | Tombol Aktifkan/Nonaktifkan muncul | 10 dtk |
| 2 | CAM-04 → **Aktifkan** | Foto normal Klabat, status Normal | 10 dtk |
| 3 | **Pilih foto** → `kabut_gunung.jpg` | Tetap Normal; panel Mengapa: AI menilai kabut | 30 dtk |
| 4 | **Pilih foto** → `potensi_01.jpg` | Perlu Dicek (potensi) | 30 dtk |
| 5 | **Pilih foto** → `asap_kolom.jpg` | Kebakaran Terdeteksi ±35 dtk, Telegram masuk | 60 dtk |
| 6 | Klik **Buka laporan lengkap** | Halaman insiden; laporan AI Agent ±1 menit | 45 dtk |
| 7 | CAM-04 → **Nonaktifkan** → OK | Kembali Normal/Nonaktif, insiden ditutup | 10 dtk |

**Kalau ada masalah:**

- AI tidak menjawab / kuota habis → status "Perlu Dicek (belum terverifikasi)" tanpa Telegram. Jelaskan sebagai perilaku aman, lalu putar rekaman gladi.
- Internet putus → pindah ke hotspot HP; pesan Telegram yang tertunda dikirim ulang otomatis.
- Status tidak berubah setelah pilih foto → tunggu 5–10 dtk (foto dicek AI), jangan klik berulang.

## Persiapan tanya jawab

**Kenapa tidak pakai YOLO/model deteksi api saja?**

Model deteksi biasa butuh data latih lokal dan tetap salah di kabut/senja. Kami memakai detektor lokal yang murah sebagai penyaring, lalu AI vision yang bisa menjelaskan alasannya. Sistem sudah mendukung YOLO opsional (YOLO_WEIGHTS) kalau ada model terlatih.

**Akurasinya 100%, apa tidak terlalu bagus?**

Ya, dan kami jujur menyebutnya: test set masih mudah (kebakaran besar). Kasus sulit seperti asap tipis, malam hari, dan kabut asap belum teruji. Itu langkah berikutnya.

**Bagaimana kalau internet atau AI mati?**

Detektor lokal tetap jalan. Status maksimal 'Perlu Dicek (belum terverifikasi)', tampil di dashboard tanpa Telegram supaya tidak ada alarm palsu. Pesan yang tertunda disimpan di antrean dan dikirim ulang.

**Bagaimana di malam hari?**

Belum teruji dan menjadi keterbatasan. Api di malam hari terlihat jelas, tapi lampu dan pantulan bisa mengecoh; perlu test set malam.

**Berapa biayanya?**

Prototipe jalan di laptop atau VPS kecil (2 vCPU, 2 GB RAM). Biaya utama di lapangan adalah kamera, daya, dan jaringan di titik pandang. AI hanya dipanggil saat ada tanda, dan kamera bisa dinonaktifkan untuk menghemat kuota.

**Bagaimana dengan privasi kamera?**

Kamera diarahkan ke lereng gunung, bukan ke permukiman. Website untuk penonton hanya-baca; mengubah kamera butuh login operator.

**Kenapa risiko pakai FWI Kanada?**

FWI adalah dasar Fire Danger Rating System yang dipakai BMKG; ambang kelasnya dari penelitian FDRS Indonesia (de Groot dkk. 2006).

**Apakah AI bisa salah memutuskan kebakaran?**

Bisa, jadi keputusan tidak diambil AI sendirian: harus yakin di atas ambang, bukan lookalike, dan terkonfirmasi 2 dari 3 cek. Setiap keputusan tercatat dan bisa diaudit, dan pesan Telegram selalu meminta verifikasi lapangan.
