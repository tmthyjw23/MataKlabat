# Deploy MataKlabat ke VPS

Panduan memasang MataKlabat di server Linux supaya bisa dibuka teman lewat HTTPS dan didemokan dari HP. Untuk laptop, lihat [`SETUP.md`](SETUP.md).

Contoh di sini memakai VPS tim: OpenCloudOS 9 (keluarga RHEL), 2 vCPU, 2 GB RAM, Python 3.11, nginx, dan **Cloudflare Tunnel** yang sudah melayani situs lain. Ganti nama pengguna, domain, dan port sesuai server kamu.

| Hal | Nilai di VPS tim |
|---|---|
| Folder | `/home/timothy/mataklabat` |
| Port website (lokal saja) | `127.0.0.1:8020` (8000 dan 8011 dipakai layanan lain) |
| Domain | `mataklabat.timotation.biz.id` |
| Service | `mataklabat.service` (systemd) |
| Kamera | `config/cameras.vps.yaml`: 3 video + 1 Kamera Foto, **semua mulai nonaktif** |

## 0. Gambaran

```
HP teman ──HTTPS──> Cloudflare ──tunnel──> nginx :80 ──> 127.0.0.1:8020 (MataKlabat web)
                                                          │
                                         monitor (kamera, AI, Telegram) ── data/runtime/*.db
```

- Website hanya mendengar di `127.0.0.1`; yang membuka ke internet adalah nginx lewat Cloudflare. HTTPS ditangani Cloudflare.
- Penonton hanya bisa **melihat**. Tombol kamera aktif/nonaktif dan galeri foto hanya muncul untuk **operator** yang masuk dengan `OPERATOR_PASSWORD`.
- Kamera yang nonaktif tidak membaca frame, tidak memanggil AI (hemat kuota), dan tidak mengirim Telegram.

## 1. Kode dan paket

```bash
git clone https://github.com/tmthyjw23/MataKlabat.git ~/mataklabat
cd ~/mataklabat
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/python scripts/fetch_media.py      # video demo, foto galeri, test set (beberapa menit)
cp data/demo/bahan/klabat.jpg data/demo/CAM-04/00_klabat_normal.jpg   # foto awal Kamera Foto
```

OpenCV yang dipakai adalah versi *headless*, jadi tidak butuh libGL/desktop di server.

## 2. File `.env`

Buat `~/mataklabat/.env` (lihat `.env.example`) lalu `chmod 600 .env`. Yang penting untuk server:

```ini
CAMERAS_FILE=config/cameras.vps.yaml
WEB_HOST=127.0.0.1
WEB_PORT=8020
PUBLIC_URL=https://mataklabat.timotation.biz.id
OPERATOR_PASSWORD=<minimal 10 karakter, acak>
GALLERY_DIR=data/demo/bahan
```

Buat password operator acak langsung di server, lalu simpan di password manager tim:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(15))"
```

Melihat password yang sudah terpasang (hanya di terminal server, jangan kirim ke grup):

```bash
grep ^OPERATOR_PASSWORD ~/mataklabat/.env
```

`TELEGRAM_*` dan `LLM_*` boleh kosong dulu: tanpa Telegram pesan hanya tampil di web (mode kering), tanpa LLM sistem memakai detektor lokal saja (maksimal "Perlu Dicek (belum terverifikasi)", tanpa pesan Telegram).

## 3. AI (9router) di server

9router di laptop (WSL) **tidak** bisa dipakai dari VPS. Pilihan:

1. **Pasang 9router di VPS** (butuh Node 20). Jalankan sebagai service, dengar di `127.0.0.1:20128` saja, lalu login akun provider di dashboard 9router lewat SSH tunnel:
   ```bash
   ssh -L 20128:127.0.0.1:20128 timothy@IP_VPS
   ```
   lalu buka `http://localhost:20128` di laptop. **Jangan** buka port 20128 ke internet.
2. Endpoint lain yang OpenAI-compatible dan mendukung gambar + tool calling: isi `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.

Cek: `.venv/bin/python -m mataklabat check --llm-sample data/demo/bahan/asap_kolom.jpg`.

Kuota: setiap kamera **aktif** memanggil AI saat ada tanda, saat status naik, dan heartbeat tiap `HEARTBEAT_S` (default 120 dtk). Nonaktifkan kamera yang tidak dipakai. Jangan menjalankan evaluasi penuh (±600 panggilan) menjelang demo.

## 4. Service systemd

Jalankan sebagai user biasa pemilik folder (di VPS tim: `timothy`), **bukan** setelah `sudo su`. Di sesi root, `~` berarti `/root` dan unit akan menunjuk `/home/root/...` lalu gagal dengan `status=226/NAMESPACE`. Nama user ditulis langsung:

```bash
cd ~/mataklabat
sed "s/USER/timothy/g" deploy/mataklabat.service | sudo tee /etc/systemd/system/mataklabat.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now mataklabat
systemctl status mataklabat --no-pager
curl -s http://127.0.0.1:8020/api/health | head -c 300
```

Unit ini membatasi memori (800 MB) dan CPU supaya layanan lain di VPS kecil tidak terganggu, dan hanya mengizinkan tulis ke `data/`.

## 5. nginx

```bash
sed "s/DOMAIN/mataklabat.timotation.biz.id/g" deploy/nginx-mataklabat.conf | sudo tee /etc/nginx/conf.d/mataklabat.conf >/dev/null
sudo nginx -t && sudo systemctl reload nginx
```

`nginx -t` wajib lulus sebelum reload, karena nginx yang sama melayani situs lain. Konfigurasi ini mematikan buffering untuk `/api/stream` (update langsung) dan membatasi percobaan login.

Uji dari server (meniru permintaan dari Cloudflare):

```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "Host: mataklabat.timotation.biz.id" -H "X-Forwarded-Proto: https" http://127.0.0.1/
```

Hasilnya harus `200`.

## 6. Cloudflare: hostname publik

Tunnel di VPS ini dikelola dari dashboard Cloudflare (token), jadi hostname ditambah di sana, **bukan** di server:

1. Cloudflare dashboard → **Zero Trust** → **Networks** → **Tunnels** → pilih tunnel VPS → **Public Hostname** → **Add a public hostname**.
2. Subdomain `mataklabat`, domain `timotation.biz.id`, service **HTTP** → `localhost:80` (sama seperti `filkomday`).
3. Simpan, lalu buka `https://mataklabat.timotation.biz.id`.

Kalau server kamu tidak memakai Cloudflare: arahkan A record domain ke IP VPS, pasang sertifikat (`sudo certbot --nginx -d DOMAIN`), dan hapus blok `if ($http_x_forwarded_proto ...)` di vhost.

## 7. Alur demo

1. Buka dashboard, klik **Masuk operator**, masukkan password operator.
2. Semua kamera tampil **Nonaktif** (abu-abu, ikon jeda). Risiko Kebakaran Kawasan tetap tampil karena berasal dari cuaca.
3. CAM-04 (Kamera Foto): **Pilih foto** → `kabut_gunung.jpg` → **Aktifkan**. Status Normal (AI menolak kabut).
4. **Pilih foto** → `potensi_01.jpg` (api unggun) → Perlu Dicek (potensi).
5. **Pilih foto** → `asap_kolom.jpg` → Kebakaran Terdeteksi dalam ±35 dtk, Telegram + laporan AI Agent.
6. Opsional: aktifkan CAM-01 (video kebakaran hutan) untuk contoh dari video.
7. Selesai: **Nonaktifkan** semua kamera. Status di-reset ke Normal dan insiden ditutup dengan catatan "kamera dinonaktifkan operator", jadi demo bisa diulang dari awal.

Pilihan operator disimpan di `data/runtime/control.db` dan bertahan saat server restart.

## 8. Operasional

| Perlu | Perintah |
|---|---|
| Lihat log langsung | `journalctl -u mataklabat -f` |
| Log aplikasi (JSON, berputar) | `ls ~/mataklabat/data/runtime/logs/` |
| Restart | `sudo systemctl restart mataklabat` |
| Update kode | `cd ~/mataklabat && git pull && .venv/bin/python -m pip install -e . && sudo systemctl restart mataklabat` |
| Kesehatan | `https://DOMAIN/health` |
| Matikan semua kamera dari server | `sqlite3 data/runtime/control.db "UPDATE camera_control SET enabled=0"` (atau lewat dashboard) |
| Mulai bersih | `sudo systemctl stop mataklabat && rm -rf data/runtime && sudo systemctl start mataklabat` |

## 9. Keamanan singkat

- Rahasia hanya di `.env` (chmod 600). Jangan kirim isi `.env` ke grup.
- Website dengar di `127.0.0.1`; hanya nginx yang terbuka.
- Login operator: password ≥ 10 karakter, sesi di memori (hilang saat restart = login ulang), cookie `HttpOnly` + `SameSite=Strict` + `Secure` di HTTPS, setiap perubahan butuh header khusus dan Origin yang sama, 10 password salah dalam 10 menit = login dikunci sementara.
- Galeri hanya menerima nama file yang persis ada di `GALLERY_DIR`; tidak ada upload.
- Prototipe akademik: untuk pemakaian sungguhan tambahkan akun per orang dan audit log operator.
