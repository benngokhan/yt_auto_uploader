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


def sahne_plani(konu: str, sahne_sayisi: int, ayar: dict) -> list[dict]:
    """LLM'den sahne sahne plan alır: ses metni + üst başlık + altyazı vurguları."""
    import urllib.request

    istem = (
        f"Konu: {konu}\n\n"
        f"Video {sahne_sayisi} sahne olacak, toplam anlatım 38-42 saniye (sahne başına ~6-7 sn).\n"
        "JSON şeması: {\"sahneler\": [{\"ses\": \"...\", \"baslik1\": \"...\", "
        "\"baslik2\": \"...\", \"emoji\": \"...\", \"gorsel\": \"...\", \"vurgular\": [\"kelime\", ...]}]}\n"
        "- ses: o sahnede söylenecek 1-2 doğal cümle (toplam ~150-170 karakter/sahne). "
        "Nokta, virgül, iki nokta, soru işareti ve gerektiğinde noktalı virgülü anlamına uygun kullan; "
        "TTS'nin doğal nefes alacağı kısa cümleler kur. Üç nokta, parantez, kısaltma ve yapay slogan ritmi kullanma.\n"
        "- baslik1: BÜYÜK HARF, beyaz satır (en fazla 22 karakter)\n"
        "- baslik2: BÜYÜK HARF, sarı satır (en fazla 22 karakter)\n"
        "- emoji: konuya uygun tek emoji\n"
        "- gorsel: her sahnede videonun ANA KONUSUNU görünür tutan, o sahnede FİZİKSEL OLARAK GÖRÜNECEK somut nesneyi/durumu anlatan 3-6 kelimelik "
        "İNGİLİZCE stok fotoğraf araması. Mecaz yasak: \"beyin kontrolü\" yerine \"human brain scan\", "
        "\"ıslak tutuş\" yerine \"wet wrinkled fingertips\" gibi. Fotoğraflanabilir bir şey yaz; "
        "yazı/logo/tabela içeren sahne istemeyin. Ana konu arı/petek ise mum, su damlası gibi yalnızca benzetmeyi gösteren konu dışı görsel YASAK; ana nesne her sorguda geçsin.\n"
        "- vurgular: o sahnenin altyazısında sarı boyanacak 1-3 kelime\n"
        "Selamlama ve 'abone olun' YASAK. İlk sahnenin sesi tek soru ve 5-8 kelime olsun. "
        "Toplam anlatım boşluklar dahil 430-560 Türkçe karakter olmalı; ilk sahne hariç her sahne 110-160 karakter olmalı. "
        "Cümleler doğal, bilgi yoğun ve sesli okumada toplam 38-42 saniyeye uygun olmalı. Son sahne yumuşak ve doğal bir cümleyle bitsin. 'Bakacağız' kelimesini ve sert slogan tonunu kullanma; gerekiyorsa 'Bir sonraki videoda bunu inceleyeceğiz.' de."
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
        denemeler.append(lambda: _ayikla(_cagir(
            "https://api.groq.com/openai/v1/chat/completions",
            {"model": os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile"),
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

    for dene in denemeler:
        try:
            veri = dene()
            sahneler = veri.get("sahneler") or []
            if len(sahneler) >= 3:
                print(f"Sahne planı hazır ({len(sahneler)} sahne)")
                return sahneler
            print("LLM yanıtı geçersiz sahne şeması döndürdü")
        except Exception as hata:  # noqa: BLE001
            print(f"LLM denemesi başarısız: {type(hata).__name__}: {str(hata)[:120]}")
    raise SystemExit("Sahne planı üretilemedi: tüm LLM sağlayıcıları başarısız.")


def _uzat(konu: str, istem: str, sahneler: list, mevcut_karakter: int) -> str:
    """Anlatım 300 karakterin altındaysa LLM'e açıkça uzatma isteği gönderir.
    Sadece ikinci bir tur; başarısız olursa çağıran karar verir."""
    import urllib.request, urllib.error, json as _j

    _ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    mevcut = " ".join(str(x.get("ses", "")) for x in sahneler)
    if not istem:
        istem = (f"Konu: {konu}\nBilgi Dozu YouTube Shorts için sahne planı üret. "
                 f"Video 4 sahne olacak, toplam anlatım 38-42 saniye. "
                 f"Her sahne sesli okunacak doğal Türkçe cümle içersin.")
    istek_metni = (
        f"{istem}\n\nÖNEMLİ: Önceki deneme çok kısaydı ({mevcut_karakter} karakter ≈ "
        f"{mevcut_karakter/15.8:.1f} saniye). Hedef 38-42 saniye, yani yaklaşık 620-680 KARAKTER.\n"
        f"Aşağıdaki anlatımı 4 sahneye bölerek genişlet. Her sahne için daha fazla açıklama, "
        f"somut sayı/örnek ve merak uyandıran detay ekle. Anlamı bozma, uydurma bilgi ekleme.\n\n"
        f"Mevcut anlatım:\n{mevcut}")

    def _dene_groq():
        k = os.getenv("GROQ_API_KEY", "").strip()
        if not k:
            raise RuntimeError("groq yok")
        govde = {"model": os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile"),
                 "temperature": 0.8,
                 "response_format": {"type": "json_object"},
                 "messages": [{"role": "system", "content": SAHNE_SISTEM},
                              {"role": "user", "content": istek_metni}]}
        r = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",
                                   data=_j.dumps(govde).encode(), method="POST",
                                   headers={"Content-Type": "application/json",
                                            "User-Agent": _ua, "Accept": "application/json",
                                            "Authorization": f"Bearer {k}"})
        with urllib.request.urlopen(r, timeout=120) as y:
            return _j.loads(y.read().decode())["choices"][0]["message"]["content"]

    def _dene_gemini():
        k = os.getenv("GEMINI_API_KEY", "").strip()
        if not k:
            raise RuntimeError("gemini yok")
        import re as _re
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
        govde = {"systemInstruction": {"parts": [{"text": SAHNE_SISTEM}]},
                 "contents": [{"role": "user", "parts": [{"text": istek_metni}]}],
                 "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8}}
        r = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={k}",
            data=_j.dumps(govde).encode(), method="POST",
            headers={"Content-Type": "application/json", "User-Agent": _ua})
        with urllib.request.urlopen(r, timeout=120) as y:
            return _j.loads(y.read().decode())["candidates"][0]["content"]["parts"][0]["text"]

    for dene in (_dene_groq, _dene_gemini):
        try:
            metin = dene()
            import re as _re
            m = _re.search(r"\{.*\}", metin, _re.S)
            veri = _j.loads(m.group(0)) if m else {}
            yeni_sahneler = veri.get("sahneler") or []
            yeni = " ".join(str(x.get("ses", "")) for x in yeni_sahneler)
            if len(yeni) >= 400:
                sahneler.clear()
                sahneler.extend(yeni_sahneler)
                return yeni
        except Exception as h:
            print(f"uzatma ({dene.__name__}): {type(h).__name__}")
    raise RuntimeError("anlatım uzatılamadı")


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
    sahne_sayisi = a.sahne or ayar.get("sahne_sayisi", 6)
    if a.sure_min:
        ayar.setdefault("sure", {})["min"] = a.sure_min
    if a.sure_max:
        ayar.setdefault("sure", {})["max"] = a.sure_max
    re_ = motor_hazirla(ayar)

    sahneler = sahne_plani(a.konu, sahne_sayisi, ayar)
    anlatim_karakter = len(" ".join(str(x.get("ses", "")).strip() for x in sahneler))
    print(f"Gerçek anlatım karakteri: {anlatim_karakter}")
    if anlatim_karakter < 300 or anlatim_karakter > 650:
        # Otomatik kurtarma: LLM kısa yazdıysa 2. turda açıkça uzat iste.
        try:
            anlatim = _uzat(a.konu, "", sahneler, anlatim_karakter)
            anlatim_karakter = len(anlatim)
            print(f"Anlatım uzatıldı: {anlatim_karakter} karakter")
        except Exception as _ue:
            print(f"Uzatma denemesi başarısız: {type(_ue).__name__}")
            raise SystemExit(f"Anlatım kalite kapısı: {anlatim_karakter} karakter; gerekli aralık 300-650. Video oluşturulmadı.")
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
