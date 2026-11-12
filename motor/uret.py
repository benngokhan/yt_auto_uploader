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
import subprocess
import sys
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


def sahne_plani(konu: str, sahne_sayisi: int, ayar: dict) -> list[dict]:
    """LLM'den sahne sahne plan alır: ses metni + üst başlık + altyazı vurguları."""
    if ayar.get("sahneler_sablon"):
        return sahne_plani_v2(konu, ayar.get("sahne_sayisi", 7), ayar)
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
        "'Bakacağız' kelimesini ve sert slogan tonunu kullanma."
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


def _tek_sahne_uzat(konu: str, ses_metni: str, hedef: int = 165) -> str:
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
             f"Somut bir ayrıntı, sayı veya örnek ekle. Uydurma bilgi yok, selamlama yok. "
             f"Yalnızca cümleyi döndür, tırnak/açıklama ekleme.\n\nCümle: {ses_metni}")

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
                yeni = _tek_sahne_uzat(konu, str(s.get("ses", "")), hedef)
                if len(yeni) > mevcut:
                    s["ses"] = yeni
        print(f"  uzatma turu {tur+1}: "
              f"{len(' '.join(str(x.get('ses','')) for x in sahneler))} karakter")
    return len(" ".join(str(x.get("ses", "")) for x in sahneler))



# ── ŞABLON v2.2 (sablon_v2 / video_196 Birebir Master Şablon) ───────────────
PROMPT_V2 = (
    "Konu: {konu}\n\n"
    "Bilgi Dozu YouTube Shorts için TANE TANE, YAVAŞ VE ÇOK ANLAŞILIR okunacak Türkçe bilimsel seslendirme metni, her sahnenin 2 satırlık vurucu üst başlığı ve gerçek bilimsel kaynağını yaz. Kurallar:\n"
    "- TAM {n} cümle yaz. Her cümle 8-12 kelimeden oluşan (58-74 karakterlik), sade ve duru tek bir cümle olsun!\n"
    "- HIZ VE DİKSİYON KURALI (ÇOK KRİTİK): Anlatıcının acele etmeden, tane tane okuyabilmesi için {n} cümlenin toplam uzunluğu KESİNLİKLE 430-505 karakter (58-68 kelime) arasında olsun (530 karakteri ASLA geçme!).\n"
    "- KELİME SEÇİMİ KURALI (ÇOK KRİTİK): Tekerleme gibi zor telaffuz edilen ağır akademik/yabancı kelimeler ('fotoreseptörlerdeki', 'rodopsinin', 'rejenerasyonu', 'biyolüminesans', 'nörotransmitterlerin', 'indirger') YASAK! Bunların yerine kulağın tek seferde şıp diye anlayacağı günlük, sade Türkçe karşılıklar kullan ('gözdeki ışık hücreleri', 'gece görüş boyası', 'yenilenmesi', 'sıfıra düşürür'). Kelimelere üst üste uzun ekler yığma; doğal nefes yerlerine virgül koy.\n"
    "- 1. cümle: KANCA (8-11 kelime). Merak uyandıran net soru.\n"
    "- 2. cümle: PROBLEM/DURUM (9-12 kelime), yaygın yanılgıyı yıkan sade cümle.\n"
    "- 3-{son}: BİLİMSEL AÇIKLAMA (her biri 9-12 kelime). Her cümlede TEK somut mekanizma ve mümkünse TEK gerçek bilimsel sayı "
    "(uydurma sayı YASAK, yalnızca doğrulanmış gerçek değer).\n"
    "- Son cümle (8-11 kelime): net özet sonuç + izleyiciyi düşünmeye çağıran kısa soru.\n"
    "- Selamlama, 'abone olun', 'takip et' YASAK (motor kendi ekler).\n"
    "- Kısaltma, parantez, üç nokta kullanma. Sesli okunduğunda doğal ve rahat aksın.\n"
    "- 'sahne_basliklari': TAM {n} elemanlı dizi. Her cümle için dilbilgisi düzgün, vurucu 2 satır TAM BÜYÜK HARF başlık (her satır EN FAZLA 18 karakter, kelime ortasından bölünmez) ve anlamına uygun ikon ('?', '▼', '⚡', '▲', '!', '✔'). Örnek: "
    "{{\"ikon\":\"?\",\"satir1\":\"ATEŞİN VARKEN\",\"satir2\":\"NEDEN ÜŞÜRSÜN?\"}}, "
    "{{\"ikon\":\"⚡\",\"satir1\":\"BEYNİN TERMOSTAT\",\"satir2\":\"OYUNU OYNUYOR!\"}}.\n"
    "- 'kapak_baslik': TAM 2 elemanlı dizi; her satır TAM BÜYÜK HARF, 10-18 karakter arası.\n"
    "- 'kaynak': Konunun gerçek bilimsel kurum veya hakemli dergi kaynağı, 'Kaynak: ...' biçiminde ve EN FAZLA 46 karakter (ör. 'Kaynak: Harvard Medical School • Nature', uydurma yıl/sayı YASAK).\n"
    "Yalnız JSON döndür: {{\"kapak_baslik\": [\"SATIR 1\", \"SATIR 2\"], \"kaynak\": \"Kaynak: ...\", \"cumleler\": [\"cümle 1\", ...], \"sahne_basliklari\": [{{\"ikon\": \"?\", \"satir1\": \"...\", \"satir2\": \"...\"}}, ...]}}"
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

    def _ayikla(metin):
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
    """Şablon v2.2: LLM yalnız cümleleri yazar, sonuna Saf 3D Kapanış CTA cümlesi eklenir.

    Sahne sayısı, 2 satırlık TAM BÜYÜK HARF başlıklar ve sarı semantik ikon
    (?, ▼, ⚡, ▲, !, ✔) motorun kendi çözümleyicisinden gelir:
    shorts_pipeline.resolve_scene_headlines() — video_187..196 standardıyla birebir aynı.
    """
    import sys as _sys

    _sys.path.insert(0, str(MOTOR))
    try:
        import shorts_pipeline as _sp
    except Exception as h:
        raise SystemExit(f"Şablon v2.2 motoru yüklenemedi (motor/shorts_pipeline.py): {h}")

    n = max(4, min(8, int(n or 7)))
    veri = _llm_json(PROMPT_V2.format(konu=konu, n=n, son=n - 1), ayar, _LLM_SISTEM)
    cumleler = veri.get("cumleler") or veri.get("sahneler") or []
    if isinstance(cumleler, str):
        cumleler = [cumleler]
    duzgun = []
    for c in cumleler:
        if isinstance(c, dict):
            c = c.get("cumle") or c.get("ses") or c.get("metin") or ""
        c = str(c).strip()
        if c:
            duzgun.append(c)
    cumleler = duzgun
    if len(cumleler) < 4:
        raise SystemExit(f"v2 sahne planı: LLM yeterli cümle vermedi ({len(cumleler)}); video üretilmedi.")
    cumleler = cumleler[:n]

    k_l1, k_l2 = _konu_iki_satir(konu, veri.get("kapak_baslik"))
    llm_basliklar = veri.get("sahne_basliklari")
    cfg = {"title": [[k_l1, "g"], [k_l2]]}
    if isinstance(llm_basliklar, list) and len(llm_basliklar) >= len(cumleler):
        cfg["scene_headlines"] = llm_basliklar[:len(cumleler)]
    try:
        basliklar = _sp.resolve_scene_headlines(cfg, cumleler, len(cumleler))
    except Exception as h:
        print(f"Başlık çözümleyici uyarısı: {type(h).__name__}; yedek başlık kullanılıyor")
        basliklar = [{"icon": "?", "line1": k_l1, "line2": k_l2}] + [
            {"icon": "!", "line1": tr_upper(c.split()[0] if c.split() else ""), "line2": "BİLİM"}
            for c in cumleler[1:]
        ]

    ham_kaynak = str(veri.get("kaynak") or "").strip()
    if ham_kaynak and not ham_kaynak.lower().startswith("kaynak"):
        ham_kaynak = f"Kaynak: {ham_kaynak}"
    if not ham_kaynak or "doğrulanmış bilimsel" in ham_kaynak.lower():
        ham_kaynak = "Kaynak: Hakemli Bilimsel Araştırma Arşivi"
    ham_kaynak = ham_kaynak[:54].strip()

    # Saf 3D Kapanış Ekranı (v2.2): başlıklar saf cümlelerden çözüldükten SONRA son sahneye sabit CTA eklenir;
    # "Daha fazla Bilgi Dozu..." başlar başlamaz ekran kararır ve tam "takip et!" dendiğinde fare tıklar.
    kapanis_cta = "Daha fazla Bilgi Dozu için takip et!"
    if "takip et" not in cumleler[-1].lower():
        son_c = cumleler[-1].rstrip()
        if son_c and son_c[-1] not in ".!?":
            son_c += "?"
        cumleler[-1] = f"{son_c} {kapanis_cta}"

    print(f"Şablon v2.2 planı: {len(cumleler)} cümle (+ Saf 3D Kapanış CTA), kapak=[{k_l1} / {k_l2}], {ham_kaynak}")
    return [{"ses": c,
             "baslik1": b.get("line1", ""),
             "baslik2": b.get("line2", ""),
             "ikon": b.get("icon", "!"),
             "kaynak": ham_kaynak}
            for c, b in zip(cumleler, basliklar)]


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
        f"Yalnız JSON döndür: {{\"sahneler_gorsel\": [{{\"ana\": \"2-3 kelimelik gerçek fotoğraflanabilir bilim nesnesi\", \"alternatif\": \"farklı 2-3 kelimelik bilim nesnesi\"}}, ...], "
        f"\"yedekler\": [\"scientist microscope\", \"laboratory test tube\", \"optical glass lens\", \"brain mri scan\"]}}. "
        f"\"sahneler_gorsel\" dizisi TAM {n} elemanlı olacak."
    )
    veri = _llm_json(istem, ayar, _LLM_SISTEM)
    ham_liste = veri.get("sahneler_gorsel") or veri.get("aramalar") or []
    yedekler = [str(x).strip() for x in (veri.get("yedekler") or []) if str(x).strip()]
    if not yedekler:
        yedekler = ["microscope lens", "light prism", "water droplets macro", "laboratory glassware"]

    sahneler_q: list[dict] = []
    for item in ham_liste[:n]:
        if isinstance(item, dict):
            ana = str(item.get("ana") or item.get("alternatif") or "").strip()
            alt = str(item.get("alternatif") or "").strip()
        else:
            ana = str(item).strip()
            alt = ""
        if ana:
            sahneler_q.append({"ana": ana, "alternatif": alt})

    while len(sahneler_q) < n:
        y = yedekler[len(sahneler_q) % len(yedekler)]
        sahneler_q.append({"ana": y, "alternatif": "science laboratory"})

    print(f"Görsel aramaları ({len(sahneler_q)}): {[x['ana'] for x in sahneler_q]} | yedekler={yedekler}")
    return sahneler_q, yedekler


def _sablon_v2_uret(a, ayar: dict, sahne_sayisi: int, calisma=None) -> int:
    """ŞABLON v2.2 üretim hattı: sahne planı -> tek istek ses -> görseller ->
    shorts_pipeline.py all (MİRA v2.2 + Saf 3D Kapanış) -> kapak -> onay."""
    import shutil
    from PIL import Image
    import tts

    re_ = sys.modules.get("render_engine") or motor_hazirla(ayar)
    kok = KOK / "motor"
    calisma = kok / "cikti" / "son"
    if calisma.exists():
        shutil.rmtree(calisma, ignore_errors=True)
    calisma.mkdir(parents=True, exist_ok=True)

    sahneler = sahne_plani_v2(a.konu, sahne_sayisi, ayar)
    anlatim = " ".join(str(x["ses"]).strip() for x in sahneler)
    print(f"Anlatım (ilk): {len(anlatim)} karakter / {len(sahneler)} cümle")
    # Tane tane okuma ile 38-44 sn hedefi için CTA dahil ideal metin 460-535 karakterdir (video_196: 485 krk)
    if len(anlatim) < 455 and len(sahneler) >= 2:
        kapanis_cta = "Daha fazla Bilgi Dozu için takip et!"
        son_ham = str(sahneler[-1]["ses"]).replace(kapanis_cta, "").strip()
        sahneler[-1]["ses"] = son_ham
        _anlatimi_uzat(a.konu, sahneler, hedef_toplam=455)
        son_yeni = str(sahneler[-1]["ses"]).rstrip()
        if son_yeni and son_yeni[-1] not in ".!?":
            son_yeni += "."
        if "takip et" not in son_yeni.lower():
            sahneler[-1]["ses"] = f"{son_yeni} {kapanis_cta}"
        anlatim = " ".join(str(x["ses"]).strip() for x in sahneler)
    print(f"Anlatım: {len(anlatim)} karakter / {len(sahneler)} cümle")
    if len(anlatim) < 300:
        raise SystemExit(f"Anlatım çok kısa: {len(anlatim)} karakter; video üretilmedi.")

    # 1) TEK İSTEK SES (kural: tek anlatıcı, tek ton)
    tek_wav = calisma / "vo_tek.wav"
    tts.uret(anlatim, tek_wav, ayar)
    if not tek_wav.exists():
        raise SystemExit("Ses üretilemedi; video oluşturulmadı.")
    print(f"Tek istek ses hazır: {round(re_.wav_duration(str(tek_wav)), 2)} sn")

    if getattr(a, "sadece_ses", False):
        ses_onay = calisma / "ses_onay.wav"
        shutil.copyfile(tek_wav, ses_onay)
        tek_wav.unlink(missing_ok=True)
        print(f"Sadece ses üretildi: {ses_onay}")
        return 0

    # 2) GÖRSELLER (sahne başına bir görsel, sinematik + konuya %100 alakalı)
    gorsel_klasoru = calisma / "gorseller"
    gorsel_klasoru.mkdir(parents=True, exist_ok=True)
    import gorsel_uret
    aramalar, yedekler = _gorsel_aramalari(
        a.konu,
        [s["ses"].replace("Daha fazla Bilgi Dozu için takip et!", "").strip() or a.konu for s in sahneler],
        ayar,
    )
    parallelar = gorsel_uret.sahneler_icin_gorseller(
        [{"gorsel": ar["ana"], "gorsel_anahtar": ar["ana"], "gorsel_alternatif": ar.get("alternatif", ""), "ses": s["ses"]}
         for s, ar in zip(sahneler, aramalar)],
        gorsel_klasoru, yedek_sorgular=yedekler)
    if len(parallelar) < len(sahneler):
        raise SystemExit(f"Görsel sayısı yetersiz: {len(parallelar)} < {len(sahneler)}")

    # 3) ONAYLI sablon_v2 MOTORU (shorts_pipeline + endcard_v2)
    vdir = calisma / "v2"
    vdir.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(parallelar, start=1):
        with Image.open(p) as im_p:
            im_p.convert("RGB").save(vdir / f"s{i}.jpg", "JPEG", quality=94)
    shutil.copyfile(tek_wav, vdir / "vo_raw.wav")
    (vdir / "script.txt").write_text(anlatim + "\n", encoding="utf-8")

    konu_kaynak = str(sahneler[0].get("kaynak") or ayar.get("kaynak_satiri") or "Kaynak: Hakemli Bilimsel Araştırma Arşivi")
    if "doğrulanmış bilimsel" in konu_kaynak.lower():
        konu_kaynak = "Kaynak: Hakemli Bilimsel Araştırma Arşivi"

    cfg = {
        "title": [[sahneler[0]["baslik1"], "g"], [sahneler[0]["baslik2"]]],
        "scene_headlines": [{"icon": s.get("ikon", "!"), "line1": s["baslik1"], "line2": s["baslik2"]}
                            for s in sahneler],
        "cover_lines": [sahneler[0]["baslik1"], sahneler[0]["baslik2"]],
        "music_theme": ayar.get("music_theme", "gunluk_bilim"),
        "intro_lead": 1.45, "sentence_pause": 0.68, "outro_hold": 1.45,
        "note1": konu_kaynak,
        "note2": "Görseller bilimsel arşivden işlenmiştir.",
        "scenes": [f"s{i}.jpg" for i in range(1, len(sahneler) + 1)],
    }
    cfg_yolu = calisma / "shorts_config.json"
    cfg_yolu.write_text(json.dumps({vdir.name: cfg}, ensure_ascii=False, indent=2), encoding="utf-8")

    motor_py = str(MOTOR / "shorts_pipeline.py")
    env = os.environ.copy()
    env.setdefault("MIRA_MOTOR_FFMPEG", shutil.which("ffmpeg") or "")
    print("MİRA v2.2 motoru çalışıyor (plates -> timing -> music -> render -> cover)…")
    subprocess.run([sys.executable, motor_py, "all", str(vdir), str(cfg_yolu)],
                   check=True, env=env)

    cikti = vdir / "video.mp4"
    if not cikti.exists():
        raise SystemExit("v2.2 motoru video üretmedi.")

    metadata = yayin_bilgisi_uret(a.konu, sahneler)
    (calisma / "yayin_bilgisi.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Yayın bilgileri hazır")

    onay_dir = calisma / "onay_bekleyen"
    onay_dir.mkdir(parents=True, exist_ok=True)
    hedef_mp4 = onay_dir / "final.mp4"
    hedef_kapak = onay_dir / "kapak.jpg"
    shutil.copyfile(cikti, hedef_mp4)

    # Standart Bilgi Dozu dikey kapak şablonu (kapak_176..196 ile birebir uyumlu)
    import kapak as kapak_mod
    kapak_bilgi = kapak_mod.kapak_metni_hazirla(a.konu, sahneler, metadata)
    kapak_mod.kapak_uret(
        parallelar[0],
        hedef_kapak,
        satirlar=kapak_bilgi["satirlar"],
        kategori=kapak_bilgi["kategori"],
        alt_aciklama=kapak_bilgi["alt_aciklama"],
    )

    # Geçici klasörleri temizle ki Drive/Telegram glob araması tek MP4 ve tek kapak bulsun
    shutil.rmtree(vdir, ignore_errors=True)
    shutil.rmtree(gorsel_klasoru, ignore_errors=True)
    tek_wav.unlink(missing_ok=True)
    cfg_yolu.unlink(missing_ok=True)

    print(f"Video hazır: {hedef_mp4}")
    print(f"Kapak hazır (standart şablon): {hedef_kapak} -> {kapak_bilgi['satirlar']}")

    if a.kuru:
        print(f"KURU KOŞU TAMAMLANDI: {hedef_mp4} (Drive/Telegram adımı atlanır)")
        return 0
    print(f"ONAY BEKLİYOR: {hedef_mp4}")
    return 0


def yayin_bilgisi_uret(konu: str, sahneler: list[dict]) -> dict:
    """Onay kartı, standart kapak ve Excel için eksiksiz YouTube yayın metadatası üretir."""
    import urllib.request, urllib.error, re
    anlatim = " ".join(str(x.get("ses", "")) for x in sahneler)
    prompt = (f"Konu: {konu}\nAnlatım: {anlatim}\nBilgi Dozu YouTube Shorts için yalnız JSON döndür: "
              '{"baslik":"70 karakteri geçmeyen merak uyandırıcı başlık","aciklama":"2 kısa paragraf, doğrulanmamış iddia yok",'
              '"hashtag":"3-5 hashtag","etiketler":"virgülle 8-12 arama etiketi","sabit_yorum":"doğal, konuya özel tek soru ve emoji",'
              '"kategori":"kategori","konu_ozeti":"tek cümle",'
              '"kapak_satirlari":["1. SATIR (<=14 harf)","2. SATIR (<=14 harf)","3. VURUCU SATIR? (<=14 harf)"],'
              '"kapak_kategori":"NÖROBİLİM veya İNSAN & BİLİM veya FİZİK & BİLİM veya DOĞA & BİLİM veya UZAY & EVREN veya TARİH & BİLİM",'
              '"kapak_alt":"en fazla 90 karakterlik tek cümle mekanizma özeti"}. '
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
    ap.add_argument("--sadece-ses", action="store_true", help="Görsel/video üretmeden yalnızca onay sesi üret")
    ap.add_argument("--onay-verildi", action="store_true",
                    help="Kullanıcı videoyu izleyip onayladı: Drive + tablo + yayın kuyruğu")
    a = ap.parse_args()

    ayar = ayar_yukle()
    if ayar.get("sahneler_sablon"):
        # ŞABLON v2.0: 7 sahne, 38-45 sn (onaylı video_187..196 standardı)
        sahne_sayisi = int(ayar.get("sahne_sayisi") or 7)
        print(f"Şablon v2 aktif: {sahne_sayisi} sahne")
    else:
        # KURAL (sahip, 12.11.2026): her video 4 sahne, 38-42 saniye.
        sahne_sayisi = 4
        ayar["sahne_sayisi"] = 4
    if a.sure_min:
        ayar.setdefault("sure", {})["min"] = a.sure_min
    if a.sure_max:
        ayar.setdefault("sure", {})["max"] = a.sure_max
    re_ = motor_hazirla(ayar)

    if ayar.get("sahneler_sablon"):
        return _sablon_v2_uret(a, ayar, sahne_sayisi, calisma=None)

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
        img = Image.open(parallelar[i]).convert("RGB")
        bgr = np.array(img)[:, :, ::-1].copy()
        bgr = re_.apply_teal_orange_cinematic(bgr)
        bgr = re_.add_bioluminescent_particles(bgr, seed=i)
        plates.append(bgr)
        scene_cfg.append({
            "img": str(parallelar[i]),
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
        ayar.get("kaynak_satiri", ""),
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
        alt_aciklama=f"{a.konu} · {ayar.get('kaynak_satiri', '')}".strip(" ·"),
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
        ayar.get("kaynak_satiri", ""))
    print(f"Teslim tamam: {dosya_adi}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
