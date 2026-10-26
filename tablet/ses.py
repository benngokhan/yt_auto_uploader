#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kartal AI · Sesli asistan katmanı
=================================
Tablet konuşur (TTS) + seni dinler (STT). Telegram'dan tek komutla test edilir.

Kurulum (Termux):
    pkg install -y termux-api ffmpeg
    pip install gtts            # opsiyonel: internetsiz TTS için termux-tts-speak yeterli

Komutlar:
    /konus metin          -> tableti konuşturur (termux-tts-speak)
    /dinle                -> 6 sn kayıt alır, yazıya çevirir (Gemini anahtarı varsa)
    /sohbet               -> dinle -> yanıtla -> konuş (tek tur)

Tasarım:
  TTS: termux-tts-speak (Android motoru, Türkçe ses varsa onu kullanır)
  STT: termux-microphone-record ile kayıt -> Gemini'ye ses dosyası gönder -> metin
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

REC_DIR = Path.home() / "kartal_tablet" / "kayitlar"
REC_DIR.mkdir(parents=True, exist_ok=True)


def _run(cmd: list[str], timeout: int = 90) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return f"(yok: {cmd[0]} — pkg install termux-api)"
    except subprocess.TimeoutExpired:
        return "(zaman aşımı)"


def tts_available() -> bool:
    return shutil.which("termux-tts-speak") is not None


def speak(text: str) -> str:
    """Tableti konuşturur."""
    text = (text or "").strip()
    if not text:
        return "❌ Söylenecek metin yok."
    if not tts_available():
        return "❌ termux-tts-speak yok → pkg install termux-api (Termux:API uygulaması da gerekli)"
    # Türkçe ses varsa kullan; yoksa cihaz varsayılanı
    out = _run([
        "termux-tts-speak",
        "-l", os.getenv("TTS_LANG", "tr-TR"),
        "-r", os.getenv("TTS_RATE", "1.0"),
        "-p", os.getenv("TTS_PITCH", "1.0"),
        text[:3000],
    ])
    return f"🔊 Konuşuyor: {text[:120]}{'…' if len(text) > 120 else ''}" if "yok" not in out else f"❌ {out}"


def record(seconds: int = 6) -> Path | None:
    """Mikrofonu kaydeder (m4a)."""
    if shutil.which("termux-microphone-record") is None:
        return None
    path = REC_DIR / f"kayit_{int(time.time())}.m4a"
    _run(["termux-microphone-record", "-f", str(path), "-e", "aac", "-b", "64000"], timeout=10)
    time.sleep(max(1, seconds))
    _run(["termux-microphone-record", "-q"], timeout=10)
    time.sleep(0.8)
    return path if path.exists() and path.stat().st_size > 2000 else None


def transcribe(path: Path) -> str:
    """Gemini ile sesi yazıya çevirir."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return "(Gemini anahtarı yok → ses yazıya çevrilemiyor)"
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={urllib.parse.quote(key)}"
    )
    mime = "audio/mp4"
    body = {
        "contents": [{
            "parts": [
                {"text": "Bu ses kaydını Türkçe olarak yazıya çevir. Sadece duyduğun metni yaz, açıklama ekleme."},
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(path.read_bytes()).decode()}},
            ]
        }],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 512},
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip() \
            or "(anlaşılamadı)"
    except Exception as e:
        return f"(çeviri hatası: {e})"


def reply_brain(user_text: str) -> str:
    """Kısa, doğal bir yanıt üretir (Gemini yoksa basit kalıp)."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return f"Duydum: {user_text}"
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={urllib.parse.quote(key)}"
    )
    body = {
        "contents": [{
            "parts": [{
                "text": (
                    "Sen Kartal'sın: Bilgi Dozu YouTube kanalının tablet asistanı. "
                    "Türkçe, samimi, kısa (en fazla 2 cümle) cevap ver. "
                    f"Kullanıcı şöyle dedi: {user_text}"
                )
            }]
        }],
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": 300},
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
    except Exception:
        return f"Duydum: {user_text}"


def listen_once(seconds: int = 6) -> tuple[str, str]:
    """(duyulan metin, durum mesajı) döner."""
    path = record(seconds)
    if not path:
        return "", (
            "❌ Kayıt alınamadı.\n"
            "  • Termux:API uygulaması kurulu mu?\n"
            "  • pkg install termux-api çalıştırıldı mı?\n"
            "  • Mikrofon izni verildi mi?"
        )
    text = transcribe(path)
    return text, f"🎧 Duyduğum: <b>{text}</b>"


def chat_turn(seconds: int = 6) -> list[str]:
    """Tek tur: dinle → cevapla → konuş."""
    msgs = ["🎧 Dinliyorum… (6 sn)"]
    text, status = listen_once(seconds)
    msgs.append(status)
    if not text or text.startswith("("):
        return msgs
    answer = reply_brain(text)
    msgs.append(f"🤖 {answer}")
    msgs.append(speak(answer))
    return msgs
