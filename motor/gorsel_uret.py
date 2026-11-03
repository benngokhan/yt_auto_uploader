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
        puan += 2.0
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


def _sorgu_adaylari(sahne: dict, yedek: list[str]) -> list[str]:
    adaylar = []
    if sahne.get("gorsel"):
        adaylar.append(str(sahne["gorsel"]))
    adaylar += yedek
    adaylar.append("science laboratory")
    # tekrarları at
    return list(dict.fromkeys(a.strip() for a in adaylar if a and a.strip()))


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
    for i, sahne in enumerate(sahneler, start=1):
        secim = None
        denenen = []
        for sorgu in _sorgu_adaylari(sahne, yedek):
            denenen.append(sorgu)
            sonuc = [h for h in pixabay_ara(sorgu, anahtar) if h["id"] not in kullanilan]
            if sonuc:
                secim = (sorgu, sonuc[0])
                break
        if not secim:
            raise SystemExit(
                f"Sahne {i} için Pixabay sonucu yok (denenen: {denenen}) — üretim durdu.")

        sorgu, hit = secim
        ham = klasor / f"ham_{i:02d}.jpg"
        _indir(hit["largeImageURL"], ham)
        kullanilan.add(hit["id"])

        png = klasor / f"sahne_{i:02d}.png"
        with Image.open(ham) as im:
            dikey_kirp(im.convert("RGB")).save(png)
        yollar.append(png)
        print(f"  görsel {i}: pixabay#{hit['id']} / sorgu={sorgu!r} / etiket={str(hit.get('tags'))[:60]}")
    return yollar
