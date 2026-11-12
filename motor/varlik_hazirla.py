#!/usr/bin/env python3
"""Eksik varlıkları hazırlar: fontlar (Montserrat Black/Bold, NotoColorEmoji) + fon müziği.

* Fontlar açık lisanslı (OFL) kaynaklardan indirilir, repoya commit edilmez.
* Fon müziği `bgm_composer.py` ile ÜRETİLİR → dış lisans sorunu yok.
* Fonksiyon idempotent: dosya varsa indirmez.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

MOTOR = Path(__file__).resolve().parent
ASSETS = MOTOR / "assets"

FONTLAR = {
    "Montserrat-Black.ttf": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Black.ttf",
    "Montserrat-Bold.ttf": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Bold.ttf",
    "Montserrat-ExtraBold.ttf": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-ExtraBold.ttf",
    "NotoColorEmoji.ttf": "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/2D/fonts/NotoColorEmoji.ttf",
    "Anton-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
    "Poppins-SemiBold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-SemiBold.ttf",
    "Poppins-Medium.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Medium.ttf",
    # Şablon v2 başlık/altyazı fontu: Poppins Bold + Black
    "Poppins-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Bold.ttf",
    "Poppins-Black.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Black.ttf",
    # Şablon v2.0 kaynak/uyarı satırı fontu
    "Poppins-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Regular.ttf",
    "ArchivoBlack-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/archivoblack/ArchivoBlack-Regular.ttf",
    "BebasNeue-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf",
}


def _indir(url: str, hedef: Path) -> None:
    istek = urllib.request.Request(url, headers={"User-Agent": "bilgidozu-motor/1.0"})
    with urllib.request.urlopen(istek, timeout=180) as y:
        veri = y.read()
    if len(veri) < 20_000:
        raise SystemExit(f"İndirilen dosya çok küçük, iptal: {hedef.name} ({len(veri)} bayt)")
    hedef.write_bytes(veri)


def hazirla(mood: str = "doga_kesif", bgm_adi: str = "ambient_science_bgm.wav") -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)

    for ad, url in FONTLAR.items():
        yol = ASSETS / ad
        if not yol.exists() or yol.stat().st_size < 20_000:
            print(f"  indiriliyor: {ad}")
            _indir(url, yol)

    bgm = ASSETS / bgm_adi
    if not bgm.exists() or bgm.stat().st_size < 100_000:
        print(f"  fon müziği üretiliyor: {mood}")
        sys.path.insert(0, str(MOTOR))
        import bgm_composer
        bgm_composer.generate_topic_bgm(str(bgm), mood=mood, duration_sec=70.0)
    return ASSETS


if __name__ == "__main__":
    print(hazirla())
