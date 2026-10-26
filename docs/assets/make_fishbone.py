"""Generate the Fishbone (Ishikawa) diagram for MataKlabat RCA.

Usage: python docs/assets/make_fishbone.py  ->  docs/assets/fishbone.png + fishbone.svg
Causes tagged "S" come from news sources (see docs/RCA.md); "A" are analysis/assumptions to verify.
"""
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).parent
PROBLEM = "Karhutla Gunung Klabat meluas\n60 → ±651 ha dan >21 hari\nbelum padam (Sep–Okt 2026)"

CATEGORIES = {
    # top row (left -> right)
    "Lingkungan & Alam": [
        ("Musim kemarau panjang", "S"),
        ("Angin kencang mempercepat sebaran", "S"),
        ("Daun & kayu kering menumpuk bertahun-tahun", "S"),
        ("Api merambat lewat akar di bawah tanah", "S"),
    ],
    "Pemantauan & Teknologi": [
        ("Satelit tidak bisa melacak saat berawan", "S"),
        ("Titik api baru (Matungkas, Laikit) terlambat diketahui", "S"),
        ("Tidak ada kamera/sensor darat yang memantau 24 jam", "A"),
        ("Deteksi bergantung laporan warga & patroli", "A"),
    ],
    "Medan & Akses": [
        ("Medan terjal, kendaraan pemadam tidak bisa masuk", "S"),
        ("Makin ke atas makin curam, mobilisasi sulit", "S"),
        ("Suplai air bergantung bantuan warga", "S"),
    ],
    # bottom row (left -> right)
    "Manusia": [
        ("Dugaan unsur kesengajaan (titik api janggal)", "S"),
        ("Kebiasaan membakar lahan/sampah saat kemarau", "A"),
        ("Api unggun / puntung rokok pengunjung", "A"),
    ],
    "Metode & Prosedur": [
        ("Koordinasi diperkuat setelah api meluas (reaktif)", "S"),
        ("Water bombing baru dipertimbangkan saat tak terkendali", "S"),
        ("Sekat api dibangun desa setelah api mendekat", "S"),
        ("Belum ada SOP peringatan dini berbasis data real-time", "A"),
    ],
    "Sumber Daya": [
        ("Armada darat terbatas & tak menjangkau lereng", "S"),
        ("Bergantung relawan & swadaya warga", "S"),
        ("Keselamatan personel membatasi operasi di lereng curam", "S"),
    ],
}

C_SPINE = "#37474F"
C_HEAD = "#C62828"
C_CAT = "#263238"
C_S = "#212121"
C_A = "#6D4C41"

fig, ax = plt.subplots(figsize=(20, 12.5), dpi=150)
ax.set_xlim(0, 20)
ax.set_ylim(-0.7, 12)
ax.axis("off")
fig.patch.set_facecolor("white")

SPINE_Y = 5.5
ax.annotate("", xy=(15.7, SPINE_Y), xytext=(0.4, SPINE_Y),
            arrowprops=dict(arrowstyle="-|>", lw=4, color=C_SPINE, mutation_scale=30))

head = FancyBboxPatch((15.8, SPINE_Y - 1.25), 3.9, 2.5, boxstyle="round,pad=0.08",
                      fc=C_HEAD, ec=C_HEAD)
ax.add_patch(head)
ax.text(17.75, SPINE_Y, PROBLEM, ha="center", va="center", color="white",
        fontsize=14, fontweight="bold", linespacing=1.4)

bases = [5.4, 10.1, 14.8]
names = list(CATEGORIES)
DX = 2.3          # horizontal lean of each bone
TOP_Y, BOT_Y = 9.9, 1.1

for i, name in enumerate(names):
    top = i < 3
    bx = bases[i % 3]
    ey = TOP_Y if top else BOT_Y
    ex = bx - DX
    ax.plot([bx, ex], [SPINE_Y, ey], color=C_SPINE, lw=2.5)
    # category label
    ax.text(ex, ey + (0.35 if top else -0.35), name, ha="center",
            va="bottom" if top else "top", fontsize=13, fontweight="bold", color="white",
            bbox=dict(boxstyle="round,pad=0.4", fc=C_CAT, ec=C_CAT))
    causes = CATEGORIES[name]
    n = len(causes)
    for j, (txt, tag) in enumerate(causes):
        t = (j + 1) / (n + 1)                      # position along bone (0 = spine)
        t = 0.18 + t * 0.72
        y = SPINE_Y + (ey - SPINE_Y) * t
        x = bx + (ex - bx) * t
        ax.plot([x - 0.45, x], [y, y], color=C_SPINE, lw=1.2)
        label = textwrap.fill(txt + (" *" if tag == "A" else ""), 30)
        ax.text(x - 0.55, y, label, ha="right", va="center", fontsize=9.5,
                color=C_A if tag == "A" else C_S,
                style="italic" if tag == "A" else "normal", linespacing=1.15)

ax.text(0.4, -0.6,
        "Teks tegak = fakta dari pemberitaan (detikSulsel, Metro TV, Teras Manado, Totabuan News, Sep–Okt 2026).   "
        "* Teks miring = hasil analisis/asumsi tim yang perlu diverifikasi.",
        fontsize=9.5, color="#555555", ha="left", va="bottom")
ax.text(0.4, 11.9, "Fishbone Diagram: Karhutla Gunung Klabat 2026  ·  MataKlabat",
        fontsize=15, fontweight="bold", color=C_CAT, ha="left", va="top")

fig.savefig(OUT / "fishbone.png", bbox_inches="tight", facecolor="white")
fig.savefig(OUT / "fishbone.svg", bbox_inches="tight", facecolor="white")
print("saved", OUT / "fishbone.png")
