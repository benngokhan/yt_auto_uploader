#!/usr/bin/env python3
"""Senaryo denetimi — yapay zekâsız BULUCULAR (bu dosya metni değiştirmez; karar motor/uret.py'dedir).

16.11.2026 (sahip kararı): terim çiftleri ve "yaklaşık + tek sayı" artık üretim öncesi düzeltme/durma sebebidir;
bu dosya yalnız bulur, düzeltmeyi ve durdurmayı uret.py yapar. Birimli diğer kesin sayılar uyarı olarak kalır.

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

_SAYI = rf"(?:\d[\d.,]*|(?:{_SAYI_KELIMELERI})(?:\s+(?:{_SAYI_KELIMELERI}))*)(?!\w)"
# Aralık: "480 ile 530 derece (arasında)", "dört yüz seksen ile beş yüz otuz derece", "480-530 derece", "%20 ile %30"
_ARALIK = re.compile(rf"(?<![\w%])(?:(?:%\s?|yüzde\s+){_SAYI}\s*(?:-|–|—|ile|ila)\s*(?:%\s?|yüzde\s+)?{_SAYI}"
                     rf"|{_SAYI}\s*(?:-|–|—|ile|ila)\s*{_SAYI}\s*(?:%|(?:{_BIRIMLER})\w*))", re.I)
_YAKLASIK_ONCE = re.compile(r"(?<!\w)(yaklaşık|ortalama|aşağı yukarı|kabaca|tahminen)(?:\s+olarak)?\s+(?:\w+\s+){0,1}$", re.I)
_YAKLASIK_SONRA = re.compile(r"^\w*\s+(?:\w+\s+)?(civar\w*|dolay\w*)", re.I)

# Aynı şey (havada asılı küçük parça) için kullanılan adlar: metinde yalnız BİRİ kullanılabilir.
TERIM_GRUPLARI = {
    "küçük parçacık": ("zerrecik", "damlacık", "tanecik", "parçacık"),
}


def _kucult(metin: str) -> str:
    return str(metin or "").replace("İ", "i").replace("I", "ı").lower()


def _tek_sayilar(metin: str) -> list[tuple[int, int, str]]:
    """Küçük harfli metinde ARALIK OLMAYAN birimli sayılar: [(başlangıç, bitiş, ifade)]."""
    maskeli = _ARALIK.sub(lambda m: " " * len(m.group(0)), metin)
    bulunan = [(m.start(), m.end(), m.group(0).strip()) for m in _RAKAMLI.finditer(maskeli)]
    for m in _YAZILI.finditer(maskeli):
        sayi = m.group(1).strip()
        if sayi == "bir":            # "bir saniye", "bir kat" çoğu zaman belirsizlik sözüdür
            continue
        if any(b <= m.start() < e for b, e, _ in bulunan):   # "yüzde otuz ..." zaten alındı
            continue
        bulunan.append((m.start(), m.end(), f"{sayi} {m.group(2)}"))
    return sorted(bulunan)


def aralik_bul(cumleler: list) -> list[dict]:
    """Aralık biçiminde verilen sayılar: [{'cumle': 5, 'ifade': '480 ile 530 derece'}]."""
    return [{"cumle": i, "ifade": m.group(0).strip()}
            for i, c in enumerate(cumleler, start=1) for m in _ARALIK.finditer(_kucult(c))]


def kesin_sayi_bul(cumleler: list) -> list[dict]:
    """Birimli TEK (aralık olmayan) sayıları döndürür: [{'cumle': 5, 'ifade': 'beş yüz derece'}]."""
    bulunan = []
    for i, c in enumerate(cumleler, start=1):
        for ifade in dict.fromkeys(x[2] for x in _tek_sayilar(_kucult(c))):
            bulunan.append({"cumle": i, "ifade": ifade})
    return bulunan


def yaklasik_tek_sayi_bul(cumleler: list) -> list[dict]:
    """KURAL İHLALİ: 'yaklaşık/ortalama/civarında' denip TEK sayı verilmiş (aralık verilmeli).

    [{'cumle': 5, 'ifade': 'beş yüz derece', 'belirtec': 'ortalama'}]
    """
    bulunan = []
    for i, c in enumerate(cumleler, start=1):
        metin = _kucult(c)
        for bas, son, ifade in _tek_sayilar(metin):
            once = _YAKLASIK_ONCE.search(metin[max(0, bas - 40):bas])
            sonra = _YAKLASIK_SONRA.search(metin[son:son + 30])
            if once or sonra:
                bulunan.append({"cumle": i, "ifade": ifade, "belirtec": (once or sonra).group(1)})
    return bulunan


def ana_terim(gecen: dict) -> str:
    """Çift adlandırmada korunacak terim: en çok cümlede geçen; eşitlikte metinde ilk geçen."""
    return max(gecen, key=lambda ad: (len(gecen[ad]), -min(gecen[ad])))


def grup_terimleri(cumle: str) -> dict:
    """Tek cümlede geçen grup terimleri: {'küçük parçacık': ['zerrecik', ...]}."""
    metin = _kucult(cumle)
    return {g: [ad for ad in adlar if re.search(rf"(?<!\w){ad[:-1]}[kğ]", metin)]
            for g, adlar in TERIM_GRUPLARI.items()}


def isimlendirme_listesi(cumleler: list) -> str:
    """Uzatma/yeniden yazma istemlerine eklenecek satır; metinde grup terimi yoksa boş."""
    satirlar = []
    for grup, adlar in TERIM_GRUPLARI.items():
        gecen: dict[str, list[int]] = {}
        for i, c in enumerate(cumleler, start=1):
            for ad in grup_terimleri(c)[grup]:
                gecen.setdefault(ad, []).append(i)
        if gecen:
            ana = ana_terim(gecen)
            yasak = ", ".join(a for a in adlar if a != ana)
            satirlar.append(f"- İSİMLENDİRME LİSTESİ: bu videoda {grup} için YALNIZCA '{ana}' adı kullanılıyor; "
                            f"şu adları YAZMA: {yasak}.\n")
    return "".join(satirlar)


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
    for s in yaklasik_tek_sayi_bul(cumleler):
        satirlar.append(f"yaklaşık değer tek sayıyla verilmiş (aralık gerekir): {s['cumle']}. cümlede "
                        f"'{s['belirtec']} … {s['ifade']}'")
    for t in terim_tutarsizligi_bul(cumleler):
        ayrinti = ", ".join(f"'{ad}' ({'/'.join(map(str, yer))}. cümle)" for ad, yer in t["terimler"].items())
        satirlar.append(f"terim tutarsızlığı ({t['grup']}): {ayrinti}")
    return satirlar
