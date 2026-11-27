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

import base64
import hashlib
import io
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

try:
    from .workspace_paths import workspace_temp_dir
except ImportError:
    from workspace_paths import workspace_temp_dir

from shorts_acceptance import MIN_AVG_BRIGHTNESS, SEMANTIC_THRESHOLD

HEDEF = (1350, 2400)  # Tam 9:16 dikey, Ken Burns zoom için yüksek keskinlik
SEMANTIC_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.8-flash")
# Ücretsiz kota model başına günlük 20 istek. Ana model tükenirse sırayla yedek dene.
_SEMANTIC_FALLBACKS = [
    m.strip() for m in os.getenv(
        "GEMINI_VISION_FALLBACKS",
        "gemini-3.8-flash-lite,gemini-3.6-flash,gemini-2.5-flash",
    ).split(",") if m.strip()
]
MAX_CANDIDATES_PER_QUERY = 5
VISUAL_QA_ENV = "MOTOR_VISUAL_QA_PASSED"


_DISCOVERED_VISION_MODELS: list[str] | None = None


def _static_vision_models() -> list[str]:
    """Ana model + env ile verilen sabit yedekler."""
    return [SEMANTIC_MODEL] + [m for m in _SEMANTIC_FALLBACKS if m != SEMANTIC_MODEL]


def _discover_flash_models() -> list[str]:
    """Yalnız ana model(ler) kotayla düşünce çağrılır: Gemini'nin diğer flash modelleri."""
    global _DISCOVERED_VISION_MODELS
    if _DISCOVERED_VISION_MODELS is not None:
        return _DISCOVERED_VISION_MODELS
    bulunan: list[str] = []
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if key:
        try:
            with urllib.request.urlopen(
                "https://generativelanguage.googleapis.com/v1beta/models?key=" + key, timeout=30
            ) as y:
                veri = json.load(y).get("models", [])
            for m in veri:
                ad = str(m.get("name", "")).split("/", 1)[-1]
                dusuk = ad.lower()
                if ("generateContent" in (m.get("supportedGenerationMethods") or [])
                        and "flash" in dusuk
                        and not any(x in dusuk for x in ("tts", "image", "live", "omni", "embedding"))):
                    if ad not in bulunan:
                        bulunan.append(ad)
        except Exception:  # noqa: BLE001 — model listesi alınamazsa sabit yedeklerle devam
            pass
    _DISCOVERED_VISION_MODELS = bulunan
    return bulunan


def semantic_score_passes(score: float | None) -> bool:
    """Tek fail-closed eşik: yok/bozuk skor veya alt eşik, görsel seçimini engeller."""
    try:
        return score is not None and 0.0 <= float(score) <= 1.0 and float(score) >= SEMANTIC_THRESHOLD
    except (TypeError, ValueError):
        return False
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


def average_image_brightness(image: Image.Image) -> float:
    """Approximate mean Rec. 601 luma in 0..255 from the actual image pixels."""
    small = np.asarray(image.convert("RGB").resize((64, 64), Image.Resampling.BILINEAR), dtype=np.float32)
    return float((0.299 * small[..., 0] + 0.587 * small[..., 1] + 0.114 * small[..., 2]).mean())


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


def _record_score_passes(record: dict) -> bool:
    """Only a live Gemini Vision score is sufficient to select a production image."""
    return (
        record.get("score_origin") == "live_gemini_vision"
        and semantic_score_passes(record.get("semantic_similarity"))
    )


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


def pexels_ara(sorgu: str, anahtar: str, adet: int = MAX_CANDIDATES_PER_QUERY) -> list[dict]:
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
                    "preview_url": src.get("medium") or src.get("small") or indir_url,
                    "source_page_url": str(p.get("url") or ""),
                },
            )
        if len(sonuclar) >= min(adet, 80):
            break
    return sorted(sonuclar.values(), key=lambda h: _puanla(h, sorgu), reverse=True)


def pixabay_ara(sorgu: str, anahtar: str, adet: int = MAX_CANDIDATES_PER_QUERY) -> list[dict]:
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
            kopya["preview_url"] = h.get("previewURL") or h.get("webformatURL") or indir_url
            kopya["source_page_url"] = str(h.get("pageURL") or "")
            sonuclar.setdefault(int(hid), kopya)
        if len(sonuclar) >= min(adet, 80):
            break
    return sorted(sonuclar.values(), key=lambda h: _puanla(h, sorgu), reverse=True)


def _sorgu_adaylari(sahne: dict, yedek: list[str] | None = None, ana_konu: str = "", sahne_sirasi: int = 0) -> list[str]:
    """Yalnız sahnenin kendi somut aramalarını döndürür; genel/atmosferik yedek yoktur."""
    def temiz(x: str) -> str:
        return " ".join(str(x or "").replace(",", " ").split())

    soyut = {"communication", "communicate", "dance", "dancing", "waggle", "collection", "process", "concept", "how", "why", "secret"}
    sorgular = []
    for raw in (sahne.get("gorsel_anahtar"), sahne.get("gorsel"), sahne.get("gorsel_alternatif")):
        q = " ".join(w for w in temiz(raw).split() if w.lower() not in soyut)
        if q and q.lower() not in {x.lower() for x in sorgular}:
            sorgular.append(q)
    return sorgular[:1]


def _yeterince_uygun(hit: dict, sorgu: str, ana_konu: str = "", gevsek: bool = False) -> bool:
    """Yalnız fotoğraf/kalite/yasak içerik ön elemesi; konu uyumunu görsel hakem puanlar."""
    ham_etiket = str(hit.get("tags", "")).lower()
    if any(ifade in ham_etiket for ifade in _YASAK_IFADELER):
        return False
    etiketler = _kelimeler(ham_etiket, sus_at=False)
    if etiketler & _yasak_etiket_seti(sorgu, ana_konu):
        return False
    if str(hit.get("type", "photo")) != "photo":
        return False
    par = _avg_parlaklik(hit.get("avg_color", ""))
    if not gevsek and par is not None and par > 232:
        return False
    return True

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
    avg_luma = float(luma.mean() * 255.0)
    if avg_luma < MIN_AVG_BRIGHTNESS:
        return True, f"karanlik_gorsel({avg_luma:.1f}/255)"
    patlak_oran = float(np.mean(luma > 0.95))
    if patlak_oran > 0.34:
        return True, f"patlamis_isik({patlak_oran:.2f})"

    gri = luma * 255.0
    keskinlik = float(np.mean(np.abs(np.diff(gri, axis=1))) + np.mean(np.abs(np.diff(gri, axis=0))))
    if keskinlik < 2.1:
        return True, f"bulanik_gorsel({keskinlik:.2f})"

    return False, "ok"


def logo_bolgesi_var_mi(im: Image.Image) -> tuple[bool, str]:
    """Köşelerdeki küçük, yüksek kontrastlı yazı/filtre bloklarını logo sayar.

    Yalnız köşelere bakılır; doğal gökyüzü/orman gibi geniş alanlar yanlışlıkla
    logo sanılmasın diye 'parlaklık + kenar yoğunluğu' birlikte aranır.
    """
    kucuk = im.convert("RGB").resize((270, 480), Image.Resampling.BILINEAR)
    a = np.asarray(kucuk, dtype=np.float32)
    h, w, _ = a.shape
    by, bx = max(10, int(h * 0.13)), max(10, int(w * 0.17))
    bolgeler = {
        "ust_sol": a[:by, :bx],
        "ust_sag": a[:by, -bx:],
        "alt_sol": a[-by:, :bx],
        "alt_sag": a[-by:, -bx:],
    }
    for ad, bolge in bolgeler.items():
        luma = 0.299 * bolge[..., 0] + 0.587 * bolge[..., 1] + 0.114 * bolge[..., 2]
        parlak = float(np.mean(luma > 224))
        koyu = float(np.mean(luma < 24))
        kenar = float(np.mean(np.abs(np.diff(luma, axis=0)) > 22)
                      + np.mean(np.abs(np.diff(luma, axis=1)) > 22))
        if (parlak > 0.22 or koyu > 0.32) and kenar > 0.05:
            return True, ad
    return False, "yok"


def logo_duzelt(im: Image.Image) -> tuple[Image.Image, dict]:
    """Logo tespit edilen kenarı kırpar; kırpılan görsel sonra 9:16'ya getirilir."""
    var, bolge = logo_bolgesi_var_mi(im)
    bilgi = {"tespit": var, "bolge": bolge, "islem": "kirpildi" if var else "dokunulmadi"}
    if not var:
        return im, bilgi
    en, boy = im.size
    kenar = max(4, int(min(en, boy) * 0.09))
    if bolge.startswith("ust"):
        kutu = (0, kenar, en, boy)
    elif bolge.startswith("alt"):
        kutu = (0, 0, en, boy - kenar)
    elif bolge.endswith("sol"):
        kutu = (kenar, 0, en, boy)
    else:
        kutu = (0, 0, en - kenar, boy)
    kutu = (max(0, kutu[0]), max(0, kutu[1]), min(en, kutu[2]), min(boy, kutu[3]))
    if kutu[2] <= kutu[0] or kutu[3] <= kutu[1]:
        bilgi["islem"] = "kirpilanmadan_red"
        return im, bilgi
    return im.crop(kutu), bilgi


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
    if str(url).startswith("file://"):
        src = Path(urllib.request.url2pathname(urllib.parse.urlparse(str(url)).path))
        hedef.write_bytes(src.read_bytes())
        return
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


def _visual_text_scores(scene_text: str, candidates: list[dict]) -> list[float | None]:
    """Gemini Vision ile gerçek aday piksellerini sahne cümlesine göre 0..1 puanlar.

    Bu puan CLIP cosine benzeri otomatik bir görsel-metin uygunluk puanıdır; hata halinde
    None döner ve fail-closed davranılır (aday görsel seçilmez).
    """
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        return [None] * len(candidates)
    if not candidates:
        return []

    parts: list[dict] = [{"text": (
        "Sahne metni: " + scene_text + "\n"
        "Her numaralı fotoğrafı, sahne metninde anlatılan somut nesne/eylem/mekanizmayı gerçekten gösterip göstermediğine göre puanla. "
        "Renk, sinematik görünüm veya yalnızca genel bilim havası alaka değildir. "
        "0 = ilgisiz/yanıltıcı, 0.5 = kısmi veya yalnızca dolaylı, 1 = sahneyi doğrudan ve açıkça gösteriyor. "
        "Sadece geçerli JSON döndür: {\"scores\":[0.0, ...]} ; sıra görsellerin numarasıyla aynı ve her puan 0 ile 1 arasında olsun."
    )}]
    valid_indices: list[int] = []
    with tempfile.TemporaryDirectory(prefix="visual-fit-", dir=workspace_temp_dir()) as td:
        for i, hit in enumerate(candidates):
            url = str(hit.get("preview_url") or hit.get("indir_url") or "")
            if not url:
                continue
            tmp = Path(td) / f"candidate_{i + 1}.img"
            try:
                _indir(url, tmp)
                with Image.open(tmp) as im:
                    im = im.convert("RGB")
                    im.thumbnail((256, 256), Image.Resampling.LANCZOS)
                    buf = io.BytesIO()
                    im.save(buf, format="JPEG", quality=65, optimize=True)
                parts.append({"text": f"Aday fotoğraf {i + 1}:"})
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode("ascii")}})
                valid_indices.append(i)
            except Exception as exc:  # noqa: BLE001
                hit["_vision_error"] = f"image_fetch:{type(exc).__name__}"
        if not valid_indices:
            return [None] * len(candidates)

        body = {"contents": [{"parts": parts}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
        try:
            last_exc: Exception | None = None
            modeller = _static_vision_models()
            denenen: set[str] = set()
            kesif_yapildi = False
            idx = 0
            while idx < len(modeller) and len(denenen) < 6:
                model = modeller[idx]
                idx += 1
                if model in denenen:
                    continue
                denenen.add(model)
                req = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
                try:
                    response = None
                    for attempt in range(2):
                        try:
                            response = urllib.request.urlopen(req, timeout=90)
                            break
                        except urllib.error.HTTPError as http_error:
                            last_exc = http_error
                            # 429/404: bu model tükendi veya yok; aynı modelde ısrar etme.
                            if http_error.code in (429, 400, 404):
                                response = None
                                break
                            if http_error.code != 503 or attempt == 1:
                                raise
                            time.sleep(min(float(2 ** (attempt + 1)), 15.0))
                        except TimeoutError:
                            if attempt == 1:
                                raise
                            time.sleep(min(float(2 ** (attempt + 1)), 15.0))
                    if response is not None:
                        with response:
                            answer = json.load(response)["candidates"][0]["content"]["parts"][0]["text"]
                        parsed = json.loads(answer)
                        raw = parsed.get("scores") if isinstance(parsed, dict) else None
                        if isinstance(raw, list) and len(raw) == len(valid_indices):
                            scores: list[float | None] = [None] * len(candidates)
                            for i, val in zip(valid_indices, raw):
                                try:
                                    score = float(val)
                                except (TypeError, ValueError):
                                    candidates[i]["_vision_error"] = "invalid_live_vision_score"
                                    continue
                                if np.isfinite(score) and 0.0 <= score <= 1.0:
                                    scores[i] = score
                                else:
                                    candidates[i]["_vision_error"] = "invalid_live_vision_score"
                            return scores
                        last_exc = RuntimeError("vision_score_shape")
                except Exception as exc:  # noqa: BLE001 — sıradaki modeli dene
                    last_exc = exc
                if idx >= len(modeller) and not kesif_yapildi:
                    kesif_yapildi = True
                    modeller.extend(_discover_flash_models())
            raise last_exc or RuntimeError("Gemini Vision hiçbir modelde yanıt vermedi")
        except Exception as exc:  # noqa: BLE001 — fail closed
            # Keep only safe quota metadata; never log the request URL or API key.
            if isinstance(exc, urllib.error.HTTPError):
                safe_error = {"http_status": int(exc.code)}
                try:
                    error_data = json.loads(exc.read().decode("utf-8", errors="replace"))
                    api_error = error_data.get("error") or {}
                    safe_error["status"] = api_error.get("status")
                    message = str(api_error.get("message") or "").replace(key, "[redacted]")
                    safe_error["message"] = message[:700]
                    safe_details = []
                    for detail in api_error.get("details") or []:
                        kind = str(detail.get("@type") or "")
                        if "QuotaFailure" in kind:
                            violations = []
                            for violation in detail.get("violations") or []:
                                violations.append({k: violation[k] for k in
                                    ("quotaMetric", "quotaId", "quotaDimensions", "quotaValue", "subject", "description")
                                    if k in violation})
                            safe_details.append({"type": "QuotaFailure", "violations": violations})
                        elif "ErrorInfo" in kind:
                            metadata = detail.get("metadata") or {}
                            allow = ("consumer", "service", "method", "reason", "quota_metric", "quota_limit",
                                     "quota_location", "quota_unit", "quota_value", "model")
                            safe_details.append({"type": "ErrorInfo", "reason": detail.get("reason"),
                                                 "metadata": {k: metadata[k] for k in allow if k in metadata}})
                    if safe_details:
                        safe_error["details"] = safe_details
                except Exception:
                    pass
                summary = json.dumps(safe_error, ensure_ascii=False, separators=(",", ":"))[:1800]
            else:
                summary = type(exc).__name__
            for hit in candidates:
                hit["_vision_error"] = f"vision_judge:{summary}"
            return [None] * len(candidates)


def _provider_page_url_ok(provider: str, url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
        host = (parsed.hostname or "").lower().rstrip(".")
        if provider == "pexels":
            domain = "pexels.com"
        elif provider == "pixabay":
            domain = "pixabay.com"
        elif provider == "cloudflare_ai":
            domain = "cloudflare.com"
        else:
            domain = ""
        return parsed.scheme == "https" and bool(domain) and (host == domain or host.endswith("." + domain))
    except Exception:
        return False


def _gorsel_kalite_logunu_yaz(klasor: Path, log: dict) -> None:
    """Her çalıştırmada hem sahne klasörüne hem üretim arşivine seçim kanıtı yazar."""
    hedef = klasor / "gorsel_secim_raporu.json"
    try:
        hedef.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[görsel log uyarısı] yerel JSON yazılamadı: {type(exc).__name__}")
    try:
        import arsiv
        arsiv.yaz_json("gorsel_secim_raporu", log)
    except Exception as exc:  # noqa: BLE001
        print(f"[görsel log uyarısı] üretim arşivi yazılamadı: {type(exc).__name__}")


def cloudflare_ai_gorseller_uret(scene_text: str, scene_index: int, klasor: Path, adet: int = 1) -> list[dict]:
    """Cloudflare Workers AI ile sahneye özel görsel üretir (fallback)."""
    account_id = (os.getenv("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    token = (os.getenv("CLOUDFLARE_API_TOKEN") or "").strip()
    if not account_id or not token:
        return []
    model = (os.getenv("CLOUDFLARE_AI_IMAGE_MODEL") or "@cf/black-forest-labs/flux-1-schnell").strip()
    prompt = (
        "Photorealistic cinematic documentary image for a science short video. "
        "Show this scene clearly and concretely: " + " ".join(str(scene_text).split()) + ". "
        "No text, no letters, no numbers, no watermark, no logo, no border, no collage. "
        "Natural lighting, high detail, vertical composition friendly."
    )
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    hits: list[dict] = []
    for i in range(max(1, min(adet, 2))):
        try:
            body = {"prompt": prompt, "num_steps": 4}
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
                ctype = (resp.headers.get("Content-Type") or "").lower()
            img_bytes: bytes | None = None
            if "application/json" in ctype or raw[:1] in (b"{", b"["):
                data = json.loads(raw.decode("utf-8", "replace"))
                result = data.get("result") if isinstance(data, dict) else None
                if isinstance(result, dict) and isinstance(result.get("image"), str):
                    img_bytes = base64.b64decode(result["image"])
                elif isinstance(data, dict) and isinstance(data.get("image"), str):
                    img_bytes = base64.b64decode(data["image"])
            if img_bytes is None and raw[:3] in (b"\xff\xd8\xff", b"\x89PN", b"RIFF"):
                img_bytes = raw
            if not img_bytes:
                print(f"  [cf-ai] sahne {scene_index}: yanıt görsel içermedi.")
                continue
            hedef = klasor / f"cf_{scene_index:02d}_{i+1}.png"
            with Image.open(io.BytesIO(img_bytes)) as im:
                im = im.convert("RGB")
                im.save(hedef, format="PNG")
                w, h = im.size
            uid = f"cloudflare_ai:{hashlib.sha256(img_bytes).hexdigest()[:16]}_{scene_index}_{i+1}"
            file_url = hedef.resolve().as_uri()
            hits.append({
                "uid": uid,
                "kaynak": "cloudflare_ai",
                "id": uid,
                "imageWidth": int(w),
                "imageHeight": int(h),
                "tags": " ".join(str(scene_text).split()[:16]),
                "type": "photo",
                "avg_color": "#666666",
                "likes": 0,
                "downloads": 0,
                "indir_url": file_url,
                "preview_url": file_url,
                "source_page_url": "https://developers.cloudflare.com/workers-ai/",
                "_local_path": str(hedef),
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  [cf-ai] sahne {scene_index} üretim hatası: {type(exc).__name__}")
    return hits


def sahneler_icin_gorseller(
    sahneler: list[dict],
    klasor: Path,
    yedek_sorgular: list[str] | None = None,
) -> list[Path | None]:
    """Sahneye özel fotoğrafları görsel-metin hakeminden geçirir; yetersiz sahne None kalır."""
    if os.getenv(VISUAL_QA_ENV) != "1":
        raise SystemExit("Görselli üretim kilitli: görsel regresyon kapısı başarıyla çalıştırılmamış.")
    pexels_key = (os.getenv("PEXELS_API_KEY") or os.getenv("PEXELS_KEY") or os.getenv("PEXELS_API") or "").strip()
    pixabay_key = os.getenv("PIXABAY_API_KEY", "").strip()
    providers: list[tuple[str, str, object]] = []
    # Stok önceliği: Pexels, yoksa Pixabay. Cloudflare AI son çare fallback olarak ayrıca denenir.
    if pexels_key:
        providers.append(("pexels", pexels_key, pexels_ara))
    elif pixabay_key:
        providers.append(("pixabay", pixabay_key, pixabay_ara))

    klasor.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    paths: list[Path | None] = []
    report = {
        "version": 1,
        "semantic_model": SEMANTIC_MODEL,
        "threshold": SEMANTIC_THRESHOLD,
        "provider_order": [p[0] for p in providers],
        "scenes": [],
    }

    for scene_index, scene in enumerate(sahneler, start=1):
        scene_text = str(scene.get("ses") or "").strip()
        queries = _sorgu_adaylari(scene)
        scene_log = {
            "scene_index": scene_index,
            "scene_text": scene_text,
            "queries": [],
            "selected": None,
            "fallback": "plain_background",
        }
        selected_path: Path | None = None
        selected_hit: dict | None = None
        selected_query = ""
        selected_provider = ""

        for query in queries:
            query_log = {"query": query, "provider_results": []}
            for provider, api_key, search_fn in providers:
                provider_log = {"provider": provider, "returned_candidate_count": 0, "candidates": []}
                query_log["provider_results"].append(provider_log)
                try:
                    hits = search_fn(query, api_key, adet=MAX_CANDIDATES_PER_QUERY)
                except TypeError:
                    hits = search_fn(query, api_key)
                except Exception as exc:  # noqa: BLE001
                    provider_log["error"] = f"{type(exc).__name__}: {exc}"
                    continue
                provider_log["returned_candidate_count"] = len(hits)
                try:
                    scores = _visual_text_scores(scene_text, hits)
                except Exception as exc:  # noqa: BLE001 — semantic failure must fail closed
                    scores = [None] * len(hits)
                    for hit in hits:
                        hit["_vision_error"] = f"vision_judge:{type(exc).__name__}"
                if len(scores) != len(hits):
                    scores = [None] * len(hits)
                scored = []
                for hit, vision_score in zip(hits, scores):
                    heuristic = float(_puanla(hit, query))
                    score_origin = "live_gemini_vision" if vision_score is not None else None
                    record = {
                        "uid": str(hit.get("uid") or f"{provider}:{hit.get('id','') }"),
                        "provider": provider,
                        "search_query": query,
                        "candidate_tags": str(hit.get("tags") or ""),
                        "heuristic_tag_score": round(heuristic, 3),
                        "semantic_similarity": None if vision_score is None else round(float(vision_score), 4),
                        "score_origin": score_origin,
                        "image_url": str(hit.get("indir_url") or hit.get("fullHDURL") or hit.get("largeImageURL") or ""),
                        "source_page_url": str(hit.get("source_page_url") or ""),
                        "selected": False,
                        "rejection_reason": None,
                    }
                    is_duplicate = record["uid"] in used
                    etiket_metni = str(hit.get("tags") or "").lower()
                    if is_duplicate:
                        record["rejection_reason"] = "duplicate_visual_already_used"
                    elif re.search(r"\b(logo|watermark|filigran)\b", etiket_metni):
                        record["rejection_reason"] = "logo_or_watermark_metadata"
                    elif not _yeterince_uygun(hit, query, scene_text, gevsek=True):
                        record["rejection_reason"] = "provider_metadata_or_photo_quality_filter"
                    elif score_origin is None:
                        record["rejection_reason"] = str(hit.get("_vision_error") or "semantic_score_unavailable_fail_closed")
                    elif not _record_score_passes(record):
                        record["rejection_reason"] = "semantic_similarity_below_threshold"
                    elif not record["image_url"] or not _provider_page_url_ok(provider, record["source_page_url"]):
                        record["rejection_reason"] = "missing_or_invalid_provider_source_url"
                    scored.append((hit, vision_score, record))
                    provider_log["candidates"].append(record)

                eligible = [x for x in scored if _record_score_passes(x[2])
                            and x[2]["rejection_reason"] is None]
                eligible.sort(key=lambda x: (float(x[1]), x[2]["heuristic_tag_score"]), reverse=True)
                for hit, score, record in eligible:
                    uid = record["uid"]
                    raw = klasor / f"ham_{scene_index:02d}.jpg"
                    try:
                        _indir(record["image_url"], raw)
                        with Image.open(raw) as im:
                            im.load()
                            defective, reason = _ham_kusurlu_mu(im)
                            if defective:
                                record["rejection_reason"] = f"pixel_filter:{reason}"
                                raw.unlink(missing_ok=True)
                                continue
                        with Image.open(raw) as im:
                            duzeltilen, logo_bilgi = logo_duzelt(im.convert("RGB"))
                            processed = sinematik_isle(dikey_kirp(duzeltilen), tohum=20261100 + scene_index)
                        record["logo_check"] = logo_bilgi
                        processed_brightness = average_image_brightness(processed)
                        if processed_brightness < MIN_AVG_BRIGHTNESS:
                            record["rejection_reason"] = f"processed_dark_image:{processed_brightness:.1f}/255"
                            raw.unlink(missing_ok=True)
                            continue
                        selected_path = klasor / f"sahne_{scene_index:02d}.png"
                        processed.save(selected_path, format="PNG")
                        record["average_brightness"] = round(processed_brightness, 2)
                        raw.unlink(missing_ok=True)
                        record["selected"] = True
                        record["rejection_reason"] = None
                        selected_hit, selected_query, selected_provider = hit, query, provider
                        used.add(uid)
                        break
                    except Exception as exc:  # noqa: BLE001
                        raw.unlink(missing_ok=True)
                        record["rejection_reason"] = f"download_or_pixel_error:{type(exc).__name__}"
                if selected_path:
                    break
            scene_log["queries"].append(query_log)
            if selected_path:
                break

        if not selected_path:
            cf_hits = cloudflare_ai_gorseller_uret(scene_text, scene_index, klasor, adet=1)
            if cf_hits:
                query_log = {"query": f"cloudflare_ai:{scene_text[:80]}", "provider_results": []}
                provider_log = {"provider": "cloudflare_ai", "returned_candidate_count": len(cf_hits), "candidates": []}
                query_log["provider_results"].append(provider_log)
                try:
                    scores = _visual_text_scores(scene_text, cf_hits)
                except Exception as exc:  # noqa: BLE001
                    scores = [None] * len(cf_hits)
                    for hit in cf_hits:
                        hit["_vision_error"] = f"vision_judge:{type(exc).__name__}"
                if len(scores) != len(cf_hits):
                    scores = [None] * len(cf_hits)
                scored = []
                for hit, vision_score in zip(cf_hits, scores):
                    heuristic = float(_puanla(hit, scene_text))
                    score_origin = "live_gemini_vision" if vision_score is not None else None
                    record = {
                        "uid": str(hit.get("uid") or f"cloudflare_ai:{scene_index}"),
                        "provider": "cloudflare_ai",
                        "search_query": query_log["query"],
                        "candidate_tags": str(hit.get("tags") or ""),
                        "heuristic_tag_score": round(heuristic, 3),
                        "semantic_similarity": None if vision_score is None else round(float(vision_score), 4),
                        "score_origin": score_origin,
                        "image_url": str(hit.get("indir_url") or ""),
                        "source_page_url": str(hit.get("source_page_url") or "https://developers.cloudflare.com/workers-ai/"),
                        "selected": False,
                        "rejection_reason": None,
                    }
                    is_duplicate = record["uid"] in used
                    etiket_metni = str(hit.get("tags") or "").lower()
                    if is_duplicate:
                        record["rejection_reason"] = "duplicate_visual_already_used"
                    elif re.search(r"\b(logo|watermark|filigran)\b", etiket_metni):
                        record["rejection_reason"] = "logo_or_watermark_metadata"
                    elif not _yeterince_uygun(hit, scene_text, scene_text, gevsek=True):
                        record["rejection_reason"] = "provider_metadata_or_photo_quality_filter"
                    elif score_origin is None:
                        record["rejection_reason"] = str(hit.get("_vision_error") or "semantic_score_unavailable_fail_closed")
                    elif not _record_score_passes(record):
                        record["rejection_reason"] = "semantic_similarity_below_threshold"
                    elif not record["image_url"] or not _provider_page_url_ok("cloudflare_ai", record["source_page_url"]):
                        record["rejection_reason"] = "missing_or_invalid_provider_source_url"
                    scored.append((hit, vision_score, record))
                    provider_log["candidates"].append(record)
                eligible = [x for x in scored if _record_score_passes(x[2]) and x[2]["rejection_reason"] is None]
                eligible.sort(key=lambda x: (float(x[1]), x[2]["heuristic_tag_score"]), reverse=True)
                for hit, score, record in eligible:
                    uid = record["uid"]
                    raw = klasor / f"ham_{scene_index:02d}.jpg"
                    try:
                        _indir(record["image_url"], raw)
                        with Image.open(raw) as im:
                            im.load()
                            defective, reason = _ham_kusurlu_mu(im)
                            if defective:
                                record["rejection_reason"] = f"pixel_filter:{reason}"
                                raw.unlink(missing_ok=True)
                                continue
                        with Image.open(raw) as im:
                            duzeltilen, logo_bilgi = logo_duzelt(im.convert("RGB"))
                            processed = sinematik_isle(dikey_kirp(duzeltilen), tohum=20261100 + scene_index)
                        record["logo_check"] = logo_bilgi
                        processed_brightness = average_image_brightness(processed)
                        if processed_brightness < MIN_AVG_BRIGHTNESS:
                            record["rejection_reason"] = f"processed_dark_image:{processed_brightness:.1f}/255"
                            raw.unlink(missing_ok=True)
                            continue
                        selected_path = klasor / f"sahne_{scene_index:02d}.png"
                        processed.save(selected_path, format="PNG")
                        record["average_brightness"] = round(processed_brightness, 2)
                        raw.unlink(missing_ok=True)
                        record["selected"] = True
                        record["rejection_reason"] = None
                        selected_hit, selected_query, selected_provider = hit, query_log["query"], "cloudflare_ai"
                        used.add(uid)
                        break
                    except Exception as exc:  # noqa: BLE001
                        raw.unlink(missing_ok=True)
                        record["rejection_reason"] = f"download_or_pixel_error:{type(exc).__name__}"
                scene_log["queries"].append(query_log)

        if selected_path and selected_hit:
            scene_log["selected"] = {
                "provider": selected_provider,
                "search_query": selected_query,
                "uid": str(selected_hit.get("uid") or f"{selected_provider}:{selected_hit.get('id','')}"),
                "semantic_similarity": next(
                    (c["semantic_similarity"] for q in scene_log["queries"]
                     for p in q["provider_results"] for c in p["candidates"] if c.get("selected")), None),
                "score_origin": next(
                    (c["score_origin"] for q in scene_log["queries"]
                     for p in q["provider_results"] for c in p["candidates"] if c.get("selected")), None),
                "average_brightness": next(
                    (c["average_brightness"] for q in scene_log["queries"]
                     for p in q["provider_results"] for c in p["candidates"]
                     if c.get("selected") and c.get("average_brightness") is not None), None),
                "image_url": str(selected_hit.get("indir_url") or selected_hit.get("fullHDURL") or selected_hit.get("largeImageURL") or ""),
                "source_page_url": str(selected_hit.get("source_page_url") or ""),
            }
            scene_log["fallback"] = None
            display_score = scene_log["selected"]["semantic_similarity"]
            print(f"  görsel {scene_index}: {selected_provider} / sorgu={selected_query!r} / Gemini Vision={display_score} / {scene_log['selected']['source_page_url']}")
        else:
            reason = "no_scene_specific_query" if not queries else "no_candidate_passed_semantic_threshold_or_pixel_checks"
            scene_log["fallback_reason"] = reason
            print(f"  sahne {scene_index}: görsel seçilmedi ({reason}); düz zemin + metin kullanılacak.")
        paths.append(selected_path)
        report["scenes"].append(scene_log)
        _gorsel_kalite_logunu_yaz(klasor, report)

    cf_ready = bool((os.getenv("CLOUDFLARE_ACCOUNT_ID") or "").strip() and (os.getenv("CLOUDFLARE_API_TOKEN") or "").strip())
    if not providers and not cf_ready:
        report["provider_error"] = "No image providers configured (PEXELS/PIXABAY/CLOUDFLARE)"
        _gorsel_kalite_logunu_yaz(klasor, report)

    # Tek satırlık, sızdırmaz tanı özeti: hangi kapının görseli reddettiği net görülür.
    nedenler: dict[str, int] = {}
    skorlar: list[float] = []
    for sahne in report["scenes"]:
        for q in sahne.get("queries", []):
            for pr in q.get("provider_results", []):
                for aday in pr.get("candidates", []):
                    neden = str(aday.get("rejection_reason") or "secildi")
                    nedenler[neden] = nedenler.get(neden, 0) + 1
                    skor = aday.get("semantic_similarity")
                    if isinstance(skor, (int, float)):
                        skorlar.append(float(skor))
    ozet = {
        "sahne": len(report["scenes"]),
        "secilen": sum(1 for s in report["scenes"] if s.get("selected")),
        "esik": SEMANTIC_THRESHOLD,
        "skor_araligi": [round(min(skorlar), 3), round(max(skorlar), 3)] if skorlar else None,
        "reddetme_nedenleri": dict(sorted(nedenler.items(), key=lambda x: (-x[1], x[0]))),
    }
    print("GORSEL_SECIM_OZET: " + json.dumps(ozet, ensure_ascii=False, sort_keys=True), flush=True)
    return paths
