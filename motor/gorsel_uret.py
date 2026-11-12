#!/usr/bin/env python3
"""Sahne görselleri — Pixabay (ücretsiz, anahtar repoda var) + 1080x1920 hazırlık.

Karar (kullanıcı): görseller Pixabay'den gelir; teal-amber sinematik renk
düzenlemesi ve parçacık efekti render motorunda uygulanır (sablon tekilliği).

Kurallar:
    * Dikey (9:16) tercih edilir, kısa kenar >= 1080 olmalı
    * Her sahne için ayrı görsel; aynı görsel iki kez kullanılmaz
    * Ham görselde yazı/filigran olmamalı → üretim sonrası 'elle onay' kapısı
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

HEDEF = (1080, 1920)
ARAMA_URL = "https://pixabay.com/api/"


def _istek(url: str) -> dict:
    istek = urllib.request.Request(url, headers={"User-Agent": "bilgidozu-motor/1.0 (+github)"})
    try:
        with urllib.request.urlopen(istek, timeout=60) as y:
            return json.loads(y.read().decode())
    except Exception as hata:  # noqa: BLE001
        govde = ""
        try:
            govde = hata.read().decode()[:300]      # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit(f"Pixabay isteği başarısız: {hata} | {govde}") from hata


def _puanla(hit: dict, sorgu: str) -> float:
    """Etiket uyumu + çözünürlük + beğeni → alaka puanı."""
    q = {k.lower() for k in sorgu.replace("+", " ").split() if len(k) > 2}
    etiketler = {t.lower() for t in str(hit.get("tags", "")).replace(",", " ").split()}
    ortak = len(q & etiketler)
    puan = ortak * 10.0
    puan += min(4.0, (hit.get("imageWidth", 0) * hit.get("imageHeight", 0)) / 6_000_000)
    puan += min(3.0, (hit.get("likes", 0) + hit.get("downloads", 0) / 50.0) / 100.0)
    if hit.get("imageHeight", 0) > hit.get("imageWidth", 0):
        puan += 3.0
    if (hit.get("imageWidth", 0) >= 1080 and hit.get("imageHeight", 0) >= 1440):
        puan += 2.0
    # Fotoğraf türü şartlarını geçemeyen (illüstrasyon/vektör) sonuçları ele
    if str(hit.get("type", "photo")) != "photo":
        puan -= 20.0
    return puan


def pixabay_ara(sorgu: str, anahtar: str, adet: int = 60) -> list[dict]:
    """Sorguya en uygun dikey fotoğrafları puana göre sıralı döndürür.

    Önce katı (dikey + büyük), sonuç azsa gevşek (her yön) arama yapılır.
    """
    temel = {
        "key": anahtar,
        "q": sorgu,
        "image_type": "photo",
        "safesearch": "true",
        "order": "popular",
        "per_page": str(min(adet, 200)),
        "lang": "en",
        "order": "popular",
    }
    sonuclar: dict[int, dict] = {}
    for ek in ({"orientation": "vertical", "min_width": 1400, "min_height": 1400},
               {"min_width": 1200, "min_height": 900}):
        try:
            veri = _istek(f"{ARAMA_URL}?{urllib.parse.urlencode({**temel, **ek})}")
        except SystemExit:
            if sonuclar:      # gevşek aramada hata olursa elimizdekiyle devam
                break
            raise
        for h in veri.get("hits", []):
            sonuclar.setdefault(h["id"], h)
        if len(sonuclar) >= 8:
            break
    return sorted(sonuclar.values(), key=lambda h: _puanla(h, sorgu), reverse=True)


def _sorgu_adaylari(sahne: dict, yedek: list[str], ana_konu: str) -> list[str]:
    """Sahnenin somut nesnesini arayan, kelime tekrarı yapmayan sorgular.

    Eski sürüm aynı kelimeleri iki kez ekliyordu ("person waking up before alarm
    clock person waking up before alarm clock") ve Pixabay alakasız sonuç
    döndürüyordu. Artık: kısa ve öz sorgu önce, süsleyici kelimeler sonra.
    """
    def _temiz(x: str) -> str:
        return " ".join(str(x or "").replace(",", " ").split())

    SOYUT = {"communication", "communicate", "dance", "dancing", "waggle",
             "collection", "process", "concept", "how", "why", "secret"}
    def _somut(x: str) -> str:
        return " ".join(w for w in _temiz(x).split() if w.lower() not in SOYUT)

    detay = _somut(sahne.get("gorsel"))
    anahtar = _somut(sahne.get("gorsel_anahtar") or "")
    anchor = _somut(ana_konu)

    # Sahnenin kendi ana nesnesi varsa onu kullan; yoksa ilk sahnenin nesnesi.
    cekirdek = anahtar or detay
    adaylar: list[str] = []
    if cekirdek:
        adaylar.append(cekirdek)                      # en yalın, en isabetli
    if cekirdek and anchor and cekirdek.lower()[:20] not in anchor.lower():
        adaylar.append(f"{cekirdek} {anchor}")
    if detay and detay != cekirdek:
        adaylar.append(detay)
    adaylar += [_temiz(y) for y in yedek if _temiz(y)]

    # Kelime tekrarını at, kısa sorguyu öne al.
    gorulen: set[str] = set()
    sonuc: list[str] = []
    for a in adaylar:
        anahtar_kelime = " ".join(sorted({k.lower() for k in a.split()}))
        if not anahtar_kelime or anahtar_kelime in gorulen:
            continue
        gorulen.add(anahtar_kelime)
        sonuc.append(a)
    return sorted(sonuc, key=lambda x: len(x.split()))[:6]


# Fotoğrafçılık/süsleme kelimeleri — alaka ölçümünde sayılmaz.
_SUS_KELIMELER = {
    "macro", "close", "closeup", "photography", "photo", "documentary",
    "cinematic", "shot", "view", "style", "light", "lighting", "nature",
    "background", "wallpaper", "beautiful", "abstract", "concept",
}


def _kelimeler(metin: str) -> set[str]:
    import re
    return {k for k in re.split(r"[^\wçğıöşü]+", str(metin or "").lower())
            if len(k) >= 3 and k not in _SUS_KELIMELER}


# Alaka ölçümünde sayılmayan süs/sanat kelimeleri.
_SUS_KELIMELER = {
    "macro", "close", "closeup", "photography", "photo", "documentary",
    "cinematic", "shot", "view", "style", "light", "lighting", "nature",
    "background", "wallpaper", "beautiful", "abstract", "concept", "dance",
    "dancing", "communication", "collection", "process", "concept",
}

# Video konusundan bağımsız, ASLA istenmeyen görsel türleri (portre/selfie/düğün/alkol/yemek/araç).
# Not: İnsan anatomisi (hand, finger, eye, brain, skin, ear, heart, sleep) konularında Pixabay
# fotoğraflarına otomatik "person/people/man/woman" etiketi eklediği için o kelimeler yalnızca
# sorgu insan vücudu içermiyorsa yasaklanır.
_YASAK_ETIKET_KESIN = {
    "portrait", "model", "hanói", "hanoi", "vietnamese", "selfie", "smile",
    "fashion", "makeup", "tea", "coffee", "drink", "cup", "wine", "beer",
    "food", "dish", "car", "motorcycle", "wedding", "couple", "bikini", "lingerie",
}
_INSAN_ANATOMI = {
    "hand", "hands", "finger", "fingers", "thumb", "palm", "skin", "eye", "eyes",
    "brain", "ear", "ears", "heart", "blood", "muscle", "bone", "skeleton", "sleep",
    "sleeping", "face", "mouth", "tongue", "nose", "human", "nerve", "body",
}


def _kelimeler(metin: str, sus_at: bool = True) -> set[str]:
    import re
    k = {x for x in re.split(r"[^\wçğıöşü]+", str(metin or "").lower()) if len(x) >= 3}
    return {x for x in k if x not in _SUS_KELIMELER} if sus_at else k


def _yasak_etiket_seti(sorgu: str, ana_konu: str) -> set[str]:
    tum = _kelimeler(f"{sorgu} {ana_konu}", sus_at=False)
    if tum & _INSAN_ANATOMI:
        return _YASAK_ETIKET_KESIN
    return _YASAK_ETIKET_KESIN | {"girl", "boy", "woman", "man"}


def _yeterince_uygun(hit: dict, sorgu: str, ana_konu: str, gevsek: bool = False) -> bool:
    """Görsel gerçekten sahnenin ana NESNESİNİ gösteriyor mu?"""
    etiketler = _kelimeler(hit.get("tags", ""), sus_at=False)
    if not etiketler:
        return False
    if etiketler & _yasak_etiket_seti(sorgu, ana_konu):
        return False
    if str(hit.get("type", "photo")) != "photo":
        return False
    cekirdek = _kelimeler(sorgu) or _kelimeler(ana_konu)
    if not cekirdek:
        return _puanla(hit, sorgu) >= 4.0
    ortak = len(cekirdek & etiketler)
    if gevsek:
        # Kök eşleşmesi (ör. fingers <-> finger, waves <-> wave)
        if ortak == 0:
            kok_c = {w[:4] for w in cekirdek if len(w) >= 4}
            kok_e = {w[:4] for w in etiketler if len(w) >= 4}
            ortak = len(kok_c & kok_e)
        return ortak >= 1 and _puanla(hit, sorgu) >= 3.5
    gerekli = 1 if len(cekirdek) <= 4 else 2
    return ortak >= gerekli and _puanla(hit, sorgu) >= 5.5


def dikey_kirp(img: Image.Image) -> Image.Image:
    """9:16'ya merkez kırp, sonra 1080x1920'ye ölçekle."""
    en, boy = img.size
    hedef_oran = HEDEF[1] / HEDEF[0]
    if en / boy > 1 / hedef_oran:          # fazla geniş → yanlardan kırp
        yeni_en = int(boy / hedef_oran)
        sol = (en - yeni_en) // 2
        img = img.crop((sol, 0, sol + yeni_en, boy))
    else:                                   # fazla uzun → üst/alttan kırp
        yeni_boy = int(en * hedef_oran)
        ust = (boy - yeni_boy) // 2
        img = img.crop((0, ust, en, ust + yeni_boy))
    return img.resize(HEDEF, Image.LANCZOS)


def sinematik_isle(img: Image.Image) -> Image.Image:
    """Ham stok fotoğrafı sinematik görünüme çevirir.

    Yapılanlar: teal-amber renk düzenlemesi, kontrast, doygunluk, kenar
    karartma (vignette), hafif film greni ve keskinleştirme. Render motoru
    ayrıca kendi katmanını uyguluyor; buradaki işlem ham görselin "stok
    fotoğraf" gibi düz görünmesini engeller.
    """
    from PIL import ImageEnhance, ImageFilter
    import numpy as np

    im = img.convert("RGB")
    a = np.asarray(im).astype(np.float32) / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]

    # Teal-amber: gölgeler soğuk (mavi-yeşil), ışıklar sıcak.
    parlaklik = a.mean(axis=2)          # (h, w) — kanal boyutu OLMAMALI
    golge = np.clip(1.0 - parlaklik * 1.4, 0.0, 1.0)
    isik = np.clip(parlaklik * 1.4 - 0.35, 0.0, 1.0)
    r = r + 0.11 * isik - 0.04 * golge
    g = g + 0.02 * isik + 0.01 * golge
    b = b + 0.12 * golge - 0.05 * isik
    a = np.stack([r, g, b], axis=2)

    # Kontrast + filmik S eğrisi
    a = np.clip((a - 0.5) * 1.16 + 0.5, 0.0, 1.0)
    a = np.clip(a + 0.045 * np.sin((a - 0.5) * 3.1), 0.0, 1.0)

    out = Image.fromarray((a * 255.0).astype(np.uint8))

    # Doygunluk ve keskinlik
    out = ImageEnhance.Color(out).enhance(1.14)
    out = ImageEnhance.Contrast(out).enhance(1.06)
    out = out.filter(ImageFilter.UnsharpMask(radius=2.0, percent=115, threshold=3))

    # Kenar karartma (vignette)
    w, h = out.size
    yy, xx = np.mgrid[0:h, 0:w]
    nx = (xx - w / 2) / (w / 2)
    ny = (yy - h / 2) / (h / 2)
    vig = np.clip(1.06 - 0.26 * (nx * nx + ny * ny), 0.72, 1.06)[..., None]
    arr = np.clip(np.asarray(out).astype(np.float32) * vig, 0, 255)

    # Hafif film greni
    rng = np.random.default_rng(20261112)
    arr = np.clip(arr + rng.normal(0.0, 3.4, arr.shape), 0, 255)
    return Image.fromarray(arr.astype(np.uint8))


def _indir(url: str, hedef: Path) -> None:
    istek = urllib.request.Request(url, headers={"User-Agent": "bilgidozu-motor/1.0"})
    with urllib.request.urlopen(istek, timeout=120) as y:
        hedef.write_bytes(y.read())


def sahneler_icin_gorseller(sahneler: list[dict], klasor: Path,
                             yedek_sorgular: list[str] | None = None) -> list[Path]:
    """Her sahne için en uygun görseli indirir, 1080x1920 PNG olarak kaydeder."""
    anahtar = os.getenv("PIXABAY_API_KEY", "").strip()
    if not anahtar:
        raise SystemExit("PIXABAY_API_KEY yok — görseller indirilemedi, üretim durdu.")
    klasor.mkdir(parents=True, exist_ok=True)
    yedek = yedek_sorgular or []

    kullanilan: set[int] = set()
    yollar: list[Path] = []
    # İlk sahnenin somut ana nesnesi tüm sahnelerde konu çıpasıdır.
    ana_konu = str((sahneler[0] if sahneler else {}).get("gorsel") or "").strip()
    for i, sahne in enumerate(sahneler, start=1):
        secim = None
        denenen = []
        aday_sorgular = _sorgu_adaylari(sahne, yedek, ana_konu)
        # 1. Aşama: Katı nesne eşleşmesi
        for sorgu in aday_sorgular:
            denenen.append(sorgu)
            sonuc = [h for h in pixabay_ara(sorgu, anahtar)
                     if h["id"] not in kullanilan and _yeterince_uygun(h, sorgu, ana_konu, gevsek=False)]
            if sonuc:
                secim = (sorgu, sonuc[0])
                break
        # 2. Aşama: Tekil kelime / kök eşleşmeli gevşek arama
        if not secim:
            tekiller = []
            for s_q in aday_sorgular:
                for w_q in s_q.split():
                    if len(w_q) >= 4 and w_q.lower() not in _SUS_KELIMELER and w_q.lower() not in tekiller:
                        tekiller.append(w_q.lower())
            for sorgu in (aday_sorgular + tekiller[:4]):
                if sorgu not in denenen:
                    denenen.append(sorgu)
                sonuc = [h for h in pixabay_ara(sorgu, anahtar)
                         if h["id"] not in kullanilan and _yeterince_uygun(h, sorgu, ana_konu, gevsek=True)]
                if sonuc:
                    secim = (sorgu, sonuc[0])
                    break
        # 3. Aşama: Bilimsel genel görsel yedeği (üretimin 0 görselle çökmesini önler)
        if not secim:
            for gen_sorgu in ("science physics", "laboratory microscope", "nature macro", "stars galaxy"):
                denenen.append(gen_sorgu)
                sonuc = [h for h in pixabay_ara(gen_sorgu, anahtar)
                         if h["id"] not in kullanilan
                         and str(h.get("type", "photo")) == "photo"
                         and not (_kelimeler(h.get("tags", ""), sus_at=False) & _YASAK_ETIKET_KESIN)]
                if sonuc:
                    secim = (gen_sorgu, sonuc[0])
                    break
        if not secim:
            raise SystemExit(
                f"Sahne {i} için Pixabay sonucu yok (denenen: {denenen}) — üretim durdu.")

        sorgu, hit = secim
        ham = klasor / f"ham_{i:02d}.jpg"
        _indir(hit.get("fullHDURL") or hit["largeImageURL"], ham)
        kullanilan.add(hit["id"])

        png = klasor / f"sahne_{i:02d}.png"
        with Image.open(ham) as im:
            sinematik_isle(dikey_kirp(im.convert("RGB"))).save(png, quality=95)
        yollar.append(png)
        print(f"  görsel {i}: pixabay#{hit['id']} / sorgu={sorgu!r} / etiket={str(hit.get('tags'))[:60]}")
    return yollar
