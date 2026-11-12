#!/usr/bin/env python3
"""Shorts kapak üretici — Bilgi Dozu standart dikey kapak şablonu (kapak_176..196 birebir uyumlu).

Kural: şablon kodda sabittir. Model/rastgelelik yok; sadece metin ve arka plan değişir.
Yerleşim (1080x1920):
  1) Sol üstte turkuaz çerçeveli 'B İ L G İ   D O Z U' kapsülü, sağ üstte aralıklı KATEGORİ
  2) Üstte 3 satırlı kalın Anton başlık (1-2. satır beyaz, 3. satır #FFD633 sarı)
  3) Başlığın hemen altında ortalanmış [• turkuaz] [━━ sarı çizgi ━━] [• turkuaz] ayırıcı
  4) Ortada/altta sinematik 9:16 dikey sahne görseli (yüz/konu net görünür)
  5) En altta 2 satırlı merak/mekanizma özeti (Poppins SemiBold, beyaz)
Çıktı: 1080x1920, JPEG baseline (progressive=False), kalite 90, subsampling=0, optimize=True.
"""
from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

MOTOR = Path(__file__).resolve().parent
ASSETS = MOTOR / "assets"

W, H = 1080, 1920
MARGIN_X = 62
MAX_TEXT_W = 936
BLOCK_TOP = 274
BLOCK_BOTTOM = 875
CAPTION_ALT = H - 134

BEYAZ = (255, 255, 255)
SARI = (255, 214, 51)          # #FFD633
TURKUAZ = (79, 227, 208)       # #4FE3D0
PUNTO_SABIT = 144
SATIR_ORANI = 1.12
KONTUR_ORANI = 0.055

_TR_UPPER_MAP = str.maketrans({"i": "İ", "ı": "I", "ğ": "Ğ", "ü": "Ü", "ş": "Ş", "ö": "Ö", "ç": "Ç"})


def tr_upper(metin: str) -> str:
    return unicodedata.normalize("NFC", str(metin or "")).translate(_TR_UPPER_MAP).upper()


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


def _vignette(guc: int = 108) -> Image.Image:
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


def _temiz_kelimeler(metin: str) -> list[str]:
    metin = re.sub(r"https?://\S+|#\S+", " ", str(metin or ""))
    korunan = []
    for ch in unicodedata.normalize("NFC", metin):
        kat = unicodedata.category(ch)
        if kat.startswith(("L", "N")) or ch in " ?!:'’.-%&":
            korunan.append(ch)
        else:
            korunan.append(" ")
    temiz = re.sub(r"\s+", " ", "".join(korunan)).strip()
    return tr_upper(temiz).split()


def uc_satir_baslik(baslik_veya_satirlar: str | list[str]) -> list[str]:
    """Başlığı kelime bölmeden dengeli 3 büyük harf satırına ayırır (1-2 beyaz, 3 sarı)."""
    if isinstance(baslik_veya_satirlar, list):
        ham = [re.sub(r"\s+", " ", tr_upper(x)).strip() for x in baslik_veya_satirlar if str(x or "").strip()]
        if 2 <= len(ham) <= 3 and all(len(s) <= 18 for s in ham):
            return ham

    metin = " ".join(baslik_veya_satirlar) if isinstance(baslik_veya_satirlar, list) else str(baslik_veya_satirlar or "")
    kelimeler = _temiz_kelimeler(metin)
    if not kelimeler:
        return ["BİLGİ DOZU", "BİLİMSEL", "GERÇEK!"]
    # Çok uzun başlığı en vurucu ilk 6-7 kelimeye daralt (ör. soru kökü korunur)
    soru_mu = any("?" in k for k in kelimeler)
    if len(kelimeler) > 7:
        kelimeler = kelimeler[:7]
        if soru_mu and not kelimeler[-1].endswith("?"):
            kelimeler[-1] = kelimeler[-1].rstrip(".,!:;") + "?"
    if len(kelimeler) == 1:
        return [kelimeler[0]]
    if len(kelimeler) == 2:
        return [kelimeler[0], kelimeler[1]]

    # 3 satıra en dengeli karakter dağılımını bul (bütün kelimelerle)
    en_iyi = None
    en_skor = 1e9
    n = len(kelimeler)
    for i in range(1, n - 1):
        for j in range(i + 1, n):
            s1 = " ".join(kelimeler[:i])
            s2 = " ".join(kelimeler[i:j])
            s3 = " ".join(kelimeler[j:])
            uzunluklar = [len(s1), len(s2), len(s3)]
            en_uzun = max(uzunluklar)
            fark = max(uzunluklar) - min(uzunluklar)
            # 16 karakter üstüne ağır ceza ver ki punto büyük ve okunaklı kalsın
            ceza = max(0, en_uzun - 16) * 18 + en_uzun * 2.2 + fark * 1.4
            if ceza < en_skor:
                en_skor = ceza
                en_iyi = [s1, s2, s3]
    return en_iyi or [" ".join(kelimeler[:2]), " ".join(kelimeler[2:4]), " ".join(kelimeler[4:])]


def kategori_etiketi_sec(konu: str, ham_kategori: str = "") -> str:
    """Sağ üst köşe için standart kısa Bilgi Dozu kategori etiketi üretir."""
    birlesik = tr_upper(f"{ham_kategori} {konu}")
    if any(k in birlesik for k in ("BEYİN", "NÖRO", "ZİHİN", "UYKU", "RÜYA", "HAFIZA", "PSİKO", "GÖZ", "GÖRME", "KÖR", "RETİNA", "RODOPSİN", "SİNİR")):
        return "NÖROBİLİM"
    if any(k in birlesik for k in ("VÜCUT", "KAS", "KAN", "KALP", "MİDE", "DERİ", "PARMAK", "FİZYOLOJİ", "TIP", "İNSAN", "BAĞIŞIK")):
        return "İNSAN & BİLİM"
    if any(k in birlesik for k in ("UZAY", "EVREN", "KARA DELİK", "GEZEGEN", "GÜNEŞ", "AY ", "YILDIZ", "ASTRONOMİ")):
        return "UZAY & EVREN"
    if any(k in birlesik for k in ("TARİH", "ANTİK", "ROMA", "MISIR", "PİRAMİT", "ARKEOLOJİ", "HEYKEL")):
        return "TARİH & BİLİM"
    if any(k in birlesik for k in ("HAYVAN", "OKYANUS", "DENİZ", "DOĞA", "BİTKİ", "AĞAÇ", "BALIK", "KUŞ")):
        return "DOĞA & BİLİM"
    return "FİZİK & BİLİM"


def alt_aciklama_hazirla(konu_ozeti: str = "", aciklama: str = "") -> str:
    """Alt bant için fiili kesmeden tam cümle halinde 2-3 satırlık özet hazırlar."""
    aday = str(konu_ozeti or "").strip() or str(aciklama or "").split("\n")[0].strip()
    aday = re.sub(r"https?://\S+|#\S+", "", aday)
    aday = re.sub(r"\s+", " ", aday).strip()
    if not aday:
        return ""
    if len(aday) > 165:
        cumleler = [c.strip() for c in re.split(r"(?<=[.!?])\s+", aday) if c.strip()]
        if cumleler and len(cumleler[0]) <= 165:
            aday = cumleler[0]
        elif "," in aday:
            parca = aday.split(",", 1)[1].strip()
            if 30 <= len(parca) <= 165:
                aday = parca[0].upper() + parca[1:]
    return aday


def kapak_metni_hazirla(konu: str, sahneler: list[dict] | None = None, metadata: dict | None = None) -> dict:
    """Motor çıktısından standart kapak alanlarını (3 satır başlık, kategori, alt açıklama) üretir."""
    md = metadata or {}
    ham_satirlar = md.get("kapak_satirlari")
    kaynak_baslik = ham_satirlar if isinstance(ham_satirlar, list) and len(ham_satirlar) >= 2 else (md.get("baslik") or konu)
    satirlar = uc_satir_baslik(kaynak_baslik)
    kategori = kategori_etiketi_sec(
        f"{konu} {md.get('aciklama') or ''}",
        str(md.get("kapak_kategori") or md.get("kategori") or ""),
    )
    alt = alt_aciklama_hazirla(
        str(md.get("kapak_alt") or md.get("konu_ozeti") or ""),
        str(md.get("aciklama") or ""),
    )
    if not alt and sahneler and len(sahneler) >= 2:
        alt = alt_aciklama_hazirla(str(sahneler[1].get("ses") or ""))
    return {"satirlar": satirlar, "kategori": kategori, "alt_aciklama": alt}


def _satirlar(draw, satirlar, punto, ust, alt) -> list[tuple[ImageFont.FreeTypeFont, str, tuple, int]]:
    """Satırları sığacak puntoya indirip ortalanmış yerleşim üretir."""
    satirlar = [tr_upper(s) for s in satirlar if str(s or "").strip()]
    while punto > 48:
        f = _font("Anton-Regular.ttf", punto)
        genislikler = [draw.textbbox((0, 0), s, font=f)[2] - draw.textbbox((0, 0), s, font=f)[0] for s in satirlar]
        satir_h = int(punto * SATIR_ORANI)
        toplam_h = satir_h * len(satirlar)
        if max(genislikler) <= MAX_TEXT_W and (ust + toplam_h) <= alt:
            break
        punto -= 4
    f = _font("Anton-Regular.ttf", punto)
    satir_h = int(punto * SATIR_ORANI)
    yerlesim = []
    for i, s in enumerate(satirlar):
        bb = draw.textbbox((0, 0), s, font=f)
        w = bb[2] - bb[0]
        yerlesim.append((f, s, (W // 2 - w // 2 - bb[0], ust + i * satir_h), punto))
    return yerlesim


def kapak_uret(arka_plan: str | Path, cikti: str | Path, *,
               satirlar: list[str], vurgu_satiri: int | None = None,
               kategori: str = "FİZİK & BİLİM", alt_aciklama: str = "") -> Path:
    """Tek kapak üretir. `vurgu_satiri` verilmezse son satır sarı olur."""
    cikti = Path(cikti)
    cikti.parent.mkdir(parents=True, exist_ok=True)
    satirlar = uc_satir_baslik(satirlar)

    bg = Image.open(arka_plan).convert("RGB")
    bg = ImageOps.fit(bg, (W, H), Image.LANCZOS, centering=(0.5, 0.5))
    bg = ImageEnhance.Color(bg).enhance(1.12)
    bg = ImageEnhance.Contrast(bg).enhance(1.10)
    tuval = bg.convert("RGBA")

    tuval.alpha_composite(_gradyan(0, 920, 0.92, 0.0))
    tuval.alpha_composite(_gradyan(1320, H, 0.0, 0.88))
    tuval.alpha_composite(_vignette(108))

    d = ImageDraw.Draw(tuval)

    # --- 1) Logo kapsülü (sol üst — kapak_176..196 ile birebir)
    logo = "B İ L G İ   D O Z U"
    lf = _font("Poppins-SemiBold.ttf", 33)
    kutu = d.textbbox((0, 0), logo, font=lf)
    lw, lh = kutu[2] - kutu[0], kutu[3] - kutu[1]
    px, py = MARGIN_X, 78
    pill_w, pill_h = lw + 52, lh + 28
    d.rounded_rectangle([px, py, px + pill_w, py + pill_h], radius=pill_h // 2,
                        fill=(4, 16, 20, 195), outline=TURKUAZ + (185,), width=2)
    d.text((px + 26, py + 14 - kutu[1]), logo, font=lf, fill=TURKUAZ)

    # --- 2) Kategori (sağ üst — Türkçe büyük harf, aralıklı)
    if kategori:
        kf = _font("Poppins-Medium.ttf", 30)
        kat = " ".join(tr_upper(kategori))
        kw = d.textbbox((0, 0), kat, font=kf)[2]
        d.text((W - MARGIN_X - kw, 100), kat, font=kf, fill=(230, 244, 244, 212))

    # --- 3) 3 satır kalın başlık bloğu (1-2 beyaz, 3 sarı)
    vurgu = vurgu_satiri if vurgu_satiri is not None else len(satirlar) - 1
    yerlesim = _satirlar(d, satirlar, PUNTO_SABIT, BLOCK_TOP, BLOCK_BOTTOM)
    son_alt_y = BLOCK_TOP
    for i, (f, s, (x, y), punto) in enumerate(yerlesim):
        renk = SARI if i == vurgu else BEYAZ
        stroke = max(2, int(punto * KONTUR_ORANI))
        golge = Image.new("RGBA", tuval.size, (0, 0, 0, 0))
        ImageDraw.Draw(golge).text((x, y + 8), s, font=f, fill=(0, 0, 0, 175))
        tuval.alpha_composite(golge.filter(ImageFilter.GaussianBlur(14)))
        d = ImageDraw.Draw(tuval)
        d.text((x, y), s, font=f, fill=renk, stroke_width=stroke, stroke_fill=(3, 10, 14, 240))
        bb_real = d.textbbox((x, y), s, font=f)
        son_alt_y = max(son_alt_y, bb_real[3])

    # --- 4) Ortalanmış ayırıcı (başlığın hemen altında: [• turkuaz] [━━ sarı ━━] [• turkuaz])
    cy = min(940, son_alt_y + 58)
    bar_w = 132
    bar_x0 = W // 2 - bar_w // 2
    dot_r = 7
    gap = 20
    # Sol turkuaz nokta (x=440..454)
    lx = bar_x0 - gap - dot_r * 2
    d.ellipse([lx, cy - 3, lx + dot_r * 2, cy + 11], fill=TURKUAZ + (220,))
    # Orta sarı çubuk (x=474..606)
    d.rounded_rectangle([bar_x0, cy, bar_x0 + bar_w, cy + 7], radius=4, fill=SARI + (242,))
    # Sağ turkuaz nokta (x=626..640)
    rx = bar_x0 + bar_w + gap
    d.ellipse([rx, cy - 3, rx + dot_r * 2, cy + 11], fill=TURKUAZ + (220,))

    # --- 5) Alt açıklama (en fazla 2-3 satır, beyaz okunaklı özet)
    if alt_aciklama:
        punto = 39
        satirlar_c = []
        while punto >= 27:
            cf = _font("Poppins-SemiBold.ttf", punto)
            satirlar_c = _sar(d, alt_aciklama, cf, MAX_TEXT_W)
            if len(satirlar_c) <= 2 or (punto <= 31 and len(satirlar_c) <= 3):
                break
            punto -= 2
        cf = _font("Poppins-SemiBold.ttf", punto)
        satir_h = int(punto * 1.44)
        toplam = satir_h * len(satirlar_c)
        ust = CAPTION_ALT - toplam + punto

        kutu_kat = Image.new("RGBA", tuval.size, (0, 0, 0, 0))
        kd = ImageDraw.Draw(kutu_kat)
        for i, s in enumerate(satirlar_c):
            w = kd.textbbox((0, 0), s, font=cf)[2]
            x = W // 2 - w // 2
            y = ust + i * satir_h
            kd.text((x, y), s, font=cf, fill=(3, 12, 16, 150),
                    stroke_width=max(8, punto // 3), stroke_fill=(3, 12, 16, 150))
        tuval.alpha_composite(kutu_kat.filter(ImageFilter.GaussianBlur(10)))

        d = ImageDraw.Draw(tuval)
        for i, s in enumerate(satirlar_c):
            w = d.textbbox((0, 0), s, font=cf)[2]
            d.text((W // 2 - w // 2, ust + i * satir_h), s, font=cf,
                   fill=(240, 249, 249, 246), stroke_width=2, stroke_fill=(0, 0, 0, 185))

    sonuc = tuval.convert("RGB")
    sonuc.save(cikti, "JPEG", quality=90, subsampling=0, optimize=True, progressive=False)
    return cikti


def _sar(draw, metin: str, font, azami: int) -> list[str]:
    kelimeler = str(metin or "").split()
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
               kategori="İNSAN & BİLİM",
               alt_aciklama="Su emmiyoruz: sinir sistemin su altında tutuşu otomatik artırıyor.")
    print(cikti)
