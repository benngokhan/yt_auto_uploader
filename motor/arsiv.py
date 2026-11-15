#!/usr/bin/env python3
"""Üretim arşivi — her üretimin kanıt dosyalarını `uretim_XX/` klasörüne yazar.

Amaç (sahip, 15.11.2026): 63/64 denetiminde ham senaryo, uzatma öncesi/sonrası, Gemini'ye giden istek ve
ham ses saklanmadığı için "kanıtlayamadım" denen her şey bundan sonra dosyada dursun.

Kurallar:
  * Bu modül üretimi ASLA etkilemez: her fonksiyon kendi hatasını yutar, hiçbir şey döndürmek zorunda değildir.
  * Dosya adı: <sıra>_<ad>_<UTC zaman damgası>.<uzantı>  (ör. 07_gemini_tts_istek_govdesi_20261115T202512Z.json)
  * Klasör: motor/cikti_arsiv/uretim_<GITHUB_RUN_NUMBER>/  (yerelde: uretim_yerel_<zaman>)
    MOTOR_ARSIV_DIR ortam değişkeni verilirse o klasör kullanılır.
  * Gizli bilgi yazılmaz: API anahtarı taşıyan adresler ve başlıklar arşive verilmez; metinler yine de maskelenir.
"""
from __future__ import annotations

import json
import os
import re
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path

MOTOR = Path(__file__).resolve().parent
_durum: dict = {"klasor": None, "sira": 0}

_GIZLI = re.compile(r"ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}"
                    r"|(?<=key=)[A-Za-z0-9_-]{16,}|(?<=Bearer )[A-Za-z0-9._-]{16,}"
                    r"|org_[A-Za-z0-9]{16,}|ya29\.[A-Za-z0-9._-]{20,}|GOCSPX-[A-Za-z0-9_-]{16,}|1//[A-Za-z0-9_-]{30,}"
                    r"|\b\d{8,10}:AA[A-Za-z0-9_-]{30,}")


class _MaskeliAkis:
    """sys.stdout/sys.stderr sarmalayıcısı: motorun yazdığı HER satır maskeden geçer (GitHub logu dahil)."""

    def __init__(self, akis):
        self._akis = akis

    def write(self, s):
        try:
            s = maskele(s)
        except Exception:  # noqa: BLE001
            pass
        return self._akis.write(s)

    def __getattr__(self, ad):
        return getattr(self._akis, ad)


def cikti_maskele_kur() -> None:
    """Motorun konsol çıktısını maskeler (Groq kuruluş kimliği, anahtarlar). Asla istisna fırlatmaz."""
    try:
        for ad in ("stdout", "stderr"):
            akis = getattr(sys, ad)
            if not isinstance(akis, _MaskeliAkis):
                setattr(sys, ad, _MaskeliAkis(akis))
    except Exception:  # noqa: BLE001
        pass


def damga() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def maskele(metin: str) -> str:
    metin = _GIZLI.sub("[MASKELENDI]", str(metin))
    for ad in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY",
               "TELEGRAM_BOT_TOKEN", "GITHUB_TOKEN"):
        deger = os.getenv(ad, "").strip()
        if len(deger) >= 8:
            metin = metin.replace(deger, "[MASKELENDI]")
    return metin


def klasor() -> Path | None:
    """Arşiv klasörünü (gerekirse oluşturup) döndürür; oluşturulamazsa None."""
    try:
        if _durum["klasor"] is None:
            ozel = os.getenv("MOTOR_ARSIV_DIR", "").strip()
            if ozel:
                k = Path(ozel)
            else:
                no = os.getenv("GITHUB_RUN_NUMBER", "").strip()
                k = MOTOR / "cikti_arsiv" / (f"uretim_{no}" if no else f"uretim_yerel_{damga()}")
            k.mkdir(parents=True, exist_ok=True)
            _durum["klasor"] = k
        return _durum["klasor"]
    except Exception:
        return None


def _yol(ad: str, uzanti: str) -> Path | None:
    k = klasor()
    if k is None:
        return None
    _durum["sira"] += 1
    temiz = re.sub(r"[^A-Za-z0-9_-]+", "_", ad).strip("_") or "dosya"
    return k / f"{_durum['sira']:02d}_{temiz}_{damga()}.{uzanti.lstrip('.')}"


def yaz(ad: str, icerik, uzanti: str = "txt") -> Path | None:
    """Metin dosyası yazar (gizli bilgiler maskelenir). Hata olursa sessizce None döner."""
    try:
        y = _yol(ad, uzanti)
        if y is None:
            return None
        y.write_text(maskele(icerik if isinstance(icerik, str) else str(icerik)), encoding="utf-8")
        return y
    except Exception:
        return None


def yaz_json(ad: str, veri) -> Path | None:
    try:
        return yaz(ad, json.dumps(veri, ensure_ascii=False, indent=2, default=str), "json")
    except Exception:
        return None


def yaz_bayt(ad: str, veri: bytes, uzanti: str) -> Path | None:
    """İkili dosya yazar (ör. ham ses). İçerik değiştirilmez."""
    try:
        y = _yol(ad, uzanti)
        if y is None:
            return None
        y.write_bytes(veri)
        return y
    except Exception:
        return None


def kopyala(ad: str, kaynak) -> Path | None:
    try:
        kaynak = Path(kaynak)
        if not kaynak.exists():
            return None
        y = _yol(ad, kaynak.suffix or "bin")
        if y is None:
            return None
        shutil.copyfile(kaynak, y)
        return y
    except Exception:
        return None


def pcm_wav_yaz(ad: str, pcm16: bytes, hz: int = 24000) -> Path | None:
    """Gemini'den gelen ham 16-bit mono PCM'i, HİÇBİR işlem yapmadan WAV kabına koyar."""
    try:
        import wave
        y = _yol(ad, "wav")
        if y is None:
            return None
        with wave.open(str(y), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(hz)
            w.writeframes(pcm16)
        return y
    except Exception:
        return None


def baslat(konu: str = "", ek: dict | None = None) -> Path | None:
    """Üretim kimliğini yazar: koşu numarası, commit, konu ve motor dosyalarının özetleri."""
    try:
        import hashlib
        ozet = {}
        for f in ("uret.py", "tts.py", "metin_hazirla.py", "shorts_pipeline.py", "kapak.py", "ayarlar.json",
                  "senaryo_denetim.py", "regresyon.py", "arsiv.py", "ses_olcum.py"):
            p = MOTOR / f
            if p.exists():
                ozet[f] = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        return yaz_json("uretim_bilgisi", {
            "uretim_no": os.getenv("GITHUB_RUN_NUMBER", "yerel"),
            "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
            "commit": os.getenv("GITHUB_SHA", ""),
            "baslangic_utc": damga(),
            "konu": konu,
            "dosya_ozetleri_sha256_ilk12": ozet,
            **(ek or {}),
        })
    except Exception:
        return None
