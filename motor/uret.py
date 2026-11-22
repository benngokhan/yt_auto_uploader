#!/usr/bin/env python3
"""Bilgi Dozu üretim orkestratörü — kanalın KENDİ motorunu (motor/render_engine.py) sürer.

Akış:
    konu → sahne planı (LLM) → sahne sahne TTS (voice-02) → kelime hizalaması
         → sahne görselleri → render_video_master → video_<N>.mp4
         → Drive/Kısa Video + tabloya satır → mevcut yükleyici slotta yayınlar

Kurallar (CEO/00_ONCE_OKU_Uretim_Kurallari.md):
    * 1080x1920, 38-42 sn, 60 fps (kullanıcı kararı 03.11.2026)
    * üst başlık 2 satır: 1. satır beyaz, 2. satır sarı #FFD600, emoji
    * altyazı 2 satır, o an seslendirilen kelime sarı
    * ses voice-02 — farklı sese fallback YOK, hata olursa üretim durur

Kullanım:
    python motor/uret.py --konu "Parmak uçların suda neden buruşur?"            # render + onay bekleyen
    python motor/uret.py --konu "..." --onay-verildi        # onaylı: Drive + tablo
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent          # repo kökü
MOTOR = KOK / "motor"
VARSAYILAN_AYAR = MOTOR / "ayarlar.json"
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(MOTOR))
try:
    import kota_sayac  # noqa: F401
except Exception:
    pass


# ----------------------------------------------------------------- yardımcı
def ayar_yukle(yol: Path | None = None) -> dict:
    yol = yol or VARSAYILAN_AYAR
    if not yol.exists():
        raise SystemExit(f"Ayar dosyası yok: {yol}")
    return json.loads(yol.read_text(encoding="utf-8"))


def motor_hazirla(ayar: dict):
    """render_engine'in sabit yollarını bu ortama yönlendirir (motor kodu değişmez)."""
    sys.path.insert(0, str(MOTOR))
    import render_engine as re_  # noqa: N813

    if not (MOTOR / "assets" / "Montserrat-Black.ttf").exists():
        import varlik_hazirla
        varlik_hazirla.hazirla(mood=ayar.get("muzik_mood", "doga_kesif"))

    font_black = MOTOR / "assets" / "Montserrat-Black.ttf"
    # Shorts altyazısı: ExtraBold (800), mobilde daha net ve sıkıştırmaya dayanıklı.
    font_bold = MOTOR / "assets" / "Montserrat-ExtraBold.ttf"
    emoji_font = MOTOR / "assets" / "NotoColorEmoji.ttf"
    bgm = MOTOR / "assets" / ayar.get("muzik", "ambient_science_bgm.wav")

    for ad, yol in (("FONT_BLACK_PATH", font_black), ("FONT_BOLD_PATH", font_bold),
                    ("EMOJI_FONT_PATH", emoji_font), ("BGM_PATH", bgm)):
        if not Path(yol).exists():
            raise SystemExit(f"Eksik varlık: {ad} -> {yol}")
        setattr(re_, ad, str(yol))
    re_.FPS_HEDEF = int(ayar.get("fps", 60))
    return re_


# ------------------------------------------------------------ 1) sahne planı
SAHNE_SISTEM = (
    "Sen Bilgi Dozu kanalının senaristisin. Yalnızca istenen JSON'u döndür. "
    "Metin Türkçe, konuşma dili, tek bir şaşırtıcı bilgi üzerine kurulu olacak."
)

# v2 istemlerinde başlık/emoji şeması istenmiyor; model eski şemayı taklit
# edip boş nesne döndürüyordu. Bu yüzden ayrı ve sade bir sistem istemi var.
_LLM_SISTEM = (
    "Sen Bilgi Dozu adlı Türkçe bilim kanalının senaristisin. "
    "Yalnızca istenen JSON şemasını döndür; açıklama, markdown veya kod bloğu ekleme. "
    "Metinler Türkçe, konuşma diline yakın ve sesli okunduğunda doğal olacak."
)



_GROQ_MODEL_ONBELLEK: dict[str, str] = {}


def groq_model() -> str:
    """Canlı model listesinden hızlı ve JSON uyumlu (reasoning olmayan) bir Groq modeli seçer."""
    import urllib.request, json as _j
    if "m" in _GROQ_MODEL_ONBELLEK:
        return _GROQ_MODEL_ONBELLEK["m"]
    anahtar = os.getenv("GROQ_API_KEY", "").strip()
    istenen = os.getenv("GROQ_LLM_MODEL", "").strip()
    # gpt-oss / deepseek-r1 / qwq / orpheus gibi reasoning veya ses modelleri tercih edilmez
    _REASONING_ATLA = ("gpt-oss", "deepseek-r1", "qwq", "guard", "whisper", "tts", "vision", "playai", "orpheus", "compound", "allam", "safeguard")
    secilen = "llama-3.3-70b-versatile"
    if anahtar:
        try:
            r = urllib.request.Request(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {anahtar}",
                         "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"})
            with urllib.request.urlopen(r, timeout=45) as y:
                canli = [m.get("id") for m in _j.load(y).get("data", []) if m.get("id")]
            if canli:
                temiz = [m for m in canli if not any(x in m.lower() for x in _REASONING_ATLA)]
                if istenen and istenen in temiz:
                    secilen = istenen
                else:
                    tercih = ([m for m in temiz if "llama-3.3-70b" in m]
                              or [m for m in temiz if "llama-4" in m or "llama-3.1-8b" in m]
                              or [m for m in temiz if "llama" in m]
                              or temiz
                              or canli)
                    secilen = tercih[0]
                    if istenen and istenen != secilen:
                        print(f"UYARI: Groq modeli '{istenen}' yerine JSON uyumlu '{secilen}' seçildi.")
        except Exception as e:
            print(f"Groq model listesi alınamadı: {type(e).__name__}")
    _GROQ_MODEL_ONBELLEK["m"] = secilen
    return secilen


def _arsivle(ad: str, icerik, uzanti: str = "txt") -> None:
    """Üretim arşivine yazar (motor/arsiv.py). Yalnız kayıt; üretimi asla etkilemez."""
    try:
        import arsiv
        arsiv.yaz(ad, icerik, uzanti)
    except Exception:  # noqa: BLE001
        pass


def _arsivle_senaryo(ad: str, sahneler: list) -> None:
    try:
        _arsivle(ad, "\n".join(f"{i}. [{x.get('baslik1', '')} / {x.get('baslik2', '')}] {x.get('ses', '')}"
                               for i, x in enumerate(sahneler, start=1)))
    except Exception:  # noqa: BLE001
        pass


def _regresyon_kapisi(ayar: dict) -> None:
    """Bilinen hata testlerini çalıştırır; biri kırmızıysa uyarır ve üretimi DURDURUR (sahip, 15.11.2026)."""
    import regresyon
    sonuc = regresyon.calistir(ayar, sys.modules[__name__])
    metin = regresyon.rapor(sonuc)
    print(metin)
    _arsivle("regresyon_sonuclari", metin + "\n\n" + json.dumps(sonuc, ensure_ascii=False, indent=2))
    if not regresyon.hepsi_yesil(sonuc):
        kirmizi = ", ".join(x["kod"] for x in sonuc if not x["gecti"] and x.get("kilit", True))
        raise SystemExit(f"UYARI: regresyon testleri KIRMIZI ({kirmizi}). Video/ses ÜRETİLMEDİ.")


# Senaryo yazan yapay zekâya verilen "terim birliği ve bilimsel tutarlılık" kuralları.
# Hem senaryo planında hem cümle uzatmada kullanılır (tek kaynak).
TERIM_KURALLARI = (
    "- TERİM BİRLİĞİ VE BİLİMSEL TUTARLILIK (ÇOK KRİTİK):\n"
    "  * Her olguyu ve maddeyi TEK bir terimle an, video boyunca değiştirme "
    "(ör. 'parafin zerrecikleri' dediysen sonradan 'karbon parçacığı' veya 'kül' deme).\n"
    "  * Yanmış artık (kül) ile yakıt maddesini birbirine karıştırma; külün tutuşabileceğini ima eden cümle kurma.\n"
    "  * Aynı nicelik için farklı sayı veya büyüklük verme (bir yerde 'milyonlarca', başka yerde 'binlerce' deme).\n"
    "  * Doğrulayamadığın kesin sayısal değer yazma; emin değilsen nitel ifade kullan "
    "(ör. 'çok küçük', 'birkaç saniye içinde').\n"
    "- TEKRAR YOK: Her cümle YENİ bir bilgi versin. Bir cümleyi (özellikle ilk cümleyi) başka kelimelerle "
    "ikinci kez söyleme; aynı kalıbı ('... kül değil, ... zerrecikleridir' gibi) iki cümlede kullanma.\n"
    "- YAZIM: Yalnız sözlükte bulunan, doğru yazılmış Türkçe kelimeler kullan; uydurma ya da harfi eksik/fazla "
    "kelime yazma (ör. 'tüten' yerine 'tütücen', 'zerrecikler' yerine 'zerrcikler' YANLIŞ). Yazdıktan sonra her kelimeyi kontrol et.\n"
)


def _kokler(metin: str) -> set:
    """Benzerlik ölçümü için kelimelerin ilk 5 harfi (Türkçe ekleri kabaca atar)."""
    import re as _re
    return {k[:5] for k in _re.findall(r"[a-zçğıöşü]+", str(metin or "").replace("İ", "i").replace("I", "ı").lower()) if len(k) >= 3}


def _benzerlik(a: str, b: str) -> float:
    """İki cümlenin ortak kelime oranı (0-1); kısa olan cümleye göre ölçülür."""
    ka, kb = _kokler(a), _kokler(b)
    if len(ka) < 4 or len(kb) < 4:
        return 0.0
    return len(ka & kb) / min(len(ka), len(kb))


TEKRAR_ESIGI = 0.7


def _tekrar_eden_cumleler(cumleler: list) -> list:
    """Birbirinin tekrarı olan cümle çiftlerini [(i, j, oran)] olarak döndürür (1'den başlar)."""
    temiz = [str(c).replace("Daha fazla Bilgi Dozu için takip et!", "") for c in cumleler]
    return [(i + 1, j + 1, round(_benzerlik(temiz[i], temiz[j]), 2))
            for i in range(len(temiz)) for j in range(i + 1, len(temiz))
            if _benzerlik(temiz[i], temiz[j]) >= TEKRAR_ESIGI]


def _yazim_denetimi(sahneler: list, ayar: dict) -> int:
    """Seslendirmeden ÖNCE cümle ve sahne başlıklarındaki yazım hatalarını düzelttirir.

    Yalnız yazım düzeltmesi kabul edilir: metin neredeyse aynı kalmalı (harf düzeyinde küçük fark).
    Yapay zekâ cümleyi yeniden yazmaya kalkarsa ya da hata olursa özgün metin korunur; üretim durmaz.
    """
    import difflib
    cta = "Daha fazla Bilgi Dozu için takip et!"
    cumleler = [str(x.get("ses", "")).replace(cta, "").strip() for x in sahneler]
    basliklar = [[str(x.get("baslik1", "")), str(x.get("baslik2", ""))] for x in sahneler]
    istem = (
        "Aşağıdaki Türkçe video metninde YALNIZCA yazım hatalarını düzelt: harfi eksik/fazla ya da uydurma kelimeleri "
        "doğru Türkçe kelimeyle değiştir (ör. 'tütücen' -> 'tüten', 'ZERRCİKLER' -> 'ZERRECİKLER'). "
        "Anlamı, kelime sırasını, cümle sayısını ve uzunluğu DEĞİŞTİRME; doğru olan hiçbir şeye dokunma; yeni bilgi ekleme. "
        "Başlıklar TAM BÜYÜK HARF kalır.\n"
        f"cumleler: {json.dumps(cumleler, ensure_ascii=False)}\n"
        f"basliklar: {json.dumps(basliklar, ensure_ascii=False)}\n"
        'Yalnız JSON döndür: {"cumleler": [...aynı sayıda...], "basliklar": [["SATIR 1", "SATIR 2"], ...aynı sayıda...]}'
    )
    try:
        veri = _llm_json(istem, ayar, "Sen titiz bir Türkçe yazım denetçisisin. Yalnız geçerli JSON döndürürsün.")
    except (Exception, SystemExit) as h:  # noqa: BLE001 — denetim üretimi asla durdurmaz
        print(f"Yazım denetimi yapılamadı ({type(h).__name__}); metin olduğu gibi kullanılıyor")
        return 0

    def _kucuk_fark(eski: str, yeni: str, esik: float = 0.9) -> bool:
        if not yeni or yeni == eski or abs(len(yeni) - len(eski)) > 4:
            return False
        if len(yeni.split()) != len(eski.split()):
            return False
        return difflib.SequenceMatcher(None, eski.lower(), yeni.lower()).ratio() >= esik

    duzeltilen = 0
    yeni_c = veri.get("cumleler") if isinstance(veri, dict) else None
    if isinstance(yeni_c, list) and len(yeni_c) == len(sahneler):
        for x, eski, yeni in zip(sahneler, cumleler, yeni_c):
            yeni = str(yeni or "").strip()
            if _kucuk_fark(eski, yeni):
                x["ses"] = str(x.get("ses", "")).replace(eski, yeni, 1)
                print(f"  yazım düzeltildi: {eski!r} -> {yeni!r}")
                duzeltilen += 1
    yeni_b = veri.get("basliklar") if isinstance(veri, dict) else None
    if isinstance(yeni_b, list) and len(yeni_b) == len(sahneler):
        for x, cift in zip(sahneler, yeni_b):
            if not (isinstance(cift, list) and len(cift) == 2):
                continue
            for anahtar, yeni in zip(("baslik1", "baslik2"), cift):
                eski = str(x.get(anahtar, ""))
                yeni = tr_upper(str(yeni or "").strip())
                if _kucuk_fark(eski, yeni, 0.7) and len(yeni) <= 18:
                    x[anahtar] = yeni
                    print(f"  yazım düzeltildi (başlık): {eski!r} -> {yeni!r}")
                    duzeltilen += 1
    print(f"Yazım denetimi: {duzeltilen} düzeltme")
    return duzeltilen

class SenaryoDuzeltilemedi(SystemExit):
    """Terim birliği ya da sayı kuralı sağlanamadı: üretim durur (sahip kararı, 16.11.2026)."""


SENARYO_DUZELTME_DENEMESI = 2
_CTA = "Daha fazla Bilgi Dozu için takip et!"

# Senaryo yazan yapay zekâya verilen sayı kuralı (16.11.2026). TERIM_KURALLARI'na dokunulmadı; ayrı bir kuraldır.
SAYI_KURALLARI = (
    "- YAKLAŞIK SAYI KURALI (ÇOK KRİTİK): 'yaklaşık', 'ortalama', 'civarında' gibi bir sözle verdiğin değeri TEK sayı "
    "olarak yazma; bilimsel olarak bilinen ARALIĞI 'X ile Y birim arasında' biçiminde yaz (ör. 'dört yüz seksen ile "
    "beş yüz otuz derece arasında'). Aralığı bilmiyorsan sayı verme, sayısız anlat. Aralık olarak bilinen bir değeri "
    "tek kesin sayıymış gibi yazma.\n"
)


def _llm_liste(istem: str, ayar: dict, sistem: str = "Sen titiz bir Türkçe bilim editörüsün. Yalnız geçerli JSON döndürürsün.") -> list:
    """_llm_json'u çağırır, 'cumleler' listesini döndürür (motorun kabul ettiği cevap biçimi)."""
    veri = _llm_json(istem, ayar, sistem)
    liste = veri.get("cumleler") if isinstance(veri, dict) else None
    if isinstance(liste, str):
        liste = [liste]
    return [str(x or "").strip() for x in liste] if isinstance(liste, list) else []


def _cta_ayir(ses: str) -> tuple[str, str]:
    ses = str(ses or "")
    return (ses.replace(_CTA, "").strip(), _CTA) if _CTA in ses else (ses.strip(), "")


def _cumle_duzelt(sahneler: list, sira: int, istem: str, uygun_mu, ayar: dict, yaz, etiket: str) -> bool:
    """Tek cümleyi yapay zekâya düzelttirir; öneri yapay zekâsız `uygun_mu(yeni) -> ''/neden` denetiminden geçmelidir."""
    import senaryo_denetim as sd
    x = sahneler[sira - 1]
    eski, cta = _cta_ayir(x.get("ses", ""))
    digerleri = [_cta_ayir(y.get("ses", ""))[0] for y in sahneler if y is not x]
    for deneme in range(1, SENARYO_DUZELTME_DENEMESI + 1):
        try:
            liste = _llm_liste(istem + "\nCümle: " + json.dumps(eski, ensure_ascii=False)
                               + '\nYalnız JSON döndür: {"cumleler": ["DÜZELTİLMİŞ CÜMLE"]}', ayar)
        except (Exception, SystemExit) as h:  # noqa: BLE001
            yaz(f"    deneme {deneme}: düzeltme alınamadı ({type(h).__name__})")
            continue
        yeni = " ".join((liste[0] if liste else "").split())
        if not yeni or yeni == eski:
            neden = "değişiklik yok"
        elif len(yeni) > len(eski) + 70 or len(yeni) < max(20, len(eski) - 45):
            neden = "uzunluk çok değişti"
        elif any(_benzerlik(yeni, d) >= TEKRAR_ESIGI for d in digerleri):
            neden = "başka bir cümleyi tekrar ediyor"
        elif sd.terim_tutarsizligi_bul(digerleri + [yeni]) and not sd.terim_tutarsizligi_bul(digerleri + [eski]):
            neden = "yeni bir terim tutarsızlığı getiriyor"
        else:
            neden = uygun_mu(yeni)
        if not neden:
            if yeni[-1] not in ".!?":
                yeni += "."
            x["ses"] = f"{yeni} {cta}".strip()
            yaz(f"  {etiket} düzeltildi ({sira}. cümle): {eski!r} -> {yeni!r}")
            return True
        yaz(f"    deneme {deneme}: öneri {yeni!r} reddedildi ({neden})")
    return False


def _terim_birligi_sagla(sahneler: list, ayar: dict, asama: str = "") -> int:
    """Aynı nesne için tek terim: çift adlandırma varsa azınlıktaki terim ana terime çevrilir; olmazsa üretim DURUR."""
    import senaryo_denetim as sd
    kayit: list[str] = []
    duzeltilen = 0

    def yaz(satir: str) -> None:
        print(satir)
        kayit.append(satir)

    try:
        cumleler = [_cta_ayir(x.get("ses", ""))[0] for x in sahneler]
        for t in sd.terim_tutarsizligi_bul(cumleler):
            gecen = t["terimler"]
            ana = sd.ana_terim(gecen)
            yaz(f"Terim birliği ({asama}): {t['grup']} için birden çok ad var {gecen}; korunacak ad: '{ana}'")
            for ad, yerler in gecen.items():
                if ad == ana:
                    continue
                for sira in yerler:
                    def uygun(yeni, _grup=t["grup"], _ana=ana):
                        kalan = [a for a in sd.grup_terimleri(yeni)[_grup] if a != _ana]
                        if kalan:
                            return f"hâlâ başka ad var: {kalan}"
                        return "" if _ana in sd.grup_terimleri(yeni)[_grup] else f"'{_ana}' adı geçmiyor"
                    istem = (f"Bu Türkçe video cümlesinde '{ad}' kelimesi geçiyor; videonun geri kalanında aynı şey için "
                             f"'{ana}' adı kullanılıyor. Cümlede '{ad}' (ve ekli hâlleri) yerine '{ana}' kelimesini, "
                             "ekleri Türkçe ses uyumuna göre düzelterek yaz. Başka HİÇBİR şeyi değiştirme; yeni bilgi, "
                             "yeni sayı ekleme.")
                    if _cumle_duzelt(sahneler, sira, istem, uygun, ayar, yaz, "terim"):
                        duzeltilen += 1
                    else:
                        yaz(f"  TERİM BİRLİĞİ SAĞLANAMADI: {sira}. cümlede '{ad}' kaldı")
                        raise SenaryoDuzeltilemedi(
                            f"Terim birliği sağlanamadı: {sira}. cümlede '{ad}', diğer cümlelerde '{ana}'. Video üretilmedi.")
        kalan = sd.terim_tutarsizligi_bul([_cta_ayir(x.get("ses", ""))[0] for x in sahneler])
        if kalan:
            raise SenaryoDuzeltilemedi(f"Terim birliği sağlanamadı: {kalan}. Video üretilmedi.")
        if duzeltilen or kayit:
            yaz(f"Terim birliği ({asama}): {duzeltilen} düzeltme, metinde tek ad kaldı")
        return duzeltilen
    finally:
        if kayit:
            _arsivle("terim_birligi", "\n".join(kayit))


def _sayi_denetimi(sahneler: list, ayar: dict) -> int:
    """Sayı kuralı (16.11.2026):

    1) 'yaklaşık/ortalama/civarında' + TEK sayı (yapay zekâsız bulunur) -> aralığa çevrilir ya da sayı çıkarılır;
       olmazsa üretim DURUR.
    2) Kalan birimli kesin sayılar ayrı bir soruyla hakeme sorulur: 'aslında aralık' denirse (ör. 'beş yüz derece'
       <-> '480-530 derece') cümle aralıkla yeniden yazılır; olmazsa üretim DURUR. Hakem çalışmazsa ya da
       'kesin/bilinmiyor' derse sayı eskisi gibi yalnız UYARI olarak kalır.
    """
    import senaryo_denetim as sd
    kayit: list[str] = []
    duzeltilen = 0

    def yaz(satir: str) -> None:
        print(satir)
        kayit.append(satir)

    def cumleler():
        return [_cta_ayir(x.get("ses", ""))[0] for x in sahneler]

    def uygun_yap(sira: int, ifade: str):
        onceki = {s["ifade"] for s in sd.kesin_sayi_bul([cumleler()[sira - 1]])} - {ifade}

        def uygun(yeni: str) -> str:
            if sd.yaklasik_tek_sayi_bul([yeni]):
                return "hâlâ yaklaşık + tek sayı var"
            fazla = {s["ifade"] for s in sd.kesin_sayi_bul([yeni])} - onceki
            return f"tek kesin sayı kaldı/eklendi: {sorted(fazla)}" if fazla else ""
        return uygun

    try:
        # 1) yaklaşık + tek sayı
        for _ in range(8):
            ihlaller = sd.yaklasik_tek_sayi_bul(cumleler())
            if not ihlaller:
                break
            s = ihlaller[0]
            yaz(f"Sayı kuralı: {s['cumle']}. cümlede yaklaşık değer tek sayıyla verilmiş: '{s['belirtec']} … {s['ifade']}'")
            istem = (f"Bu Türkçe video cümlesinde '{s['ifade']}' değeri '{s['belirtec']}' sözüyle, yani yaklaşık olarak ama "
                     "TEK sayıyla verilmiş. Kural: yaklaşık değerler ARALIK olarak yazılır. Bu değerin bilimsel olarak "
                     "bilinen aralığını 'X ile Y birim arasında' biçiminde, sayıları YAZIYLA yaz (ör. 'dört yüz seksen ile "
                     "beş yüz otuz derece arasında') ve 'yaklaşık/ortalama/civarında' sözünü kaldır. Aralıktan emin "
                     "değilsen sayıyı tamamen çıkar ve sayısız anlat (ör. 'çok yüksek bir sıcaklığa'). Başka bilgiyi "
                     "değiştirme, yeni sayı ekleme.")
            if _cumle_duzelt(sahneler, s["cumle"], istem, uygun_yap(s["cumle"], s["ifade"]), ayar, yaz, "sayı"):
                duzeltilen += 1
            else:
                yaz(f"  SAYI DÜZELTİLEMEDİ: {s['cumle']}. cümle '{s['ifade']}'")
                raise SenaryoDuzeltilemedi(
                    f"Sayı kuralı sağlanamadı: {s['cumle']}. cümlede yaklaşık değer tek sayıyla kaldı ('{s['ifade']}'). "
                    "Video üretilmedi.")

        # 2) kalan kesin sayılar: hakem sorusu
        kesinler = sd.kesin_sayi_bul(cumleler())
        if kesinler:
            c = cumleler()
            maddeler = "\n".join(f"{i}) ifade: '{s['ifade']}' — cümle: {c[s['cumle'] - 1]}" for i, s in enumerate(kesinler, start=1))
            istem = ("Aşağıda bir Türkçe bilim videosunda TEK kesin sayı olarak verilen değerler var. Her biri için karar ver:\n"
                     "- 'KESİN' : yerleşik sabit ya da herkesçe tek değer olarak kabul edilen, yuvarlanmış yaygın değer "
                     "(ör. suyun yüz derecede kaynaması).\n"
                     "- 'ARALIK: X ile Y birim' : gerçekte tek değer değil, koşula göre değişen bir aralık; tek sayı yazmak "
                     "yanıltıcı (ör. 'ARALIK: 480 ile 530 derece'). Yalnız aralıktan EMİNSEN bunu seç.\n"
                     "- 'BİLİNMİYOR' : emin değilsin.\n"
                     f"{maddeler}\n"
                     f'Yalnız JSON döndür: {{"cumleler": [TAM {len(kesinler)} karar, aynı sırayla]}}')
            try:
                kararlar = _llm_liste(istem, ayar, "Sen titiz bir bilim doğrulama editörüsün. Yalnız geçerli JSON döndürürsün.")
            except (Exception, SystemExit) as h:  # noqa: BLE001
                kararlar = []
                yaz(f"Sayı hakemi çalışmadı ({type(h).__name__}); kesin sayılar yalnız uyarı olarak kaldı")
            if kararlar and len(kararlar) != len(kesinler):
                yaz(f"Sayı hakemi {len(kesinler)} yerine {len(kararlar)} karar döndürdü; kesin sayılar yalnız uyarı olarak kaldı")
                kararlar = []
            for s, karar in zip(kesinler, kararlar):
                yaz(f"Sayı hakemi: {s['cumle']}. cümle '{s['ifade']}' -> {karar}")
                if not tr_upper(karar).startswith("ARALIK"):
                    continue
                aralik = karar.split(":", 1)[1].strip() if ":" in karar else ""
                istem = (f"Bu Türkçe video cümlesinde '{s['ifade']}' tek kesin sayı olarak verilmiş; oysa bu değer bir "
                         f"aralıktır: {aralik or 'bilinen aralık'}. '{s['ifade']}' yerine aralığı 'X ile Y birim arasında' "
                         "biçiminde, sayıları YAZIYLA yaz. Başka bilgiyi değiştirme, yeni sayı ekleme.")
                if _cumle_duzelt(sahneler, s["cumle"], istem, uygun_yap(s["cumle"], s["ifade"]), ayar, yaz, "sayı"):
                    duzeltilen += 1
                else:
                    yaz(f"  SAYI DÜZELTİLEMEDİ: {s['cumle']}. cümle '{s['ifade']}' (aralık: {aralik})")
                    raise SenaryoDuzeltilemedi(
                        f"Sayı kuralı sağlanamadı: {s['cumle']}. cümlede '{s['ifade']}' tek sayı, bilinen aralık {aralik}. "
                        "Video üretilmedi.")
        if kayit:
            yaz(f"Sayı denetimi: {duzeltilen} düzeltme")
        return duzeltilen
    finally:
        if kayit:
            _arsivle("sayi_denetimi", "\n".join(kayit))


def _senaryo_son_kapi(sahneler: list) -> None:
    """Yazım denetiminden SONRA yapay zekâsız son bakış: terim çifti ya da yaklaşık+tek sayı kaldıysa üretim DURUR."""
    import senaryo_denetim as sd
    c = [_cta_ayir(x.get("ses", ""))[0] for x in sahneler]
    terim, sayi = sd.terim_tutarsizligi_bul(c), sd.yaklasik_tek_sayi_bul(c)
    if terim or sayi:
        raise SenaryoDuzeltilemedi(f"Senaryo son kapıdan geçemedi (terim: {terim}; sayı: {sayi}). Video üretilmedi.")
    print("Senaryo son kapı: terim birliği ve sayı kuralı sağlanıyor")


def _baslik_anlam_denetimi(sahneler: list, ayar: dict) -> list:
    """Başlıkların ANLAMLI olup olmadığını ayrı bir soruyla denetler. YALNIZ UYARI: metni değiştirmez, durdurmaz."""
    uyarilar: list[str] = []
    try:
        maddeler = "\n".join(
            f"{i}) başlık: '{x.get('baslik1', '')} / {x.get('baslik2', '')}' — cümle: {_cta_ayir(x.get('ses', ''))[0]}"
            for i, x in enumerate(sahneler, start=1))
        istem = ("Aşağıda bir Türkçe bilim videosunun sahne başlıkları (iki satır, '/' ile ayrılmış) ve ait oldukları "
                 "cümleler var. Her başlık için karar ver: iki satır birlikte okunduğunda ANLAMLI, dilbilgisi düzgün, "
                 "yarım kalmamış ve cümlesiyle ilgili mi?\n"
                 "- uygunsa yalnız 'UYGUN' yaz;\n"
                 "- değilse 'SORUNLU: kısa neden' yaz (ör. 'SORUNLU: ikinci satır yarım kalmış, soru tamamlanmıyor').\n"
                 f"{maddeler}\n"
                 f'Yalnız JSON döndür: {{"cumleler": [TAM {len(sahneler)} karar, aynı sırayla]}}')
        kararlar = _llm_liste(istem, ayar, "Sen titiz bir Türkçe editörsün. Yalnız geçerli JSON döndürürsün.")
        if len(kararlar) != len(sahneler):
            print(f"Başlık anlam denetimi: {len(sahneler)} yerine {len(kararlar)} karar geldi; sonuç kullanılmadı")
            _arsivle("baslik_anlam_denetimi", f"SONUÇ KULLANILMADI: {kararlar}")
            return []
        for i, (x, karar) in enumerate(zip(sahneler, kararlar), start=1):
            if not tr_upper(karar).startswith("UYGUN"):
                satir = (f"UYARI (başlık anlamı): {i}. sahne '{x.get('baslik1', '')} / {x.get('baslik2', '')}' — "
                         + (karar.split(":", 1)[1].strip() if ":" in karar else karar))
                print(satir)
                uyarilar.append(satir)
        print(f"Başlık anlam denetimi: {len(uyarilar)} uyarı (yalnız uyarı; üretim durmaz)")
        _arsivle("baslik_anlam_denetimi", "\n".join(uyarilar) or "tüm başlıklar UYGUN bulundu")
    except (Exception, SystemExit) as h:  # noqa: BLE001 — bu denetim üretimi asla durdurmaz
        print(f"Başlık anlam denetimi yapılamadı ({type(h).__name__}); üretim sürüyor")
    return uyarilar


class BaslikDuzeltilemedi(SystemExit):
    """Başlıkta sözlükte olmayan kelime kaldı: başlık ekrana basılmaz, üretim durur."""


BASLIK_DUZELTME_DENEMESI = 2


def _baslik_duzeltme_iste(baslik: str, hatali: list, cumle: str, ayar: dict) -> str:
    """Yalnız işaretlenen kelime(ler) için yapay zekâdan düzeltme ister; cevabı olduğu gibi (büyük harfle) döndürür."""
    istem = (
        "Bir Türkçe video başlığında yazım hatası var. Başlık: " + json.dumps(baslik, ensure_ascii=False) + ". "
        "Sözlükte bulunmayan kelime(ler): " + json.dumps(hatali, ensure_ascii=False) + ". "
        "Başlığın ait olduğu cümle: " + json.dumps(cumle, ensure_ascii=False) + ". "
        "YALNIZCA sözlükte bulunmayan kelimeyi, cümleye uyan DOĞRU yazılmış Türkçe kelimeyle değiştir "
        "(ör. 'MUM EYİ' -> 'MUM EVİ', 'ZERRCİKLER' -> 'ZERRECİKLER'). Diğer kelimelere dokunma, kelime sayısını "
        "değiştirme, TAM BÜYÜK HARF yaz.\n"
        'Yalnız JSON döndür: {"cumleler": ["DÜZELTİLMİŞ BAŞLIK"]}'
    )
    # Not: _llm_json yalnız "cumleler" (vb.) anahtarı taşıyan cevabı kabul eder; o yüzden cevap bu anahtarla istenir.
    # (67. çalıştırmada "baslik" anahtarı istendiği için doğru cevaplar yok sayılmıştı.)
    veri = _llm_json(istem, ayar, "Sen titiz bir Türkçe yazım denetçisisin. Yalnız geçerli JSON döndürürsün.")
    liste = veri.get("cumleler") if isinstance(veri, dict) else None
    if isinstance(liste, str):
        liste = [liste]
    return tr_upper(str(liste[0] or "").strip()) if isinstance(liste, list) and liste else ""


def _baslik_denetimi(sahneler: list, ayar: dict) -> int:
    """YALNIZ BAŞLIKLAR: önce sözlük (yapay zekâsız), sonra yalnız işaretlenen kelimeler için düzeltme.

    Kural (sahip, 16.11.2026): başlıkta sözlükte olmayan kelime varsa düzeltilir ve loga eski -> yeni yazılır;
    düzeltilemezse başlık ekrana basılmaz, üretim DURUR. Senaryo gövdesine (cümlelere) dokunmaz.
    """
    import sozluk
    kayit: list[str] = []
    duzeltilen = 0

    def yaz(satir: str) -> None:
        print(satir)
        kayit.append(satir)

    try:
        for sira, x in enumerate(sahneler, start=1):
            for anahtar in ("baslik1", "baslik2"):
                eski = str(x.get(anahtar, ""))
                try:
                    hatali = sozluk.bilinmeyenler(eski)
                except sozluk.SozlukYok as h:
                    yaz(f"Başlık denetimi YAPILAMADI: sözlük yüklenemedi ({h})")
                    raise BaslikDuzeltilemedi("Başlık sözlük denetimi yapılamadı (sözlük yok); video üretilmedi.") from h
                if not hatali:
                    continue
                nedenler = {k: sozluk.durum(k) for k in hatali}
                yaz(f"  başlık sözlük denetimi: {sira}. sahne {eski!r} -> şüpheli kelime: {nedenler}")
                kabul = ""
                for deneme in range(1, BASLIK_DUZELTME_DENEMESI + 1):
                    try:
                        yeni = _baslik_duzeltme_iste(eski, hatali, str(x.get("ses", "")), ayar)
                    except (Exception, SystemExit) as h:  # noqa: BLE001
                        yaz(f"    deneme {deneme}: düzeltme alınamadı ({type(h).__name__})")
                        continue
                    eski_k, yeni_k = sozluk.kelimeler(eski), sozluk.kelimeler(yeni)
                    if not yeni or yeni == eski:
                        neden = "değişiklik yok"
                    elif len(yeni) > 18:
                        neden = "18 karakterden uzun"
                    elif len(yeni_k) != len(eski_k) or any(
                            e != y for e, y in zip(eski_k, yeni_k) if e not in hatali):
                        neden = "işaretlenmeyen kelimeler de değiştirilmiş"
                    elif sozluk.bilinmeyenler(yeni):
                        neden = f"hâlâ sözlükte olmayan kelime var: {sozluk.bilinmeyenler(yeni)}"
                    else:
                        kabul = yeni
                        break
                    yaz(f"    deneme {deneme}: öneri {yeni!r} reddedildi ({neden})")
                if not kabul:
                    yaz(f"  BAŞLIK DÜZELTİLEMEDİ: {sira}. sahne {eski!r} (sözlükte olmayan: {hatali})")
                    for k in hatali:   # yanlış alarm olabilir: kelime ek kelime dosyasına NOT olarak düşülür
                        if sozluk.not_dus(k, eski, nedenler.get(k, "")):
                            yaz(f"  not düşüldü: {k!r} -> motor/sozluk_ek_kelimeler.txt (doğruysa orada onaylayın)")
                    raise BaslikDuzeltilemedi(
                        f"Başlık düzeltilemedi: {sira}. sahne {eski!r}, sözlükte olmayan kelime {hatali}. "
                        "Başlık ekrana basılmadı; video üretilmedi.")
                x[anahtar] = kabul
                duzeltilen += 1
                yaz(f"  başlık düzeltildi: {eski!r} -> {kabul!r} (sözlükte olmayan: {hatali})")
        yaz(f"Başlık sözlük denetimi: {duzeltilen} düzeltme, tüm başlık kelimeleri sözlükte")
        return duzeltilen
    finally:
        _arsivle("baslik_denetimi", "\n".join(kayit) or "kayıt yok")


_GENEL_KAYNAK_IZLERI = (
    "doğrulanmış bilimsel", "hakemli bilimsel", "bilimsel araştırma", "bilimsel yayın",
    "bilimsel kaynak", "araştırma arşivi", "çeşitli kaynak", "genel kaynak", "yoksa boş",
)
GORSEL_TEMSILI_NOTU = "Görseller temsilidir."


def _kaynak_temizle(ham, *, kaynaksiz_etiket: str = "") -> str:
    """Yalnız erişilebilir HTTPS kaynak URL'sini kabul eder; kurum adını tek başına asla göstermez."""
    import ipaddress
    from urllib.parse import urlparse

    raw = " ".join(str(ham or "").split()).strip()
    label = " ".join(str(kaynaksiz_etiket or "").split()).strip()
    if not raw:
        if label:
            print(f"UYARI (kaynak doğrulama): URL'siz kaynak alanı ekrana yazılmadı: {label}")
        return ""
    if raw.lower().startswith("kaynak:"):
        raw = raw.split(":", 1)[1].strip()
    parsed = urlparse(raw)
    allowed_domains = (
        "nasa.gov", "boeing.com", "doi.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
        "nature.com", "science.org", "aaas.org", "nejm.org", "thelancet.com", "pnas.org",
        "aps.org", "arxiv.org", "who.int", "cdc.gov", "nih.gov", "esa.int",
    )
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        host_ok = False
    except ValueError:
        host_ok = any(host == domain or host.endswith("." + domain) for domain in allowed_domains)
    if parsed.scheme != "https" or not host_ok or not parsed.path.startswith("/"):
        print(f"UYARI (kaynak doğrulama): güvenilir HTTPS kaynak URL'si yok; alan gizlendi: {label or raw[:100]}")
        return ""
    try:
        request = urllib.request.Request(raw, headers={"User-Agent": "BilgiDozuSourceVerifier/1.0"})
        with urllib.request.urlopen(request, timeout=8) as response:
            final = urlparse(response.geturl())
            final_host = (final.hostname or "").lower().rstrip(".")
            if response.status < 200 or response.status >= 400 or final.scheme != "https" or not any(
                    final_host == d or final_host.endswith("." + d) for d in allowed_domains):
                raise ValueError("URL güvenli/başarılı bir kaynak sayfasına yönlenmedi")
        return raw
    except Exception as exc:  # noqa: BLE001 — doğrulanamayan kaynak ekrana çıkmaz
        print(f"UYARI (kaynak doğrulama): kaynak URL doğrulanamadı ({type(exc).__name__}); alan gizlendi: {label or raw[:100]}")
        return ""


def sahne_plani(konu: str, sahne_sayisi: int, ayar: dict) -> list[dict]:
    """LLM'den sahne sahne plan alır: ses metni + üst başlık + altyazı vurguları."""
    if ayar.get("sahneler_sablon"):
        return sahne_plani_v2(konu, ayar.get("sahne_sayisi", 4), ayar)
    import urllib.request

    istem = (
        f"Konu: {konu}\n\n"
        f"Video TAM 4 sahne olacak, toplam anlatım 38-42 saniye (sahne başına ~9-10 sn).\n"
        "JSON şeması: {\"sahneler\": [{\"ses\": \"...\", \"baslik1\": \"...\", "
        "\"baslik2\": \"...\", \"emoji\": \"...\", \"gorsel\": \"...\", "
        "\"gorsel_anahtar\": \"...\", \"vurgular\": [\"kelime\", ...]}]}\n"
        "- ses: o sahnede söylenecek 1-2 doğal cümle (toplam ~150-170 karakter/sahne). "
        "Nokta, virgül, iki nokta, soru işareti ve gerektiğinde noktalı virgülü anlamına uygun kullan; "
        "TTS'nin doğal nefes alacağı kısa cümleler kur. Üç nokta, parantez, kısaltma ve yapay slogan ritmi kullanma.\n"
        "- baslik1: BÜYÜK HARF, beyaz satır (en fazla 22 karakter)\n"
        "- baslik2: BÜYÜK HARF, sarı satır (en fazla 22 karakter)\n"
        "- emoji: konuya uygun tek emoji\n"
        "- gorsel: o sahnede ekranda görünecek sahneyi anlatan İNGİLİZCE arama cümlesi (4-8 kelime). "
        "Mecaz yasak: \"beyin kontrolü\" yerine \"human brain scan\", \"ıslak tutuş\" yerine \"wet wrinkled fingertips\" gibi "
        "fotoğraflanabilir somut bir şey yaz. Yazı, logo, tabela, ekran metni isteme. "
        "Konuyla ilgisiz süs görseli (duvar kağıdı, soyut ışık, genel manzara) YASAK; her sahne videonun ana konusunu gösterir.\n"
        "- gorsel_anahtar: o sahnenin EN ÖNEMLİ 2-3 İNGİLİZCE kelimesi (sadece ana nesne, sıfat yok). "
        "Örnek: \"honeybee hive\", \"cortisol brain\", \"alarm clock night\". Bu kelimeler görsel aramasında birebir kullanılacak.\n"
        "- vurgular: o sahnenin altyazısında sarı boyanacak 1-3 kelime\n"
        "\nSAHNE YAPISI (sahibin onayladığı akış, TAM 4 sahne):\n"
        "1) KANCA (0-3 sn): Merak uyandıran soru veya şaşırtıcı iddia. Tek soru, 5-8 kelime.\n"
        "2) PROBLEM / DURUM: Ne olduğunu tek cümlede kur. İzleyici 'ne oluyor?' diye bağlansın.\n"
        "3) BİLİMSEL AÇIKLAMA: Asıl bilgi. Her cümlede TEK ana bilgi ve MÜMKÜNSE TEK SOMUT SAYI "
        "(ör. 'saniyede 13 kez', '2,5 milimetre'). Uydurma sayı yasak; kaynaklı gerçek değer ver.\n"
        "4) SONUÇ + KAPANIŞ: Net, doğrulanmış cevabı ver ve sonunda izleyiciyi düşündüren KISA bir soru sor "
        "(ör. 'PEKİ O ANDA SEN İLK NE YAPARDIN?').\n"
        "Selamlama ve 'abone olun' YASAK. Sabit kapanış cümlesini ve takip butonunu video motoru ekler, sen yazma.\n"
        "Uzunluk: toplam anlatım boşluklar dahil 620-700 Türkçe karakter (4 sahne, 38-42 sn) olmalı; "
        "her sahne 150-185 karakter olmalı. Cümleler doğal, bilgi yoğun ve sesli okumada 38-42 saniyeye uygun olmalı. "
        "'Bakacağız' kelimesini ve sert slogan tonunu kullanma.\n"
        + TERIM_KURALLARI
    )

    def _cagir(url, govde, basliklar):
        import time, urllib.error
        veri = json.dumps(govde).encode()
        son_hata = None
        for bekle in (0, 4, 12, 25):
            if bekle: time.sleep(bekle)
            try:
                _ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
                istek = urllib.request.Request(url, data=veri, method="POST",
                                               headers={"Content-Type": "application/json",
                                                        "User-Agent": _ua,
                                                        "Accept": "application/json",
                                                        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
                                                        **basliklar})
                with urllib.request.urlopen(istek, timeout=120) as y:
                    return json.loads(y.read().decode())
            except urllib.error.HTTPError as e:
                son_hata = e
                # 401/403 geçersiz veya yetkisiz anahtardır; tekrar bekleme.
                if e.code in (400, 401, 403, 404): raise
                if e.code not in (429, 500, 502, 503, 504): raise
            except Exception as e:
                son_hata = e
        raise son_hata

    def _ayikla(metin):
        import re
        m = re.search(r"\{.*\}", metin, re.S)
        return json.loads(m.group(0)) if m else {}

    # sağlayıcı zinciri: groq -> gemini -> openrouter (mpt_uret ile aynı mantık)
    denemeler = []
    if os.getenv("GROQ_API_KEY"):
        _groq_model = groq_model()
        denemeler.append(lambda: _ayikla(_cagir(
            "https://api.groq.com/openai/v1/chat/completions",
            {"model": _groq_model,
             "temperature": 0.7,
             "messages": [{"role": "system", "content": SAHNE_SISTEM},
                          {"role": "user", "content": istem}]},
            {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        )["choices"][0]["message"]["content"]))
    if os.getenv("GEMINI_API_KEY"):
        model = os.getenv("GEMINI_LLM_MODEL", "").strip()
        if not model or model.startswith("llama-") or model == "gemini-3.6-flash":
            try:
                with urllib.request.urlopen("https://generativelanguage.googleapis.com/v1beta/models?key=" + os.environ["GEMINI_API_KEY"], timeout=60) as y:
                    modeller = json.load(y).get("models", [])
                uygun = [m["name"].split("/",1)[-1] for m in modeller if "generateContent" in m.get("supportedGenerationMethods",[]) and "flash" in m.get("name","").lower() and not any(x in m.get("name","").lower() for x in ("tts","image","live","omni"))]
                model = sorted(uygun, key=lambda x: (("preview" not in x), x), reverse=True)[0]
            except Exception:
                model = "gemini-2.5-flash"
        denemeler.append(lambda: _ayikla(_cagir(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={os.environ['GEMINI_API_KEY']}",
            {"systemInstruction": {"parts": [{"text": SAHNE_SISTEM}]},
             "contents": [{"role": "user", "parts": [{"text": istem}]}],
             "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7}},
            {},
        )["candidates"][0]["content"]["parts"][0]["text"]))

    # OpenRouter — son yedek (ücretsiz modeller)
    if os.getenv("OPENROUTER_API_KEY"):
        _or_model = os.getenv("OPENROUTER_LLM_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
        denemeler.append(lambda: _ayikla(_cagir(
            "https://openrouter.ai/api/v1/chat/completions",
            {"model": _or_model, "temperature": 0.7,
             "messages": [{"role": "system", "content": SAHNE_SISTEM},
                          {"role": "user", "content": istem}]},
            {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
             "HTTP-Referer": "https://github.com/benngokhan/yt_auto_uploader",
             "X-Title": "Bilgi Dozu Motor"},
        )["choices"][0]["message"]["content"]))

    def _tamamla(liste: list, adet: int, konu: str) -> list:
        """LLM 4'ten az/çok sahne verdiyse 4'e oturt ve boş alanları doldur."""
        liste = [x for x in liste if str(x.get("ses", "")).strip()][:adet]
        while len(liste) < adet:
            liste.append({"ses": "", "baslik1": "", "baslik2": "",
                          "emoji": "🔎", "gorsel": konu, "gorsel_anahtar": konu,
                          "vurgular": []})
        for x in liste:
            x.setdefault("baslik1", "")
            x.setdefault("baslik2", "")
            x.setdefault("emoji", "🔎")
            x.setdefault("gorsel", konu)
            x.setdefault("gorsel_anahtar", x.get("gorsel", konu))
            x.setdefault("vurgular", [])
        return liste

    for dene in denemeler:
        try:
            veri = dene()
            sahneler = veri.get("sahneler") or []
            if len(sahneler) >= 2:
                sahneler = _tamamla(sahneler, 4, konu)
                print(f"Sahne planı hazır ({len(sahneler)} sahne)")
                return sahneler
            print("LLM yanıtı geçersiz sahne şeması döndürdü")
        except Exception as hata:  # noqa: BLE001
            print(f"LLM denemesi başarısız: {type(hata).__name__}: {str(hata)[:120]}")
    raise SystemExit("Sahne planı üretilemedi: tüm LLM sağlayıcıları başarısız.")


def _tek_sahne_uzat(konu: str, ses_metni: str, hedef: int = 165, baglam: str = "", isimler: str = "") -> str:
    """Tek bir sahne cümlesini hedef karakter sayısına genişletir.

    Tüm anlatımı tek istekte uzatmak güvenilir değildi (LLM yine kısa yazıyordu).
    Sahne sahne genişletmek hem kesin hem de sahne başına ~9-10 sn hedefini korur.
    """
    import urllib.request, json as _j

    _ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    istek = (f"Konu: {konu}\n"
             f"Aşağıdaki Türkçe anlatım cümlesi çok kısa. Aynı bilgiyi koruyarak "
             f"{hedef-8}-{hedef+10} karakterlik TEK bir doğal cümle yaz. "
             f"Somut bir ayrıntı veya örnek ekle. Uydurma bilgi yok, selamlama yok.\n"
             + TERIM_KURALLARI + SAYI_KURALLARI + isimler +
             "- Cümledeki terimleri ve sayıları AYNEN koru; aynı şey için yeni bir ad kullanma, yeni kesin sayı ekleme.\n"
             + (f"Videonun diğer cümleleri (YALNIZCA terim ve sayı tutarlılığı için; bu cümlelerdeki bilgiyi "
                f"TEKRAR ETME, onlardan parça kopyalama): {baglam}\n" if baglam else "")
             + f"Yalnızca cümleyi döndür, tırnak/açıklama ekleme.\n\nCümle: {ses_metni}")

    def _gemini():
        k = os.getenv("GEMINI_API_KEY", "").strip()
        if not k:
            raise RuntimeError("gemini yok")
        with urllib.request.urlopen(
            "https://generativelanguage.googleapis.com/v1beta/models?key=" + k, timeout=60) as y:
            modeller = _j.load(y).get("models", [])
        uygun = [m["name"].split("/", 1)[-1] for m in modeller
                 if "generateContent" in m.get("supportedGenerationMethods", [])
                 and "flash" in m.get("name", "").lower()
                 and not any(x in m.get("name", "").lower() for x in ("tts", "image", "live", "omni"))]
        if not uygun:
            raise RuntimeError("gemini model yok")
        model = sorted(uygun, key=lambda x: (("preview" not in x), x), reverse=True)[0]
        govde = {"contents": [{"role": "user", "parts": [{"text": istek}]}],
                 "generationConfig": {"temperature": 0.75, "maxOutputTokens": 2048}}
        r = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={k}",
            data=_j.dumps(govde).encode(), method="POST",
            headers={"Content-Type": "application/json", "User-Agent": _ua})
        with urllib.request.urlopen(r, timeout=120) as y:
            ham = _j.loads(y.read().decode())
        aday = (ham.get("candidates") or [{}])[0]
        return "".join(p.get("text", "") for p in (aday.get("content") or {}).get("parts") or []).strip()

    def _groq():
        k = os.getenv("GROQ_API_KEY", "").strip()
        if not k:
            raise RuntimeError("groq yok")
        govde = {"model": groq_model(), "temperature": 0.75,
                 "messages": [{"role": "user", "content": istek}]}
        r = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",
                                   data=_j.dumps(govde).encode(), method="POST",
                                   headers={"Content-Type": "application/json", "User-Agent": _ua,
                                            "Authorization": f"Bearer {k}"})
        with urllib.request.urlopen(r, timeout=120) as y:
            return _j.loads(y.read().decode())["choices"][0]["message"]["content"].strip()

    for dene in (_gemini, _groq):
        try:
            metin = " ".join(dene().replace("\n", " ").split())
            metin = metin.strip('"\' ')
            if len(metin) >= max(68, hedef - 18):
                return metin
        except Exception as h:
            print(f"  sahne uzatma ({dene.__name__}): {type(h).__name__}")
    return ses_metni


def _anlatimi_uzat(konu: str, sahneler: list, hedef_toplam: int = 620) -> int:
    """Her sahneyi ayrı ayrı genişletir; toplam hedefe ulaşana kadar dener."""
    import math
    alt_sinir = max(78, hedef_toplam // max(1, len(sahneler)))
    ust_sinir = max(115, alt_sinir + 35)
    for tur in range(3):
        toplam = len(" ".join(str(x.get("ses", "")) for x in sahneler))
        if toplam >= hedef_toplam:
            break
        eksik = hedef_toplam - toplam
        for s in sahneler:
            if len(" ".join(str(x.get("ses", "")) for x in sahneler)) >= hedef_toplam:
                break
            mevcut = len(str(s.get("ses", "")))
            pay = max(12, eksik // max(1, len(sahneler)))
            hedef = min(ust_sinir, max(alt_sinir, mevcut + pay))
            if mevcut < hedef - 5:
                digerleri = [str(x.get("ses", "")) for x in sahneler if x is not s]
                try:
                    import senaryo_denetim as _sdu
                    _isimler = _sdu.isimlendirme_listesi([str(x.get("ses", "")) for x in sahneler])
                    _cift = lambda c: bool(_sdu.terim_tutarsizligi_bul(digerleri + [c]))  # noqa: E731
                except Exception:  # noqa: BLE001
                    _isimler, _cift = "", (lambda c: False)
                yeni = _tek_sahne_uzat(konu, str(s.get("ses", "")), hedef, baglam=" ".join(digerleri), isimler=_isimler)
                # Uzatılmış cümle başka bir cümlenin tekrarına dönüştüyse kabul edilmez (özgün cümle kalır).
                _eski_ses = str(s.get("ses", ""))
                if len(yeni) > mevcut and any(_benzerlik(yeni, d) >= TEKRAR_ESIGI for d in digerleri):
                    print("  uzatma reddedildi: başka bir cümleyi tekrar ediyor")
                    _karar = "REDDEDİLDİ (başka bir cümleyi tekrar ediyor)"
                elif len(yeni) > mevcut and _cift(yeni) and not _cift(_eski_ses):
                    print("  uzatma reddedildi: aynı şey için farklı bir ad getiriyor")
                    _karar = "REDDEDİLDİ (farklı terim getiriyor)"
                elif len(yeni) > mevcut:
                    s["ses"] = yeni
                    _karar = "KABUL"
                else:
                    _karar = "KULLANILMADI (daha uzun değil)"
                _arsivle("senaryo_uzatma_adimi",
                         f"tur: {tur + 1}\nhedef karakter: {hedef}\nkarar: {_karar}\n\nÖNCE:\n{_eski_ses}\n\nYAPAY ZEKÂNIN ÖNERDİĞİ:\n{yeni}")
        print(f"  uzatma turu {tur+1}: "
              f"{len(' '.join(str(x.get('ses','')) for x in sahneler))} karakter")
    return len(" ".join(str(x.get("ses", "")) for x in sahneler))



# ── SHORTS V2.4: dört görsel, beş anlatım vuruşu ve ilk görsele dönen loop ──
PROMPT_V2 = (
    "Konu: {konu}\n\n"
    "Bilgi Dozu için 15–25 saniyelik (varsayılan hedef yaklaşık 20 saniye), Türkçe bilim Shorts planı yaz. "
    "Tam dört benzersiz fotoğraf kullanılır; finalde ilk fotoğraf yeniden gösterilir.\n"
    "- 'cumleler' dizisine TAM {n} kısa cümle yaz. Her bir cümle 7–9 kelime olsun; toplam 35–45 kelime zorunludur. Göndermeden önce kelimeleri say, 35'ten azsa cümleleri somut ayrıntılarla uzat.\n"
    "- 1. cümle doğrudan merak uyandıran soru-hook olsun; ilk kelime video başında duyulur.\n"
    "- 2. cümle cevabın ilk kısmıdır ve ikinci görselle gösterilir. Ekrana ayrıca 'Takip et' yazı katmanı konur; "
    "bu ifade SADECE görsel katmanıdır, seslendirme cümlelerine ekleme.\n"
    "- 3. ve 4. cümleler cevabı tamamlayan, birbirini tekrar etmeyen iki kısa ve somut bilgidir; 3. ve 4. görsellerle gösterilir.\n"
    "- 5. cümle kısa bir soru ile kapanmalı; açılıştaki konuya ve aynı 3+ harfli anahtar sözcüğe dönerek ilk görsele kesintisiz loop kurmalı.\n"
    "- 'sahne_basliklari' yalnız dört benzersiz görsel içindir ve tam {visual_count} elemanlı olmalı; son loop vuruşu ilk görsel ve ilk başlığı yeniden kullanır.\n"
    "- EXTREME TOPIC FİLTRESİ: doğrulanmamış 'asla/her zaman/en büyük/tek gerçek', sansasyonel sağlık/ölüm iddiası, ölçü veya kesin sayı kullanma. Kaynağı doğrulanmayan kurum/araştırma adı da ekleme.\n"
    "- Kaynak yoksa sayısal/ölçülü iddia, kurum atfı veya kaynak varmış izlenimi oluşturma. Emin değilsen iddiayı çıkar; uydurma bilgi ve sayı YASAK.\n"
    "- KELİME SEÇİMİ: kulağın hemen anlayacağı sade Türkçe kullan; tekerleme gibi zor akademik/yabancı kelimeler ('fotoreseptörlerdeki', 'rodopsinin', 'rejenerasyonu', 'biyolüminesans') YASAK.\n"
    "- Başlık soru biçiminde ve verilen konuyla doğrudan ilgili olsun; 'title_question' en fazla 70 karakter ve '?' ile bitsin.\n"
    "- 'kapak_baslik' tek bir sorunun 2 veya 3 satıra bölünmüş hâlidir: tümü TAM BÜYÜK HARF, her satır 3–18 karakter, kelime bölünmez; soru işareti yalnız son satırın sonunda olur.\n"
    "- 'loop_anchor' ilk ve son cümlede geçen, konuya özgü tek bir 3+ harfli kelime olsun.\n"
    "- Her başlık anlamlı, vurucu iki TAM BÜYÜK HARF satırdan oluşsun (satır başı en fazla 18 karakter, kelime bölünmez) ve ikon ('?', '▼', '⚡', '▲', '!', '✔') içersin.\n"
    "- Kısaltma, parantez, üç nokta, selamlama veya sesli CTA kullanma.\n"
    + TERIM_KURALLARI + SAYI_KURALLARI +
    "- 'kaynak_url': yalnızca bu senaryodaki iddiayı gerçekten destekleyen ve erişilebilir birincil/akademik sayfanın tam HTTPS URL'si. Kurum adı tek başına kaynak değildir; gerçek bir kaynak yoksa boş bırak; genel geçer ifade YASAK; emin değilsen boş bırak.\n"
    "- 'kaynak': eski kaynak adı alanı; kaynak_url yoksa ekrana yazılmaz.\n"
    "Yalnız JSON döndür: {{\"title_question\": \"Soru başlığı?\", \"kapak_baslik\": [\"İLK SATIR\", \"SON SATIR?\"], "
    "\"loop_anchor\": \"konu kelimesi\", \"kaynak_url\": \"https://... (yoksa boş)\", \"kaynak\": \"isteğe bağlı kurum adı\", "
    "\"cumleler\": [\"1. hook sorusu?\", \"2. cevap başlangıcı.\", \"3. kısa bilgi.\", \"4. kısa bilgi.\", \"5. loop sorusu?\"], "
    "\"sahne_basliklari\": [{{\"ikon\": \"?\", \"satir1\": \"...\", \"satir2\": \"...\"}}, ... dört başlık]}}"
)

def _llm_json(istem: str, ayar: dict, sistem: str | None = None) -> dict:
    """Sahne planındaki sağlayıcı zincirini (groq -> gemini -> openrouter) tek istem için kullanır."""
    import urllib.request
    import re as _re
    sistem = sistem or _LLM_SISTEM

    def _cagir(url, govde, basliklar):
        import time, urllib.error
        veri = json.dumps(govde).encode()
        son_hata = None
        for bekle in (0, 4, 12, 25):
            if bekle:
                time.sleep(bekle)
            try:
                _ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
                istek = urllib.request.Request(url, data=veri, method="POST",
                                               headers={"Content-Type": "application/json",
                                                        "User-Agent": _ua,
                                                        "Accept": "application/json",
                                                        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
                                                        **basliklar})
                with urllib.request.urlopen(istek, timeout=120) as y:
                    return json.loads(y.read().decode())
            except urllib.error.HTTPError as e:
                son_hata = e
                try:
                    print(f"v2 LLM HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
                except Exception:
                    pass
                if e.code in (400, 401, 403, 404):
                    raise
                if e.code not in (429, 500, 502, 503, 504):
                    raise
            except Exception as e:
                son_hata = e
        raise son_hata

    _arsivle("llm_istek", f"SİSTEM:\n{sistem}\n\nİSTEM:\n{istem}")

    def _ayikla(metin):
        _arsivle("llm_ham_cevap", metin or "(boş cevap)")
        metin = (metin or "").strip()
        if not metin:
            return {}
        metin = _re.sub(r"<think>.*?</think>", "", metin, flags=_re.S).strip()
        m = _re.search(r"\{.*\}", metin, _re.S)
        if not m:
            print(f"v2 LLM ham yanıt (JSON yok): {metin[:400]}")
            return {}
        try:
            d = json.loads(m.group(0))
            if isinstance(d, dict):
                print(f"v2 LLM JSON anahtarları: {list(d.keys())[:6]}")
            return d
        except Exception:
            print(f"v2 LLM JSON çözülemedi: {metin[:500]}")
            return {}

    if os.getenv("GROQ_API_KEY"):
        for m in dict.fromkeys([groq_model(), "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]):
            try:
                print(f"v2 LLM: groq {m}")
                yanit = _cagir(
                    "https://api.groq.com/openai/v1/chat/completions",
                    {"model": m, "temperature": 0.65, "max_tokens": 2048,
                     "response_format": {"type": "json_object"},
                     "messages": [{"role": "system", "content": sistem},
                                  {"role": "user", "content": istem}]},
                    {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
                )
                msg = (yanit.get("choices") or [{}])[0].get("message") or {}
                icerik = msg.get("content") or msg.get("reasoning") or ""
                d = _ayikla(icerik)
                print(f"v2 groq yanıtı ({m}): {'dolu' if d else 'BOŞ'}")
                if d.get("cumleler") or d.get("sahneler") or d.get("aramalar") or d.get("sahneler_gorsel"):
                    return d
            except Exception as h:
                print(f"v2 groq ({m}) başarısız: {type(h).__name__}")

    if os.getenv("GEMINI_API_KEY"):
        aday_modeller: list[str] = []
        istenen_gem = os.getenv("GEMINI_LLM_MODEL", "").strip()
        if istenen_gem and not istenen_gem.startswith("llama-") and istenen_gem not in ("gemini-2.5-flash", "gemini-3.6-flash"):
            aday_modeller.append(istenen_gem)
        try:
            with urllib.request.urlopen(
                "https://generativelanguage.googleapis.com/v1beta/models?key=" + os.environ["GEMINI_API_KEY"],
                timeout=45,
            ) as y:
                modeller = json.load(y).get("models", [])
            uygun = [
                m["name"].split("/", 1)[-1]
                for m in modeller
                if "generateContent" in m.get("supportedGenerationMethods", [])
                and ("flash" in m.get("name", "").lower() or "pro" in m.get("name", "").lower())
                and not any(x in m.get("name", "").lower() for x in ("tts", "image", "live", "omni", "embedding", "2.5-flash", "1.5-"))
            ]
            aday_modeller.extend(sorted(uygun, key=lambda x: (("flash" in x), ("preview" not in x), x), reverse=True)[:3])
        except Exception as e:
            print(f"Gemini model listesi alınamadı: {type(e).__name__}")
        for model in dict.fromkeys(aday_modeller or ["gemini-flash-latest", "gemini-2.5-pro"]):
            try:
                print(f"v2 LLM: gemini {model}")
                ham = _cagir(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                    f"?key={os.environ['GEMINI_API_KEY']}",
                    {"systemInstruction": {"parts": [{"text": sistem}]},
                     "contents": [{"role": "user", "parts": [{"text": istem}]}],
                     "generationConfig": {"responseMimeType": "application/json", "temperature": 0.65, "maxOutputTokens": 2048}},
                    {},
                )
                parcalar = ((ham.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                metin_gem = "".join(p.get("text", "") for p in parcalar if not p.get("thought"))
                d = _ayikla(metin_gem)
                print(f"v2 gemini yanıtı ({model}): {'dolu' if d else 'BOŞ'}")
                if d.get("cumleler") or d.get("sahneler") or d.get("aramalar") or d.get("sahneler_gorsel"):
                    return d
            except Exception as h:
                print(f"v2 gemini ({model}) başarısız: {type(h).__name__}")

    if os.getenv("OPENROUTER_API_KEY"):
        try:
            m = os.getenv("OPENROUTER_LLM_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
            d = _ayikla(_cagir("https://openrouter.ai/api/v1/chat/completions",
                {"model": m, "temperature": 0.7,
                 "messages": [{"role": "system", "content": sistem},
                              {"role": "user", "content": istem}]},
                {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "HTTP-Referer": "https://github.com/benngokhan/yt_auto_uploader",
                 "X-Title": "Bilgi Dozu Motor"})["choices"][0]["message"]["content"])
            print(f"v2 openrouter yanıtı: {'dolu' if d else 'BOŞ'}")
            if d.get("cumleler") or d.get("sahneler") or d.get("aramalar") or d.get("sahneler_gorsel"):
                return d
        except Exception as h:
            print(f"v2 openrouter başarısız: {type(h).__name__}")
    return {}


def _konu_iki_satir(konu: str, llm_kapak: list | None = None) -> tuple[str, str]:
    """Konuyu kelime ortasından ASLA bölmeden <=20 karakterlik 2 vurucu satıra ayırır."""
    if isinstance(llm_kapak, list) and len(llm_kapak) >= 2:
        s1 = tr_upper(str(llm_kapak[0]).strip())
        s2 = tr_upper(str(llm_kapak[1]).strip())
        if 3 <= len(s1) <= 20 and 3 <= len(s2) <= 20:
            return s1, s2
    kelimeler = [tr_upper(k) for k in str(konu or "").split() if k.strip()]
    satir1, satir2 = [], []
    for k in kelimeler:
        aday1 = " ".join(satir1 + [k])
        if not satir2 and len(aday1) <= 19:
            satir1.append(k)
        else:
            aday2 = " ".join(satir2 + [k])
            if len(aday2) <= 19:
                satir2.append(k)
            else:
                break
    if not satir1 and kelimeler:
        satir1 = [kelimeler[0][:19]]
    if not satir2:
        satir2 = [kelimeler[1][:19]] if len(kelimeler) > 1 else ["GERÇEĞİ"]
    return " ".join(satir1), " ".join(satir2)


def sahne_plani_v2(konu: str, n: int, ayar: dict) -> list[dict]:
    """Plan five narration beats over four unique visuals; the closing beat reuses visual 1."""
    import sys as _sys
    from shorts_acceptance import (
        EXPECTED_NARRATION_BEATS, EXPECTED_SCENES, ShortsAcceptanceError,
        topic_score, validate_script,
    )

    if int(n) != EXPECTED_SCENES:
        raise SystemExit(f"Shorts v2.4 tam {EXPECTED_SCENES} benzersiz görsel ister")
    _sys.path.insert(0, str(MOTOR))
    try:
        import shorts_pipeline as _sp
    except Exception as h:
        raise SystemExit(f"Shorts v2.4 renderer yüklenemedi (motor/shorts_pipeline.py): {type(h).__name__}") from h

    istem = PROMPT_V2.format(konu=konu, n=EXPECTED_NARRATION_BEATS, visual_count=EXPECTED_SCENES)
    last_error = "LLM geçerli plan döndürmedi"
    accepted = None
    for deneme in range(3):
        veri = _llm_json(istem, ayar, _LLM_SISTEM)
        if not isinstance(veri, dict):
            veri = {}
        ham_cumleler = veri.get("cumleler") or veri.get("sahneler") or []
        if isinstance(ham_cumleler, str):
            ham_cumleler = [ham_cumleler]
        cumleler = []
        for c in ham_cumleler if isinstance(ham_cumleler, list) else []:
            if isinstance(c, dict):
                c = c.get("cumle") or c.get("ses") or c.get("metin") or ""
            c = " ".join(str(c or "").split())
            if c:
                cumleler.append(c)

        title = " ".join(str(veri.get("title_question") or "").split())
        raw_cover = veri.get("kapak_baslik")
        cover_lines = [tr_upper(" ".join(str(line or "").split()))
                       for line in raw_cover] if isinstance(raw_cover, list) else []
        loop_anchor = " ".join(str(veri.get("loop_anchor") or "").split())
        raw_headlines = veri.get("sahne_basliklari")
        ham_kaynak = _kaynak_temizle(
            veri.get("kaynak_url"), kaynaksiz_etiket=str(veri.get("kaynak") or "")
        )
        tekrarlar = _tekrar_eden_cumleler(cumleler)
        _arsivle(
            f"senaryo_ham_deneme{deneme + 1}",
            "\n".join(f"{i}. {line}" for i, line in enumerate(cumleler, 1))
            + f"\n\ntekrar denetimi (cümle, cümle, benzerlik): {tekrarlar or 'tekrar yok'}",
        )
        try:
            if len(cumleler) != EXPECTED_NARRATION_BEATS:
                raise ShortsAcceptanceError(
                    f"tam {EXPECTED_NARRATION_BEATS} anlatım vuruşu yerine {len(cumleler)} geldi"
                )
            if tekrarlar:
                raise ShortsAcceptanceError(f"tekrar eden cümleler: {tekrarlar}")
            checked = validate_script(
                [{"ses": line} for line in cumleler], topic=konu,
                verified_source_url=ham_kaynak, title=title,
                cover_lines=cover_lines, loop_anchor=loop_anchor,
            )
            if not isinstance(raw_headlines, list) or len(raw_headlines) != EXPECTED_SCENES:
                raise ShortsAcceptanceError(f"sahne_basliklari tam {EXPECTED_SCENES} benzersiz görsel başlığı içermeli")
            if not isinstance(cover_lines, list) or len(cover_lines) not in (2, 3):
                raise ShortsAcceptanceError("kapak_baslik 2 veya 3 satır değil")
            accepted = {
                "data": veri,
                "lines": cumleler,
                "title": title,
                "cover_lines": cover_lines,
                "loop_anchor": loop_anchor,
                "source_url": ham_kaynak,
                "headlines": raw_headlines,
                "validation": checked,
            }
            break
        except ShortsAcceptanceError as exc:
            last_error = str(exc)
            _arsivle(
                f"senaryo_v24_dogrulama_deneme{deneme + 1}",
                f"karar: REDDEDİLDİ\nneden: {last_error}\n\n"
                + "\n".join(f"{i}. {line}" for i, line in enumerate(cumleler, 1)),
            )
            if deneme < 2:
                istem = (
                    PROMPT_V2.format(konu=konu, n=EXPECTED_NARRATION_BEATS, visual_count=EXPECTED_SCENES)
                    + f"\nÖNCEKİ DENEME REDDEDİLDİ: {last_error}. Beş anlatım vuruşu ve dört görsel başlığını baştan doğru üret."
                )

    if accepted is None:
        raise SystemExit(f"Shorts v2.4 senaryo kapısı geçilemedi: {last_error}. Üretim yapılmadı.")

    cumleler = accepted["lines"]
    title = accepted["title"]
    cover_lines = accepted["cover_lines"]
    loop_anchor = accepted["loop_anchor"]
    ham_kaynak = accepted["source_url"]
    title_l1, title_l2 = _sp._wrap_two_lines_20(tr_upper(title), 20)
    cfg = {"title": [[title_l1, "w"], [title_l2]], "scene_headlines": accepted["headlines"]}
    try:
        headlines = _sp.resolve_scene_headlines(cfg, cumleler[:EXPECTED_SCENES], EXPECTED_SCENES)
    except Exception as h:
        raise SystemExit(f"Shorts v2.4 sahne başlıkları doğrulanamadı ({type(h).__name__}).") from h
    headlines[0] = {"icon": "?", "line1": title_l1, "line2": title_l2}
    # Loop closing shows image 1 and repeats its question headline; it is not a fifth asset.
    timeline_headlines = headlines + [dict(headlines[0])]

    topic_filter = topic_score(konu, ham_kaynak)
    print(
        f"Shorts v2.4 planı: {EXPECTED_SCENES} benzersiz görsel, {EXPECTED_NARRATION_BEATS} anlatım vuruşu, "
        f"{accepted['validation']['word_count']} kelime, hook/loop={loop_anchor!r}, başlık={title!r}, "
        f"konu filtresi={topic_filter['score']}/100, {ham_kaynak or 'kaynak yok (gösterilmeyecek)'}"
    )
    scenes = [{
        "ses": c,
        "baslik1": b.get("line1", ""),
        "baslik2": b.get("line2", ""),
        "ikon": b.get("icon", "!"),
        "kaynak": ham_kaynak,
    } for c, b in zip(cumleler, timeline_headlines)]
    scenes[0]["_v2_metadata"] = {
        "title_question": title,
        "cover_lines": cover_lines,
        "loop_anchor": loop_anchor,
        "source_url": ham_kaynak,
        "topic_filter": topic_filter,
    }
    return scenes

def tr_upper(metin: str) -> str:
    """Türkçe doğru büyük harf (i -> İ, ı -> I)."""
    return (metin or "").replace("i", "İ").replace("ı", "I").upper()


def _gorsel_aramalari(konu: str, cumleler: list, ayar: dict) -> tuple[list[dict], list[str]]:
    """Her sahne için birbirinden FARKLI 2 kademeli yakın plan bilimsel/makro İngilizce Pexels araması üretir."""
    n = len(cumleler)
    numarali = "\n".join(f"{i+1}) {c}" for i, c in enumerate(cumleler))
    istem = (
        f"Konu: {konu}\n\n"
        f"Cümleler:\n{numarali}\n\n"
        f"Yukarıdaki {n} Türkçe bilim cümlesinin her biri için Pexels gerçek kamera fotoğrafı arşivinde "
        f"net 4K dikey bilimsel/tıbbi/optik sonuç verecek BİRBİRİNDEN TAMAMEN FARKLI İngilizce somut nesne aramaları yaz.\n"
        "KESİN KURALLAR (Pexels gerçek kamera fotoğrafı arşividir, 3D çizim arşivi değildir):\n"
        "1) İki sahnede aynı ana kelimeyi TEKRARLAMA.\n"
        "2) SADECE gerçek bir fotoğrafçının kamerayla çekebileceği somut bilimsel/optik/anatomik/laboratuvar nesneleri yaz "
        "(mükemmel örnekler: 'human eye iris', 'scientist microscope', 'laboratory test tube', 'brain mri scan', "
        "'optical glass lens', 'blue laser beam', 'hourglass sand', 'medical laboratory', 'astronomy night sky', "
        "'water droplets glass', 'wristwatch gears', 'clinical thermometer').\n"
        "3) YASAK SORGULAR: Kamerayla çekilemeyen soyut molekül/bakteri adları ('vitamin molecule', 'retinal pigment', 'bacteria', 'protein') YASAK (bunlar kozmetik şişesi döndürür; yerine 'laboratory pipette' veya 'scientist microscope' yaz)! "
        "'texture', 'pattern', 'abstract', 'background' kelimeleri YASAK (kağıt dokusu döndürür)! "
        "Gündelik stok klişeleri ('mobile phone', 'hand holding phone', 'person texting', 'person in bed', 'man', 'woman', 'office', 'window') YASAK!\n"
        f"Yalnız JSON döndür: {{\"sahneler_gorsel\": [{{\"ana\": \"bu sahnenin metnindeki somut nesne/eylem\", \"alternatif\": \"aynı sahneyle doğrudan ilgili başka somut nesne\"}}, ...]}}. "
        f"\"sahneler_gorsel\" dizisi TAM {n} elemanlı olacak."
    )
    veri = _llm_json(istem, ayar, _LLM_SISTEM)
    ham_liste = veri.get("sahneler_gorsel") or veri.get("aramalar") or []
    # Genel bilim/atmosfer yedeği bilinçli olarak yok: sahneye uygun terim yoksa görsel seçilmez.
    yedekler: list[str] = []
    sahneler_q: list[dict] = []
    for item in ham_liste[:n]:
        if isinstance(item, dict):
            ana = str(item.get("ana") or item.get("alternatif") or "").strip()
            alt = str(item.get("alternatif") or "").strip()
        else:
            ana = str(item).strip()
            alt = ""
        sahneler_q.append({"ana": ana, "alternatif": alt})

    while len(sahneler_q) < n:
        sahneler_q.append({"ana": "", "alternatif": ""})

    print(f"Görsel aramaları ({len(sahneler_q)}): {[x['ana'] for x in sahneler_q]} | genel yedek yok")
    return sahneler_q, yedekler


def _v2_gemini_voice_settings(ayar: dict) -> dict:
    """Validate the configured natural TTS voice without making a provider call."""
    import math
    from shorts_acceptance import ShortsAcceptanceError, V2_VOICE_ID, V2_VOICE_PROVIDER

    voice_settings = ayar.get("ses") if isinstance(ayar.get("ses"), dict) else {}
    configured_provider = str(voice_settings.get("saglayici") or "").strip().lower()
    voice_id = str(voice_settings.get("voice_id") or V2_VOICE_ID).strip()
    model = str(voice_settings.get("model") or "gemini-2.5-flash-preview-tts").strip()
    language = str(voice_settings.get("dil") or "tr").strip()
    try:
        speed = float(voice_settings.get("voice_speed_factor", 1.0))
    except (TypeError, ValueError) as exc:
        raise ShortsAcceptanceError("Gemini/Charon voice_speed_factor sayı olmalı") from exc

    if configured_provider not in {"gemini", "gemini_tts", "gemini_natural"}:
        raise ShortsAcceptanceError("Shorts v2 yalnız mevcut Gemini Natural TTS sağlayıcısını kullanabilir")
    if voice_id != V2_VOICE_ID:
        raise ShortsAcceptanceError("Shorts v2 ses kimliği Charon olmalı")
    if not model.startswith("gemini-") or language not in {"tr", "tr-TR"}:
        raise ShortsAcceptanceError("Gemini TTS modeli veya Türkçe dil ayarı geçersiz")
    if not math.isfinite(speed) or abs(speed - 1.0) > 1e-9:
        raise ShortsAcceptanceError("Shorts v2 Charon sesi 1.00x kalmalı")
    return {
        "provider": V2_VOICE_PROVIDER,
        "voice_id": voice_id,
        "model": model,
        "language": language,
        "speed_factor": speed,
    }


def _generate_gemini_v2_voice_audio(scene_lines: list[str], work_dir: Path, ayar: dict) -> Path:
    """Generate the v2 narration through the existing Gemini Natural TTS/Charon path."""
    import hashlib
    from shorts_acceptance import (
        ShortsAcceptanceError, V2_VOICE_GENERATION,
        V2_VOICE_PROVENANCE_STATUS, sha256_file,
    )

    voice = _v2_gemini_voice_settings(ayar)
    from shorts_acceptance import EXPECTED_NARRATION_BEATS
    if len(scene_lines) != EXPECTED_NARRATION_BEATS:
        raise ShortsAcceptanceError(f"Gemini/Charon sesi için tam {EXPECTED_NARRATION_BEATS} anlatım vuruşu gerekli")

    work_dir.mkdir(parents=True, exist_ok=True)
    raw_wav = work_dir / "vo_raw.wav"
    raw_wav.unlink(missing_ok=True)
    narration = " ".join(" ".join(str(line).split()) for line in scene_lines)
    try:
        import tts
        tts.uret("\n".join(str(line).strip() for line in scene_lines), raw_wav, ayar)
    except Exception:
        raw_wav.unlink(missing_ok=True)
        raise
    if not raw_wav.is_file() or raw_wav.stat().st_size == 0:
        raise SystemExit("Gemini Natural TTS Charon ses dosyası üretmedi; v2 üretimi durduruldu.")

    manifest = {
        "provider": voice["provider"],
        "generation": V2_VOICE_GENERATION,
        "provenance_status": V2_VOICE_PROVENANCE_STATUS,
        "voice_id": voice["voice_id"],
        "model": voice["model"],
        "language": voice["language"],
        "narration_sha256": hashlib.sha256(narration.encode("utf-8")).hexdigest(),
        "audio_sha256": sha256_file(raw_wav),
    }
    (work_dir / "voice_provenance_v2.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return raw_wav


def _sablon_v2_uret(a, ayar: dict, sahne_sayisi: int, calisma=None) -> int:
    """Shorts v2.4 local production path; it never uploads or publishes."""
    if os.getenv("MOTOR_EXPERIMENTAL_OPENROUTER") == "1" and not getattr(a, "kuru", False):
        raise SystemExit("Deneysel görsel doğrulayıcı yalnız yayınsız kuru testte kullanılabilir.")
    import shutil
    from PIL import Image
    from shorts_acceptance import (
        EXPECTED_NARRATION_BEATS, EXPECTED_SCENES, V2_CTA_OVERLAY_BEAT_INDEX,
        V2_CTA_OVERLAY_TEXT, V2_VISUAL_SEQUENCE,
        FORMAT_VERSION, LOCKED_MIX_TIMING, SHORTS_VERSION, TEMPLATE_VERSION, validate_script,
    )

    if int(sahne_sayisi) != EXPECTED_SCENES:
        raise SystemExit(f"Shorts v2 tam {EXPECTED_SCENES} benzersiz görsel ister; legacy yoluna geçilmedi.")
    calisma = MOTOR / "cikti" / "son"

    sahneler = sahne_plani_v2(a.konu, EXPECTED_SCENES, ayar)
    _arsivle_senaryo("senaryo_1_plan_sonrasi", sahneler)
    _terim_birligi_sagla(sahneler, ayar, "kısa v2 planı")
    _sayi_denetimi(sahneler, ayar)
    _arsivle_senaryo("senaryo_2_terim_ve_sayi_sonrasi", sahneler)
    _yazim_denetimi(sahneler, ayar)
    _arsivle_senaryo("senaryo_3_yazim_denetimi_sonrasi", sahneler)
    _baslik_denetimi(sahneler, ayar)
    _arsivle_senaryo("senaryo_4_baslik_denetimi_sonrasi_SON", sahneler)
    _senaryo_son_kapi(sahneler)
    _baslik_anlam_denetimi(sahneler, ayar)
    try:
        import senaryo_denetim as _sd
        _uy = _sd.uyarilar([x["ses"] for x in sahneler])
        for _u in _uy:
            print(f"UYARI (denetim): {_u}")
        _arsivle("senaryo_uyarilari", "\n".join(_uy) or "uyarı yok")
    except Exception as _dh:  # noqa: BLE001
        print(f"Senaryo uyarı denetimi çalışmadı ({type(_dh).__name__})")

    v2_meta = sahneler[0].get("_v2_metadata") if sahneler else None
    if not isinstance(v2_meta, dict):
        raise SystemExit("Shorts v2.4 başlık/loop/kaynak metaverisi eksik; üretim durduruldu.")
    script_lines = [" ".join(str(x.get("ses") or "").split()) for x in sahneler]
    script_check = validate_script(
        sahneler, topic=a.konu,
        verified_source_url=str(v2_meta.get("source_url") or ""),
        title=str(v2_meta.get("title_question") or ""),
        cover_lines=v2_meta.get("cover_lines"),
        loop_anchor=str(v2_meta.get("loop_anchor") or ""),
    )
    anlatim = script_check["narration"]
    voice_plan = _v2_gemini_voice_settings(ayar)
    for sira, x in enumerate(sahneler, start=1):
        print(f"  senaryo {sira}: [{x.get('baslik1', '')} / {x.get('baslik2', '')}] {x['ses']}")
    print(f"Anlatım: {script_check['word_count']} kelime / {len(sahneler)} sahne")

    if getattr(a, "plan_only", False):
        plan_dir = MOTOR / "cikti" / "plan_only"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / "shorts_v2_plan.json"
        plan_path.write_text(json.dumps({
            "topic": a.konu,
            "format_version": FORMAT_VERSION,
            "shorts_version": SHORTS_VERSION,
            "template_version": TEMPLATE_VERSION,
            "production_mode": "production_v2",
            "scene_count": EXPECTED_SCENES,
            "narration_beat_count": EXPECTED_NARRATION_BEATS,
            "word_count": script_check["word_count"],
            "voice_speed_factor": voice_plan["speed_factor"],
            "voice_provider": voice_plan["provider"],
            "voice_id": voice_plan["voice_id"],
            "voice_model": voice_plan["model"],
            "voice_language": voice_plan["language"],
            "voice_generation": "not_run_plan_only",
            "script_lines": script_lines,
            "narration": anlatim,
            "question_title": v2_meta["title_question"],
            "cover_lines": v2_meta["cover_lines"],
            "loop_anchor": v2_meta["loop_anchor"],
            "topic_filter": v2_meta.get("topic_filter"),
            "plan_only": True,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"PLAN-ONLY: metin planı yazıldı; ses sentezi ve render çalıştırılmadı: {plan_path}")
        return 0

    if calisma.exists():
        shutil.rmtree(calisma, ignore_errors=True)
    calisma.mkdir(parents=True, exist_ok=True)
    vdir = calisma / "v2"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "script.txt").write_text("\n".join(script_lines) + "\n", encoding="utf-8")
    raw_wav = _generate_gemini_v2_voice_audio(script_lines, vdir, ayar)

    if getattr(a, "sadece_ses", False):
        ses_onay = calisma / "ses_onay.wav"
        shutil.copyfile(raw_wav, ses_onay)
        print(f"Yalnızca Gemini Natural TTS/Charon sesi üretildi; render yapılmadı: {ses_onay}")
        return 0

    # 2) GÖRSELLER (v2 fail-closed: all seven scenes require live Pexels + Gemini Vision)
    gorsel_klasoru = calisma / "gorseller"
    gorsel_klasoru.mkdir(parents=True, exist_ok=True)
    import gorsel_uret

    visual_sentences = [str(s["ses"]) for s in sahneler[:EXPECTED_SCENES]]
    aramalar, yedekler = _gorsel_aramalari(a.konu, visual_sentences, ayar)
    visual_scene_inputs = [
        {
            "gorsel": ar["ana"],
            "gorsel_anahtar": ar["ana"],
            "gorsel_alternatif": ar.get("alternatif", ""),
            "ses": visual_sentences[index],
        }
        for index, ar in enumerate(aramalar)
    ]
    parallelar = gorsel_uret.sahneler_icin_gorseller(
        visual_scene_inputs, gorsel_klasoru, yedek_sorgular=yedekler
    )
    if len(parallelar) != EXPECTED_SCENES or any(path is None for path in parallelar):
        raise SystemExit("Shorts v2 fail-closed: dört görselin tamamı canlı görsel seçimini geçmedi.")

    secim_raporu_yolu = gorsel_klasoru / "gorsel_secim_raporu.json"
    if not secim_raporu_yolu.is_file():
        raise SystemExit("Canlı görsel seçim raporu eksik; Shorts v2 durduruldu.")
    secim_raporu = json.loads(secim_raporu_yolu.read_text(encoding="utf-8"))
    rows = secim_raporu.get("scenes")
    if not isinstance(rows, list) or len(rows) != EXPECTED_SCENES:
        raise SystemExit("Canlı görsel seçim raporu tam dört görsel içermiyor.")
    for index, row in enumerate(rows, start=1):
        selected = row.get("selected") if isinstance(row, dict) else None
        experimental_origin = (os.getenv("MOTOR_EXPERIMENTAL_OPENROUTER") == "1" and a.kuru and
                               secim_raporu.get("semantic_model") == "particle-ai/particle-1:free" and
                               isinstance(selected, dict) and selected.get("score_origin") == "live_openrouter_experimental")
        if not isinstance(selected, dict) or selected.get("provider") != "pexels" \
                or not (selected.get("score_origin") == "live_gemini_vision" or experimental_origin):
            raise SystemExit(f"Shorts v2 sahne {index}: canlı görsel doğrulama kanıtı yok.")

    from shorts_acceptance import sha256_file
    render_inputs = []
    for index, path in enumerate(parallelar, start=1):
        target = vdir / f"s{index}.jpg"
        with Image.open(path) as image:
            image.convert("RGB").save(target, "JPEG", quality=94)
        render_inputs.append({"file": target.name, "sha256": sha256_file(target)})

    visual_validation = {
        "version": 2,
        "mode": "production_v2",
        "generation": "live",
        "fallback_policy": "fail_closed",
        "semantic_model": secim_raporu.get("semantic_model"),
        "semantic_threshold": secim_raporu.get("threshold"),
        "scenes": rows,
        "render_inputs": render_inputs,
    }
    (vdir / "visual_validation.json").write_text(
        json.dumps(visual_validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Künye: kaynak bu videonun kendi senaryosundan; yoksa kaynak satırı gösterilmez.
    kaynak_url = str(sahneler[0].get("kaynak") or "")
    konu_kaynak = f"Kaynak URL: {kaynak_url}" if kaynak_url else ""
    # Görsel açıklaması ve sağlayıcı linkleri her sahne için ayrı üretilecek.
    gorsel_notu = ""

    cfg = {
        "format_version": FORMAT_VERSION,
        "shorts_version": SHORTS_VERSION,
        "template_version": TEMPLATE_VERSION,
        "production_mode": "production_v2",
        "topic": a.konu,
        "question_title": v2_meta["title_question"],
        "loop_anchor": v2_meta["loop_anchor"],
        "topic_filter": v2_meta.get("topic_filter"),
        "voice_speed_factor": voice_plan["speed_factor"],
        "voice_provider": voice_plan["provider"],
        "voice_id": voice_plan["voice_id"],
        "voice_model": voice_plan["model"],
        "voice_language": voice_plan["language"],
        "title": [[sahneler[0]["baslik1"], "g"], [sahneler[0]["baslik2"]]],
        "scene_headlines": [{"icon": s.get("ikon", "!"), "line1": s["baslik1"], "line2": s["baslik2"]}
                            for s in sahneler[:EXPECTED_SCENES]],
        "cover_lines": v2_meta["cover_lines"],
        "music_theme": ayar.get("music_theme", "gunluk_bilim"),
        "intro_lead": LOCKED_MIX_TIMING["intro_lead"],
        "sentence_pause": LOCKED_MIX_TIMING["sentence_pause"],
        "outro_hold": LOCKED_MIX_TIMING["outro_hold"],
        "note1": konu_kaynak,
        "note2": gorsel_notu,
        "source_url": kaynak_url,
        "visual_credits": [
            ({"provider": row["selected"]["provider"], "url": row["selected"]["source_page_url"],
              "representative": True} if row.get("selected") else None)
            for row in (secim_raporu.get("scenes") or [])
        ],
        "scenes": [f"s{i}.jpg" for i in range(1, EXPECTED_SCENES + 1)],
        "visual_sequence": list(V2_VISUAL_SEQUENCE),
        "cta_overlay_text": V2_CTA_OVERLAY_TEXT,
        "cta_overlay_beat_index": V2_CTA_OVERLAY_BEAT_INDEX,
    }
    cfg_yolu = calisma / "shorts_config.json"
    cfg_yolu.write_text(json.dumps({vdir.name: cfg}, ensure_ascii=False, indent=2), encoding="utf-8")

    motor_py = str(MOTOR / "shorts_pipeline.py")
    env = os.environ.copy()
    env.setdefault("MIRA_MOTOR_FFMPEG", shutil.which("ffmpeg") or "")
    print("Shorts v2.4 renderer çalışıyor (plates -> timing -> music -> render -> cover; CTA yalnız görsel katman)…")
    subprocess.run([sys.executable, motor_py, "all", str(vdir), str(cfg_yolu)],
                   check=True, env=env)

    cikti = vdir / "video.mp4"
    if not cikti.exists():
        raise SystemExit("Shorts v2.4 renderer video üretmedi.")

    # Deterministic local metadata: it may restate the checked script, but does not invent claims.
    metadata = {
        "baslik": v2_meta["title_question"],
        "aciklama": anlatim + (f"\n\nKaynak: {kaynak_url}" if kaynak_url else ""),
        "hashtag": "#bilgidozu #shorts #bilim",
        "etiketler": ", ".join(dict.fromkeys(
            [w.lower() for w in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]{4,}", a.konu)[:8]]
            + ["bilgi dozu", "bilim", "shorts"]
        )),
        "sabit_yorum": v2_meta["title_question"],
        "kategori": "Bilim ve Eğitim",
        "konu_ozeti": anlatim,
        "kapak_satirlari": v2_meta["cover_lines"],
        "kapak_vurgu": len(v2_meta["cover_lines"]),
        "kapak_kategori": "BİLİM & KEŞİF",
        "kapak_alt": script_lines[1],
    }
    (calisma / "yayin_bilgisi.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Yayın bilgileri hazır")
    _arsivle("yayin_bilgileri", json.dumps(metadata, ensure_ascii=False, indent=2), "json")

    onay_dir = calisma / "onay_bekleyen"
    onay_dir.mkdir(parents=True, exist_ok=True)
    hedef_mp4 = onay_dir / "final.mp4"
    hedef_kapak = onay_dir / "kapak.jpg"
    shutil.copyfile(cikti, hedef_mp4)

    # Keep the complete local proof bundle, then verify the delivered copy against it.
    evidence_dir = onay_dir / "evidence_v2"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "render_manifest_v2.json", "visual_validation.json", "voice_provenance_v2.json",
        "script.txt", "timing.json", "audio_qc.json", "vo_raw.wav", "vo_final.wav", "mix.wav",
    ):
        source_path = vdir / name
        if source_path.is_file():
            shutil.copyfile(source_path, evidence_dir / name)
    for name in cfg["scenes"]:
        shutil.copyfile(vdir / name, evidence_dir / name)
    (evidence_dir / "shorts_config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise SystemExit("FFprobe yok; teslim MP4 SHA256/süre doğrulaması yapılamadı.")
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(hedef_mp4)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    from shorts_acceptance import validate_render_manifest_v2
    validate_render_manifest_v2(evidence_dir, cfg, probe.stdout.strip(), mp4_path=hedef_mp4)

    # Standart Bilgi Dozu dikey kapak şablonu (kapak_176..196 ile birebir uyumlu)
    import kapak as kapak_mod
    kapak_bilgi = kapak_mod.kapak_metni_hazirla(a.konu, sahneler, metadata)
    gercek_kapak_adaylari = [p for p in parallelar if p is not None]
    kapak_arka = _kapak_gorseli_sec(a.konu, gercek_kapak_adaylari) if gercek_kapak_adaylari else (vdir / "s1.jpg")
    kapak_mod.kapak_uret(
        kapak_arka,
        hedef_kapak,
        satirlar=kapak_bilgi["satirlar"],
        vurgu_satiri=kapak_bilgi.get("vurgu"),
        kategori=kapak_bilgi["kategori"],
        alt_aciklama=kapak_bilgi["alt_aciklama"],
    )
    from shorts_acceptance import validate_title_cover
    validate_title_cover(
        v2_meta["title_question"], kapak_bilgi["satirlar"], topic=a.konu
    )
    with Image.open(hedef_kapak) as final_cover:
        if final_cover.size != (1080, 1920):
            raise SystemExit(f"Kapak 9:16 ölçüsünde değil: {final_cover.size}")

    # Geçici klasörleri temizle ki yalnız yerel onay dosyaları kalsın; hiçbir yerde yayımlanmaz.
    shutil.rmtree(vdir, ignore_errors=True)
    shutil.rmtree(gorsel_klasoru, ignore_errors=True)
    cfg_yolu.unlink(missing_ok=True)

    print(f"Video hazır: {hedef_mp4}")
    print(f"Kapak hazır (standart şablon): {hedef_kapak} -> {kapak_bilgi['satirlar']}")

    if a.kuru:
        print(f"KURU KOŞU TAMAMLANDI: {hedef_mp4} (Drive/Telegram adımı atlanır)")
        return 0
    print(f"ONAY BEKLİYOR: {hedef_mp4}")
    return 0


def _kapak_gorseli_sec(konu: str, yollar: list) -> Path:
    """Kapak arka planı: sahne görselleri içinden konuyu en doğru ve net göstereni seçer.

    Eskiden her zaman 1. sahnenin görseli kullanılıyordu (ör. mum konusunda çakmak fotoğrafı kapağa çıktı).
    Seçimi Gemini görsellere bakarak yapar; anahtar yoksa ya da hata olursa eski davranış (1. görsel) sürer.
    """
    yollar = [Path(y) for y in yollar]
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if len(yollar) < 2 or not key:
        return yollar[0]
    try:
        import base64, io, urllib.request
        from PIL import Image
        parcalar = [{"text": (
            f"Konu: {konu}\nAşağıda numaralı {len(yollar)} dikey fotoğraf var. Bir YouTube Shorts kapağının arka planı için "
            "konunun ana nesnesini EN DOĞRU ve EN NET gösteren fotoğrafı seç. Konuyla ilgisiz ya da yanıltıcı nesne gösteren "
            "(ör. mum konusunda çakmak), bulanık, yazı/logo içeren fotoğrafı seçme; koyu ve sinematik olanı tercih et. "
            'Yalnız JSON döndür: {"secim": numara}')}]
        for i, y in enumerate(yollar, start=1):
            im = Image.open(y).convert("RGB")
            im.thumbnail((384, 384))
            tampon = io.BytesIO()
            im.save(tampon, "JPEG", quality=80)
            parcalar.append({"text": f"Fotoğraf {i}:"})
            parcalar.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(tampon.getvalue()).decode()}})
        with urllib.request.urlopen("https://generativelanguage.googleapis.com/v1beta/models?key=" + key, timeout=60) as r:
            modeller = json.load(r).get("models", [])
        uygun = [m["name"].split("/", 1)[-1] for m in modeller
                 if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in m.get("name", "").lower()
                 and not any(x in m.get("name", "").lower() for x in ("tts", "image", "live", "omni", "1.5-"))]
        model = sorted(uygun, key=lambda x: (("preview" not in x), x), reverse=True)[0]
        govde = {"contents": [{"parts": parcalar}],
                 "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0}}
        istek = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            data=json.dumps(govde).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(istek, timeout=120) as r:
            metin = json.load(r)["candidates"][0]["content"]["parts"][0]["text"]
        secim = int(json.loads(metin)["secim"])
        if 1 <= secim <= len(yollar):
            print(f"Kapak görseli: {secim}. sahne seçildi ({len(yollar)} aday)")
            return yollar[secim - 1]
        print(f"Kapak görseli seçimi geçersiz ({secim}); 1. sahne kullanılıyor")
    except Exception as e:  # noqa: BLE001 — kapak seçimi üretimi asla durdurmaz
        print(f"Kapak görseli seçilemedi ({type(e).__name__}); 1. sahne kullanılıyor")
    return yollar[0]


def yayin_bilgisi_uret(konu: str, sahneler: list[dict]) -> dict:
    """Onay kartı, standart kapak ve Excel için eksiksiz YouTube yayın metadatası üretir."""
    import urllib.request, urllib.error, re
    anlatim = " ".join(str(x.get("ses", "")) for x in sahneler)
    prompt = (f"Konu: {konu}\nAnlatım: {anlatim}\nBilgi Dozu YouTube Shorts için yalnız JSON döndür: "
              '{"baslik":"70 karakteri geçmeyen merak uyandırıcı başlık","aciklama":"2 kısa paragraf, doğrulanmamış iddia yok",'
              '"hashtag":"3-5 hashtag","etiketler":"virgülle 8-12 arama etiketi","sabit_yorum":"doğal, konuya özel tek soru ve emoji",'
              '"kategori":"kategori","konu_ozeti":"tek cümle",'
              '"kapak_satirlari":["1. SATIR","2. SATIR","3. SATIR?"],"kapak_vurgu":2,'
              '"kapak_kategori":"KONUYA ÖZEL ALAN ETİKETİ","kapak_alt":"tek cümle"}. '
              'KAPAK KURALLARI: kapak_satirlari, videonun cevapladığı TEK merak sorusunun sırayla 3 satıra bölünmüş hâlidir; '
              'satırlar art arda okununca tek düzgün Türkçe soru cümlesi olmalı (ör. ["YUTKUNUNCA GELEN","KULAKTAKİ KLİK","SESİ NEDİR?"]). '
              'İki ayrı cümle veya slogan yazma (YANLIŞ: ["BEYAZ DUMAN","YAKIT MIDIR?","ALEV İNİYOR"]); soru işareti yalnız son satırın sonunda olur. '
              'Her satır TAM BÜYÜK HARF, 8-16 karakter, kelime bölünmez. '
              'kapak_vurgu: konunun anahtar kavramını taşıyan satırın numarası (1, 2 veya 3); o satır sarı yazılır. '
              'kapak_kategori: konunun bilim alanını anlatan, konuya özel kısa etiket; "X & Y" biçiminde, en fazla 20 karakter '
              '(ör. ANATOMİ & AKUSTİK, KİMYA & YANMA, FİZİK & OPTİK); konu insan vücudu değilse İNSAN yazma. '
              'kapak_alt: yanlış bilineni düzelten veya mekanizmayı söyleyen, en fazla 90 karakterlik tek cümle '
              '(ör. "Çene kemiği değil: Östaki borusunun basıncı eşitleme sesidir."). '
              'Abartılı garanti, sahte bilgi ve genel/geçici metin kullanma.')
    text=None; errors=[]
    groq=os.getenv("GROQ_API_KEY","").strip()
    _ua="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
    if groq:
        try:
            body={"model":groq_model(),"temperature":0.5,"response_format":{"type":"json_object"},"messages":[{"role":"user","content":prompt}]}
            req=urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",data=json.dumps(body).encode(),headers={"Content-Type":"application/json","User-Agent":_ua,"Authorization":"Bearer "+groq})
            with urllib.request.urlopen(req,timeout=120) as r:text=json.load(r)["choices"][0]["message"]["content"]
        except Exception as e: errors.append("groq:"+repr(e))
    key=os.getenv("GEMINI_API_KEY","").strip()
    if text is None and key:
        try:
            import time
            with urllib.request.urlopen("https://generativelanguage.googleapis.com/v1beta/models?key="+key,timeout=60) as r:models=json.load(r).get("models",[])
            usable=[m["name"].split("/",1)[-1] for m in models if "generateContent" in m.get("supportedGenerationMethods",[]) and "flash" in m.get("name","").lower() and not any(x in m.get("name","").lower() for x in ("tts","image","live","omni","2.5-flash","1.5-"))]
            model=sorted(usable,key=lambda x:(("preview" not in x),x),reverse=True)[0]
            body={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"responseMimeType":"application/json","temperature":0.5}}
            son=None
            for bekle in (0,5,15,30):
                if bekle: time.sleep(bekle)
                try:
                    req=urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
                    with urllib.request.urlopen(req,timeout=120) as r:data=json.load(r)
                    text=data["candidates"][0]["content"]["parts"][0]["text"]
                    break
                except urllib.error.HTTPError as e:
                    son=e
                    if e.code not in (429,500,502,503,504): raise
            if text is None and son: raise son
        except Exception as e: errors.append("gemini:"+repr(e))
    if text is None:
        # Metadata servisi geçici olarak kapalı olsa bile tamamlanmış MP4'ü kaybetme.
        temiz = re.sub(r"\s+", " ", konu).strip()
        etiket_kelimeler = [x.lower() for x in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]{4,}", temiz)[:8]]
        return {"baslik": temiz[:67].rstrip(" ?!.,") + "?",
                "aciklama": anlatim + "\n\nBu kısa videoda " + temiz.lower() + " konusunu açıklıyoruz.",
                "hashtag": "#bilgidozu #shorts #bilim",
                "etiketler": ", ".join(dict.fromkeys(etiket_kelimeler + ["bilgi dozu","bilim","shorts"])),
                "sabit_yorum": temiz.rstrip(" ?!.,") + " hakkında daha önce bunu fark etmiş miydiniz? 🧠",
                "kategori": "Bilim ve Teknoloji", "konu_ozeti": temiz,
                "metadata_notu": "LLM metadata servisi geçici erişilemedi; güvenli konu tabanlı yedek kullanıldı."}
    m=re.search(r"\{.*\}",text,re.S);out=json.loads(m.group(0) if m else text)
    gerekli=["baslik","aciklama","hashtag","etiketler","sabit_yorum","kategori","konu_ozeti"]
    if any(not str(out.get(k,"")).strip() for k in gerekli): raise SystemExit("Yayın bilgisi eksik üretildi.")
    return out


# ------------------------------------------------------------------- 2) TTS
# ------------------------------------------------------- 3) hizalama (karaoke)
def hizala(ses_yolu: Path, metin: str, ayar: dict) -> dict:
    sys.path.insert(0, str(MOTOR))
    import karaoke_timing as kt

    model_boyut = ayar.get("teknik", {}).get("whisper_model", "small")
    aligner = kt.KaraokeAligner(model_name=model_boyut)
    return aligner.align(ses_yolu, [metin])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--konu", required=True)
    ap.add_argument("--sahne", type=int, default=0, help="0 = ayardan oku")
    ap.add_argument("--sure-min", type=float, default=0, help="0 = ayardan oku")
    ap.add_argument("--sure-max", type=float, default=0, help="0 = ayardan oku")
    ap.add_argument("--kuru", action="store_true", help="Sadece üret, hiçbir yere yükleme")
    ap.add_argument("--shorts-v2", action="store_true", help="Fail-closed Shorts v2 hattını zorla; legacy TTS fallback yok")
    ap.add_argument("--plan-only", action="store_true", help="Yalnız 4 görsel ve 5 anlatım vuruşu planı yaz; ses sentezi ve render yapma")
    ap.add_argument("--sadece-ses", action="store_true", help="Görsel/video üretmeden yalnızca onay sesi üret")
    ap.add_argument("--onay-verildi", action="store_true",
                    help="Kullanıcı videoyu izleyip onayladı: Drive + tablo + yayın kuyruğu")
    a = ap.parse_args()

    ayar = ayar_yukle()
    if a.shorts_v2 or a.plan_only:
        ayar["sahneler_sablon"] = True
        ayar["sahne_sayisi"] = 4
    try:
        import arsiv
        arsiv.cikti_maskele_kur()   # konsola/GitHub loguna yazılan her satır maskeden geçer
        arsiv.baslat(a.konu, {"argumanlar": {k: v for k, v in vars(a).items()}})
    except Exception:  # noqa: BLE001
        pass
    _regresyon_kapisi(ayar)
    if ayar.get("sahneler_sablon"):
        # V2.4: 4 unique visuals, 5 narration beats, 15–25 seconds.
        sahne_sayisi = int(a.sahne or ayar.get("sahne_sayisi") or 4)
        print(f"Şablon v2.4 aktif: {sahne_sayisi} benzersiz görsel")
    else:
        # KURAL (sahip, 12.11.2026): her video 4 sahne, 38-42 saniye.
        sahne_sayisi = 4
        ayar["sahne_sayisi"] = 4
    if a.sure_min:
        ayar.setdefault("sure", {})["min"] = a.sure_min
    if a.sure_max:
        ayar.setdefault("sure", {})["max"] = a.sure_max

    if ayar.get("sahneler_sablon"):
        if sahne_sayisi != 4:
            raise SystemExit("Shorts v2.4 tam 4 görsel ister; legacy TTS fallback yapılmadı.")
        return _sablon_v2_uret(a, ayar, 4, calisma=None)

    if a.shorts_v2 or a.plan_only:
        raise SystemExit("Shorts v2 planlama başarısız; legacy TTS fallback yapılmadı.")
    re_ = motor_hazirla(ayar)
    sahneler = sahne_plani(a.konu, sahne_sayisi, ayar)
    anlatim_karakter = len(" ".join(str(x.get("ses", "")).strip() for x in sahneler))
    print(f"Gerçek anlatım karakteri: {anlatim_karakter}")
    # Kalite kapısı: yalnız KISA anlatım video üretimini engeller.
    # Az yazdıysa sahne sahne otomatik genişletilir (hedef 38-42 sn ≈ 620-700 karakter).
    esik = 380 if ayar.get("sahneler_sablon") else 560
    if anlatim_karakter < esik:
        try:
            anlatim_karakter = _anlatimi_uzat(a.konu, sahneler, 620)
            print(f"Anlatım uzatıldı: {anlatim_karakter} karakter")
        except Exception as _ue:
            print(f"Uzatma denemesi başarısız: {type(_ue).__name__}")
        if anlatim_karakter < esik:
            raise SystemExit(f"Anlatım kalite kapısı: {anlatim_karakter} karakter; en az {esik} gerekli. Video oluşturulmadı.")
    if anlatim_karakter > 760:
        print(f"UYARI: anlatım uzun ({anlatim_karakter} karakter ≈ {anlatim_karakter/15.4:.0f} sn). Video yine üretilir.")
    # XTTS'nin sert veya hatalı okuduğu kalıpları senaryo düzeyinde doğal Türkçeyle değiştir.
    # Böylece ses ile ekrandaki altyazı birebir aynı kalır.
    for s in sahneler:
        metin = str(s.get("ses", ""))
        metin = metin.replace("Sıradaki videoda bakacağız", "Bir sonraki videoda inceleyeceğiz")
        metin = metin.replace("bakacağız.", "inceleyeceğiz.")
        metin = metin.replace("Bakacağız.", "İnceleyeceğiz.")
        s["ses"] = metin

    calisma = KOK / "motor" / "cikti" / "son"
    calisma.mkdir(parents=True, exist_ok=True)
    import tts

    vo_files, hizalamalar = [], []
    if ayar.get("ses", {}).get("tek_istek") and len(sahneler) > 1:
        # TEK SES KURALI: tüm cümleler TEK Gemini isteğinde okunur; 4 ayrı istek
        # farklı ton üretiyordu (sahne 1: 106 Hz ... sahne 4: 156 Hz).
        birlesik = " ".join(str(x["ses"]).strip() for x in sahneler)
        tek_wav = calisma / "vo_tek.wav"
        print(f"Tek istek ses: {len(birlesik)} karakter")
        tts.uret(birlesik, tek_wav, ayar)
        if tek_wav.exists():
            import ses_kenar
            import wave as _wv
            ses_kenar.duzelt(tek_wav)
            parcalar = ses_kenar.cumlelere_bol(tek_wav, [str(x["ses"]).strip() for x in sahneler])
            for i, parca in enumerate(parcalar, start=1):
                wav = calisma / f"vo_{i:02d}.wav"
                parca.to_wav(wav)
                vo_files.append(str(wav))
                hizalamalar.append(hizala(wav, sahneler[i - 1]["ses"], ayar))
                print(f"  sahne {i}: ses {round(re_.wav_duration(str(wav)), 2)} sn")
            if len(vo_files) != len(sahneler):
                raise SystemExit(f"Tek istek ses bölünmesi tutarsız: {len(vo_files)}/{len(sahneler)}")
        else:
            print("Tek istek ses üretilemedi; sahne sahne üretime dönülüyor.")
    for i, s in enumerate(sahneler, start=1):
        if vo_files:
            break
        wav = calisma / f"vo_{i:02d}.wav"
        hiz = tts.uret(s["ses"], wav, ayar)
        if hiz is None:
            # sağlayıcı kelime zamanı vermediyse: sessizlik kırp + Whisper ile hizala
            import ses_kenar
            ses_kenar.duzelt(wav)
            hiz = hizala(wav, s["ses"], ayar)
        vo_files.append(str(wav))
        hizalamalar.append(hiz)
        print(f"  sahne {i}: ses {round(re_.wav_duration(str(wav)), 2)} sn")

    if a.sadece_ses:
        # Geçici kalite modu: görsel ve video yok. Sahne seslerini doğal cümle
        # aralarıyla tek WAV'da birleştir; kullanıcının ses onayını bekle.
        liste = calisma / "ses_birlestir.txt"
        liste.write_text("\n".join(f"file '{Path(v).resolve()}'" for v in vo_files), encoding="utf-8")
        ses_cikti = calisma / "ses_onay.wav"
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(liste),
                        "-af", "aresample=async=1:first_pts=0,loudnorm=I=-18:TP=-1.5:LRA=11",
                        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(ses_cikti)],
                       check=True, timeout=240)
        print(f"Ses onayı hazır: {ses_cikti}")
        return 0

    # ---------------------------------------------------------- 4) görseller
    if os.getenv("MOTOR_VISUAL_QA_PASSED") != "1":
        raise SystemExit("Görselli üretim kilitli: A-D görsel test kapısı yeşil değil.")
    import gorsel_uret
    import altyazi

    gorsel_ayar = ayar.get("gorsel", {})
    kaynak = gorsel_ayar.get("kaynak", "")
    gorsel_klasoru = Path(gorsel_ayar.get("klasor") or (KOK / "motor" / "cikti" / "gorseller"))
    if not gorsel_klasoru.is_absolute():
        gorsel_klasoru = KOK / gorsel_klasoru

    if kaynak in ("pexels", "pixabay", "auto", "stok"):
        konu_kelimeleri = [k for k in {w.strip('.,?!:;').lower() for w in a.konu.split()} if len(k) > 3]
        yedek = [" ".join(konu_kelimeleri[:3])] if konu_kelimeleri else []
        parallelar = gorsel_uret.sahneler_icin_gorseller(sahneler, gorsel_klasoru, yedek)
    elif kaynak == "klasor" and gorsel_klasoru.exists():
        parallelar = sorted(gorsel_klasoru.glob("*.png")) + sorted(gorsel_klasoru.glob("*.jpg"))
    else:
        raise SystemExit(f"Görsel kaynağı tanımsız: {kaynak!r} (ayarlar.json -> gorsel)")

    from PIL import Image
    import numpy as np

    plates = []
    if len(parallelar) < sahne_sayisi:
        raise SystemExit(f"Görsel sayısı yetersiz: {len(parallelar)} < {sahne_sayisi}")

    scene_cfg = []
    for i, (s, hiz) in enumerate(zip(sahneler, hizalamalar)):
        scene_image = parallelar[i]
        is_plain = scene_image is None
        if is_plain:
            scene_image = gorsel_klasoru / f"duz_zemin_{i + 1:02d}.png"
            Image.new("RGB", (1080, 1920), (10, 17, 23)).save(scene_image, "PNG")
        img = Image.open(scene_image).convert("RGB")
        bgr = np.array(img)[:, :, ::-1].copy()
        if not is_plain:
            bgr = re_.apply_teal_orange_cinematic(bgr)
            bgr = re_.add_bioluminescent_particles(bgr, seed=i)
        plates.append(bgr)
        scene_cfg.append({
            "img": str(scene_image),
            # 38–42 sn / 4 sahne: efekt hissedilmeyecek kadar yavaş, akıcı hareket.
            "zoom": (1.00, 1.04),
            "pan_x": (0.0, 0.0),
            "pan_y": (8.0, -8.0) if i % 2 == 0 else (-8.0, 8.0),
            "emoji": s.get("emoji", ""),
            "title_line1": s["baslik1"],
            "title_line2": s["baslik2"],
            "subs": altyazi.grupla(s["ses"]),
            "karaoke": hiz,
        })

    cikti = calisma / "final.mp4"
    re_.render_video_master(
        str(cikti), scene_cfg, vo_files, plates,
        "",  # doğrulanmış kaynak URL'si yoksa kaynak satırı gösterilmez
        is_wide=False,
        target_min_dur=ayar.get("sure", {}).get("min", 38),
        target_max_dur=ayar.get("sure", {}).get("max", 42),
    )
    print(f"Video hazır: {cikti}")

    # ---------------------------------------------------- 6) kapak (şablon sabit)
    import kapak
    kapak_yolu = cikti.parent / "kapak.jpg"
    kapak_satirlari = [sahneler[0]["baslik1"], sahneler[0]["baslik2"]]
    kapak.kapak_uret(
        parallelar[0], kapak_yolu,
        satirlar=[k.upper() for k in kapak_satirlari],
        kategori=ayar.get("kategori", "BİLİM").upper(),
        alt_aciklama=f"{a.konu}",
    )
    print(f"Kapak hazır: {kapak_yolu}")
    metadata = yayin_bilgisi_uret(a.konu, sahneler)
    (cikti.parent / "yayin_bilgisi.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Yayın bilgileri hazır: başlık, açıklama, hashtag, etiket ve sabit yorum")

    if ayar.get("onay", {}).get("mod") == "elle" and not a.onay_verildi:
        onay_dir = calisma / "onay_bekleyen"
        onay_dir.mkdir(parents=True, exist_ok=True)
        hedef = onay_dir / cikti.name
        cikti.replace(hedef)
        print(f"ONAY BEKLİYOR: {hedef}")
        print("Drive'a yüklenmedi, tabloya yazılmadı. İzleyip 'tamam' de; --onay-verildi ile teslim edilir.")
        return 0

    if a.kuru:
        print("KURU: Drive'a yüklenmedi.")
        return 0

    # teslim: drive + tablo (mpt_uret.py'deki yardımcılar yeniden kullanılır)
    import mpt_uret as teslim  # noqa: E402
    drive = teslim.drive_istemci()
    numara = teslim.sonraki_numara(drive)
    dosya_adi = f"video_{numara}.mp4"
    baslik = f"{a.konu} #bilgidozu #shorts"
    teslim.drive_yukle(drive, cikti, dosya_adi)
    teslim.tablo_satir_ekle(
        drive, dosya_adi, baslik,
        "\n\n".join(s["ses"] for s in sahneler),
        "#bilgidozu #shorts", "bilgidozu, shorts, bilgi dozu",
        "Sen bunu biliyor muydun? 👇", ayar.get("kategori", "Bilim"),
        "")
    print(f"Teslim tamam: {dosya_adi}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
