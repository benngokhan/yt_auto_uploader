#!/usr/bin/env python3
"""Ses üretimi — Speechify (birincil) / ElevenLabs (yedek, aynı ses kimliği şartıyla).

Speechify avantajı: yanıtında kelime zaman damgaları (`speech_marks`) geliyor,
bu yüzden karaoke için Whisper hizalamasına gerek kalmıyor.

Kural: ses kimliği sabittir. Sağlayıcı hata verirse başka sese GEÇİLMEZ,
üretim durur (ayarlar.json -> ses.saglayici).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import soundfile as sf

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




def _gemini_tts(metin: str, cikti: Path, ayar: dict) -> None:
    """Onaylı doğal Gemini erkek anlatıcı; pilotla aynı ham 24 kHz PCM çıkışı."""
    import wave
    anahtar = os.getenv("GEMINI_API_KEY", "").strip()
    if not anahtar:
        raise SesHatasi("GEMINI_API_KEY yok — doğal ses üretimi durduruldu.")
    ses = ayar.get("ses", {})
    tarz = ses.get("tarz", "Sıcak, merak uyandıran ve doğal bir erkek bilim anlatıcısı gibi anlat. Kağıttan okur gibi monoton olma. Soruda hafifçe yüksel; şaşırtıcı bilgileri doğal biçimde vurgula. Enerjik ol ama bağırma. Cümle aralarını kısa ve akıcı tut.")
    prompt = f"Türkçe konuş. {tarz} Metin: {metin}"
    govde = {"contents":[{"parts":[{"text":prompt}]}], "generationConfig":{"responseModalities":["AUDIO"], "speechConfig":{"voiceConfig":{"prebuiltVoiceConfig":{"voiceName":ses.get("voice_id", "Charon")}}}}}
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key=" + anahtar
    istek = urllib.request.Request(url, data=json.dumps(govde).encode(), method="POST", headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(istek, timeout=180) as y:
            veri = json.loads(y.read().decode())
        raw = base64.b64decode(veri["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
        with wave.open(str(cikti), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(raw)
    except Exception as hata:
        cikti.unlink(missing_ok=True)
        raise SesHatasi(f"Gemini doğal ses üretimi başarısız: {str(hata)[:160]}") from hata

def _edge_tts(metin: str, cikti: Path, ayar: dict) -> None:
    """Ücretsiz Ahmet Neural; uzun nokta boşluklarını yaklaşık 0,40 sn ile sınırlar."""
    ses = ayar.get("ses", {})
    voice = ses.get("voice_id", "tr-TR-AhmetNeural")
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

def uret(metin: str, cikti: str | Path, ayar: dict) -> dict | None:
    """Sesi üretir. Hizalama hazırsa döndürür; yoksa None (çağıran Whisper'a düşer)."""
    cikti = Path(cikti)
    cikti.parent.mkdir(parents=True, exist_ok=True)
    saglayici = (ayar.get("ses", {}).get("saglayici") or "").lower()

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
        _gemini_tts(metin, cikti, ayar)
        return None
    raise SesHatasi(f"Desteklenmeyen ses sağlayıcısı: {saglayici!r}")
