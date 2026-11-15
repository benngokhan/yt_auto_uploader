#!/usr/bin/env python3
"""Seslendirme öncesi metin hazırlığı (motordan bağımsız).

Hangi ses servisi kullanılırsa kullanılsın metin aynı şekilde hazırlanır:
  1) Sayılar yazıya çevrilir      : "13" -> "on üç", "2,5" -> "iki virgül beş",
                                    "%50" -> "yüzde elli", "14:30" -> "on dört otuz",
                                    "29.10.1923" -> "yirmi dokuz Ekim bin dokuz yüz yirmi üç"
  2) Kısaltmalar açılır           : "dk" -> "dakika", "5 km" -> "beş kilometre", "vb." -> "vesaire"
  3) İstisnalar olduğu gibi kalır : marka adları, İngilizce teknik terimler vb.

Tek giriş noktası: hazirla(metin, ayar). Yalnız motor/tts.py -> uret() çağırır.
Listeler motor/ayarlar.json -> "metin_hazirlik" bölümünden genişletilir; kod değişmez.

Not: Bu fonksiyon yalnız SESE giden metni değiştirir. Ekrandaki altyazı senaryodaki
özgün yazımı ("13", "%50") kullanmaya devam eder.
"""
from __future__ import annotations

import re

HARF = "A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû"
_KUCUK = "a-zçğıöşüâîû"
_BUYUK = "A-ZÇĞİÖŞÜÂÎÛ"

BIRLER = ["sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
ONLAR = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
BUYUKLER = ["", "bin", "milyon", "milyar", "trilyon", "katrilyon"]
AYLAR = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
         "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
SIRA = {
    "sıfır": "sıfırıncı", "bir": "birinci", "iki": "ikinci", "üç": "üçüncü", "dört": "dördüncü",
    "beş": "beşinci", "altı": "altıncı", "yedi": "yedinci", "sekiz": "sekizinci", "dokuz": "dokuzuncu",
    "on": "onuncu", "yirmi": "yirminci", "otuz": "otuzuncu", "kırk": "kırkıncı", "elli": "ellinci",
    "altmış": "altmışıncı", "yetmiş": "yetmişinci", "seksen": "sekseninci", "doksan": "doksanıncı",
    "yüz": "yüzüncü", "bin": "bininci", "milyon": "milyonuncu", "milyar": "milyarıncı",
    "trilyon": "trilyonuncu", "katrilyon": "katrilyonuncu",
}

# Her yerde açılan kısaltmalar (tam kelime olarak geçtiğinde).
VARSAYILAN_KISALTMALAR = {
    "vb.": "vesaire", "vs.": "vesaire", "vd.": "ve diğerleri", "örn.": "örneğin",
    "bkz.": "bakınız", "yy.": "yüzyıl", "yak.": "yaklaşık", "ort.": "ortalama",
    "M.Ö.": "milattan önce", "MÖ": "milattan önce", "M.S.": "milattan sonra",
    "Dr.": "Doktor", "Prof.": "Profesör", "Doç.": "Doçent",
    "dk": "dakika", "dk.": "dakika", "sn": "saniye", "sn.": "saniye",
    "km": "kilometre", "cm": "santimetre", "mm": "milimetre", "kg": "kilogram",
    "24/7": "yedi gün yirmi dört saat",
}

# Yalnız bir sayıdan hemen sonra açılan birimler ("5 m" -> "beş metre").
# Açılımda {n} varsa sayı oraya yerleşir ("90 km/sa" -> "saatte doksan kilometre").
VARSAYILAN_BIRIMLER = {
    "mm": "milimetre", "cm": "santimetre", "m": "metre", "km": "kilometre",
    "m²": "metrekare", "km²": "kilometrekare", "m³": "metreküp",
    "mg": "miligram", "g": "gram", "gr": "gram", "kg": "kilogram",
    "ml": "mililitre", "lt": "litre", "L": "litre",
    "ms": "milisaniye", "sn": "saniye", "dk": "dakika", "sa": "saat",
    "km/sa": "saatte {n} kilometre", "km/s": "saniyede {n} kilometre", "m/s": "saniyede {n} metre",
    "Hz": "hertz", "kHz": "kilohertz", "MHz": "megahertz", "GHz": "gigahertz",
    "W": "vat", "kW": "kilovat", "V": "volt",
    "MB": "megabayt", "GB": "gigabayt", "TB": "terabayt",
    "kcal": "kilokalori", "°C": "derece", "°": "derece",
    "TL": "lira", "₺": "lira", "$": "dolar", "€": "avro",
}

VARSAYILAN_ISTISNALAR: list[str] = []

# Sayı kalıbı: 1.500 / 1.250.000 / 2,5 / 2.5 / 13
_SAYI = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
_ONCE = rf"(?<![{HARF}\d])(?<![{HARF}]-)"   # öncesinde harf/rakam yok ("COVID-19" gibi kod adları da korunur)
_SONRA = rf"(?![{HARF}\d])"          # sonrasında harf/rakam yok
_EK = rf"(?:['’](?=[{_KUCUK}])|{_SONRA})"   # ya ek gelir ("km'lik" -> kesme düşer) ya da kelime biter


# ------------------------------------------------------------------ sayılar
def _uc_hane(n: int) -> list[str]:
    parca = []
    yuz, kalan = divmod(n, 100)
    if yuz:
        if yuz > 1:
            parca.append(BIRLER[yuz])
        parca.append("yüz")
    on, bir = divmod(kalan, 10)
    if on:
        parca.append(ONLAR[on])
    if bir:
        parca.append(BIRLER[bir])
    return parca


def tam_sayi(n: int) -> str:
    """0 -> 'sıfır', 13 -> 'on üç', 1000 -> 'bin', 2026 -> 'iki bin yirmi altı'."""
    if n == 0:
        return "sıfır"
    gruplar = []
    while n:
        n, g = divmod(n, 1000)
        gruplar.append(g)
    if len(gruplar) > len(BUYUKLER):
        raise ValueError("sayı çok büyük")
    parca: list[str] = []
    for i in range(len(gruplar) - 1, -1, -1):
        g = gruplar[i]
        if not g:
            continue
        if not (i == 1 and g == 1):       # "bir bin" denmez, "bin" denir
            parca.extend(_uc_hane(g))
        if BUYUKLER[i]:
            parca.append(BUYUKLER[i])
    return " ".join(parca)


def _rakam_rakam(s: str) -> str:
    return " ".join(BIRLER[int(c)] for c in s)


def _tam_oku(s: str) -> str:
    """Rakam dizisini okur; başta sıfır varsa ya da çok uzunsa rakam rakam."""
    if (len(s) > 1 and s[0] == "0") or len(s) > 18:
        return _rakam_rakam(s)
    return tam_sayi(int(s))


def sayi_oku(s: str) -> str:
    """'13' / '1.500' / '2,5' / '2.5' / '0,05' -> yazıyla."""
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):
        tam, _, kesir = s.partition(",")
        tam = tam.replace(".", "")
    else:
        m = re.fullmatch(r"(\d+)(?:[.,](\d+))?", s)
        tam, kesir = m.group(1), m.group(2) or ""
    okunus = _tam_oku(tam)
    if kesir:
        if kesir[0] == "0" or len(kesir) > 3:
            okunus += " virgül " + _rakam_rakam(kesir)
        else:
            okunus += " virgül " + tam_sayi(int(kesir))
    return okunus


def sira_oku(s: str) -> str:
    """'3' -> 'üçüncü', '19' -> 'on dokuzuncu'."""
    kelimeler = _tam_oku(s).split()
    kelimeler[-1] = SIRA.get(kelimeler[-1], kelimeler[-1])
    return " ".join(kelimeler)


def _b(m, okunus: str) -> str:
    """Çeviri cümle başına geldiyse ilk harfi büyütür ("13 kişi" -> "On üç kişi").
    Yalnız çevrilen parçaya uygulanır; özgün metnin harflerine dokunulmaz."""
    once = m.string[:m.start()]
    if okunus and (not once.strip() or re.search(r"[.!?]\s+$", once)):
        return {"i": "İ", "ı": "I"}.get(okunus[0], okunus[0].upper()) + okunus[1:]
    return okunus


# ------------------------------------------------------------------ adımlar
def _koru(metin: str, istisnalar: list[str]) -> tuple[str, list[str]]:
    """İstisnaları, içinde rakam/harf olmayan yer tutucularla değiştirir."""
    saklanan: list[str] = []
    for ifade in sorted({i for i in istisnalar if i and i.strip()}, key=len, reverse=True):
        kalip = re.compile(_ONCE + re.escape(ifade.strip()) + _SONRA, re.IGNORECASE)

        def _yer(m, saklanan=saklanan):
            saklanan.append(m.group(0))
            return f"\uE000{chr(0xE100 + len(saklanan) - 1)}\uE001"

        metin = kalip.sub(_yer, metin)
    return metin, saklanan


def _geri_koy(metin: str, saklanan: list[str]) -> str:
    return re.sub("\uE000(.)\uE001", lambda m: saklanan[ord(m.group(1)) - 0xE100], metin)


def _kisaltmalari_ac(metin: str, kisaltmalar: dict) -> str:
    for kisa in sorted(kisaltmalar, key=len, reverse=True):
        acik = str(kisaltmalar[kisa])
        kalip = re.compile(_ONCE + re.escape(kisa) + _EK)

        def _ac(m, kisa=kisa, acik=acik):
            # "vb." cümle sonundaysa noktayı koru; unvanlarda ("Dr.") koruma.
            if kisa.endswith(".") and kisa[:1].islower():
                kalan = m.string[m.end():]
                if not kalan.strip() or re.match(rf"\s+[\"“‘'(]?[{_BUYUK}]", kalan):
                    return acik + "."
            return acik

        metin = kalip.sub(_ac, metin)
    return metin


def _tarihler(metin: str) -> str:
    def _t(m):
        gun, ay, yil = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= gun <= 31 and 1 <= ay <= 12):
            return m.group(0)
        return f"{gun} {AYLAR[ay]} {yil}"
    return re.sub(r"(?<![\d.,/])(\d{1,2})[./](\d{1,2})[./](\d{4})(?![\d/]|[.,]\d)", _t, metin)


def _saatler(metin: str) -> str:
    def _s(m):
        saat, dakika = m.group(1), m.group(2)
        okunus = tam_sayi(int(saat))
        if dakika != "00":
            okunus += " " + (_rakam_rakam(dakika) if dakika[0] == "0" else tam_sayi(int(dakika)))
        return _b(m, okunus + (m.group(3) or ""))      # "14:30'da" -> "on dört otuzda"
    return re.sub(rf"(?<![\d:{HARF}])([01]?\d|2[0-3]):([0-5]\d)(?:['’]([{_KUCUK}]+)|(?![\d:{HARF}]))", _s, metin)


def _yuzdeler(metin: str) -> str:
    metin = re.sub(rf"%\s?(?=\d)", lambda m: _b(m, "yüzde "), metin)
    return re.sub(rf"{_ONCE}({_SAYI})\s?%", lambda m: _b(m, "yüzde ") + m.group(1), metin)


def _birimler(metin: str, birimler: dict) -> str:
    # Öne yazılan para simgesi: "$5" -> "5 $"
    metin = re.sub(rf"([$€₺])\s?({_SAYI})", r"\2 \1", metin)
    for birim in sorted(birimler, key=len, reverse=True):
        acik = str(birimler[birim])
        son = _EK if re.search(rf"[{HARF}\d]$", birim) else rf"(?:['’](?=[{_KUCUK}]))?"
        # Birimden sonraki kısaltma noktası cümle ortasındaysa düşer ("20 dk. sürdü")
        kalip = re.compile(rf"{_ONCE}({_SAYI})\s?{re.escape(birim)}{son}(?:\.(?=\s+[{_KUCUK}]))?")
        if "{n}" in acik:
            metin = kalip.sub(lambda m, a=acik: a.replace("{n}", m.group(1)), metin)
        else:
            metin = kalip.sub(lambda m, a=acik: f"{m.group(1)} {a}", metin)
    return metin


def _araliklar(metin: str) -> str:
    """'30-45' / '30–45' -> '30 ile 45'."""
    return re.sub(rf"{_ONCE}({_SAYI})\s?[-–—]\s?({_SAYI}){_SONRA}", r"\1 ile \2", metin)


def _bulunma_eki(kelime: str) -> str:
    """'üç' -> 'üçte', 'dört' -> 'dörtte', 'on' -> 'onda', 'yüz' -> 'yüzde'."""
    son_unlu = next((c for c in reversed(kelime) if c in "aıoueiöü"), "e")
    sert = kelime[-1] in "çfhkpsşt"
    return kelime + ("t" if sert else "d") + ("a" if son_unlu in "aıou" else "e")


def _kesirler(metin: str) -> str:
    """'1/3' -> 'üçte bir'; kesir değilse '24/5' -> '24 bölü 5'."""
    def _k(m):
        pay, payda = int(m.group(1)), int(m.group(2))
        if 0 < pay < payda <= 100:
            kelimeler = tam_sayi(payda).split()
            kelimeler[-1] = _bulunma_eki(kelimeler[-1])
            return _b(m, " ".join(kelimeler) + " " + tam_sayi(pay) + (m.group(3) or ""))
        return f"{m.group(1)} bölü {m.group(2)}" + (("'" + m.group(3)) if m.group(3) else "")
    return re.sub(rf"{_ONCE}(\d{{1,4}})/(\d{{1,4}})(?:['’]([{_KUCUK}]+)|{_SONRA}(?!/))", _k, metin)


def _sayilari_cevir(metin: str) -> str:
    # Sıra sayısı: "3. sırada", "19. yüzyıl" (noktadan sonra küçük harf gelirse)
    metin = re.sub(rf"{_ONCE}(\d+)\.(?=\s+[{_KUCUK}])", lambda m: _b(m, sira_oku(m.group(1))), metin)
    # Ek almış sayı: "13'ü" -> "on üçü", "1923'te" -> "... yirmi üçte"
    metin = re.sub(rf"{_ONCE}({_SAYI})['’]([{_KUCUK}]+)",
                   lambda m: _b(m, sayi_oku(m.group(1)) + m.group(2)), metin)
    # Eksi sayı: " -5" -> " eksi beş"
    metin = re.sub(rf"(?:(?<=\s)|^)[-−]({_SAYI}){_SONRA}", lambda m: _b(m, "eksi " + sayi_oku(m.group(1))), metin)
    # Kalan tüm sayılar
    return re.sub(rf"{_ONCE}({_SAYI}){_SONRA}", lambda m: _b(m, sayi_oku(m.group(1))), metin)


# ------------------------------------------------------------------ giriş
def hazirla(metin: str, ayar: dict | None = None) -> str:
    """Metni seslendirmeye hazırlar. Hata olursa metni OLDUĞU GİBİ döndürür."""
    bolum = (ayar or {}).get("metin_hazirlik") or {}
    if not metin or bolum.get("etkin", True) is False:
        return metin
    try:
        kisaltmalar = bolum["kisaltmalar"] if isinstance(bolum.get("kisaltmalar"), dict) else VARSAYILAN_KISALTMALAR
        birimler = bolum["birimler"] if isinstance(bolum.get("birimler"), dict) else VARSAYILAN_BIRIMLER
        istisnalar = bolum["istisnalar"] if isinstance(bolum.get("istisnalar"), list) else VARSAYILAN_ISTISNALAR

        sonuc, saklanan = _koru(metin, [str(i) for i in istisnalar])
        sonuc = _tarihler(sonuc)
        sonuc = _saatler(sonuc)
        sonuc = _yuzdeler(sonuc)
        sonuc = _birimler(sonuc, birimler)          # önce birimler: "90 km/sa" bütün olarak okunur
        sonuc = _kisaltmalari_ac(sonuc, kisaltmalar)
        sonuc = _araliklar(sonuc)
        sonuc = _kesirler(sonuc)
        sonuc = _sayilari_cevir(sonuc)
        sonuc = _geri_koy(sonuc, saklanan)
        return re.sub(r"[ \t]{2,}", " ", sonuc).strip()
    except Exception as hata:  # noqa: BLE001 — hazırlık asla üretimi durdurmaz
        print(f"  [Metin hazırlık] atlandı ({type(hata).__name__}: {hata}); özgün metin kullanılıyor.")
        return metin


if __name__ == "__main__":
    import sys
    print(hazirla(" ".join(sys.argv[1:]) or "Saat 14:30'da %50 indirimle 2,5 km koştu vb."))
