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
    return _hizalama(metin, cikti, veri.get("speech_marks") or {})


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
    raise SesHatasi(f"Desteklenmeyen ses sağlayıcısı: {saglayici!r}")
