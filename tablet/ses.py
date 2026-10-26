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

# Termux araçlarının yeri sabit olabilir; PATH'e ekle
for _p in ("/data/data/com.termux/files/usr/bin",):
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + ":" + os.environ.get("PATH", "")

REC_DIR = Path.home() / "kartal_tablet" / "kayitlar"
REC_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Gemini çağrısı: hem ?key= hem x-goog-api-key, hem v1beta hem v1, model yedeği
# ---------------------------------------------------------------------------
GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash")


def _list_models(key: str) -> list[str]:
    """Anahhtarin erisebildigi, generateContent destekleyen modeller."""
    out = []
    for ver in ("v1beta", "v1"):
        url = f"https://generativelanguage.googleapis.com/{ver}/models?pageSize=50"
        try:
            req = urllib.request.Request(url, headers={"x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            for m in data.get("models", []):
                methods = m.get("supportedGenerationMethods") or []
                if "generateContent" in methods:
                    name = (m.get("name") or "").replace("models/", "")
                    if name and name not in out:
                        out.append(name)
            if out:
                break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise
            continue
        except Exception:
            continue
    return out


def gemini_call(parts, temperature=0.2, max_tokens=800):
    """Gemini'ye icerik gonderir. Modeli canli listeden secer."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return "(GEMINI_API_KEY yok)"

    payload = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }).encode()

    models = []
    env_model = os.getenv("GEMINI_MODEL", "").strip()
    if env_model:
        models.append(env_model)
    # Liste alinamazsa yine de bilinen modelleri dene (AQ. anahtarlar ListModels'i reddedebilir)
    try:
        models += _list_models(key)
    except Exception:
        pass
    models += list(GEMINI_MODELS)

    seen = set()
    last = "bilinmeyen hata"
    for model in models:
        if model in seen:
            continue
        seen.add(model)
        for ver in ("v1beta", "v1"):
            for auth in ("header", "query"):
                url = f"https://generativelanguage.googleapis.com/{ver}/models/{model}:generateContent"
                if auth == "query":
                    url += f"?key={urllib.parse.quote(key)}"
                headers = {"Content-Type": "application/json"}
                if auth == "header":
                    headers["x-goog-api-key"] = key
                try:
                    req = urllib.request.Request(url, data=payload, headers=headers)
                    with urllib.request.urlopen(req, timeout=90) as r:
                        data = json.loads(r.read().decode())
                    cand = data.get("candidates") or []
                    if not cand:
                        continue
                    txt = "".join(pt.get("text", "") for pt in cand[0]["content"]["parts"]).strip()
                    if txt:
                        os.environ["GEMINI_MODEL_OK"] = model
                        return txt
                except urllib.error.HTTPError as e:
                    try:
                        body = e.read().decode()[:160].replace("\n", " ")
                    except Exception:
                        body = ""
                    last = f"HTTP {e.code} ({model}/{ver}) {body}"
                    if e.code in (401, 403):
                        return f"(anahtar reddedildi: {last})"
                    if e.code in (404, 400):
                        break
                except Exception as e:
                    last = f"{type(e).__name__}: {e}"
    return f"({last})"


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
    # Türkçe ses yoksa Android sessizce İngilizce okur. Sıra: tr-TR -> tr -> cihaz varsayılanı
    langs = [os.getenv("TTS_LANG", "tr-TR").strip() or "tr-TR", "tr", ""]
    last = ""
    for lang in langs:
        args = ["termux-tts-speak"]
        if lang:
            args += ["-l", lang]
        args += ["-r", os.getenv("TTS_RATE", "1.0"), "-p", os.getenv("TTS_PITCH", "1.0"), text[:3000]]
        out = _run(args)
        last = out
        if "yok" in out:
            return f"❌ {out}"
        # Android hata vermeyip yine de okur; ilk denemede bırak
        break
    hint = ""
    if not tts_lang_installed():
        hint = ("\n\n⚠️ Tablette Türkçe ses paketi YOK — İngilizce okuyor.\n"
                "Ayarlar → Dil ve klavye → Metin okuma → Google konuşma hizmetleri\n"
                "→ 'Dilleri yükle' → Türkçe → İndir")
    return f"🔊 Konuşuyor: {text[:120]}{'…' if len(text) > 120 else ''}{hint}"


def tts_lang_installed() -> bool:
    """Türkçe TTS ses paketi kurulu mu? (termux-tts-engines ile kontrol edilir)"""
    out = _run(["termux-tts-engines"], timeout=25)
    low = (out or "").lower()
    if "yok" in low:
        return False
    return "tr" in low and ("tur" in low or "türk" in low or "tr-tr" in low or "tr_tr" in low)


def record(seconds: int = 6) -> Path | None:
    """Mikrofonu kaydeder (m4a)."""
    if shutil.which("termux-microphone-record") is None:
        return None
    # Mikrofon izni kontrolü (termux-microphone-record yoksa da buraya gelinmez)
    try:
        st = _run(["termux-microphone-record", "-i"], timeout=15)
        if "yok" in st:
            return None
    except Exception:
        pass
    path = REC_DIR / f"kayit_{int(time.time())}.m4a"
    _run(["termux-microphone-record", "-f", str(path), "-e", "aac", "-b", "64000"], timeout=10)
    time.sleep(max(1, seconds))
    _run(["termux-microphone-record", "-q"], timeout=10)
    time.sleep(0.8)
    return path if path.exists() and path.stat().st_size > 2000 else None


def transcribe(path: Path) -> str:
    """Gemini ile sesi yazıya çevirir."""
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return "(Gemini anahtarı yok → ses yazıya çevrilemiyor)"
    return gemini_call(
        [
            {"text": "Bu ses kaydını Türkçe olarak yazıya çevir. Sadece duyduğun metni yaz, açıklama ekleme."},
            {"inline_data": {"mime_type": "audio/mp4", "data": base64.b64encode(path.read_bytes()).decode()}},
        ],
        temperature=0.0,
    )


def reply_brain(user_text: str) -> str:
    """Kısa, doğal bir yanıt üretir."""
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return f"Duydum: {user_text}"
    out = gemini_call(
        [{"text": (
            "Sen Kartal'sın: Bilgi Dozu YouTube kanalının tablet asistanı. "
            "Türkçe, samimi, kısa (en fazla 2 cümle) cevap ver. "
            f"Kullanıcı şöyle dedi: {user_text}"
        )}],
        temperature=0.6,
        max_tokens=300,
    )
    return out if not out.startswith("(") else f"Duydum: {user_text}"


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
