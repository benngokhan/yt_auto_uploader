#!/usr/bin/env python3
"""Bilgi Dozu şablon renderer — kanaldaki mevcut videoların birebir tipografik şablonu.

Ölçüler 1080x1920 (9:16) referans videodan alındı (youtu.be/KfHoxTt2y60):
  • üst sol: lime rozet "BİLGİ DOZU"  (x72-275, y61-131, #D9F11E)
  • rozet üstü: lime kısa çizgi + gri ince çizgi (y58, 72→620)
  • başlık: BÜYÜK HARF, 2 satır, beyaz + lacivert kontur, ortalı (y~150)
  • anlatım: 2 satır, beyaz + lacivert kontur, ortalı (y~1380)
  • alt: kaynak satırları (gri, x288) + wordmark "BİLGİ DOZU" (y~1835)

Kullanım:
    python sablon_render.py --baslik "BOL HAVUÇ YEMEK GECE GÖRÜŞÜNÜ AÇAR MI?" \
        --altyazi "bilimsel bir gerçek mi|yoksa gizli askeri oyun mu?" \
        --kaynak "Smithsonian Magazine & Imperial War Museums Archives" \
        --arka-plan bg.png --cikti kare.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
LIME = (217, 241, 30)
LACI = (8, 28, 42)
BEYAZ = (255, 255, 255)
GRI = (176, 186, 192)
KONTUR = (6, 26, 38)
KOK = Path(__file__).resolve().parent
_FONT_ADAYLARI = [KOK / "assets" / "Anton-Regular.ttf",
                  KOK / "repo_live" / "assets" / "Anton-Regular.ttf"]
FONT_YOLU = next((f for f in _FONT_ADAYLARI if f.exists()), _FONT_ADAYLARI[0])

TR_BUYUK = str.maketrans({"i": "İ", "ı": "I", "ş": "Ş", "ğ": "Ğ", "ç": "Ç", "ö": "Ö", "ü": "Ü"})


def tr_upper(metin: str) -> str:
    return metin.translate(TR_BUYUK).upper()


def font(boyut: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_YOLU), boyut)


def satir_sar(draw, metin, fnt, azami_genislik):
    kelimeler, satirlar, mevcut = metin.split(), [], ""
    for k in kelimeler:
        deneme = (mevcut + " " + k).strip()
        if draw.textlength(deneme, font=fnt) <= azami_genislik or not mevcut:
            mevcut = deneme
        else:
            satirlar.append(mevcut)
            mevcut = k
    if mevcut:
        satirlar.append(mevcut)
    return satirlar


def sigdir(draw, metin, azami_genislik, azami_satir, ust_boyut, alt_boyut=34):
    """Yazıyı verilen satır sayısına sığana kadar küçültür."""
    boyut = ust_boyut
    while boyut > alt_boyut:
        fnt = font(boyut)
        satirlar = satir_sar(draw, metin, fnt, azami_genislik)
        if len(satirlar) <= azami_satir:
            return fnt, satirlar
        boyut -= 4
    fnt = font(alt_boyut)
    return fnt, satir_sar(draw, metin, fnt, azami_genislik)


def konturlu_yazi(draw, xy, metin, fnt, dolgu, kontur=KONTUR, kalinlik=6, anchor="ma"):
    draw.text(xy, metin, font=fnt, fill=dolgu, anchor=anchor,
              stroke_width=kalinlik, stroke_fill=kontur)


def arka_plan(yol: Path | None) -> Image.Image:
    if yol and Path(yol).exists():
        im = Image.open(yol).convert("RGB")
        # 9:16 kırp-doldur
        oran = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * oran) + 1, int(im.height * oran) + 1), Image.LANCZOS)
        x = (im.width - W) // 2
        y = (im.height - H) // 2
        im = im.crop((x, y, x + W, y + H))
        return im.filter(ImageFilter.GaussianBlur(0.4))

    # arka plan yoksa: koyu lacivert degrade (şablon testi için)
    im = Image.new("RGB", (W, H), LACI)
    d = ImageDraw.Draw(im)
    for i in range(H):
        t = i / H
        d.line([(0, i), (W, i)], fill=(int(6 + 6 * t), int(24 + 14 * t), int(38 + 18 * t)))
    d.ellipse([(W * 0.10, H * 0.13), (W * 0.90, H * 0.53)], outline=(0, 120, 130), width=4)
    d.ellipse([(W * 0.18, H * 0.17), (W * 0.82, H * 0.49)], outline=(0, 90, 100), width=3)
    return im


def render(baslik: str, altyazi: str, kaynak: str, bg: Path | None) -> Image.Image:
    im = arka_plan(bg)
    d = ImageDraw.Draw(im)

    # ---- rozet + üst çizgi
    d.rounded_rectangle([72, 61, 275, 131], radius=35, fill=LIME)
    d.rectangle([72, 58, 173, 64], fill=LIME)
    d.rectangle([173, 59, 620, 62], fill=(52, 58, 64))
    rozet_font = font(34)
    d.text((173, 96), "BİLGİ DOZU", font=rozet_font, fill=LACI, anchor="mm")

    # ---- başlık (büyük harf, 2 satır)
    baslik = tr_upper(baslik)
    fnt, satirlar = sigdir(d, baslik, 980, 2, 84)
    y = 168
    for satir in satirlar:
        konturlu_yazi(d, (W // 2, y), satir, fnt, BEYAZ, kalinlik=7)
        y += int(fnt.size * 1.12)

    # ---- anlatım (2 satır)
    if altyazi:
        parcalar = [p.strip() for p in altyazi.split("|") if p.strip()]
        if len(parcalar) > 1:
            afnt = font(48)
            ay = 1330
            for p in parcalar[:2]:
                konturlu_yazi(d, (W // 2, ay), p, afnt, BEYAZ, kalinlik=6)
                ay += int(afnt.size * 1.18)
        else:
            afnt, asatirlar = sigdir(d, parcalar[0], 940, 2, 48, alt_boyut=36)
            ay = 1330
            for s in asatirlar:
                konturlu_yazi(d, (W // 2, ay), s, afnt, BEYAZ, kalinlik=6)
                ay += int(afnt.size * 1.18)

    # ---- alt kaynak + wordmark
    kfnt = font(27)
    d.text((288, 1738), "*Görseller temsilidir (AI bilimsel canlandırma)", font=kfnt, fill=GRI)
    if kaynak:
        d.text((288, 1772), f"Kaynak: {kaynak}", font=kfnt, fill=GRI)

    wfnt = font(52)
    sol = "BİLGİ "
    sag = "DOZU"
    genislik = d.textlength(sol + sag, font=wfnt)
    x0 = (W - genislik) / 2
    konturlu_yazi(d, (x0, 1862), sol, wfnt, BEYAZ, kalinlik=6, anchor="lm")
    d.text((x0 + d.textlength(sol, font=wfnt), 1862), sag, font=wfnt, fill=LIME,
           anchor="lm", stroke_width=6, stroke_fill=KONTUR)
    return im


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baslik", required=True)
    ap.add_argument("--altyazi", default="", help="'satır1|satır2' veya tek cümle")
    ap.add_argument("--kaynak", default="")
    ap.add_argument("--arka-plan", default="")
    ap.add_argument("--cikti", required=True)
    a = ap.parse_args()
    im = render(a.baslik, a.altyazi, a.kaynak, Path(a.arka_plan) if a.arka_plan else None)
    im.save(a.cikti)
    print(f"yazıldı: {a.cikti} ({im.width}x{im.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
