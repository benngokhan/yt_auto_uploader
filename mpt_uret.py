#!/usr/bin/env python3
"""Yedek üretim hattı — MoneyPrinterTurbo (MPT) ile dikey short üretir.

Akış:
    konu -> MPT (stok görüntü + altyazı + ElevenLabs ses) -> video_<N>.mp4
         -> Drive/Kısa Video klasörü + tabloya BEKLEMEDE satırı
         -> mevcut yükleyici (uploader.py) slotta YouTube'a atar

Kurallar (SENARYO_KURALLARI.md):
    * 38-42 sn hedef, 30-45 sn sınır -> dışındaysa UYARI (yayın engellenmez)
    * ses: ElevenLabs (ELEVENLABS_VOICE_ID). Farklı sese fallback YASAK;
      voice_id yoksa hat durur.
    * tek fikir, selamlama yok, kapanış sorusu ekranda.

Örnek:
    python mpt_uret.py --konu "Karıncalar neden kendi ağırlıklarının 50 katını taşır?"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent
sys.path.insert(0, str(KOK))

MPT_DIR = Path(os.getenv("MPT_DIR", str(KOK / "MoneyPrinterTurbo")))

HEDEF_SN = (38, 42)
SINIR_SN = (30, 45)
MIN_KRK, MAX_KRK = 600, 680

SENARYO_YONERGESI = (
    "Metin Türkçe olacak. Tek bir şaşırtıcı bilgi anlat; ikinci bir fikir ekleme. "
    f"Uzunluk {MIN_KRK}-{MAX_KRK} karakter (yaklaşık 40 saniye konuşma). "
    "Selamlama, 'merhaba', 'bugün sizlere', 'kanalımıza abone olun' gibi kalıplar YASAK. "
    "İlk cümle 3 saniyede merak uyandırsın; son cümle ekranda cevaplanacak bir soru olsun. "
    "Cümleler kısa, konuşma diliyle, sayı ve kaynak somut olsun."
)


# ---------------------------------------------------------------- yardımcılar
def _env(ad: str, zorunlu: bool = True) -> str:
    deger = os.getenv(ad, "").strip()
    if zorunlu and not deger:
        raise SystemExit(f"EKSİK AYAR: {ad} tanımlı değil.")
    return deger


def video_kaynagi() -> str:
    """Stok görüntü sağlayıcısı. Pexels yeni anahtar vermeyi durdurdu (Kas 2026),
    bu yüzden Pixabay varsayılan. VIDEO_SOURCE ile elle de seçilebilir."""
    secim = os.getenv("VIDEO_SOURCE", "").strip().lower()
    if secim in ("pexels", "pixabay", "coverr"):
        return secim
    if os.getenv("PIXABAY_API_KEY", "").strip():
        return "pixabay"
    if os.getenv("COVERR_API_KEY", "").strip():
        return "coverr"
    return "pexels"



# ---------------------------------------------------------- senaryo (LLM)
def _post_json(url: str, govde: dict, basliklar: dict):
    import urllib.request
    veri = json.dumps(govde).encode()
    h = {"Content-Type": "application/json", **basliklar}
    istek = urllib.request.Request(url, data=veri, headers=h, method="POST")
    with urllib.request.urlopen(istek, timeout=90) as y:
        return json.loads(y.read().decode())


SENARYO_SISTEM = (
    "Sen Türkçe kısa video senaristisin. Yalnızca istenen JSON'u döndür; açıklama yazma. "
    "Metin tek bir şaşırtıcı bilgiyi anlatır, ikinci bir fikir eklemez."
)


def _senaryo_istem(konu: str) -> str:
    return (
        f"Konu: {konu}\n\n"
        "JSON şeması: {\"senaryo\": \"...\", \"terimler\": \"a, b, c\"}\n"
        f"- senaryo: Türkçe, {MIN_KRK}-{MAX_KRK} karakter, konuşma dili, 6-9 kısa cümle. "
        "Selamlama/'bugün sizlere'/'abone olun' YASAK. İlk cümle 3 saniyede merak uyandırsın. "
        "Son cümle ekranda cevaplanacak bir soru olsun. Sayı ve kaynak somut olsun.\n"
        "- terimler: stok görüntü aramak için 3-4 İNGİLİZCE anahtar kelime, virgülle."
    )


def _cevap_ayikla(metin: str):
    import re as _re
    m = _re.search(r"\{.*\}", metin, _re.S)
    veri = json.loads(m.group(0)) if m else {}
    senaryo = (veri.get("senaryo") or "").strip()
    terimler = (veri.get("terimler") or "").strip()
    return senaryo, terimler


def _groq(konu):
    anahtar = _env("GROQ_API_KEY")
    for model in [os.getenv("MPT_SCRIPT_MODEL", "").strip() or "llama-3.3-70b-versatile",
                  "llama-3.1-8b-instant"]:
        try:
            y = _post_json("https://api.groq.com/openai/v1/chat/completions",
                           {"model": model, "temperature": 0.7,
                            "messages": [{"role": "system", "content": SENARYO_SISTEM},
                                         {"role": "user", "content": _senaryo_istem(konu)}]},
                           {"Authorization": f"Bearer {anahtar}"})
            return _cevap_ayikla(y["choices"][0]["message"]["content"]), f"groq:{model}"
        except Exception as hata:  # noqa: BLE001
            print(f"groq {model} başarısız: {type(hata).__name__}")
    return None, None


def _gemini(konu):
    anahtar = _env("GEMINI_API_KEY")
    for model in [os.getenv("MPT_SCRIPT_MODEL", "").strip() or "gemini-3.8-flash", "gemini-3-flash"]:
        try:
            y = _post_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={anahtar}",
                {"systemInstruction": {"parts": [{"text": SENARYO_SISTEM}]},
                 "contents": [{"role": "user", "parts": [{"text": _senaryo_istem(konu)}]}]},
                {})
            metin = y["candidates"][0]["content"]["parts"][0]["text"]
            return _cevap_ayikla(metin), f"gemini:{model}"
        except Exception as hata:  # noqa: BLE001
            print(f"gemini {model} başarısız: {type(hata).__name__}")
    return None, None


def _openrouter(konu):
    anahtar = _env("OPENROUTER_API_KEY")
    for model in [os.getenv("MPT_SCRIPT_MODEL", "").strip() or "google/gemini-2.5-flash",
                  "meta-llama/llama-3.3-70b-instruct"]:
        try:
            y = _post_json("https://openrouter.ai/api/v1/chat/completions",
                           {"model": model, "temperature": 0.7,
                            "messages": [{"role": "system", "content": SENARYO_SISTEM},
                                         {"role": "user", "content": _senaryo_istem(konu)}]},
                           {"Authorization": f"Bearer {anahtar}"})
            return _cevap_ayikla(y["choices"][0]["message"]["content"]), f"openrouter:{model}"
        except Exception as hata:  # noqa: BLE001
            print(f"openrouter {model} başarısız: {type(hata).__name__}")
    return None, None


def senaryo_uret(konu: str):
    """Sağlayıcı zinciri: groq -> gemini -> openrouter. İlki tutmazsa sıradakine geçer."""
    for saglayici in (_groq, _gemini, _openrouter):
        (senaryo, terimler), etiket = saglayici(konu)
        if senaryo and len(senaryo) >= 400:
            print(f"Senaryo hazır ({etiket}, {len(senaryo)} karakter)")
            return senaryo, terimler
    raise SystemExit("Senaryo üretilemedi: tüm LLM sağlayıcıları başarısız.")


def mpt_config_yaz() -> Path:
    """config.example.toml -> config.toml, anahtarlar env'den doldurulur."""
    ornek = MPT_DIR / "config.example.toml"
    hedef = MPT_DIR / "config.toml"
    if not ornek.exists():
        raise SystemExit(f"MPT kurulu değil: {ornek} yok.")
    metin = ornek.read_text(encoding="utf-8")

    def ayarla(anahtar: str, deger: str) -> None:
        nonlocal metin
        desen = re.compile(rf'^{re.escape(anahtar)}\s*=\s*.*$', re.M)
        yeni = f'{anahtar} = "{deger}"'
        metin = desen.sub(yeni, metin, count=1) if desen.search(metin) else metin

    model = os.getenv("MPT_LLM_MODEL", "gemini-3.8-flash").strip()
    ayarla("llm_provider", "gemini")
    ayarla("gemini_api_key", _env("GEMINI_API_KEY"))
    ayarla("gemini_model_name", model)

    kaynak = video_kaynagi()
    if kaynak == "pixabay":
        anahtar = _env("PIXABAY_API_KEY").replace('"', "")
        metin = re.sub(r'^pixabay_api_keys\s*=\s*.*$',
                       f'pixabay_api_keys = ["{anahtar}"]', metin, count=1, flags=re.M)
    else:
        anahtar = _env("PEXELS_API_KEY").replace('"', "")
        metin = re.sub(r'^pexels_api_keys\s*=\s*.*$',
                       f'pexels_api_keys = ["{anahtar}"]', metin, count=1, flags=re.M)
    ayarla("video_source", kaynak)
    print(f"Görüntü kaynağı: {kaynak}")

    # ElevenLabs ses bölümü
    el = _env("ELEVENLABS_API_KEY")
    metin = re.sub(r'^\[elevenlabs\]\n(?:.*\n)*?api_key\s*=\s*.*$',
                   f'[elevenlabs]\napi_key = "{el}"', metin, count=1, flags=re.M)
    metin = re.sub(r'^model_id\s*=\s*"eleven_multilingual_v2"',
                   'model_id = "' + os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2").strip() + '"',
                   metin, count=1, flags=re.M)

    hedef.write_text(metin, encoding="utf-8")
    print(f"config.toml yazıldı -> {hedef}")
    return hedef


def mpt_calistir(konu: str, ses_edge: bool = False, senaryo: str = "", terimler: str = "") -> Path:
    """cli.py'yi çağırır, üretilen mp4 yolunu döndürür."""
    if ses_edge:
        # SADECE TEST: yayına gitmeyen kuru çalışmalarda hattı doğrulamak için.
        # Kanonik ses kuralı gereği gerçek üretimde kullanılmaz.
        print("DİKKAT: Edge ses (test) kullanılıyor — bu çıktı yayına alınmaz.")
        ses_adi = "tr-TR-EmelNeural"
    else:
        voice_id = _env("ELEVENLABS_VOICE_ID")
        voice_ad = os.getenv("ELEVENLABS_VOICE_NAME", "bilgi-dozu").strip()
        ses_adi = f"elevenlabs:{voice_id}:{voice_ad}"
    argv = [
        sys.executable, "cli.py",
        "--video-subject", konu,
        "--video-language", "tr",
    ]
    if senaryo:
        argv += ["--video-script", senaryo]
    else:
        argv += ["--video-script-prompt", SENARYO_YONERGESI, "--paragraph-number", "1"]
    if terimler:
        argv += ["--video-terms", terimler]
    argv += [
        "--video-aspect", "9:16",
        "--video-source", video_kaynagi(),
        "--video-clip-duration", "4",
        "--video-count", "1",
        "--voice-name", ses_adi,
        "--voice-volume", "1.0",
    ]
    print("MPT çağrısı:", " ".join(argv[:6]), "…")
    sonuc = subprocess.run(argv, cwd=str(MPT_DIR), text=True)
    if sonuc.returncode != 0:
        raise SystemExit(f"MPT üretimi başarısız (çıkış kodu {sonuc.returncode})")

    adaylar = sorted(
        MPT_DIR.glob("storage/tasks/*/final*.mp4"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not adaylar:
        raise SystemExit("MPT çıktısı bulunamadı (storage/tasks/*/final*.mp4).")
    print(f"Üretilen video: {adaylar[0]}")
    return adaylar[0]


def sure_sn(yol: Path):
    try:
        import imageio_ffmpeg
        return float(imageio_ffmpeg.count_frames_and_secs(str(yol))[1])
    except Exception as hata:  # noqa: BLE001
        print(f"Süre ölçülemedi ({type(hata).__name__})")
        return None


def sure_kontrol(yol: Path):
    """Kural: uyarı üretir, üretimi engellemez."""
    s = sure_sn(yol)
    if s is None:
        return None, "bilinmiyor"
    durum = "ok"
    if s > SINIR_SN[1]:
        durum = "uzun"
    elif s < SINIR_SN[0]:
        durum = "kisa"
    if durum != "ok":
        print(f"UYARI: {s:.1f} sn (ideal {HEDEF_SN[0]}-{HEDEF_SN[1]}, sınır {SINIR_SN[0]}-{SINIR_SN[1]})")
    else:
        print(f"Süre uygun: {s:.1f} sn")
    return round(s, 1), durum


# ------------------------------------------------------------ Drive / tablo
def drive_istemci():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token = KOK / "token.json"
    if not token.exists():
        raise SystemExit("token.json yok (Google yetkilendirmesi eksik).")
    creds = Credentials.from_authorized_user_file(str(token))
    if not creds.valid:
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=creds)


def sonraki_numara(drive) -> int:
    from sheets_metadata import SHORTS_VIDEO_FOLDER_ID, extract_video_number, list_drive_videos

    numaralar = []
    for oge in list_drive_videos(drive, SHORTS_VIDEO_FOLDER_ID):
        try:
            numaralar.append(extract_video_number(oge["name"]))
        except Exception:  # noqa: BLE001
            continue
    return (max(numaralar) + 1) if numaralar else 1


def drive_yukle(drive, yol: Path, hedef_ad: str) -> str:
    from googleapiclient.http import MediaFileUpload
    from sheets_metadata import SHORTS_VIDEO_FOLDER_ID

    medya = MediaFileUpload(str(yol), mimetype="video/mp4", resumable=True)
    istek = drive.files().create(
        body={"name": hedef_ad, "parents": [SHORTS_VIDEO_FOLDER_ID]},
        media_body=medya, fields="id, name, webViewLink",
    )
    yanit = istek.execute()
    print(f"Drive'a yüklendi: {yanit['name']} ({yanit['id']})")
    return yanit["id"]


def tablo_satir_ekle(drive, dosya, baslik, aciklama, hashtag, etiketler, sabit_yorum, kategori, kaynak) -> bool:
    from sheets_metadata import CEO_FOLDER_ID, _drive_table_write, _find_primary_table

    tablo_id = _find_primary_table(drive, CEO_FOLDER_ID)
    if not tablo_id:
        print("UYARI: tablo bulunamadı, satır eklenmedi.")
        return False

    def yazici(wb):
        ws = next((s for s in wb.worksheets if s.title.strip().casefold() == "drive"), wb.active)
        r = ws.max_row + 1
        for i, deger in enumerate(
            ["BEKLEMEDE", dosya, baslik, aciklama, hashtag, etiketler, sabit_yorum, kategori, kaynak],
            start=1,
        ):
            ws.cell(r, i).value = deger

    ok = _drive_table_write(drive, tablo_id, yazici)
    print("Tablo satırı eklendi." if ok else "UYARI: tablo satırı yazılamadı.")
    return ok


def metinler(konu: str, video: Path):
    """Başlık/açıklama/yorum: MPT'nin ürettiği metin varsa ondan, yoksa konudan."""
    gorev = video.parent
    metin = ""
    for ad in ("script.txt", "script.md", "text.txt"):
        aday = gorev / ad
        if aday.exists():
            metin = aday.read_text(encoding="utf-8").strip()
            break
    ozet = metin or konu
    baslik = konu if konu.endswith(("?", "!")) else f"{konu}?"
    baslik = f"{baslik[:92].strip()} #bilgidozu #shorts"
    aciklama = f"{ozet}\n\n🖼️ Görseller temsili (stok görüntü).\n\nDaha fazla bilgi dozu için takip et! 🔔"
    sabit_yorum = "Sen bunu biliyor muydun? Cevabını yorumlara yaz 👇"
    return baslik, aciklama, "#bilgidozu #shorts", "bilgidozu, shorts, bilgi dozu", sabit_yorum


def main() -> int:
    ap = argparse.ArgumentParser(description="MPT yedek üretim hattı")
    ap.add_argument("--konu", required=True, help="video konusu (tek cümle)")
    ap.add_argument("--kategori", default="Bilim", help="tablodaki kategori sütunu")
    ap.add_argument("--kuru", action="store_true", help="sadece üret, Drive'a yükleme")
    ap.add_argument("--ses-edge", action="store_true",
                    help="TEST: Edge ses kullan (yalnız --kuru ile; yayına alınmaz)")
    args = ap.parse_args()

    if args.ses_edge and not args.kuru:
        raise SystemExit("--ses-edge yalnız --kuru ile kullanılabilir (kanonik ses kuralı).")

    mpt_config_yaz()
    senaryo, terimler = senaryo_uret(args.konu)
    video = mpt_calistir(args.konu, ses_edge=args.ses_edge, senaryo=senaryo, terimler=terimler)
    sure, durum = sure_kontrol(video)

    if args.kuru:
        print("KURU ÇALIŞMA: Drive'a yüklenmedi.")
        return 0

    drive = drive_istemci()
    numara = sonraki_numara(drive)
    dosya_adi = f"video_{numara}.mp4"
    baslik, aciklama, hashtag, etiketler, sabit_yorum = metinler(args.konu, video)

    drive_yukle(drive, video, dosya_adi)
    tablo_satir_ekle(drive, dosya_adi, baslik, aciklama, hashtag, etiketler,
                     sabit_yorum, args.kategori, "MoneyPrinterTurbo (yedek hat)")

    print(json.dumps({"dosya": dosya_adi, "sure_sn": sure, "sure_durum": durum,
                      "baslik": baslik}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
