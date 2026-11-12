#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kota_sayac.py — Gemini/Groq gerçek kotayı API'de vermediği için KENDİ sayacımız.

Gemini ve Groq, "kalan kota" bilgisini API yanıtında döndürmüyor (test edildi:
rate-limit başlığı yok). Bu yüzden panelde gerçek sayı göstermek için
yaptığımız çağrıları burada sayıyoruz.

Kullanım (her giriş betiğinin en üstünde tek satır):
    import kota_sayac  # noqa: F401

Sayım şurada tutulur : kota_kullanim.json
Günlük limitler       : kota_limitleri.json (elle ayarlanır)
"""
from __future__ import annotations

import atexit
import json
import os
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
KULLANIM = BASE / "kota_kullanim.json"
LIMITLER = BASE / "kota_limitleri.json"

# Gemini/Groq ücretsiz katman için makul varsayılanlar — elle ayarlanabilir
VARSAYILAN_LIMIT = {
    # Gerçek ÜCRETSİZ KATMAN değerleri (Google AI + Groq + Pexels rate-limit dokümanı)
    "gemini": {"gunluk_istek": 1500, "dakika_istek": 15, "birim": "istek/gün"},
    "groq": {"gunluk_istek": 1000, "dakika_istek": 30, "birim": "istek/gün"},
    "openrouter": {"gunluk_istek": 50, "birim": "istek/gün"},  # ücretsiz modeller
    "pexels": {"gunluk_istek": 4800, "birim": "istek/gün"},
    "pixabay": {"gunluk_istek": 5000, "birim": "istek/gün"},
}

_SAYAC = {"gemini": 0, "groq": 0, "openrouter": 0, "elevenlabs": 0, "telegram": 0, "pexels": 0, "pixabay": 0}
_KILIT = threading.Lock()
_OKU, _YAZ = urllib.request.urlopen, urllib.request.Request


def _saglayici(url: str) -> str | None:
    u = str(url).lower()
    if "generativelanguage.googleapis.com" in u:
        return "gemini"
    if "api.groq.com" in u:
        return "groq"
    if "openrouter.ai" in u:
        return "openrouter"
    if "api.elevenlabs.io" in u:
        return "elevenlabs"
    if "api.telegram.org" in u:
        return "telegram"
    if "api.pexels.com" in u:
        return "pexels"
    if "pixabay.com/api" in u:
        return "pixabay"
    return None


def _say(url) -> None:
    s = _saglayici(url)
    if s:
        with _KILIT:
            _SAYAC[s] = _SAYAC.get(s, 0) + 1


def _sarilmis_urlopen(*a, **kw):
    """Tüm urllib çağrılarını sayar. Hata durumunda da sayar (deneme yapıldı)."""
    url = a[0] if a else kw.get("url", "")
    if hasattr(url, "full_url"):
        url = url.full_url
    try:
        return _OKU(*a, **kw)
    finally:
        _say(url)


def limitleri() -> dict:
    if LIMITLER.exists():
        try:
            return json.loads(LIMITLER.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return VARSAYILAN_LIMIT


def _bugun() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def yaz() -> None:
    """Sayaçları diske ekler (gün değişince sıfırlar)."""
    eski: dict = {}
    if KULLANIM.exists():
        try:
            eski = json.loads(KULLANIM.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            eski = {}
    gun = _bugun()
    if eski.get("gun") != gun:
        eski = {"gun": gun, "sayaclar": {}, "gecmis": (eski.get("gecmis") or [])[-30:]}
        if eski["gecmis"] is None:
            eski["gecmis"] = []
    sayaclar = eski.setdefault("sayaclar", {})
    with _KILIT:
        for ad, n in _SAYAC.items():
            if n:
                sayaclar[ad] = sayaclar.get(ad, 0) + n
                _SAYAC[ad] = 0
    eski["guncelleme"] = datetime.now(timezone.utc).isoformat()
    KULLANIM.write_text(json.dumps(eski, ensure_ascii=False, indent=1), encoding="utf-8")


def bugun_ozet() -> dict:
    """Panel için: sağlayıcı başına bugünkü kullanım + limit."""
    lim = limitleri()
    d: dict = {}
    if KULLANIM.exists():
        try:
            d = json.loads(KULLANIM.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            d = {}
    ayni_gun = d.get("gun") == _bugun()
    sayaclar = (d.get("sayaclar") or {}) if ayni_gun else {}
    out = {}
    for ad in ("gemini", "groq", "openrouter", "pexels", "pixabay"):
        kullanilan = int(sayaclar.get(ad) or 0)
        limit = (lim.get(ad) or {}).get("gunluk_istek")
        birim = (lim.get(ad) or {}).get("birim") or "istek/gün"
        out[ad] = {
            "kullanilan": kullanilan,
            "limit": limit,
            "kalan": (limit - kullanilan) if limit else None,
            "birim": birim,
            "gun": _bugun(),
        }
    return out


def kur() -> None:
    """urllib'i sar. İki kez çağrılırsa zararsız."""
    if getattr(urllib.request, "_kota_sayac_kuruldu", False):
        return
    urllib.request.urlopen = _sarilmis_urlopen
    urllib.request._kota_sayac_kuruldu = True
    atexit.register(yaz)


kur()
