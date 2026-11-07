#!/usr/bin/env python3
"""Altyazıyı noktalama ve ekran sınırlarına göre gruplar.

Her yeni cümle mutlaka yeni altyazı grubundan başlar; önceki cümlenin
son kelimeleriyle aynı kartta birleştirilmez.
"""
from __future__ import annotations
import re

AZAMI_KELIME = 5
_CUMLE_SONU = re.compile(r"(?<=[.!?])(?:[\"”’']*)\s+")


def _cumleler(metin: str) -> list[str]:
    return [p.strip() for p in _CUMLE_SONU.split(metin.strip()) if p.strip()]


def grupla(metin: str, azami: int = AZAMI_KELIME) -> list[tuple[str, list[str]]]:
    if not metin.strip():
        return []
    sonuc: list[tuple[str, list[str]]] = []
    for cumle in _cumleler(metin):
        kelimeler = cumle.split()
        gruplar = [kelimeler[i:i + azami] for i in range(0, len(kelimeler), azami)]
        # Yalnızca aynı cümle içinde dengele; nokta sonrasını asla geriye ekleme.
        if len(gruplar) > 1 and len(gruplar[-1]) < 2:
            gruplar[-2].extend(gruplar.pop())
        sonuc.extend((" ".join(g), []) for g in gruplar)
    return sonuc


if __name__ == "__main__":
    for parca in grupla("Yardıma muhtaç bir yunus. Gerçekten yardım istiyor."):
        print(parca[0])
