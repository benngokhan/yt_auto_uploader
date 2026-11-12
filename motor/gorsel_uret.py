#!/usr/bin/env python3
"""Sahne görselleri — Pexels (birincil, küratörlü dikey) + Pixabay (yedek) + Anti-Ham Sinematik İşleme.

Karar (kullanıcı):
    * Görseller öncelikle Pexels API'den (orientation=portrait, yüksek çözünürlük) çekilir;
      Pexels'te bulunamayan niş terimlerde Pixabay yedek olarak devreye girer.
    * Ham / düz stok fotoğraf, beyaz stüdyo kesimi (isolated cutout), bulanık veya patlamış
      ışıklı görsel videoya GİREMEZ: hem etiket/renk puanlamasında hem indirme sonrası
      piksel denetiminde (_ham_kusurlu_mu) elenir.
    * Kabul edilen her görsel 9:16 dikey kadraj + Bilgi Dozu koyu teal-amber sinematik
      renk düzenlemesi + pozlama dengeleme + mikro-parçacık derinliği ile işlenir.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

HEDEF = (1350, 2400)  # Tam 9:16 dikey, Ken Burns zoom için yüksek keskinlik
PEXELS_URL = "https://api.pexels.com/v1/search"
PIXABAY_URL = "https://pixabay.com/api/"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _istek(url: str, ek_baslik: dict | None = None, saglayici: str = "Görsel API") -> dict:
    basliklar = {"User-Agent": _UA, "Accept": "application/json"}
    if ek_baslik:
        basliklar.update(ek_baslik)
    son_hata: Exception | None = None
    for bekle in (0, 2, 5):
        if bekle:
            time.sleep(bekle)
        istek = urllib.request.Request(url, headers=basliklar)
        try:
            with urllib.request.urlopen(istek, timeout=60) as y:
                return json.loads(y.read().decode("utf-8"))
        except urllib.error.HTTPError as hata:
            son_hata = hata
            if hata.code in (429, 500, 502, 503, 504):
                continue
            govde = ""
            try:
                govde = hata.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise SystemExit(f"{saglayici} isteği başarısız (HTTP {hata.code}): {govde}") from hata
        except Exception as hata:  # noqa: BLE001
            son_hata = hata
            continue
    govde = ""
    if hasattr(son_hata, "read"):
        try:
            govde = son_hata.read().decode("utf-8", "replace")[:300]  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    raise SystemExit(f"{saglayici} isteği başarısız: {son_hata} | {govde}") from son_hata


def _pexels_slug_kelimeler(url: str) -> str:
    """Pexels URL'sindeki açıklayıcı İngilizce başlığı çıkarır."""
    m = re.search(r"/photo/([a-z0-9-]+?)(?:-\d+)?/?$", str(url or "").lower())
    if not m:
        return ""
    kelimeler = [k for k in m.group(1).split("-") if k and not k.isdigit()]
    return " ".join(kelimeler)


def _avg_parlaklik(hex_renk: str) -> float | None:
    """'#RRGGBB' ortalama parlaklığını (0..255) döndürür."""
    h = str(hex_renk or "").strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return 0.299 * r + 0.587 * g + 0.114 * b
    except ValueError:
        return None


# Alaka ölçümünde sayılmayan süs/sanat kelimeleri.
_SUS_KELIMELER = {
    "macro", "close", "closeup", "photography", "photo", "documentary",
    "cinematic", "shot", "view", "style", "light", "lighting", "nature",
    "background", "wallpaper", "beautiful", "abstract", "concept", "dance",
    "dancing", "communication", "collection", "process", "dark", "studio",
    "vertical", "selective", "focus", "high", "resolution",
    "texture", "textures", "textured", "surface", "pattern", "patterns",
    "structure", "material", "object", "detail", "details", "detailed",
}

# Video konusundan bağımsız, ASLA istenmeyen görsel türleri + ham katalog/vektör/yazı/gündelik stok terimleri.
_YASAK_ETIKET_KESIN = {
    "portrait", "model", "girl", "boy", "beauty", "glamour", "hanói", "hanoi", "vietnamese",
    "selfie", "smile", "fashion", "makeup", "tea", "coffee", "drink", "cup", "wine", "beer",
    "food", "dish", "car", "motorcycle", "wedding", "couple", "bikini", "lingerie",
    "cleaner", "vacuuming", "cleaning", "delivery", "cardboard", "trolley", "subway", "businessman",
    "businesswoman", "texting", "denim", "jeans", "casual", "influencer", "blogger", "outfit", "streetwear",
    "isolated", "cutout", "mockup", "template", "banner", "poster", "signboard", "watermark",
    "collage", "infographic", "diagram", "cartoon", "vector", "illustration", "sketch", "drawing",
    "clipart", "mannequin", "shopping", "sale", "discount",
    "crumpled", "paper", "cosmetic", "cosmetics", "skincare", "serum", "lotion", "cream",
    "perfume", "twine", "burlap", "citrus", "orange", "lemon", "blinds", "curtain", "curtains",
}
_YASAK_IFADELER = (
    "white background",
    "isolated on white",
    "blank sign",
    "empty board",
    "copy space",
    "text space",
)
_BILIM_MAKRO_BONUS = {
    "macro", "closeup", "microscope", "laboratory", "science", "scientific", "optical",
    "lens", "anatomy", "iris", "pupil", "crystal", "droplet", "droplets", "prism",
    "laser", "medical", "thermometer", "molecular", "neuron", "glowing", "frost",
}
_INSAN_ANATOMI = {
    "hand", "hands", "finger", "fingers", "thumb", "palm", "skin", "eye", "eyes",
    "brain", "ear", "ears", "heart", "blood", "muscle", "bone", "skeleton", "sleep",
    "sleeping", "face", "mouth", "tongue", "nose", "human", "nerve", "body",
}


def _kelimeler(metin: str, sus_at: bool = True) -> set[str]:
    k = {x for x in re.split(r"[^\wçğıöşü]+", str(metin or "").lower()) if len(x) >= 3}
    return {x for x in k if x not in _SUS_KELIMELER} if sus_at else k


def _yasak_etiket_seti(sorgu: str, ana_konu: str) -> set[str]:
    tum = _kelimeler(f"{sorgu} {ana_konu}", sus_at=False)
    if tum & _INSAN_ANATOMI:
        return _YASAK_ETIKET_KESIN
    return _YASAK_ETIKET_KESIN | {"girl", "boy", "woman", "man"}


def _puanla(hit: dict, sorgu: str) -> float:
    """Etiket/açıklama uyumu + dikey kadraj + çözünürlük + kaynak kalitesi → alaka puanı."""
    q = _kelimeler(sorgu.replace("+", " "), sus_at=True)
    etiketler = _kelimeler(hit.get("tags", ""), sus_at=False)
    ortak = len(q & etiketler)
    # Çoğul/tekil kök uyumu (droplet <-> droplets, finger <-> fingers)
    ek_kok = 0
    if q and etiketler:
        kalan_q = q - etiketler
        kok_q = {w[:4] for w in kalan_q if len(w) >= 4}
        kok_e = {w[:4] for w in etiketler if len(w) >= 4}
        ek_kok = len(kok_q & kok_e)

    puan = ortak * 10.0 + ek_kok * 4.0
    w = int(hit.get("imageWidth") or 0)
    h = int(hit.get("imageHeight") or 0)
    puan += min(4.0, (w * h) / 6_000_000)
    puan += min(3.0, (hit.get("likes", 0) + hit.get("downloads", 0) / 50.0) / 100.0)

    if hit.get("kaynak") == "pexels":
        puan += 4.5  # Küratörlü editoryal fotoğraf önceliği

    if h > w:
        puan += 4.5
        if w > 0 and (h / w) >= 1.32:
            puan += 2.5
    elif w > 0 and (w / max(h, 1)) > 1.45:
        puan -= 3.5  # Yatay geniş açılı görsellerde kırpma kaybı olur

    if min(w, h) >= 1080 and max(w, h) >= 1600:
        puan += 2.5

    # Makro / bilimsel editoryal fotoğraf bonusu
    if etiketler & _BILIM_MAKRO_BONUS:
        puan += 3.5

    # Sorguda el/telefon tutma istenmediği halde "hand holding smartphone" stok klişelerini ağır cezalandır
    ham_alt = str(hit.get("tags", "")).lower()
    sorgu_ham = _kelimeler(sorgu, sus_at=False)
    if not (sorgu_ham & {"hand", "hands", "finger", "fingers", "palm", "holding"}):
        if any(k in ham_alt for k in ("holding a mobile", "holding a smart", "hands holding", "hand holding", "using a smart")):
            puan -= 14.0

    # Beyaz stüdyo arka planlı ham katalog görsellerini ağır cezalandır
    par = _avg_parlaklik(hit.get("avg_color", ""))
    if par is not None:
        if par > 228:
            puan -= 20.0
        elif 35 <= par <= 165:
            puan += 1.8

    if str(hit.get("type", "photo")) != "photo":
        puan -= 25.0
    return puan


def pexels_ara(sorgu: str, anahtar: str, adet: int = 40) -> list[dict]:
    """Pexels API üzerinden dikey ve yüksek çözünürlüklü fotoğrafları puana göre döndürür."""
    baslik = {"Authorization": anahtar}
    sonuclar: dict[int, dict] = {}
    for ek in (
        {"orientation": "portrait", "size": "large"},
        {"size": "large"},
    ):
        param = {
            "query": sorgu,
            "per_page": str(min(adet, 80)),
            "locale": "en-US",
            **ek,
        }
        try:
            veri = _istek(f"{PEXELS_URL}?{urllib.parse.urlencode(param)}", baslik, saglayici="Pexels")
        except SystemExit:
            if sonuclar:
                break
            raise
        for p in veri.get("photos", []):
            pid = p.get("id")
            src = p.get("src") or {}
            indir_url = (
                src.get("original")
                or src.get("large2x")
                or src.get("portrait")
                or src.get("large")
                or ""
            )
            if not pid or not indir_url:
                continue
            alt_birlesik = f"{p.get('alt') or ''} {_pexels_slug_kelimeler(p.get('url') or '')}".strip()
            sonuclar.setdefault(
                int(pid),
                {
                    "uid": f"pexels:{pid}",
                    "kaynak": "pexels",
                    "id": int(pid),
                    "imageWidth": int(p.get("width") or 0),
                    "imageHeight": int(p.get("height") or 0),
                    "tags": alt_birlesik or sorgu,
                    "type": "photo",
                    "avg_color": str(p.get("avg_color") or ""),
                    "likes": 120,
                    "downloads": 4000,
                    "indir_url": indir_url,
                },
            )
        if len(sonuclar) >= 8:
            break
    return sorted(sonuclar.values(), key=lambda h: _puanla(h, sorgu), reverse=True)


def pixabay_ara(sorgu: str, anahtar: str, adet: int = 60) -> list[dict]:
    """Pixabay yedek fotoğraf araması."""
    temel = {
        "key": anahtar,
        "q": sorgu,
        "image_type": "photo",
        "safesearch": "true",
        "order": "popular",
        "per_page": str(min(adet, 200)),
        "lang": "en",
    }
    sonuclar: dict[int, dict] = {}
    for ek in (
        {"orientation": "vertical", "min_width": 1400, "min_height": 1400},
        {"min_width": 1200, "min_height": 900},
    ):
        try:
            veri = _istek(f"{PIXABAY_URL}?{urllib.parse.urlencode({**temel, **ek})}", saglayici="Pixabay")
        except SystemExit:
            if sonuclar:
                break
            raise
        for h in veri.get("hits", []):
            hid = h.get("id")
            indir_url = h.get("fullHDURL") or h.get("largeImageURL") or ""
            if not hid or not indir_url:
                continue
            kopya = dict(h)
            kopya["uid"] = f"pixabay:{hid}"
            kopya["kaynak"] = "pixabay"
            kopya["indir_url"] = indir_url
            sonuclar.setdefault(int(hid), kopya)
        if len(sonuclar) >= 8:
            break
    return sorted(sonuclar.values(), key=lambda h: _puanla(h, sorgu), reverse=True)


def _sorgu_adaylari(sahne: dict, yedek: list[str], ana_konu: str, sahne_sirasi: int = 0) -> list[str]:
    """Sahnenin kendi somut nesnesini DAİMA en başta arar; genel yedekler yalnızca en sonda denenir."""
    def _temiz(x: str) -> str:
        return " ".join(str(x or "").replace(",", " ").split())

    soyut = {
        "communication", "communicate", "dance", "dancing", "waggle",
        "collection", "process", "concept", "how", "why", "secret",
    }

    def _somut(x: str) -> str:
        return " ".join(w for w in _temiz(x).split() if w.lower() not in soyut)

    detay = _somut(sahne.get("gorsel"))
    anahtar = _somut(sahne.get("gorsel_anahtar") or "")
    alternatif = _somut(sahne.get("gorsel_alternatif") or "")
    anchor = _somut(ana_konu)

    cekirdek = anahtar or detay
    adaylar: list[str] = []
    if cekirdek:
        adaylar.append(cekirdek)
        oz_kelimeler = [w for w in cekirdek.split() if w.lower() not in _SUS_KELIMELER]
        if len(oz_kelimeler) >= 2 and " ".join(oz_kelimeler[-2:]).lower() != cekirdek.lower():
            adaylar.append(" ".join(oz_kelimeler[-2:]))
    if detay and detay != cekirdek:
        adaylar.append(detay)
    if alternatif and alternatif != cekirdek:
        adaylar.append(alternatif)
        alt_oz = [w for w in alternatif.split() if w.lower() not in _SUS_KELIMELER]
        if len(alt_oz) >= 2 and " ".join(alt_oz[-2:]).lower() != alternatif.lower():
            adaylar.append(" ".join(alt_oz[-2:]))
    if cekirdek and anchor and cekirdek.lower()[:18] not in anchor.lower():
        adaylar.append(f"{cekirdek} {anchor}")

    # Genel konu yedekleri YALNIZCA sahnenin kendi sorguları sonuç vermezse en sonda denenir
    temiz_yedek = [_temiz(y) for y in yedek if _temiz(y)]
    if temiz_yedek:
        kaydir = sahne_sirasi % len(temiz_yedek)
        adaylar += temiz_yedek[kaydir:] + temiz_yedek[:kaydir]

    gorulen: set[str] = set()
    sonuc: list[str] = []
    for a in adaylar:
        anahtar_kelime = " ".join(sorted({k.lower() for k in a.split()}))
        if not anahtar_kelime or anahtar_kelime in gorulen:
            continue
        gorulen.add(anahtar_kelime)
        sonuc.append(a)
    return sonuc[:8]


def _yeterince_uygun(hit: dict, sorgu: str, ana_konu: str, gevsek: bool = False) -> bool:
    """Görsel gerçekten sahnenin ana nesnesini gösteriyor ve ham kusur taşımıyor mu?"""
    ham_etiket = str(hit.get("tags", "")).lower()
    if any(ifade in ham_etiket for ifade in _YASAK_IFADELER):
        return False
    etiketler = _kelimeler(ham_etiket, sus_at=False)
    if not etiketler:
        return False
    if etiketler & _yasak_etiket_seti(sorgu, ana_konu):
        return False
    if str(hit.get("type", "photo")) != "photo":
        return False
    par = _avg_parlaklik(hit.get("avg_color", ""))
    if not gevsek and par is not None and par > 232:
        return False

    cekirdek = _kelimeler(sorgu) or _kelimeler(ana_konu)
    if not cekirdek:
        return _puanla(hit, sorgu) >= 4.0

    ortak = len(cekirdek & etiketler)
    kok_ortak = 0
    if ortak == 0:
        kok_c = {w[:4] for w in cekirdek if len(w) >= 4}
        kok_e = {w[:4] for w in etiketler if len(w) >= 4}
        kok_ortak = len(kok_c & kok_e)

    if gevsek:
        return (ortak + kok_ortak) >= 1 and _puanla(hit, sorgu) >= 3.5

    # Pexels alt metinlerinde çoğul/tekil farkı sık olduğundan kök eşleşmesini katı modda da tanı
    etkin_ortak = ortak + (1 if kok_ortak >= 1 and hit.get("kaynak") == "pexels" else 0)
    gerekli = 1 if len(cekirdek) <= 4 else 2
    return etkin_ortak >= gerekli and _puanla(hit, sorgu) >= 5.5


def _ham_kusurlu_mu(im: Image.Image) -> tuple[bool, str]:
    """İndirilen ham görseli piksel düzeyinde denetler:
    beyaz stüdyo kesimi, düz clipart arka planı, aşırı patlamış ışık veya bulanıklığı eler."""
    en, boy = im.size
    if min(en, boy) < 700:
        return True, f"cozunurluk_dusuk({en}x{boy})"

    kucuk = np.asarray(im.convert("RGB").resize((270, 480), Image.BILINEAR), dtype=np.float32)
    h, w, _ = kucuk.shape
    b_y, b_x = max(8, int(h * 0.06)), max(8, int(w * 0.06))
    kenar = np.concatenate(
        [
            kucuk[:b_y, :, :].reshape(-1, 3),
            kucuk[-b_y:, :, :].reshape(-1, 3),
            kucuk[:, :b_x, :].reshape(-1, 3),
            kucuk[:, -b_x:, :].reshape(-1, 3),
        ],
        axis=0,
    )
    beyaz_oran = float(np.mean((kenar[:, 0] > 238) & (kenar[:, 1] > 238) & (kenar[:, 2] > 238)))
    if beyaz_oran > 0.30:
        return True, f"beyaz_studyo_kesim({beyaz_oran:.2f})"

    kenar_std = float(np.std(kenar))
    if kenar_std < 4.2:
        return True, f"duz_yapay_arkaplan(std={kenar_std:.1f})"

    luma = (0.299 * kucuk[..., 0] + 0.587 * kucuk[..., 1] + 0.114 * kucuk[..., 2]) / 255.0
    patlak_oran = float(np.mean(luma > 0.95))
    if patlak_oran > 0.34:
        return True, f"patlamis_isik({patlak_oran:.2f})"

    gri = luma * 255.0
    keskinlik = float(np.mean(np.abs(np.diff(gri, axis=1))) + np.mean(np.abs(np.diff(gri, axis=0))))
    if keskinlik < 2.1:
        return True, f"bulanik_gorsel({keskinlik:.2f})"

    return False, "ok"


def dikey_kirp(img: Image.Image) -> Image.Image:
    """9:16 dikey kadraj (1350x2400).
    Dikey/kareye yakın fotoğrafları akıllı merkez kırpar;
    nadir yatay yedeklerde konuyu %70 kesmek yerine atmosferik koyu-teal zemin üzerine yumuşak yedirir."""
    im = img.convert("RGB")
    en, boy = im.size
    hedef_w, hedef_h = HEDEF
    hedef_oran = hedef_h / hedef_w  # 1.777...

    if (en / max(boy, 1)) > 1.22:
        # Yatay fotoğraf: konuyu parçalamadan sinematik atmosferli dikey tuvale yerleştir
        arka = im.resize((hedef_w, hedef_h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(42))
        arka_np = np.asarray(arka, dtype=np.float32) * 0.28 + np.array([8.0, 18.0, 24.0], dtype=np.float32)
        tuval = np.clip(arka_np, 0, 255)

        ic_h = int(hedef_h * 0.78)
        ic_w = max(hedef_w, int(en * (ic_h / max(boy, 1))))
        on = im.resize((ic_w, ic_h), Image.LANCZOS)
        sol = (ic_w - hedef_w) // 2
        on_kirp = np.asarray(on.crop((sol, 0, sol + hedef_w, ic_h)), dtype=np.float32)

        maske = np.ones((ic_h, hedef_w, 1), dtype=np.float32)
        gecis = int(ic_h * 0.14)
        ust_egri = (np.linspace(0.0, 1.0, gecis, dtype=np.float32) ** 1.45)[:, None, None]
        maske[:gecis] = ust_egri
        maske[-gecis:] = ust_egri[::-1]

        y0 = (hedef_h - ic_h) // 2
        tuval[y0 : y0 + ic_h] = tuval[y0 : y0 + ic_h] * (1.0 - maske) + on_kirp * maske
        return Image.fromarray(np.clip(tuval, 0, 255).astype(np.uint8))

    if en / boy > 1.0 / hedef_oran:
        yeni_en = int(boy / hedef_oran)
        sol = (en - yeni_en) // 2
        im = im.crop((sol, 0, sol + yeni_en, boy))
    else:
        yeni_boy = int(en * hedef_oran)
        # Dikey portre/nesne çekimlerinde odak genelde üst-orta bölgededir (%45)
        ust = int((boy - yeni_boy) * 0.45)
        im = im.crop((0, ust, en, ust + yeni_boy))
    return im.resize(HEDEF, Image.LANCZOS)


def sinematik_isle(img: Image.Image, tohum: int = 20261112) -> Image.Image:
    """Ham fotoğrafı sablon_v2 (video_187..196) doğal editoryal netliğine hazırlar.

    Kurallar:
      - Turuncu/mavi yapay boyama (orange skin crush) ve yapay bokeh benekleri KESİNLİKLE YOKTUR.
      - Normal/dengeli pozlamalı fotoğrafların orta kadraj parlaklığı ve doğal rengi %100 korunur
        (üst/alt yazı okuma vinyetini shorts_pipeline.prepare_fullscreen_plate tek geçişte uygular).
      - Yalnızca aşırı patlak çiğ gündüz çekimlerinde (ort_lum > 0.52) parlak tavan dengelenir.
    """
    _ = tohum
    im = img.convert("RGB")
    a = np.asarray(im, dtype=np.float32) / 255.0

    lum0 = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    ort_lum = float(lum0.mean())
    if ort_lum > 0.52:
        gamma = float(np.clip(1.0 + (ort_lum - 0.42) * 1.65, 1.0, 1.58))
        a = np.power(np.clip(a, 0.0, 1.0), gamma)
        fazla = np.maximum(0.0, a - 0.64)
        a = a - 0.25 * fazla
        h, w, _ = a.shape
        yy, xx = np.mgrid[0:h, 0:w]
        nx = (xx - w / 2.0) / (w / 2.0)
        ny = (yy - h / 2.0) / (h / 2.0)
        vig = np.clip(1.02 - 0.18 * (nx * nx + ny * ny), 0.78, 1.0)[..., None]
        a = np.clip(a * vig, 0.0, 1.0)
    elif ort_lum < 0.13:
        a = np.power(np.clip(a, 0.0, 1.0), 0.85)

    out = Image.fromarray((np.clip(a, 0.0, 1.0) * 255.0).astype(np.uint8))
    out = ImageEnhance.Color(out).enhance(1.04)
    out = ImageEnhance.Contrast(out).enhance(1.04)
    out = out.filter(ImageFilter.UnsharpMask(radius=1.5, percent=85, threshold=3))
    return out


def _indir(url: str, hedef: Path) -> None:
    son_hata: Exception | None = None
    for bekle in (0, 2, 4):
        if bekle:
            time.sleep(bekle)
        istek = urllib.request.Request(url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(istek, timeout=120) as y:
                hedef.write_bytes(y.read())
                return
        except Exception as hata:  # noqa: BLE001
            son_hata = hata
    raise SystemExit(f"Görsel indirilemedi ({url[:90]}): {son_hata}") from son_hata


def _adaylardan_indir_ve_dogrula(
    adaylar: list[dict],
    sorgu: str,
    ham_dosya: Path,
    kullanilan: set[str],
    siki_piksel: bool = True,
) -> tuple[str, dict] | None:
    """Sıralı adaylardan ilk piksel-temiz görseli indirip doğrular."""
    for hit in adaylar[:4]:
        uid = str(hit.get("uid") or f"{hit.get('kaynak', 'stok')}:{hit['id']}")
        if uid in kullanilan:
            continue
        indir_url = str(hit.get("indir_url") or hit.get("fullHDURL") or hit.get("largeImageURL") or "")
        if not indir_url:
            continue
        try:
            _indir(indir_url, ham_dosya)
            with Image.open(ham_dosya) as im:
                im.load()
                if siki_piksel:
                    kusurlu, neden = _ham_kusurlu_mu(im)
                    if kusurlu:
                        print(f"    [anti-ham elendi] {uid} ({neden}) — sonraki adaya geçiliyor")
                        ham_dosya.unlink(missing_ok=True)
                        continue
            return (sorgu, hit)
        except SystemExit:
            ham_dosya.unlink(missing_ok=True)
            continue
        except Exception as e:  # noqa: BLE001
            print(f"    [görsel okuma uyarısı] {uid}: {e}")
            ham_dosya.unlink(missing_ok=True)
            continue
    return None


def sahneler_icin_gorseller(
    sahneler: list[dict],
    klasor: Path,
    yedek_sorgular: list[str] | None = None,
) -> list[Path]:
    """Her sahne için Pexels (birincil) / Pixabay (yedek) üzerinden görsel indirir,
    anti-ham piksel denetiminden geçirir ve sinematik 9:16 PNG olarak kaydeder."""
    pexels_key = (
        os.getenv("PEXELS_API_KEY")
        or os.getenv("PEXELS_KEY")
        or os.getenv("PEXELS_API")
        or ""
    ).strip()
    pixabay_key = os.getenv("PIXABAY_API_KEY", "").strip()

    if not pexels_key and not pixabay_key:
        raise SystemExit("PEXELS_API_KEY (veya PIXABAY_API_KEY) yok — görseller indirilemedi, üretim durdu.")

    saglayicilar: list[tuple[str, str, object]] = []
    if pexels_key:
        saglayicilar.append(("pexels", pexels_key, pexels_ara))
    if pixabay_key:
        saglayicilar.append(("pixabay", pixabay_key, pixabay_ara))

    aktif_adlar = " -> ".join(ad for ad, _, _ in saglayicilar)
    print(f"Görsel sağlayıcı sırası: {aktif_adlar} (anti-ham piksel filtresi + koyu sinematik işleme aktif)")

    klasor.mkdir(parents=True, exist_ok=True)
    yedek = yedek_sorgular or []

    kullanilan: set[str] = set()
    kullanilan_sorgular: set[str] = set()
    yollar: list[Path] = []
    ana_konu = str((sahneler[0] if sahneler else {}).get("gorsel") or "").strip()

    for i, sahne in enumerate(sahneler, start=1):
        secim: tuple[str, dict] | None = None
        denenen: list[str] = []
        ham = klasor / f"ham_{i:02d}.jpg"
        ham_aday_sorgular = _sorgu_adaylari(sahne, yedek, ana_konu, sahne_sirasi=i - 1)
        # Daha önce başka bir sahnede seçilmiş yedek sorguyu sona at ki 7 sahnede çeşitlilik korunsun
        aday_sorgular = (
            [q for q in ham_aday_sorgular if q.lower() not in kullanilan_sorgular]
            + [q for q in ham_aday_sorgular if q.lower() in kullanilan_sorgular]
        )

        tekiller: list[str] = []
        for s_q in aday_sorgular:
            for w_q in s_q.split():
                if len(w_q) >= 4 and w_q.lower() not in _SUS_KELIMELER and w_q.lower() not in tekiller:
                    tekiller.append(w_q.lower())

        # Önce Pexels'te (katı -> gevşek), bulunamazsa Pixabay'de (katı -> gevşek) dene
        for sag_adi, sag_key, ara_fn in saglayicilar:
            if secim:
                break
            try:
                # 1. Aşama: Katı nesne + anti-ham piksel denetimi
                for sorgu in aday_sorgular:
                    denenen.append(f"{sag_adi}:{sorgu}")
                    uygunlar = [
                        h for h in ara_fn(sorgu, sag_key)
                        if str(h.get("uid") or f"{sag_adi}:{h['id']}") not in kullanilan
                        and _yeterince_uygun(h, sorgu, ana_konu, gevsek=False)
                    ]
                    if uygunlar:
                        secim = _adaylardan_indir_ve_dogrula(uygunlar, sorgu, ham, kullanilan, siki_piksel=True)
                        if secim:
                            break

                # 2. Aşama: Kök/tekil kelime eşleşmeli gevşek arama + anti-ham piksel denetimi
                if not secim:
                    for sorgu in (aday_sorgular + tekiller[:4]):
                        etiket_s = f"{sag_adi}~{sorgu}"
                        if etiket_s not in denenen:
                            denenen.append(etiket_s)
                        uygunlar = [
                            h for h in ara_fn(sorgu, sag_key)
                            if str(h.get("uid") or f"{sag_adi}:{h['id']}") not in kullanilan
                            and _yeterince_uygun(h, sorgu, ana_konu, gevsek=True)
                        ]
                        if uygunlar:
                            secim = _adaylardan_indir_ve_dogrula(uygunlar, sorgu, ham, kullanilan, siki_piksel=True)
                            if secim:
                                break
            except SystemExit as e:
                # Birincil sağlayıcıda geçici sorun olursa yedek sağlayıcıya şans ver
                if len(saglayicilar) > 1 and sag_adi != saglayicilar[-1][0]:
                    print(f"  [uyarı] {sag_adi} geçici hata verdi, yedek kaynağa geçiliyor: {e}")
                    continue
                raise

        # 3. Aşama: Koyu bilimsel atmosfer yedeği (üretimin 0 görselle çökmesini önler)
        if not secim:
            for gen_sorgu in (
                "dark laboratory microscope",
                "cosmos galaxy nebula",
                "physics light prism",
                "deep ocean bioluminescence",
            ):
                if secim:
                    break
                for sag_adi, sag_key, ara_fn in saglayicilar:
                    denenen.append(f"{sag_adi}:{gen_sorgu}")
                    try:
                        uygunlar = [
                            h for h in ara_fn(gen_sorgu, sag_key)
                            if str(h.get("uid") or f"{sag_adi}:{h['id']}") not in kullanilan
                            and str(h.get("type", "photo")) == "photo"
                            and not (_kelimeler(h.get("tags", ""), sus_at=False) & _YASAK_ETIKET_KESIN)
                        ]
                    except SystemExit:
                        continue
                    if uygunlar:
                        secim = _adaylardan_indir_ve_dogrula(uygunlar, gen_sorgu, ham, kullanilan, siki_piksel=False)
                        if secim:
                            break

        if not secim or not ham.exists():
            raise SystemExit(
                f"Sahne {i} için uygun görsel bulunamadı (denenen: {denenen}) — üretim durdu."
            )

        sorgu, hit = secim
        uid = str(hit.get("uid") or f"{hit.get('kaynak', 'stok')}:{hit['id']}")
        kullanilan.add(uid)
        kullanilan_sorgular.add(sorgu.lower())

        png = klasor / f"sahne_{i:02d}.png"
        with Image.open(ham) as im:
            sinematik_isle(dikey_kirp(im.convert("RGB")), tohum=20261100 + i).save(png, quality=95)
        ham.unlink(missing_ok=True)
        yollar.append(png)
        print(
            f"  görsel {i}: {uid} ({hit.get('imageWidth')}x{hit.get('imageHeight')}) "
            f"/ sorgu={sorgu!r} / açıklama={str(hit.get('tags'))[:65]}"
        )
    return yollar
