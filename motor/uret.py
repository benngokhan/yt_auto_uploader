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
        "- ses: o sahnede söylenecek 1-2 cümle (toplam ~110 karakter/sahne)\n"
        "- baslik1: BÜYÜK HARF, beyaz satır (en fazla 22 karakter)\n"
        "- baslik2: BÜYÜK HARF, sarı satır (en fazla 22 karakter)\n"
        "- emoji: konuya uygun tek emoji\n"
        "- gorsel: o sahnede FİZİKSEL OLARAK GÖRÜNECEK somut nesneyi/durumu anlatan 2-3 kelimelik "
        "İNGİLİZCE stok fotoğraf araması. Mecaz yasak: \"beyin kontrolü\" yerine \"human brain scan\", "
        "\"ıslak tutuş\" yerine \"wet wrinkled fingertips\" gibi. Fotoğraflanabilir bir şey yaz; "
        "yazı/logo/tabela içeren sahne istemeyin.\n"
        "- vurgular: o sahnenin altyazısında sarı boyanacak 1-3 kelime\n"
        "Selamlama ve 'abone olun' YASAK. İlk sahnenin sesi tek soru ve ≤6 kelime olsun. "
        "Son sahne 'Sıradaki videoda ... bakacağız.' kalıbıyla bitsin."
    )

    def _cagir(url, govde, basliklar):
        veri = json.dumps(govde).encode()
        istek = urllib.request.Request(url, data=veri, method="POST",
                                       headers={"Content-Type": "application/json", **basliklar})
        with urllib.request.urlopen(istek, timeout=120) as y:
            return json.loads(y.read().decode())

    def _ayikla(metin):
        import re
        m = re.search(r"\{.*\}", metin, re.S)
        return json.loads(m.group(0)) if m else {}

    # sağlayıcı zinciri: groq -> gemini -> openrouter (mpt_uret ile aynı mantık)
    denemeler = []
    if os.getenv("GROQ_API_KEY"):
        denemeler.append(lambda: _ayikla(_cagir(
            "https://api.groq.com/openai/v1/chat/completions",
            {"model": os.getenv("MOTOR_LLM_MODEL", "llama-3.3-70b-versatile"),
             "temperature": 0.7,
             "messages": [{"role": "system", "content": SAHNE_SISTEM},
                          {"role": "user", "content": istem}]},
            {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        )["choices"][0]["message"]["content"]))
    if os.getenv("GEMINI_API_KEY"):
        model = os.getenv("MOTOR_LLM_MODEL", "gemini-3.6-flash")
        denemeler.append(lambda: _ayikla(_cagir(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={os.environ['GEMINI_API_KEY']}",
            {"systemInstruction": {"parts": [{"text": SAHNE_SISTEM}]},
             "contents": [{"role": "user", "parts": [{"text": istem}]}]},
            {},
        )["candidates"][0]["content"]["parts"][0]["text"]))

    for dene in denemeler:
        try:
            veri = dene()
            sahneler = veri.get("sahneler") or []
            if len(sahneler) >= 3:
                print(f"Sahne planı hazır ({len(sahneler)} sahne)")
                return sahneler
        except Exception as hata:  # noqa: BLE001
            print(f"LLM denemesi başarısız: {type(hata).__name__}: {str(hata)[:120]}")
    raise SystemExit("Sahne planı üretilemedi: tüm LLM sağlayıcıları başarısız.")


# ------------------------------------------------------------------- 2) TTS
# ------------------------------------------------------- 3) hizalama (karaoke)
def hizala(ses_yolu: Path, metin: str, ayar: dict) -> dict:
    sys.path.insert(0, str(MOTOR))
    import karaoke_timing as kt

    model_boyut = ayar.get("teknik", {}).get("whisper_model", "small")
    aligner = kt.KaraokeAligner(model_size=model_boyut)
    return aligner.align(ses_yolu, metin)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--konu", required=True)
    ap.add_argument("--sahne", type=int, default=0, help="0 = ayardan oku")
    ap.add_argument("--sure-min", type=float, default=0, help="0 = ayardan oku")
    ap.add_argument("--sure-max", type=float, default=0, help="0 = ayardan oku")
    ap.add_argument("--kuru", action="store_true", help="Sadece üret, hiçbir yere yükleme")
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
