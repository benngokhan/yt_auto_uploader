#!/usr/bin/env python3
"""Senaryo denetimi — YALNIZ UYARI VERİR (metni değiştirmez, üretimi durdurmaz).

Bilinen hatalardan (63/64/65. üretimler) çıkarılmış iki basit, yapay zekâsız denetim:
  * kesin_sayi_bul        : "beş yüz derece", "2 mikrometre" gibi birimli kesin sayıları işaretler.
                            Motor sayının doğruluğunu denetleyemediği için HER birimli kesin sayı
                            "doğrulanamayan kesin sayı" olarak işaretlenir.
  * terim_tutarsizligi_bul: aynı küçük parçacık için birden çok ad kullanılmışsa uyarır
                            (zerrecik / damlacık / tanecik / parçacık).
Senaryo yazan yapay zekâya verilen kurallar (TERIM_KURALLARI) ve yazım denetimi burada DEĞİŞTİRİLMEZ.
"""
from __future__ import annotations

import re

_SAYI_KELIMELERI = ("sıfır|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|yirmi|otuz|kırk|elli|altmış|yetmiş|seksen|doksan"
                    "|yüz|bin|milyon|milyar|trilyon|yarım|buçuk")
_BIRIMLER = ("derece|santigrat|kelvin|mikrometre|nanometre|milimetre|santimetre|metre|kilometre|mikron"
             "|miligram|gram|kilogram|kilo|ton|mililitre|litre|saniye|salise|dakika|saat|gün|hafta|ay|yıl|yüzyıl"
             "|kat|katı|volt|watt|hertz|desibel|kalori|joule|pascal|bar|atmosfer|km|cm|mm|kg|dk|sn|°c|°")
_RAKAMLI = re.compile(rf"(?<![\w%])(%\s?\d[\d.,]*|\d[\d.,]*\s?%|yüzde\s+(?:\d[\d.,]*|(?:{_SAYI_KELIMELERI})(?:\s+(?:{_SAYI_KELIMELERI}))*)"
                      rf"|\d[\d.,]*\s?(?:{_BIRIMLER})\w*)", re.I)
_YAZILI = re.compile(rf"(?<!\w)((?:{_SAYI_KELIMELERI})(?:\s+(?:{_SAYI_KELIMELERI}|virgül))*)\s+((?:{_BIRIMLER})\w*)", re.I)

# Aynı şey (havada asılı küçük parça) için kullanılan adlar. Yalnız UYARI içindir.
TERIM_GRUPLARI = {
    "küçük parçacık": ("zerrecik", "damlacık", "tanecik", "parçacık"),
}


def _kucult(metin: str) -> str:
    return str(metin or "").replace("İ", "i").replace("I", "ı").lower()


def kesin_sayi_bul(cumleler: list) -> list[dict]:
    """Birimli kesin sayıları döndürür: [{'cumle': 5, 'ifade': 'beş yüz derece'}]."""
    bulunan = []
    for i, c in enumerate(cumleler, start=1):
        metin = _kucult(c)
        ifadeler = [m.group(0).strip() for m in _RAKAMLI.finditer(metin)]
        for m in _YAZILI.finditer(metin):
            sayi = m.group(1).strip()
            if sayi == "bir":            # "bir saniye", "bir kat" çoğu zaman belirsizlik sözüdür
                continue
            ifadeler.append(f"{sayi} {m.group(2)}")
        for ifade in dict.fromkeys(ifadeler):
            bulunan.append({"cumle": i, "ifade": ifade})
    return bulunan


def terim_tutarsizligi_bul(cumleler: list) -> list[dict]:
    """Aynı gruptan birden çok ad kullanıldıysa döndürür: [{'grup':..., 'terimler': {'zerrecik': [2,4], 'damlacık': [3]}}]."""
    sonuc = []
    for grup, adlar in TERIM_GRUPLARI.items():
        gecen: dict[str, list[int]] = {}
        for i, c in enumerate(cumleler, start=1):
            metin = _kucult(c)
            for ad in adlar:
                if re.search(rf"(?<!\w){ad[:-1]}[kğ]", metin):   # zerrecik / zerreciği / zerrecikler…
                    gecen.setdefault(ad, []).append(i)
        if len(gecen) >= 2:
            sonuc.append({"grup": grup, "terimler": gecen})
    return sonuc


def uyarilar(cumleler: list) -> list[str]:
    """Senaryo için okunur uyarı satırları (boş liste = uyarı yok)."""
    satirlar = []
    for s in kesin_sayi_bul(cumleler):
        satirlar.append(f"doğrulanamayan kesin sayı: {s['cumle']}. cümlede '{s['ifade']}'")
    for t in terim_tutarsizligi_bul(cumleler):
        ayrinti = ", ".join(f"'{ad}' ({'/'.join(map(str, yer))}. cümle)" for ad, yer in t["terimler"].items())
        satirlar.append(f"terim tutarsızlığı ({t['grup']}): {ayrinti}")
    return satirlar
