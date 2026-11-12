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



_GROQ_MODEL_ONBELLEK: dict[str, str] = {}


def groq_model() -> str:
    """Canlı model listesinden geçerli bir Groq modeli seçer.

    404'ün kök nedeni buydu: GROQ_LLM_MODEL eski/yanlış bir ada işaret ediyor,
    istek "model not found" dönüyordu. Seçim bir kez yapılır, önbelleğe alınır.
    """
    import urllib.request, json as _j
    if "m" in _GROQ_MODEL_ONBELLEK:
        return _GROQ_MODEL_ONBELLEK["m"]
    anahtar = os.getenv("GROQ_API_KEY", "").strip()
    istenen = os.getenv("GROQ_LLM_MODEL", "").strip()
    secilen = istenen or "llama-3.3-70b-versatile"
    if anahtar:
        try:
            r = urllib.request.Request(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {anahtar}",
                         "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"})
            with urllib.request.urlopen(r, timeout=45) as y:
                canli = [m.get("id") for m in _j.load(y).get("data", []) if m.get("id")]
            if canli:
                if istenen and istenen in canli:
                    secilen = istenen
                else:
                    tercih = ([m for m in canli if "llama-3.3-70b" in m]
                              or [m for m in canli if "llama" in m and "guard" not in m]
                              or [m for m in canli if "gpt-oss" in m]
                              or canli)
                    secilen = tercih[0]
                    if istenen and istenen != secilen:
                        print(f"UYARI: Groq modeli '{istenen}' geçersiz, '{secilen}' kullanılıyor.")
        except Exception as e:
            print(f"Groq model listesi alınamadı: {type(e).__name__}")
    _GROQ_MODEL_ONBELLEK["m"] = secilen
    return secilen


def sahne_plani(konu: str, sahne_sayisi: int, ayar: dict) -> list[dict]:
    """LLM'den sahne sahne plan alır: ses metni + üst başlık + altyazı vurguları."""
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
            if len(metin) >= 110:
                return metin
        except Exception as h:
            print(f"  sahne uzatma ({dene.__name__}): {type(h).__name__}")
    return ses_metni


def _anlatimi_uzat(konu: str, sahneler: list, hedef_toplam: int = 620) -> int:
    """Her sahneyi ayrı ayrı genişletir; toplam hedefe ulaşana kadar dener."""
    import math
    for tur in range(3):
        toplam = len(" ".join(str(x.get("ses", "")) for x in sahneler))
        if toplam >= hedef_toplam:
            break
        eksik = hedef_toplam - toplam
        for s in sahneler:
            mevcut = len(str(s.get("ses", "")))
            pay = max(0, eksik // max(1, len(sahneler)))
            hedef = min(190, max(140, mevcut + pay))
            if mevcut < hedef - 5:
                yeni = _tek_sahne_uzat(konu, str(s.get("ses", "")), hedef)
                if len(yeni) > mevcut:
                    s["ses"] = yeni
        print(f"  uzatma turu {tur+1}: "
              f"{len(' '.join(str(x.get('ses','')) for x in sahneler))} karakter")
    return len(" ".join(str(x.get("ses", "")) for x in sahneler))


def yayin_bilgisi_uret(konu: str, sahneler: list[dict]) -> dict:
    """Onay kartı ve Excel için eksiksiz YouTube yayın metadatası üretir."""
    import urllib.request, urllib.error, re
    anlatim = " ".join(str(x.get("ses", "")) for x in sahneler)
    prompt = (f"Konu: {konu}\nAnlatım: {anlatim}\nBilgi Dozu YouTube Shorts için yalnız JSON döndür: "
              '{"baslik":"70 karakteri geçmeyen merak uyandırıcı başlık","aciklama":"2 kısa paragraf, doğrulanmamış iddia yok",'
              '"hashtag":"3-5 hashtag","etiketler":"virgülle 8-12 arama etiketi","sabit_yorum":"doğal, konuya özel tek soru ve emoji",'
              '"kategori":"kategori","konu_ozeti":"tek cümle"}. Abartılı garanti, sahte bilgi ve genel/geçici metin kullanma.')
    text=None; errors=[]
    groq=os.getenv("GROQ_API_KEY","").strip()
    if groq:
        try:
            body={"model":"llama-3.3-70b-versatile","temperature":0.5,"response_format":{"type":"json_object"},"messages":[{"role":"user","content":prompt}]}
            req=urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",data=json.dumps(body).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+groq})
            with urllib.request.urlopen(req,timeout=120) as r:text=json.load(r)["choices"][0]["message"]["content"]
        except Exception as e: errors.append("groq:"+repr(e))
    key=os.getenv("GEMINI_API_KEY","").strip()
    if text is None and key:
        try:
            import time
            with urllib.request.urlopen("https://generativelanguage.googleapis.com/v1beta/models?key="+key,timeout=60) as r:models=json.load(r).get("models",[])
            usable=[m["name"].split("/",1)[-1] for m in models if "generateContent" in m.get("supportedGenerationMethods",[]) and "flash" in m.get("name","").lower() and not any(x in m.get("name","").lower() for x in ("tts","image","live","omni"))]
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
    # KURAL (sahip, 12.11.2026): her video 4 sahne, 38-42 saniye.
    # Görsel sayısı = sahne sayısı (4). Komut satırı bunu değiştiremez.
    sahne_sayisi = 4
    ayar["sahne_sayisi"] = 4
    if a.sure_min:
        ayar.setdefault("sure", {})["min"] = a.sure_min
    if a.sure_max:
        ayar.setdefault("sure", {})["max"] = a.sure_max
    re_ = motor_hazirla(ayar)

    sahneler = sahne_plani(a.konu, sahne_sayisi, ayar)
    anlatim_karakter = len(" ".join(str(x.get("ses", "")).strip() for x in sahneler))
    print(f"Gerçek anlatım karakteri: {anlatim_karakter}")
    # Kalite kapısı: yalnız KISA anlatım video üretimini engeller.
    # Az yazdıysa sahne sahne otomatik genişletilir (hedef 38-42 sn ≈ 620-700 karakter).
    if anlatim_karakter < 560:
        try:
            anlatim_karakter = _anlatimi_uzat(a.konu, sahneler, 620)
            print(f"Anlatım uzatıldı: {anlatim_karakter} karakter")
        except Exception as _ue:
            print(f"Uzatma denemesi başarısız: {type(_ue).__name__}")
        if anlatim_karakter < 560:
            raise SystemExit(f"Anlatım kalite kapısı: {anlatim_karakter} karakter; en az 560 gerekli. Video oluşturulmadı.")
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
    for i, s in enumerate(sahneler, start=1):
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

    if kaynak == "pixabay":
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
