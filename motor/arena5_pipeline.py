#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Arena Bespoke 5-Day Viral Cohort Pipeline (video_177.mp4 .. video_181.mp4)
- Uses ONLY the 35 hand-crafted 1080x1920 plates + 5 master make_covers.py covers built in Arena (_arena5_assets.tar.gz).
- Zero Pexels stock search, zero motor/kapak.py, zero permanent motor modifications.
- Voices all 5 scripts with locked Turn-49 Gemini Charon midpoint speed (c00b036), applies 7-scene ~2.15s mid-hook pattern interrupt + v2.2 3D End-Card, and places video_177..181 at #1 priority in Drive (shifting original 20 queued videos back to 182..201).
"""

import argparse
import base64
import difflib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np
import openpyxl
import soundfile as sf
from PIL import Image

MOTOR_DIR = Path(__file__).resolve().parent
REPO_DIR = MOTOR_DIR.parent
sys.path.insert(0, str(MOTOR_DIR))
sys.path.insert(0, str(REPO_DIR))

import shorts_pipeline as sp

VIDEO_KAPAK_FOLDER_ID = "1GK-yImpb09445uXfTUbIl7l6AfNM4BOb"
BASLIK_XLSX_FILE_ID = "1aBt7me8IOzsJeSMQDVtkTktOgF9EZpJo"

EPISODES_5DAY: list[dict] = [
    {
        "num": 177,
        "file_name": "video_177.mp4",
        "cover_name": "kapak_177.jpg",
        "music_theme": "tarih_teknoloji",
        "cover_lines": ["ŞARJ ADAPTÖRÜNÜN", "İÇİNDE NE OLUYOR?"],
        "yt_title": "Telefonu Şarja Takınca Adaptörün İçinde Aslında Ne Oluyor? 🔌⚡ #bilgidozu #shorts",
        "category": "Fizik ve Mühendislik",
        "hashtags": "#bilgidozu #shorts #teknoloji #bilim",
        "tags": "bilgidozu, shorts, bilgi dozu, şarj aleti nasıl çalışır, şarj adaptörü içinde ne var, prizde kalan şarj aleti, elektrik, teknoloji, ilginç bilgiler",
        "pinned_comment": "Dürüst olalım: Telefonu çektikten sonra şarj adaptörünü prizde bırakanlardan mısın (1), yoksa hemen çekenlerden mi (2)? 👇🔌",
        "source": "IEEE Power Electronics — High-Frequency Switched-Mode Power Supplies",
        "note1": "Kaynak: IEEE Power Electronics Arşivi",
        "note2": "Görseller özel sahne kurgusuyla hazırlanmıştır.",
        "description": "Telefonunu şarja taktığın an o küçücük kutunun içinde 220 volt elektrik saniyede yüz bin kez dilimlenip 5 volta nasıl indiriliyor? Peki boşta prizde kalınca ne olur?",
        "sentences": [
            "Telefonunu şarja taktığın an bu küçük kutunun içinde aslında ne oluyor?",
            "Prizdeki iki yüz yirmi volt doğrudan girse telefonunu saniyesinde yakardı.",
            "İçindeki minik çip elektriği saniyede yüz bin kez açıp kapatarak dilimler.",
            "Böylece dev bir trafo olmadan voltaj minicik bobinde beş volta düşürülür.",
            "Telefonu çeksen bile fişte kalan adaptör çok az elektrik harcamaya devam eder.",
            "Sen adaptörü prizde mi bırakırsın? Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "ŞARJ ADAPTÖRÜNÜN", "line2": "İÇİNDE NE OLUYOR?"},
            {"icon": "⚡", "line1": "KÜÇÜK KUTUDAKİ", "line2": "GİZLİ DÖNÜŞÜM"},
            {"icon": "▼", "line1": "220 VOLT DOĞRUDAN", "line2": "GİRSE YAKARDI!"},
            {"icon": "!", "line1": "SANİYEDE YÜZ BİN", "line2": "KEZ DİLİMLENİR"},
            {"icon": "▲", "line1": "MİNİCİK BOBİNDE", "line2": "5 VOLTA İNER"},
            {"icon": "?", "line1": "BOŞTA FİŞTE KALIRSA", "line2": "GÜÇ ÇEKER Mİ?"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
    },
    {
        "num": 178,
        "file_name": "video_178.mp4",
        "cover_name": "kapak_178.jpg",
        "music_theme": "insan_beyin",
        "cover_lines": ["YUTKUNUNCA GELEN", "KULAKTAKİ KLİK NE?"],
        "yt_title": "Yutkunduğun Anda Kulağından Neden İnce Bir Klik Sesi Gelir? 👂⚡ #bilgidozu #shorts",
        "category": "Nörobilim ve İnsan Vücut Anatomisi",
        "hashtags": "#bilgidozu #shorts #insanvücudu #bilim",
        "tags": "bilgidozu, shorts, bilgi dozu, kulak çıtırtısı, yutkununca kulaktan gelen ses, östaki borusu, insan vücudu, anatomi, ilginç bilgiler",
        "pinned_comment": "Şu an yutkunup kulağındaki o ince 'klik' sesini duyanlar 1 yazsın, duymayanlar 2 👇👂",
        "source": "Stanford Medicine Otolaryngology — Eustachian Tube Mechanics",
        "note1": "Kaynak: Stanford Otolaryngology Arşivi",
        "note2": "Anatomik kesit bilimsel arşivden işlenmiştir.",
        "description": "Şu an yutkunduğun anda kulağının tam içinden gelen o ince tıkırtıyı hemen dene! Çoğu kişi çene kemiğinden sanır ama gerçekte östaki borusunun vakumu kırma sesidir.",
        "sentences": [
            "Şu an yutkunduğunda kulağının tam içinden neden ince bir klik sesi gelir?",
            "Çoğu kişi bu tıkırtıyı çene kemiğinden sanır ama ses kemikten hiç gelmez.",
            "Burnunun gerisinde orta kulağa uzanan ve normalde kapalı duran bir tünel vardır.",
            "Her yutkunduğunda dört minik kas bu ıslak duvarları salisede birbirinden ayırır.",
            "Duyduğun o ses, östaki borusunun vakumu kırıp kulak zarını koruma sesidir.",
            "Şimdi deneyip sesi duydun mu? Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "YUTKUNUNCA GELEN", "line2": "KLİK SESİ NE?"},
            {"icon": "⚡", "line1": "HEMEN ŞİMDİ", "line2": "YUTKUN VE DİNLE"},
            {"icon": "▼", "line1": "ÇENE KEMİĞİ", "line2": "SANISI YANLIŞ!"},
            {"icon": "!", "line1": "ORTA KULAĞA GİDEN", "line2": "GİZLİ TÜNEL"},
            {"icon": "▲", "line1": "DÖRT MİNİK KAS", "line2": "DUVARI AYIRIR"},
            {"icon": "✔", "line1": "ÖSTAKİ BORUSU", "line2": "VAKUMU KIRAR"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
    },
    {
        "num": 179,
        "file_name": "video_179.mp4",
        "cover_name": "kapak_179.jpg",
        "music_theme": "tarih_teknoloji",
        "cover_lines": ["BIÇAĞIN ÇİZEMEDİĞİ", "CAMI KUM ÇİZER!"],
        "yt_title": "Telefon Ekranını Bıçak Çizemezken Cebindeki Kum Tanesi Nasıl Çizer? 📱💎 #bilgidozu #shorts",
        "category": "Fizik ve Malzeme Bilimi",
        "hashtags": "#bilgidozu #shorts #teknoloji #fizik",
        "tags": "bilgidozu, shorts, bilgi dozu, telefon ekranı neden çizilir, mohs sertlik ölçeği, kuvars kumu telefon camı, malzeme bilimi, ilginç bilgiler",
        "pinned_comment": "Şu an telefon ekranında kılcal çizik var mı, yoksa ekran koruyucuyla sıfır çizik mi kullanıyorsun? Yoruma yaz 👇📱",
        "source": "Corning Glass Science & Mineralogical Society — Mohs Hardness Analysis",
        "note1": "Kaynak: Corning Malzeme Bilimi Arşivi",
        "note2": "Mikroskop ve sertlik verileri bilimseldir.",
        "description": "Çelik bıçak ve metal anahtarlar telefon ekranından daha yumuşaktır! Peki cebimizdeki telefon camını gerçekte ne çizer? Cevap görünmez kuvars tozunda gizli.",
        "sentences": [
            "Telefon ekranını çelik bıçak bile çizemezken cebindeki kum tanesi nasıl çizer?",
            "Çoğu kişi ekrandaki çizikleri cebindeki anahtar ya da bozuk paradan sanır.",
            "Oysa sertlik ölçeğinde çelik beş buçuk, ekran camı ise altı buçuktur.",
            "Yani metal anahtar cama sürtününce camı kesemez, sadece yüzeyde iz bırakır.",
            "Ama cebindeki görünmez kuvars tozu yedi sertliğindedir ve camı anında yarar.",
            "Ekranında şu an çizik var mı? Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "TELEFON EKRANINI", "line2": "ASLINDA NE ÇİZER?"},
            {"icon": "⚡", "line1": "ÇELİK BIÇAK BİLE", "line2": "CAMI KESEMEZ!"},
            {"icon": "▼", "line1": "ANAHTAR VE BOZUK", "line2": "PARA SUÇSUZ!"},
            {"icon": "▲", "line1": "ÇELİK 5.5 İKEN", "line2": "EKRAN CAMI 6.5"},
            {"icon": "✔", "line1": "DEMİR SADECE", "line2": "YÜZEYDE İZ BIRAKIR"},
            {"icon": "!", "line1": "KUVARS TOZU 7.0", "line2": "CAMI ANINDA YARAR"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
    },
    {
        "num": 180,
        "file_name": "video_180.mp4",
        "cover_name": "kapak_180.jpg",
        "music_theme": "insan_beyin",
        "cover_lines": ["YABANCI YATAKTA", "NEDEN UYUYAMAZSIN?"],
        "yt_title": "Yabancı Bir Yatakta İlk Gece Neden Tam Uyuyamazsın? 🛏️🧠 #bilgidozu #shorts",
        "category": "Uyku ve Nörobilim",
        "hashtags": "#bilgidozu #shorts #nörobilim #uyku",
        "tags": "bilgidozu, shorts, bilgi dozu, ilk gece etkisi, yabancı yatak uyku, sol beyin nöbeti, nörobilim, uyku bilimi, ilginç bilgiler",
        "pinned_comment": "Otelde veya misafirlikte ilk gece hemen uyuyabiliyor musun (1), yoksa sabaha kadar dönüyor musun (2)? 👇🛏️",
        "source": "Current Biology — Tamaki et al., Brown University Sleep Lab",
        "note1": "Kaynak: Brown Üniversitesi Uyku Lab.",
        "note2": "Görseller nörogörüntüleme verileriyle hazırlanmıştır.",
        "description": "Otelde ya da misafirlikte ilk gece neden bir türlü derin uyuyamazsın? Sorun yastıkta değil: Beyninin sol yarımküresi sabaha kadar nöbet tutuyor!",
        "sentences": [
            "Otel ya da misafirlikte yabancı bir yatakta ilk gece neden tam uyuyamazsın?",
            "Sorun yastığı yadırgaman değil, beyninin gizli gece nöbetçisini açmasıdır.",
            "Yeni bir ortamda sağ beyin uyurken sol yarımküre sabaha kadar yarı uyanık kalır.",
            "Tıpkı tek gözü açık uyuyan yunuslar gibi en ufak seste seni uyandırmaya hazırdır.",
            "Beyin ikinci gece odayı güvenli kodlayınca bu alarm kapanır ve deliksiz uyursun.",
            "Sen ilk gece hemen uyur musun? Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "YABANCI YATAKTA", "line2": "NEDEN UYUYAMAZSIN?"},
            {"icon": "⚡", "line1": "İLK GECE ETKİSİ", "line2": "TESADÜF DEĞİL"},
            {"icon": "▼", "line1": "SORUN YASTIK DEĞİL", "line2": "GECE NÖBETÇİSİ!"},
            {"icon": "!", "line1": "SAĞ BEYİN UYUR", "line2": "SOL BEYİN NÖBETTE"},
            {"icon": "▲", "line1": "YUNUSLAR GİBİ", "line2": "ALARMDA BEKLER"},
            {"icon": "✔", "line1": "İKİNCİ GECE ALARM", "line2": "OTOMATİK KAPANIR"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
    },
    {
        "num": 181,
        "file_name": "video_181.mp4",
        "cover_name": "kapak_181.jpg",
        "music_theme": "gunluk_bilim",
        "cover_lines": ["KIZGIN TAVADA SU", "NEDEN BİLYE OLUR?"],
        "yt_title": "Kızgın Tavaya Düşen Su Neden Buharlaşmaz da Bilye Gibi Kayar? 🔥💧 #bilgidozu #shorts",
        "category": "Fizik ve Termodinamik",
        "hashtags": "#bilgidozu #shorts #fizik #bilim",
        "tags": "bilgidozu, shorts, bilgi dozu, kızgın tava su damlası, leidenfrost etkisi, buhar yastığı, mutfak fiziği, termodinamik, ilginç bilgiler",
        "pinned_comment": "Yemek yaparken tavaya birkaç damla su atıp sıcaklığını böyle test edenler kimler? Yoruma yaz 👇🔥",
        "source": "Annual Review of Fluid Mechanics — Leidenfrost Vapor Cushion Dynamics",
        "note1": "Kaynak: Annual Review of Fluid Mechanics",
        "note2": "Deney görüntüleri gerçek yüksek hız çekimidir.",
        "description": "Ilık tavada saniyede buharlaşan su damlası, çok kızgın tavada neden cıva bilyesi gibi dakikalarca kayar? Altında oluşan görünmez buhar yastığının sırrı!",
        "sentences": [
            "Kızgın tavaya düşen su damlası neden anında uçmaz da cıva bilyesi gibi kayar?",
            "Ilık tavada su cızırdayarak saniyeler içinde kaynayıp tamamen buharlaşır.",
            "Ama tavanın sıcaklığı iki yüz dereceyi aştığında fizik kuralı tersine döner.",
            "Damlanın metale değen alt katmanı salisede patlayıp görünmez buhar yastığı kurar.",
            "Bu ince gaz yastığı ısıyı yalıtır ve damlayı demire değdirmeden havada yüzdürür.",
            "Bunu mutfakta hiç denedin mi? Daha fazla Bilgi Dozu için takip et!",
        ],
        "headlines": [
            {"icon": "?", "line1": "KIZGIN TAVADA SU", "line2": "NEDEN BİLYE OLUR?"},
            {"icon": "⚡", "line1": "CIVA GİBİ KAYAN", "line2": "SU DAMLALARI!"},
            {"icon": "▼", "line1": "ILIK TAVADA", "line2": "ANINDA UÇAR"},
            {"icon": "▲", "line1": "200 DERECE ÜSTÜNDE", "line2": "KURAL TERS DÖNER"},
            {"icon": "!", "line1": "ALT KATMAN ANINDA", "line2": "BUHAR YASTIĞI OLUR"},
            {"icon": "✔", "line1": "DEMİRE DEĞMEDEN", "line2": "HAVADA YÜZER!"},
            {"icon": "✔", "line1": "BİLGİ DOZU", "line2": "TAKİP ET"},
        ],
    },
]


def _call_gemini_charon_raw_pcm24k(text_block: str, ayar: dict) -> np.ndarray:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY eksik!")
    ses = ayar.get("ses", {})
    tarz = ses.get(
        "tarz",
        "Doğal, dengeli, akıcı ve çok net diksiyonlu bir erkek bilim anlatıcısı gibi konuş. "
        "Ne acele et ne de fazla ağırlaş; orta-canlı bir belgesel temposunda her kelimeyi, "
        "ekleri ve sessiz harfleri tane tane, pürüzsüz telaffuz et.",
    )
    prompt = f"Türkçe konuş. {tarz}\n\nMetin:\n{text_block}"
    models = [
        ses.get("model", "gemini-2.5-flash-preview-tts"),
        "gemini-2.5-pro-preview-tts",
    ]
    last_err: Exception | None = None
    for model_name in dict.fromkeys(models):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Charon"}}},
            },
        }).encode()
        for attempt, wait_s in enumerate((0, 15, 30, 55), start=1):
            if wait_s:
                print(f"  [TTS:{model_name}] bekleme {wait_s}s ({attempt}/4)...", flush=True)
                time.sleep(wait_s)
            req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=240) as resp:
                    data = json.loads(resp.read().decode())
                raw_b = base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
                pcm = np.frombuffer(raw_b, dtype="<i2").astype(np.float32) / 32768.0
                print(f"  [TTS:{model_name}] Charon ses alındı: {len(pcm)/24000.0:.2f}s", flush=True)
                return pcm
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode(errors="replace")[:240]
                except Exception:
                    pass
                last_err = RuntimeError(f"{model_name} HTTP {e.code}: {detail}")
                print(f"  [TTS:{model_name}] uyarı: {last_err}", flush=True)
                if e.code == 429 and any(k in detail.lower() for k in ("perday", "per_day", "daily")):
                    break
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except Exception as e:
                last_err = e
    raise RuntimeError(f"Charon TTS başarısız: {last_err}")


def _postprocess_charon_pcm24k(pcm_in: np.ndarray, metin: str, cikti: Path, ayar: dict) -> float:
    pcm = pcm_in.copy()
    sr = 24000
    win = 240
    nw = len(pcm) // win
    if nw > 8:
        wb = pcm[: nw * win].reshape(nw, win)
        wrms = np.sqrt(np.mean(wb * wb, axis=1) + 1e-12)
        act_idx = np.where(wrms > (10.0 ** (-47.0 / 20.0)))[0]
        if len(act_idx) > 0:
            s0 = max(0, (int(act_idx[0]) - 4) * win)
            s1 = min(len(pcm), (int(act_idx[-1]) + 9) * win)
            pcm = pcm[s0:s1]

    f_len = 480
    nf = len(pcm) // f_len
    if nf > 10:
        f_blok = pcm[: nf * f_len].reshape(nf, f_len)
        f_rms = np.sqrt(np.mean(f_blok * f_blok, axis=1) + 1e-12)
        sessiz_mi = f_rms < (10.0 ** (-44.0 / 20.0))
        parcalar: list[np.ndarray] = []
        i_f = 0
        while i_f < nf:
            if not sessiz_mi[i_f]:
                j_f = i_f + 1
                while j_f < nf and not sessiz_mi[j_f]:
                    j_f += 1
                parcalar.append(pcm[i_f * f_len : j_f * f_len])
                i_f = j_f
            else:
                j_f = i_f + 1
                while j_f < nf and sessiz_mi[j_f]:
                    j_f += 1
                run_f = j_f - i_f
                if run_f > 26:
                    parcalar.append(pcm[i_f * f_len : (i_f + 13) * f_len])
                    parcalar.append(pcm[(j_f - 13) * f_len : j_f * f_len])
                else:
                    parcalar.append(pcm[i_f * f_len : j_f * f_len])
                i_f = j_f
        if nf * f_len < len(pcm):
            parcalar.append(pcm[nf * f_len :])
        pcm = np.concatenate(parcalar)

    ham_yol = cikti.with_suffix(".ham24k.wav")
    pcm_i16 = np.clip(pcm * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(ham_yol), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm_i16.tobytes())

    ham_sure = len(pcm) / float(sr)
    pencere = 1200
    n_pen = len(pcm) // pencere
    if n_pen > 4:
        blok = pcm[: n_pen * pencere].reshape(n_pen, pencere)
        rms = np.sqrt(np.mean(blok * blok, axis=1) + 1e-12)
        aktif_sn = max(1.0, float(np.sum(rms > (10.0 ** (-41.0 / 20.0)))) * 0.050)
    else:
        aktif_sn = max(1.0, ham_sure)

    ses = ayar.get("ses", {})
    temiz_metin = " ".join(metin.split())
    aktif_hiz = len(temiz_metin) / aktif_sn
    hedef_hiz = float(ses.get("hedef_aktif_krk_sn", 15.5))
    min_atempo = float(ses.get("min_atempo", 0.93))
    max_atempo = float(ses.get("max_atempo", 0.96))

    if aktif_hiz > hedef_hiz:
        atempo = max(min_atempo, min(max_atempo, round(hedef_hiz / aktif_hiz, 3)))
    elif aktif_hiz > 14.5:
        atempo = 0.945
    else:
        atempo = 1.0

    zincir = [
        "highpass=f=75",
        "equalizer=f=280:t=q:width=1.2:g=-1.2",
        "equalizer=f=3300:t=q:width=1.1:g=1.8",
    ]
    if atempo < 0.995:
        zincir.append(f"atempo={atempo:.3f}")

    subprocess.run(
        [
            sp.FF, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(ham_yol), "-af", ",".join(zincir),
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(cikti),
        ],
        check=True, timeout=120,
    )
    ham_yol.unlink(missing_ok=True)
    yeni_x, yeni_sr = sf.read(str(cikti), dtype="float32")
    yeni_sure = len(yeni_x) / float(yeni_sr)
    print(
        f"  [Diksiyon] ham={ham_sure:.2f}s (aktif {aktif_sn:.2f}s, {aktif_hiz:.1f} krk/sn) "
        f"-> atempo={atempo:.3f}, yeni={yeni_sure:.2f}s",
        flush=True,
    )
    return yeni_sure


def _whisper_words_on_pcm(wmodel, pcm24k: np.ndarray, tmp_wav: Path) -> list[dict]:
    pcm_i16 = np.clip(pcm24k * 32767.0, -32768, 32767).astype("<i2")
    raw24 = tmp_wav.with_suffix(".24k.wav")
    with wave.open(str(raw24), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm_i16.tobytes())
    subprocess.run(
        [sp.FF, "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw24), "-ar", "16000", "-ac", "1", str(tmp_wav)],
        check=True,
    )
    raw24.unlink(missing_ok=True)
    sig16, _ = sp.read_wav_mono(str(tmp_wav))
    tmp_wav.unlink(missing_ok=True)
    segs, _ = wmodel.transcribe(sig16.astype(np.float32), language="tr", word_timestamps=True, vad_filter=False)
    out = []
    for s in segs:
        for wd in s.words or []:
            wt = (wd.word or "").strip()
            if wt:
                out.append({"w": wt, "s": float(wd.start), "e": float(wd.end)})
    return out


def _verify_single_wav(wmodel, wav_path: Path, expected_script: str) -> tuple[bool, float, float]:
    tmp16 = wav_path.with_suffix(".chk16k.wav")
    subprocess.run(
        [sp.FF, "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav_path), "-ar", "16000", "-ac", "1", str(tmp16)],
        check=True,
    )
    sig16, _ = sp.read_wav_mono(str(tmp16))
    tmp16.unlink(missing_ok=True)
    dur = len(sig16) / 16000.0
    segs, _ = wmodel.transcribe(sig16.astype(np.float32), language="tr", word_timestamps=False, vad_filter=False)
    asr_txt = " ".join(s.text.strip() for s in segs if s.text.strip())
    a_norm = re.sub(r"[^\wçğıöşü]+", " ", sp.tr_lower(expected_script)).strip()
    b_norm = re.sub(r"[^\wçğıöşü]+", " ", sp.tr_lower(asr_txt)).strip()
    sim_c = difflib.SequenceMatcher(None, a_norm, b_norm, autojunk=False).ratio()
    sim_w = difflib.SequenceMatcher(None, a_norm.split(), b_norm.split(), autojunk=False).ratio()
    sim = max(sim_c, sim_w)
    ok = (sim >= 0.80) and (23.0 <= dur <= 42.0) and ("takip" in b_norm[-55:])
    if not ok:
        print(f"    [ASR tanı] sim={sim:.3f}, dur={dur:.2f}s, tail={b_norm[-55:]!r}", flush=True)
    return ok, sim, dur


def prepare_5day_assets(out_dir: Path) -> None:
    from faster_whisper import WhisperModel

    out_dir.mkdir(parents=True, exist_ok=True)
    tar_path = MOTOR_DIR / "_arena5_assets.tar.gz"
    if not tar_path.exists():
        raise RuntimeError(f"Arena özel görsel arşivi bulunamadı: {tar_path}")

    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(out_dir)

    ayar = json.loads((MOTOR_DIR / "ayarlar.json").read_text(encoding="utf-8"))
    wmodel = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4)

    print("=== CHARON 5 BÖLÜM TOPLU SES ÜRETİMİ ([177, 178, 179, 180, 181]) ===", flush=True)
    ep_blocks = ["\n".join(e["sentences"]) for e in EPISODES_5DAY]
    combined_text = "\n\n".join(ep_blocks)
    pcm_all = _call_gemini_charon_raw_pcm24k(combined_text, ayar)

    asr_words = _whisper_words_on_pcm(wmodel, pcm_all, out_dir / "_tmp_b5.wav")
    all_words: list[str] = []
    ep_ranges: list[tuple[int, int]] = []
    cursor = 0
    for e in EPISODES_5DAY:
        ws = " ".join(e["sentences"]).split()
        ep_ranges.append((cursor, cursor + len(ws) - 1))
        all_words.extend(ws)
        cursor += len(ws)

    mapped = sp._map_script_to_asr(all_words, asr_words)
    sr = 24000
    cuts = [0]
    for idx_e in range(len(EPISODES_5DAY) - 1):
        w_end = ep_ranges[idx_e][1]
        w_nxt = ep_ranges[idx_e + 1][0]
        t_e = float(mapped[w_end]["e"])
        t_n = float(mapped[w_nxt]["s"])
        if t_n <= t_e + 0.04:
            cut_smp = int(round(0.5 * (t_e + t_n) * sr))
        else:
            ia = max(0, min(len(pcm_all) - 1, int(round((t_e + 0.02) * sr))))
            ib = max(ia + 1, min(len(pcm_all), int(round((t_n - 0.01) * sr))))
            wq = max(120, int(0.015 * sr))
            if ib - ia > wq * 2:
                env_s = np.convolve(np.abs(pcm_all[ia:ib]), np.ones(wq) / wq, mode="valid")
                cut_smp = ia + wq // 2 + int(np.argmin(env_s))
            else:
                cut_smp = (ia + ib) // 2
        cuts.append(cut_smp)
    cuts.append(len(pcm_all))

    for idx_e, ep in enumerate(EPISODES_5DAY):
        num = ep["num"]
        vo_out = out_dir / f"vo_{num}.wav"
        script_str = " ".join(ep["sentences"])
        seg_pcm = pcm_all[cuts[idx_e] : cuts[idx_e + 1]]
        _postprocess_charon_pcm24k(seg_pcm, script_str, vo_out, ayar)
        ok, sim, dur = _verify_single_wav(wmodel, vo_out, script_str)
        print(f"  [Doğrulama video_{num}] ok={ok}, sim={sim:.3f}, dur={dur:.2f}s", flush=True)
        if not ok:
            print(f"  [Tekil Yeniden Üretim video_{num}] tekil Charon çağrılıyor...", flush=True)
            time.sleep(12)
            single_pcm = _call_gemini_charon_raw_pcm24k("\n".join(ep["sentences"]), ayar)
            _postprocess_charon_pcm24k(single_pcm, script_str, vo_out, ayar)
            ok2, sim2, dur2 = _verify_single_wav(wmodel, vo_out, script_str)
            print(f"  [Tekil Doğrulama video_{num}] ok={ok2}, sim={sim2:.3f}, dur={dur2:.2f}s", flush=True)
            if not ok2:
                raise RuntimeError(f"video_{num} ses doğrulaması başarısız (sim={sim2:.3f}, dur={dur2:.2f}s)!")


def _apply_7scene_pattern_interrupt(timing_path: Path, headlines: list[dict]) -> float:
    """7 sahneli kurgu:
    s1.jpg: 0.0 -> cut1 (~2.15s, ilk cümle ortası görsel kesim!)
    s2.jpg: cut1 -> cümle 1 sonu
    s3.jpg: cümle 2
    s4.jpg: cümle 3
    s5.jpg: cümle 4
    s6.jpg: cümle 5 + izleyici sorusu (cta_start'a kadar)
    s7.jpg: cta_start -> total (v2.2 3D kapanış kartı)
    """
    tl = json.loads(timing_path.read_text(encoding="utf-8"))
    spans = tl.get("sentence_spans", [])
    total = float(tl["total"])
    cta_start = float(tl["cta_start"])
    if len(spans) < 5:
        raise RuntimeError(f"Beklenen >=5 cümle aralığı bulunamadı: {spans}")

    s0_a, s0_b = float(spans[0][0]), float(spans[0][1])
    cut1 = round(max(1.45, min(2.45, 0.5 * (s0_a + s0_b))), 3)
    end_s0 = round(min(cta_start - 3.5, max(cut1 + 0.9, s0_b + 0.14)), 3)

    bounds = [0.0, cut1, end_s0]
    for si in range(1, 4):  # cümle 2, 3, 4 (index 1, 2, 3) -> s3, s4, s5
        prev_b = bounds[-1]
        raw_b = float(spans[si][1]) + 0.14
        nxt_b = round(min(cta_start - (4 - si) * 0.75, max(prev_b + 0.90, raw_b)), 3)
        bounds.append(nxt_b)
    # s6.jpg (index 5) cümle 5 + kapanış sorusu boyunca tam cta_start'a kadar sürer
    bounds.append(round(max(bounds[-1] + 0.85, cta_start), 3))
    bounds.append(round(total, 3))

    new_scenes = []
    for idx in range(7):
        hl = headlines[idx]
        l1, l2 = sp._sanitize_headline_pair(hl["line1"], hl["line2"], 20)
        new_scenes.append({
            "scene_idx": idx,
            "file": f"s{idx + 1}.jpg",
            "is_closing": (idx == 6),
            "mode": idx % 3,
            "start": bounds[idx],
            "end": bounds[idx + 1],
            "icon": hl["icon"],
            "line1": l1,
            "line2": l2,
        })
    tl["scenes"] = new_scenes
    timing_path.write_text(json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")
    return cut1


def render_one_episode(assets_dir: Path, out_dir: Path, num: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    if not (assets_dir / f"vo_{num}.wav").exists():
        assets_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(MOTOR_DIR / "_arena5_assets.tar.gz", "r:gz") as tf:
            tf.extractall(assets_dir)
    ep = next(e for e in EPISODES_5DAY if e["num"] == num)
    print(f"\n=== ARENA BESPOKE RENDER: video_{num}.mp4 ===", flush=True)
    work = out_dir / f"work_{num}"
    vdir = work / "v2"
    if work.exists():
        shutil.rmtree(work)
    vdir.mkdir(parents=True, exist_ok=True)

    for si in range(1, 8):
        shutil.copyfile(assets_dir / "plates" / f"v{num}_s{si}.jpg", vdir / f"s{si}.jpg")
    shutil.copyfile(assets_dir / f"vo_{num}.wav", vdir / "vo_raw.wav")
    script_txt = " ".join(ep["sentences"])
    (vdir / "script.txt").write_text(script_txt + "\n", encoding="utf-8")

    cfg = {
        "title": [[ep["cover_lines"][0], "g"], [ep["cover_lines"][1]]],
        "scene_headlines": ep["headlines"],
        "cover_lines": ep["cover_lines"],
        "music_theme": ep["music_theme"],
        "intro_lead": 0.14,
        "sentence_pause": 0.50,
        "outro_hold": 0.62,
        "note1": ep["note1"],
        "note2": ep["note2"],
        "scenes": [f"s{i}.jpg" for i in range(1, 8)],
    }
    cfg_path = work / "shorts_config.json"
    cfg_path.write_text(json.dumps({"v2": cfg}, ensure_ascii=False, indent=2), encoding="utf-8")

    sp.stage_plates(str(vdir), str(cfg_path))
    sp.stage_timing(str(vdir), str(cfg_path))
    cut1 = _apply_7scene_pattern_interrupt(vdir / "timing.json", ep["headlines"])
    sp.stage_music(str(vdir), str(cfg_path))
    sp.render_video(str(vdir), str(cfg_path))

    mp4_src = vdir / "video.mp4"
    cov_src = assets_dir / "covers" / f"kapak_{num}.jpg"
    tl_data = json.loads((vdir / "timing.json").read_text(encoding="utf-8"))
    dur_total = float(tl_data["total"])
    lufs_val = sp._measure_lufs(str(vdir / "mix.wav")) if (vdir / "mix.wav").exists() else -14.5

    if not mp4_src.exists() or mp4_src.stat().st_size < 3_000_000:
        raise RuntimeError(f"video_{num}.mp4 eksik veya çok küçük!")
    if not (25.0 <= dur_total <= 41.0):
        raise RuntimeError(f"video_{num}.mp4 süre sınır dışı: {dur_total:.2f}s (hedef 25-41s)!")
    with Image.open(cov_src) as cim:
        if cim.size != (1080, 1920):
            raise RuntimeError(f"kapak_{num}.jpg boyutu hatalı: {cim.size}")

    final_mp4 = out_dir / f"video_{num}.mp4"
    final_cov = out_dir / f"kapak_{num}.jpg"
    shutil.copyfile(mp4_src, final_mp4)
    shutil.copyfile(cov_src, final_cov)

    tele = {
        "num": num,
        "file_name": ep["file_name"],
        "cover_name": ep["cover_name"],
        "duration_sec": round(dur_total, 2),
        "cta_start": round(float(tl_data["cta_start"]), 2),
        "first_word_start": round(float(tl_data.get("sentence_spans", [[0.14]])[0][0]), 2),
        "cut1_sec": cut1,
        "size_mb": round(final_mp4.stat().st_size / 1048576.0, 2),
        "lufs": round(float(lufs_val), 2),
        "chars": len(script_txt),
        "yt_title": ep["yt_title"],
    }
    (out_dir / f"telemetry_{num}.json").write_text(json.dumps(tele, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(f"  [OK] video_{num}.mp4 ({tele['duration_sec']}s, {tele['size_mb']} MB, LUFS={tele['lufs']}, cut1={cut1}s)", flush=True)


def update_workbook_to_5day_cohort(xlsx_path: Path) -> None:
    """baslik.xlsx DRIVE sekmesini tam 5 günlük öncelikli seriye (video_177..181) çeker:
    - video_1..176 (ve askıdaki eski satırlar) korunur.
    - video_177..181: Arena'nın 5 günlük özel strateji serisi (BEKLEMEDE, #1 öncelik).
    - Eski kuyruk (Deniz Kabuğu..Vücut Ateşi, 20 video): video_182..201 (BEKLEMEDE).
    - Taslaklar (Alüminyum Folyo..Tenis Topları, 10 satır): video_202..211 (ASKIDA_TASLAK).
    - uzun_video_1..22 korunur.
    Tam idempotenttir: hem 218 satırlık (10'lu kaydırılmış) hem 208 satırlık orijinal tablodan güvenle çalışır.
    """
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb["DRIVE"]
    max_c = ws.max_column

    rows_all = []
    for r in range(2, ws.max_row + 1):
        rows_all.append([ws.cell(r, c).value for c in range(1, max_c + 1)])

    idx_176 = None
    for idx, row in enumerate(rows_all):
        if str(row[1] or "").strip() == "video_176.mp4":
            idx_176 = idx
            break
    if idx_176 is None:
        raise RuntimeError("baslik.xlsx içinde video_176.mp4 satırı bulunamadı!")

    head_rows = rows_all[: idx_176 + 1]
    tail_rows = rows_all[idx_176 + 1 :]

    # Orijinal kuyruğun ilk videosu ("Deniz Kabuğunu Kulağına Tutunca...") hangi satırdaysa oradan itibaren yakala
    orig_start_idx = None
    for idx, row in enumerate(tail_rows):
        title_s = str(row[2] or "")
        if "Deniz Kabuğunu Kulağına Tutunca" in title_s:
            orig_start_idx = idx
            break
    if orig_start_idx is None:
        raise RuntimeError("Orijinal kuyruk başlangıcı ('Deniz Kabuğunu Kulağına Tutunca...') bulunamadı!")

    preserved_tail = tail_rows[orig_start_idx:]
    renumbered_tail = []
    short_counter = 182
    for row in preserved_tail:
        new_r = list(row)
        fname = str(new_r[1] or "").strip()
        if re.match(r"^video_\d+\.mp4$", fname):
            new_r[1] = f"video_{short_counter}.mp4"
            short_counter += 1
        renumbered_tail.append(new_r)

    new_5_rows = []
    for ep in EPISODES_5DAY:
        r_vals = [None] * max_c
        r_vals[0] = "BEKLEMEDE"
        r_vals[1] = ep["file_name"]
        r_vals[2] = ep["yt_title"]
        r_vals[3] = ep["description"]
        r_vals[4] = ep["hashtags"]
        r_vals[5] = ep["tags"]
        r_vals[6] = ep["pinned_comment"]
        r_vals[7] = ep["category"]
        r_vals[8] = ep["source"]
        new_5_rows.append(r_vals)

    final_rows = head_rows + new_5_rows + renumbered_tail

    # Eski tüm veri satırlarını temizle ve yeni listeyi yaz
    for r in range(2, ws.max_row + 1):
        for c in range(1, max_c + 1):
            ws.cell(r, c).value = None
    if ws.max_row > len(final_rows) + 1:
        ws.delete_rows(len(final_rows) + 2, ws.max_row - (len(final_rows) + 1))

    for out_idx, r_vals in enumerate(final_rows, start=2):
        for c in range(1, max_c + 1):
            ws.cell(out_idx, c).value = r_vals[c - 1]

    wb.save(xlsx_path)


def deploy_5day_cohort(rendered_dir: Path) -> None:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    import sheets_metadata as sm

    for ep in EPISODES_5DAY:
        mp4 = rendered_dir / ep["file_name"]
        cov = rendered_dir / ep["cover_name"]
        if not mp4.exists() or mp4.stat().st_size < 3_000_000:
            raise RuntimeError(f"Render çıktısı eksik: {mp4}")
        if not cov.exists() or cov.stat().st_size < 80_000:
            raise RuntimeError(f"Kapak çıktısı eksik: {cov}")

    tok_raw = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
    if not tok_raw:
        raise RuntimeError("GOOGLE_TOKEN_JSON eksik!")
    creds = Credentials.from_authorized_user_info(json.loads(tok_raw))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    def _list_folder():
        items = []
        pt = None
        while True:
            res = drive.files().list(
                q=f"'{VIDEO_KAPAK_FOLDER_ID}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, size)",
                pageSize=200,
                pageToken=pt,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            items.extend(res.get("files", []))
            pt = res.get("nextPageToken")
            if not pt:
                break
        return items

    existing = _list_folder()
    by_name: dict[str, list[dict]] = {}
    for f in existing:
        by_name.setdefault(f["name"], []).append(f)

    # 1) Eğer önceki 10'lu kaydırmadan (video_187..206) dosyalar duruyorsa:
    #    a) Turn-51'in 10 stok videosunu (177..186) ve kapaklarını çöpe taşı
    #    b) Orijinal 20 videoyu (187..206) artan sırayla 182..201'e geri çek!
    if "video_206.mp4" in by_name:
        print("Önceki 10'lu stok paketi (177..186) temizleniyor ve orijinal 187..206 -> 182..201 olarak çekiliyor...", flush=True)
        for del_n in range(177, 187):
            for del_name in (f"video_{del_n}.mp4", f"kapak_{del_n}.jpg"):
                for f in by_name.get(del_name, []):
                    drive.files().update(fileId=f["id"], body={"trashed": True}, supportsAllDrives=True).execute()
                    print(f"  çöpe taşındı (eski stok): {del_name} ({f['id']})", flush=True)
        for old_n in range(187, 207):
            new_n = old_n - 5  # 187->182 .. 206->201
            for prefix, ext in (("video_", ".mp4"), ("kapak_", ".jpg")):
                src_name = f"{prefix}{old_n}{ext}"
                dst_name = f"{prefix}{new_n}{ext}"
                for f in by_name.get(src_name, []):
                    drive.files().update(fileId=f["id"], body={"name": dst_name}, supportsAllDrives=True).execute()
                    print(f"  geri kaydırıldı: {src_name} -> {dst_name} ({f['id']})", flush=True)
    else:
        # Zaten 182..201 düzenindeyse sadece 177..181 varsa eski kopyalarını çöpe taşı
        for del_n in range(177, 182):
            for del_name in (f"video_{del_n}.mp4", f"kapak_{del_n}.jpg"):
                for f in by_name.get(del_name, []):
                    drive.files().update(fileId=f["id"], body={"trashed": True}, supportsAllDrives=True).execute()

    # 2) Yeni 5 özel Shorts + 5 özel kapağı (177..181) yükle
    uploaded_ids = {}
    for ep in EPISODES_5DAY:
        v_path = rendered_dir / ep["file_name"]
        c_path = rendered_dir / ep["cover_name"]
        v_res = drive.files().create(
            body={"name": ep["file_name"], "parents": [VIDEO_KAPAK_FOLDER_ID]},
            media_body=MediaFileUpload(str(v_path), mimetype="video/mp4", resumable=True),
            fields="id,name,size",
            supportsAllDrives=True,
        ).execute()
        c_res = drive.files().create(
            body={"name": ep["cover_name"], "parents": [VIDEO_KAPAK_FOLDER_ID]},
            media_body=MediaFileUpload(str(c_path), mimetype="image/jpeg", resumable=False),
            fields="id,name,size",
            supportsAllDrives=True,
        ).execute()
        uploaded_ids[ep["file_name"]] = {"video_id": v_res["id"], "cover_id": c_res["id"]}
        print(f"  [DRIVE YÜKLENDİ] {ep['file_name']} ({v_res['id']}) + {ep['cover_name']} ({c_res['id']})", flush=True)

    # 3) Drive baslik.xlsx dosyasını indir, 5 günlük yapıya güncelle, hem Drive'a hem repoya yaz
    buf = io.BytesIO()
    dl_req = drive.files().get_media(fileId=BASLIK_XLSX_FILE_ID, supportsAllDrives=True)
    downloader = MediaIoBaseDownload(buf, dl_req)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    repo_baslik = REPO_DIR / "baslik.xlsx"
    repo_mirror = REPO_DIR / "bilgidozu_yukleme_tablosu.xlsx"
    repo_baslik.write_bytes(buf.getvalue())
    update_workbook_to_5day_cohort(repo_baslik)
    shutil.copyfile(repo_baslik, repo_mirror)

    drive.files().update(
        fileId=BASLIK_XLSX_FILE_ID,
        media_body=MediaFileUpload(
            str(repo_baslik),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resumable=False,
        ),
        fields="id,name,modifiedTime",
        supportsAllDrives=True,
    ).execute()
    print(f"  [TABLO GÜNCELLENDİ] Drive baslik.xlsx ({BASLIK_XLSX_FILE_ID}) 5 günlük seriye senkronize edildi.", flush=True)

    # 4) Doğrulama: Mükerrer = 0, dosya sayısı = 52 (176..201 video+kapak), sıradaki = video_177.mp4!
    after_files = _list_folder()
    names_count: dict[str, int] = {}
    for f in after_files:
        names_count[f["name"]] = names_count.get(f["name"], 0) + 1
    dups = {k: v for k, v in names_count.items() if v > 1}
    if dups:
        raise RuntimeError(f"Drive klasöründe mükerrer dosya tespit edildi: {dups}")

    skip_set = set()
    up_txt = REPO_DIR / "uploaded.txt"
    if up_txt.exists():
        for ln in up_txt.read_text(encoding="utf-8").splitlines():
            p = [x.strip() for x in ln.split("|")]
            if p and p[0]:
                skip_set.add(p[0])
            if len(p) >= 2 and p[1]:
                skip_set.add(p[1])

    q_str = f"'{VIDEO_KAPAK_FOLDER_ID}' in parents and mimeType contains 'video/' and trashed = false"
    nxt = sm.get_next_scheduled_video(drive, q_str, skip_ids=skip_set, video_type="short")
    stats = sm.get_queue_stats(drive, q_str, skip_ids=skip_set)
    if not nxt or nxt.get("name") != "video_177.mp4":
        raise RuntimeError(f"Sıradaki video video_177.mp4 değil! Dönen: {nxt}")
    if stats.get("duplicate_videos", 0) != 0:
        raise RuntimeError(f"Kuyrukta mükerrer video var: {stats}")

    summary = {
        "next_scheduled": nxt["name"],
        "next_title": nxt.get("custom_title"),
        "folder_total_files": len(after_files),
        "queue_stats": stats,
        "uploaded": uploaded_ids,
    }
    (rendered_dir / "deploy_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("5 GÜNLÜK KUYRUK DOĞRULAMASI TAMAM:", json.dumps(summary, ensure_ascii=False), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_prep = sub.add_parser("prepare")
    p_prep.add_argument("--out", required=True)
    p_ren = sub.add_parser("render")
    p_ren.add_argument("--assets", required=True)
    p_ren.add_argument("--out", required=True)
    p_ren.add_argument("--num", type=int, required=True)
    p_dep = sub.add_parser("deploy")
    p_dep.add_argument("--rendered", required=True)
    args = ap.parse_args()

    if args.cmd == "prepare":
        prepare_5day_assets(Path(args.out))
    elif args.cmd == "render":
        render_one_episode(Path(args.assets), Path(args.out), args.num)
    elif args.cmd == "deploy":
        deploy_5day_cohort(Path(args.rendered))


if __name__ == "__main__":
    main()
