#!/usr/bin/env python3
"""Shorts kapak üretici — CEO/Shorts Kapak Şablon/SABLON.md birebir uygulaması.

Kural: şablon kodda sabittir. Model/rastgelelik yok; sadece metin ve arka plan değişir.
Çıktı: 1080x1920, JPEG **baseline** (progressive=False), kalite 90, subsampling=0, optimize=True.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

MOTOR = Path(__file__).resolve().parent
ASSETS = MOTOR / "assets"

W, H = 1080, 1920
MARGIN_X = 62
MAX_TEXT_W = 916
BLOCK_TOP = 296
BLOCK_BOTTOM = 1080
CAPTION_ALT = H - 128

BEYAZ = (255, 255, 255)
SARI = (255, 214, 51)          # #FFD633
TURKUAZ = (79, 227, 208)       # #4FE3D0
PUNTO_SABIT = 140              # tüm sette aynı punto
SATIR_ORANI = 0.99
KONTUR_ORANI = 0.055


def _font(ad: str, boyut: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / ad), boyut)


def _smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _gradyan(y0: int, y1: int, a0: float, a1: float, renk=(2, 8, 12)) -> Image.Image:
    katman = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(katman)
    h = max(1, y1 - y0)
    for y in range(y0, y1):
        a = int(round(255 * (a0 + (a1 - a0) * _smoothstep((y - y0) / h))))
        if a > 0:
            d.line([(0, y), (W, y)], fill=renk + (a,))
    return katman


def _vignette(guc: int = 110) -> Image.Image:
    kucuk = Image.new("L", (108, 192), 0)
    d = ImageDraw.Draw(kucuk)
    for y in range(192):
        for x in range(108):
            dx = (x - 54) / 54.0
            dy = (y - 96) / 96.0
            r = min(1.0, math.hypot(dx, dy))
            d.point((x, y), fill=int(guc * (r ** 2.2)))
    alfa = kucuk.resize((W, H), Image.BILINEAR)
    siyah = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    siyah.putalpha(alfa)
    return siyah


def _satirlar(draw, satirlar, punto, ust, alt) -> list[tuple[ImageFont.FreeTypeFont, str, tuple, int]]:
    """Satırları sığacak puntoya indirip ortalanmış yerleşim üretir."""
    while punto > 40:
        f = _font("Anton-Regular.ttf", punto)
        genislikler = [draw.textbbox((0, 0), s, font=f)[2] for s in satirlar]
        satir_h = int(punto * SATIR_ORANI)
        toplam_h = satir_h * len(satirlar)
        if max(genislikler) <= MAX_TEXT_W and (ust + toplam_h) <= alt:
            break
        punto -= 4
    f = _font("Anton-Regular.ttf", punto)
    satir_h = int(punto * SATIR_ORANI)
    yerlesim = []
    for i, s in enumerate(satirlar):
        w = draw.textbbox((0, 0), s, font=f)[2]
        yerlesim.append((f, s, (W // 2 - w // 2, ust + i * satir_h), punto))
    return yerlesim


def kapak_uret(arka_plan: str | Path, cikti: str | Path, *,
               satirlar: list[str], vurgu_satiri: int | None = None,
               kategori: str = "BİLİM", alt_aciklama: str = "") -> Path:
    """Tek kapak üretir. `vurgu_satiri` verilmezse son satır sarı olur."""
    cikti = Path(cikti)
    cikti.parent.mkdir(parents=True, exist_ok=True)

    bg = Image.open(arka_plan).convert("RGB")
    bg = ImageOps.fit(bg, (W, H), Image.LANCZOS, centering=(0.5, 0.5))
    bg = ImageEnhance.Color(bg).enhance(1.12)
    bg = ImageEnhance.Contrast(bg).enhance(1.10)
    tuval = bg.convert("RGBA")

    tuval.alpha_composite(_gradyan(0, 880, 0.93, 0.0))
    tuval.alpha_composite(_gradyan(1280, H, 0.0, 0.86))
    tuval.alpha_composite(_vignette(110))

    d = ImageDraw.Draw(tuval)

    # --- logo pill (sol üst)
    logo = "B İ L G İ   D O Z U"
    lf = _font("Poppins-SemiBold.ttf", 33)
    kutu = d.textbbox((0, 0), logo, font=lf)
    lw, lh = kutu[2] - kutu[0], kutu[3] - kutu[1]
    px, py = MARGIN_X, 78
    pill_w, pill_h = lw + 52, lh + 28
    d.rounded_rectangle([px, py, px + pill_w, py + pill_h], radius=pill_h // 2,
                        fill=(4, 16, 20, 190), outline=TURKUAZ + (170,), width=2)
    d.text((px + 26, py + 14 - kutu[1]), logo, font=lf, fill=TURKUAZ)

    # --- kategori (sağ üst)
    if kategori:
        kf = _font("Poppins-Medium.ttf", 30)
        kat = " ".join(kategori.upper())
        kw = d.textbbox((0, 0), kat, font=kf)[2]
        d.text((W - MARGIN_X - kw, 100), kat, font=kf, fill=(230, 244, 244, 205))

    # --- başlık bloğu
    vurgu = vurgu_satiri if vurgu_satiri is not None else len(satirlar) - 1
    yerlesim = _satirlar(d, satirlar, PUNTO_SABIT, BLOCK_TOP, BLOCK_BOTTOM)
    for i, (f, s, (x, y), punto) in enumerate(yerlesim):
        renk = SARI if i == vurgu else BEYAZ
        stroke = max(1, int(punto * KONTUR_ORANI))
        golge = Image.new("RGBA", tuval.size, (0, 0, 0, 0))
        ImageDraw.Draw(golge).text((x, y + 8), s, font=f, fill=(0, 0, 0, 158))
        tuval.alpha_composite(golge.filter(ImageFilter.GaussianBlur(14)))
        d = ImageDraw.Draw(tuval)
        d.text((x, y), s, font=f, fill=renk, stroke_width=stroke, stroke_fill=(3, 10, 14, 235))

    # --- vurgu çizgisi + yan noktalar (başlığın hemen üstü)
    cy = BLOCK_TOP - 46
    d.rounded_rectangle([MARGIN_X, cy, MARGIN_X + 132, cy + 7], radius=4, fill=SARI + (235,))
    for i in range(2):
        dx = MARGIN_X + 160 + i * 34
        d.ellipse([dx, cy - 4, dx + 14, cy + 10], fill=TURKUAZ + (200,))

    # --- alt açıklama
    if alt_aciklama:
        punto = 40
        while punto >= 26:
            cf = _font("Poppins-SemiBold.ttf", punto)
            satirlar_c = _sar(d, alt_aciklama, cf, MAX_TEXT_W)
            if len(satirlar_c) <= 3:
                break
            punto -= 2
        cf = _font("Poppins-SemiBold.ttf", punto)
        satir_h = int(punto * 1.45)
        toplam = satir_h * len(satirlar_c)
        ust = CAPTION_ALT - toplam + punto

        kutu_kat = Image.new("RGBA", tuval.size, (0, 0, 0, 0))
        kd = ImageDraw.Draw(kutu_kat)
        for i, s in enumerate(satirlar_c):
            w = kd.textbbox((0, 0), s, font=cf)[2]
            x = W // 2 - w // 2
            y = ust + i * satir_h
            kd.text((x, y), s, font=cf, fill=(3, 12, 16, 132),
                    stroke_width=max(8, punto // 3), stroke_fill=(3, 12, 16, 132))
        tuval.alpha_composite(kutu_kat.filter(ImageFilter.GaussianBlur(9)))

        d = ImageDraw.Draw(tuval)
        for i, s in enumerate(satirlar_c):
            w = d.textbbox((0, 0), s, font=cf)[2]
            d.text((W // 2 - w // 2, ust + i * satir_h), s, font=cf,
                   fill=(238, 248, 248, 242), stroke_width=2, stroke_fill=(0, 0, 0, 170))

    sonuc = tuval.convert("RGB")
    sonuc.save(cikti, "JPEG", quality=90, subsampling=0, optimize=True, progressive=False)
    return cikti


def _sar(draw, metin: str, font, azami: int) -> list[str]:
    kelimeler = metin.split()
    satirlar, mevcut = [], ""
    for k in kelimeler:
        deneme = (mevcut + " " + k).strip()
        if draw.textbbox((0, 0), deneme, font=font)[2] <= azami or not mevcut:
            mevcut = deneme
        else:
            satirlar.append(mevcut)
            mevcut = k
    if mevcut:
        satirlar.append(mevcut)
    return satirlar


if __name__ == "__main__":
    import sys
    arka = sys.argv[1]
    cikti = sys.argv[2]
    kapak_uret(arka, cikti,
               satirlar=["PARMAK UCUN", "SUDA NEDEN", "BURUŞUR?"],
               kategori="FİZYOLOJİ",
               alt_aciklama="Su emmiyoruz: sinir sistemin tutuşu artırıyor. Kaynak: Nature Neuroscience")
    print(cikti)
