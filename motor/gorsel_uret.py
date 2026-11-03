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


def pixabay_ara(sorgu: str, anahtar: str, adet: int = 20) -> list[dict]:
    """Dikey, yüksek çözünürlüklü fotoğraf sonuçları (beğeniye göre sıralı)."""
    parametre = {
        "key": anahtar,
        "q": sorgu,
        "image_type": "photo",
        "orientation": "vertical",
        "min_width": 1600,
        "min_height": 1600,
        "safesearch": "true",
        "order": "popular",
        "per_page": str(min(adet, 200)),
        "lang": "en",
    }
    veri = _istek(f"{ARAMA_URL}?{urllib.parse.urlencode(parametre)}")
    return [h for h in veri.get("hits", []) if h.get("imageWidth", 0) >= 1600]


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


def _indir(url: str, hedef: Path) -> None:
    istek = urllib.request.Request(url, headers={"User-Agent": "bilgidozu-motor/1.0"})
    with urllib.request.urlopen(istek, timeout=120) as y:
        hedef.write_bytes(y.read())


def sahneler_icin_gorseller(sahneler: list[dict], klasor: Path, sorgular: dict | None = None) -> list[Path]:
    """Her sahne için bir görsel indirir, 1080x1920 PNG olarak kaydeder."""
    anahtar = os.getenv("PIXABAY_API_KEY", "").strip()
    if not anahtar:
        raise SystemExit("PIXABAY_API_KEY yok — görseller indirilemedi, üretim durdu.")
    klasor.mkdir(parents=True, exist_ok=True)
    sorgular = sorgular or {}

    kullanilan: set[int] = set()
    yollar: list[Path] = []
    for i, sahne in enumerate(sahneler, start=1):
        sorgu = sahne.get("gorsel") or sorgular.get(i) or sahne.get("baslik2") or "science"
        sonuc = [h for h in pixabay_ara(str(sorgu), anahtar) if h["id"] not in kullanilan]
        if not sonuc:
            raise SystemExit(f"Sahne {i} için Pixabay sonucu yok (sorgu: {sorgu!r}) — üretim durdu.")

        ham = klasor / f"ham_{i:02d}.jpg"
        _indir(sonuc[0]["largeImageURL"], ham)
        kullanilan.add(sonuc[0]["id"])

        png = klasor / f"sahne_{i:02d}.png"
        with Image.open(ham) as im:
            dikey_kirp(im.convert("RGB")).save(png)
        yollar.append(png)
        print(f"  görsel {i}: pixabay#{sonuc[0]['id']} / sorgu={sorgu!r}")
    return yollar
