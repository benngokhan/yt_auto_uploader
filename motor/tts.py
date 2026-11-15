#!/usr/bin/env python3
"""Ses üretimi — Speechify (birincil) / ElevenLabs (yedek, aynı ses kimliği şartıyla).

Speechify avantajı: yanıtında kelime zaman damgaları (`speech_marks`) geliyor,
bu yüzden karaoke için Whisper hizalamasına gerek kalmıyor.

Kural: ses kimliği sabittir. Sağlayıcı hata verirse başka sese GEÇİLMEZ,
üretim durur (ayarlar.json -> ses.saglayici).
"""
from __future__ import annotations

try:  # Gemini/Groq çağrılarını say (kota API'de yok)
    import kota_sayac  # noqa: F401
except Exception:
    pass

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import soundfile as sf

import metin_hazirla

SPEECHIFY_URL = "https://api.sws.speechify.com/v1/audio/speech"


class SesHatasi(RuntimeError):
    pass


def _sha256(yol: Path) -> str:
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1 << 20), b""):
            h.update(parca)
    return h.hexdigest()


def _speechify(metin: str, cikti: Path, ayar: dict) -> dict:
    anahtar = os.getenv("SPEECHIFY_API_KEY", "").strip()
    if not anahtar:
        raise SesHatasi("SPEECHIFY_API_KEY yok — üretim durduruldu (ses kuralı).")

    ses = ayar.get("ses", {})
    govde = {
        "input": metin,
        "voice_id": ses.get("voice_id", "ayse"),
        "model": ses.get("model", "simba-3.5"),
        "language": ses.get("dil", "tr"),
        "audio_format": "wav",
        "options": {"text_normalization": True},
    }
    istek = urllib.request.Request(
        SPEECHIFY_URL, data=json.dumps(govde).encode(), method="POST",
        headers={"Authorization": f"Bearer {anahtar}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(istek, timeout=180) as y:
            veri = json.loads(y.read().decode())
    except Exception as hata:  # noqa: BLE001
        raise SesHatasi(f"Speechify hatası: {str(hata)[:160]}") from hata

    cikti.write_bytes(base64.b64decode(veri["audio_data"]))
    _wav_basligini_duzelt(cikti)
    return _hizalama(metin, cikti, veri.get("speech_marks") or {})


def _wav_basligini_duzelt(yol: Path) -> None:
    """Speechify akış (streaming) WAV başlığı yazıyor: kare sayısı 0x7FFFFFFF.
    Dosyayı yeniden yazıp geçerli başlık üretiyoruz; aksi hâlde ses süresi
    on binlerce saniye görünüyor."""
    x, sr = sf.read(str(yol), dtype="float32", always_2d=True)
    sf.write(str(yol), x, sr, subtype="PCM_16")


def _hizalama(metin: str, yol: Path, marks: dict) -> dict:
    """Speechify kelime işaretlerini karaoke hizalamasına çevirir."""
    kelimeler = []

    def gez(d):
        if d.get("type") == "word":
            kelimeler.append({
                "word": str(d.get("value", "")).strip(),
                "start": round(float(d.get("start_time", 0)) / 1000.0, 4),
                "end": round(float(d.get("end_time", 0)) / 1000.0, 4),
                "probability": 1.0,
            })
        for c in d.get("chunks") or []:
            gez(c)

    for parca in marks.get("chunks") if isinstance(marks, dict) and marks.get("chunks") else [marks]:
        if parca:
            gez(parca)

    kelimeler = [k for k in kelimeler if k["word"]]
    if len(kelimeler) != len(metin.split()):
        raise SesHatasi(
            f"Kelime sayısı uyuşmuyor (ses {len(kelimeler)} / metin {len(metin.split())}) — "
            "sahte zaman üretilmedi, üretim durdu.")

    x, sr = sf.read(str(yol), dtype="float32", always_2d=True)
    sure = round(len(x) / sr, 4)
    return {
        "audio_sha256": _sha256(yol),
        "audio_duration_seconds": sure,
        "transcript": metin,
        "asr_transcript": metin,          # işaretler doğrudan metinden geliyor
        "asr_similarity": 1.0,
        "kaynak": "speechify_speech_marks",
        "words": kelimeler,
    }


def _elevenlabs(metin: str, cikti: Path, ayar: dict) -> None:
    ses = ayar.get("ses", {})
    anahtar = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not anahtar:
        raise SesHatasi("ELEVENLABS_API_KEY yok — üretim durduruldu (ses kuralı).")
    vid = ses.get("voice_id", "")
    if not vid or vid.upper().startswith("KUTUPHANE"):
        raise SesHatasi("Geçerli voice_id yok — üretim durduruldu.")
    govde = {
        "text": metin,
        "model_id": ses.get("model_id", "eleven_multilingual_v2"),
        "voice_settings": {
            "stability": ses.get("stability", 0.35),
            "similarity_boost": ses.get("similarity_boost", 0.75),
            "style": ses.get("style", 0.35),
            "speed": ses.get("speed", 1.0),
        },
    }
    istek = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
        data=json.dumps(govde).encode(), method="POST",
        headers={"xi-api-key": anahtar, "Content-Type": "application/json",
                 "Accept": "audio/wav"})
    try:
        with urllib.request.urlopen(istek, timeout=180) as y:
            cikti.write_bytes(y.read())
    except Exception as hata:  # noqa: BLE001
        raise SesHatasi(f"ElevenLabs hatası: {str(hata)[:160]}") from hata


def _xtts_referansini_hazirla(ses: dict) -> Path:
    """Onaylı 0,95 referansı Drive'dan indirir; referansın kendisini işlemez."""
    yol = Path(os.getenv("MOTOR_XTTS_REFERENCE", ses.get("referans_yolu", "ref_095.wav")))
    if yol.is_file() and yol.stat().st_size > 0:
        return yol
    token = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
    if token:
        Path("token.json").write_text(token, encoding="utf-8")
    if not Path("token.json").is_file():
        raise SesHatasi("XTTS referansı yok ve GOOGLE_TOKEN_JSON bulunamadı.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        kimlik = Credentials.from_authorized_user_file("token.json")
        if not kimlik.valid:
            kimlik.refresh(Request())
        drive = build("drive", "v3", credentials=kimlik, cache_discovery=False)
        yol.parent.mkdir(parents=True, exist_ok=True)
        with yol.open("wb") as dosya:
            indir = MediaIoBaseDownload(dosya, drive.files().get_media(
                fileId=ses.get("referans_drive_id", "1c1lstH03Kkf4pzvHVu5vavDJ_xDigxNQ")))
            tamam = False
            while not tamam:
                _, tamam = indir.next_chunk()
    except Exception as hata:  # noqa: BLE001
        yol.unlink(missing_ok=True)
        raise SesHatasi(f"XTTS referansı indirilemedi: {str(hata)[:160]}") from hata
    return yol


def _xtts(metin: str, cikti: Path, ayar: dict) -> None:
    """Onaylı referansla XTTS-v2 üretir; yeni çıktıya ses işlemini tam bir kez uygular."""
    ses = ayar.get("ses", {})
    referans = _xtts_referansini_hazirla(ses)
    with tempfile.TemporaryDirectory(prefix="xtts_") as gecici:
        ham = Path(gecici) / "ham.wav"
        komut = [
            "tts", "--text", metin,
            "--model_name", ses.get("model", "tts_models/multilingual/multi-dataset/xtts_v2"),
            "--speaker_wav", str(referans), "--language_idx", ses.get("dil", "tr"),
            "--out_path", str(ham),
        ]
        try:
            subprocess.run(komut, check=True, timeout=900)
            filtre = (
                "highpass=f=70,equalizer=f=250:t=q:width=1.1:g=-1.0,"
                "equalizer=f=3500:t=q:width=1.0:g=0.8,atempo=0.95,"
                "loudnorm=I=-18:TP=-1.5:LRA=11"
            )
            subprocess.run(["ffmpeg", "-y", "-i", str(ham), "-af", filtre,
                            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(cikti)],
                           check=True, timeout=180, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        except Exception as hata:  # noqa: BLE001
            cikti.unlink(missing_ok=True)
            raise SesHatasi(f"XTTS-v2 üretimi başarısız: {str(hata)[:160]}") from hata




def _ton_zinciri(ses: dict) -> list[str]:
    """Ton ayarı (uğultu kesme + 2 bant EQ): ayarlar.json -> ses.ton"""
    ton = ses.get("ton") or {}
    b1 = ton.get("bant1") or {}
    b2 = ton.get("bant2") or {}
    return [
        f"highpass=f={float(ton.get('alt_kesim_hz', 75)):g}",
        f"equalizer=f={float(b1.get('hz', 280)):g}:t=q:width={float(b1.get('genislik', 1.2)):g}:g={float(b1.get('kazanc_db', -1.2)):g}",
        f"equalizer=f={float(b2.get('hz', 3300)):g}:t=q:width={float(b2.get('genislik', 1.1)):g}:g={float(b2.get('kazanc_db', 1.8)):g}",
    ]


def _gemini_tts(metin: str, cikti: Path, ayar: dict) -> None:
    """Onaylı doğal Gemini erkek anlatıcı (Charon); tane tane belgesel diksiyonu + adaptif hız tavanı + netlik EQ."""
    import re, shutil, time, urllib.error, wave
    import numpy as np

    anahtar = os.getenv("GEMINI_API_KEY", "").strip()
    if not anahtar:
        raise SesHatasi("GEMINI_API_KEY yok — doğal ses üretimi durduruldu.")
    ses = ayar.get("ses", {})
    model_adi = ses.get("model", "gemini-2.5-flash-preview-tts")
    tarz = ses.get(
        "tarz",
        "Doğal, dengeli, akıcı ve çok net diksiyonlu bir erkek bilim anlatıcısı gibi konuş. "
        "Ne acele et ne de fazla ağırlaş; orta-canlı bir belgesel temposunda her kelimeyi, "
        "ekleri ve sessiz harfleri tane tane, pürüzsüz telaffuz et.",
    )
    # Tek satır sonu (\n) ile cümleleri ayır: doğal yarım saniye es verir, 2 saniyelik aşırı boşluk bırakmaz
    cumleler = [s.strip() for s in re.split(r"(?<=[.!?])\s+", metin.strip()) if s.strip()]
    cumle_blok = "\n".join(cumleler) if cumleler else metin.strip()
    prompt = f"Türkçe konuş. {tarz}\n\nMetin:\n{cumle_blok}"
    govde = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": ses.get("voice_id", "Charon")}}},
        },
    }
    veri_bytes = json.dumps(govde).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_adi}:generateContent?key={anahtar}"
    son_hata: Exception | None = None
    raw: bytes | None = None
    for deneme, bekle in enumerate((0, 12, 25, 45), start=1):
        if bekle:
            print(f"  Gemini TTS geçici yoğunluk, {bekle} sn beklenip tekrar deneniyor ({deneme}/4)...")
            time.sleep(bekle)
        istek = urllib.request.Request(url, data=veri_bytes, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(istek, timeout=180) as y:
                veri = json.loads(y.read().decode())
            raw = base64.b64decode(veri["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
            break
        except urllib.error.HTTPError as e:
            detay = ""
            try:
                detay = e.read().decode(errors="replace")[:220]
            except Exception:
                pass
            son_hata = RuntimeError(f"HTTP {e.code}: {detay or e.reason}")
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:
            son_hata = e

    if not raw:
        cikti.unlink(missing_ok=True)
        raise SesHatasi(f"Gemini doğal ses üretimi başarısız: {str(son_hata)[:180]}") from son_hata

    ham_yol = cikti.with_suffix(".ham24k.wav")
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0

    # Gemini cümle aralarında 0.55 sn'den uzun ölü sessizlik bıraktıysa konuşmaya dokunmadan 0.50 sn'ye daralt
    # Sessizlik kısaltma ayarları: ayarlar.json -> ses.sessizlik_kisaltma
    _sk = ses.get("sessizlik_kisaltma") or {}
    sk_esik_db = float(_sk.get("esik_db", -44.0))
    sk_cerceve_ms = float(_sk.get("cerceve_ms", 20))
    sk_en_uzun = int(_sk.get("en_uzun_sessizlik_cerceve", 26))
    sk_bas = int(_sk.get("korunan_bas_cerceve", 13))
    sk_son = int(_sk.get("korunan_son_cerceve", 13))
    f_len = int(round(24000 * sk_cerceve_ms / 1000.0))  # 20 ms @ 24 kHz = 480 örnek
    nf = len(pcm) // f_len
    if nf > 10:
        f_blok = pcm[: nf * f_len].reshape(nf, f_len)
        f_rms = np.sqrt(np.mean(f_blok * f_blok, axis=1) + 1e-12)
        sessiz_mi = f_rms < (10.0 ** (sk_esik_db / 20.0))
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
                if run_f > sk_en_uzun:  # > 0.52 sn saf sessizlik -> baştan 13 + sondan 13 çerçeve (0.52 sn) koru
                    parcalar.append(pcm[i_f * f_len : (i_f + sk_bas) * f_len])
                    parcalar.append(pcm[(j_f - sk_son) * f_len : j_f * f_len])
                else:
                    parcalar.append(pcm[i_f * f_len : j_f * f_len])
                i_f = j_f
        if nf * f_len < len(pcm):
            parcalar.append(pcm[nf * f_len :])
        pcm = np.concatenate(parcalar)

    pcm_i16 = np.clip(pcm * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(ham_yol), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm_i16.tobytes())

    # Aktif konuşma hızını ölç ve iki üretimin tam ortasına (~0.94x / ~15.5-15.8 krk/sn aktif) dengele
    ham_sure = len(pcm) / 24000.0
    pencere = 1200  # 50 ms @ 24 kHz
    n_pen = len(pcm) // pencere
    if n_pen > 4:
        blok = pcm[: n_pen * pencere].reshape(n_pen, pencere)
        rms = np.sqrt(np.mean(blok * blok, axis=1) + 1e-12)
        aktif_sn = max(1.0, float(np.sum(rms > (10.0 ** (-41.0 / 20.0)))) * 0.050)
    else:
        aktif_sn = max(1.0, ham_sure)

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

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        try:
            import imageio_ffmpeg
            ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg_bin = None

    if ffmpeg_bin:
        zincir = _ton_zinciri(ses)
        if atempo < 0.995:
            zincir.append(f"atempo={atempo:.3f}")
        try:
            subprocess.run(
                [
                    ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(ham_yol), "-af", ",".join(zincir),
                    "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(cikti),
                ],
                check=True,
                timeout=120,
            )
            ham_yol.unlink(missing_ok=True)
            yeni_x, yeni_sr = sf.read(str(cikti), dtype="float32")
            yeni_sure = len(yeni_x) / float(yeni_sr)
            print(
                f"  [Diksiyon] ham={ham_sure:.2f}s (aktif {aktif_sn:.2f}s, {aktif_hiz:.1f} krk/sn) "
                f"-> atempo={atempo:.3f}, yeni={yeni_sure:.2f}s"
            )
            return
        except Exception as e:
            print(f"  [Diksiyon] FFmpeg işleme atlandı ({e}); ham WAV korunuyor.")

    ham_yol.replace(cikti)

def _edge_tts(metin: str, cikti: Path, ayar: dict) -> None:
    """Ücretsiz Ahmet Neural; uzun nokta boşluklarını yaklaşık 0,40 sn ile sınırlar."""
    ses = ayar.get("ses", {})
    # voice_id Gemini/ElevenLabs adı olabilir (ör. "Charon"); edge-tts bunları tanımaz.
    # Yalnız tr-TR-* biçimindeki adlar kullanılır, aksi halde varsayılana düşülür.
    _v = str(ses.get("voice_id") or "").strip()
    voice = _v if _v.lower().startswith("tr-tr-") else "tr-TR-AhmetNeural"
    with tempfile.TemporaryDirectory(prefix="edge_tts_") as gecici:
        ham = Path(gecici) / "ham.mp3"
        try:
            subprocess.run(["edge-tts", "--voice", voice, "--rate=+2%", "--pitch=-5Hz",
                            "--text", metin, "--write-media", str(ham)],
                           check=True, timeout=240)
            filtre = (
                "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-38dB:"
                "start_silence=0.05:stop_periods=-1:stop_duration=0.35:"
                "stop_threshold=-38dB:stop_silence=0.05,"
                "highpass=f=70,loudnorm=I=-18:TP=-1.5:LRA=11"
            )
            subprocess.run(["ffmpeg", "-y", "-i", str(ham), "-af", filtre,
                            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(cikti)],
                           check=True, timeout=180, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        except Exception as hata:
            cikti.unlink(missing_ok=True)
            raise SesHatasi(f"Edge Ahmet Neural üretimi başarısız: {str(hata)[:160]}") from hata

def _ses_kontrol(ayar: dict) -> None:
    """Şablon/kural: ses Gemini + Charon olmalı. Değişirse üretim durur."""
    ses = ayar.get("ses", {})
    sag = str(ses.get("saglayici") or "").lower()
    vid = str(ses.get("voice_id") or "").strip()
    if sag not in {"gemini", "gemini_tts", "gemini_natural"}:
        raise SesHatasi(f"Ses sağlayıcısı Gemini olmalı, ayarda: {sag!r}")
    if vid and vid != "Charon":
        raise SesHatasi(f"Ses kimliği Charon olmalı, ayarda: {vid!r}")


def uret(metin: str, cikti: str | Path, ayar: dict) -> dict | None:
    """Sesi üretir. Hizalama hazırsa döndürür; yoksa None (çağıran Whisper'a düşer)."""
    cikti = Path(cikti)
    cikti.parent.mkdir(parents=True, exist_ok=True)
    saglayici = (ayar.get("ses", {}).get("saglayici") or "").lower()

    # Motordan bağımsız TEK metin hazırlığı: sayılar yazıya, kısaltmalar açık hâle.
    # Yalnız sese giden metin değişir; altyazı senaryodaki özgün yazımı kullanır.
    metin = metin_hazirla.hazirla(metin, ayar)

    if saglayici == "speechify":
        return _speechify(metin, cikti, ayar)
    if saglayici == "elevenlabs":
        _elevenlabs(metin, cikti, ayar)
        return None
    if saglayici in {"xtts", "xtts_v2", "coqui_xtts"}:
        _xtts(metin, cikti, ayar)
        return None
    if saglayici in {"edge", "edge_tts", "ahmet_neural"}:
        _edge_tts(metin, cikti, ayar)
        return None
    if saglayici in {"gemini", "gemini_tts", "gemini_natural"}:
        # KURAL (sahip): ses her zaman Gemini + Charon. Başka sese GEÇİLMEZ.
        # Gemini kotası dolarsa üretim DURUR; video yanlış sesle çıkmaz.
        _gemini_tts(metin, cikti, ayar)
        _ses_kontrol(ayar)
        return None
    raise SesHatasi(f"Desteklenmeyen ses sağlayıcısı: {saglayici!r}")
