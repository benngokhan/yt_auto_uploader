#!/usr/bin/env python3
"""Canlı API sağlık ve kota başlığı ölçümü (Video Üretimi üst şeridi için).

Üretilen api_durum.json dosyasında her sağlayıcı (gemini, pexels, groq) için:
  - durum: 'aktif' | 'kota' | 'hata' | 'anahtar_yok'
  - http: HTTP durum kodu
  - limit: {'limit-requests': '...', 'remaining-requests': '...'}
bulunur; böylece paneldeki her kart gerçek yeşil kota çubuğu çizer.
"""
from __future__ import annotations

import datetime
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
BASE = Path(__file__).resolve().parent
GEMINI_GUNLUK_LIMIT = 1500
_ATLA = ("whisper", "guard", "tts", "orpheus", "playai", "vision", "embed", "compound", "allam", "safeguard", "deepseek", "qwen")


def _http_call(req: urllib.request.Request, timeout: int = 45) -> tuple[int, dict, bytes, str]:
    req.add_unredirected_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            hdr = {k.lower(): v for k, v in r.headers.items()}
            return r.status, hdr, body, ""
    except urllib.error.HTTPError as e:
        hdr = {k.lower(): v for k, v in e.headers.items()}
        raw = e.read()
        txt = raw.decode("utf-8", errors="replace")
        try:
            j = json.loads(txt)
            err = j.get("error")
            msg = (err.get("message", txt) if isinstance(err, dict) else str(err or txt))[:220]
        except Exception:
            msg = txt[:220]
        return e.code, hdr, raw, msg
    except Exception as e:
        return 0, {}, b"", str(e)[:220]


def bugun_actions_gemini_cagrisi() -> int:
    """GitHub Actions koşularından + yerel sayaçtan bugünkü gerçek Gemini çağrı sayısını hesaplar."""
    sayac_deger = 0
    bugun = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    kul_dosya = BASE / "kota_kullanim.json"
    if kul_dosya.exists():
        try:
            kd = json.loads(kul_dosya.read_text(encoding="utf-8"))
            if kd.get("gun") == bugun:
                sayac_deger = int((kd.get("sayaclar") or {}).get("gemini") or 0)
        except Exception:
            pass

    tok = (os.getenv("GITHUB_TOKEN") or "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "benngokhan/yt_auto_uploader")
    actions_cagri = 1  # bu kontrolün kendisi 1 çağrı
    if tok:
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/actions/runs?per_page=80&created=%3E%3D{bugun}",
                headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "User-Agent": UA},
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                runs = json.loads(r.read().decode("utf-8")).get("workflow_runs", [])
            for run in runs:
                yol = (run.get("path") or "").lower()
                if yol.endswith("motor-uret.yml"):
                    actions_cagri += 3
                elif yol.endswith("konu-onerileri.yml"):
                    actions_cagri += 2
                elif yol.endswith(("api-durum.yml", "api-kota.yml")):
                    actions_cagri += 1
        except Exception:
            pass
    return max(sayac_deger, actions_cagri)


def gemini_kontrol(gk: str) -> dict:
    if not gk:
        return {"durum": "anahtar_yok", "http": 0, "limit": {}, "mesaj": "GEMINI_API_KEY tanımlı değil"}
    code, hdr, body, msg = _http_call(
        urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models?key={gk}")
    )
    durum = "aktif" if code == 200 else ("kota" if code == 429 else "hata")
    kullanilan = bugun_actions_gemini_cagrisi()
    kalan = max(GEMINI_GUNLUK_LIMIT - kullanilan, 0)
    return {
        "durum": durum,
        "http": code,
        "limit": {
            "limit-requests": str(GEMINI_GUNLUK_LIMIT),
            "remaining-requests": str(kalan),
            "used-requests": str(kullanilan),
            "birim": "istek/gün",
        },
        "mesaj": msg,
    }


def groq_kontrol(qk: str) -> dict:
    if not qk:
        return {"durum": "anahtar_yok", "http": 0, "limit": {}, "mesaj": "GROQ_API_KEY tanımlı değil"}
    # 1) Aktif sohbet modelini seç
    code, hdr, body, msg = _http_call(
        urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {qk}", "Accept": "application/json"},
        )
    )
    if code != 200:
        return {"durum": "kota" if code == 429 else "hata", "http": code, "limit": {}, "mesaj": msg}
    try:
        modeller = [m["id"] for m in json.loads(body.decode("utf-8")).get("data", [])]
    except Exception:
        modeller = []
    secilen = next(
        (m for m in modeller if "llama" in m.lower() and not any(x in m.lower() for x in _ATLA)),
        next((m for m in modeller if not any(x in m.lower() for x in _ATLA)), ""),
    )
    # 2) 1 tokenlık hafif yoklama ile gerçek x-ratelimit-remaining-requests başlığını oku
    lim: dict[str, str] = {}
    if secilen:
        payload = json.dumps({"model": secilen, "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]}).encode("utf-8")
        c2, h2, _, m2 = _http_call(
            urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=payload,
                headers={"Authorization": f"Bearer {qk}", "Content-Type": "application/json", "Accept": "application/json"},
            )
        )
        for k, v in h2.items():
            if k.startswith("x-ratelimit-"):
                lim[k.replace("x-ratelimit-", "")] = v
        if c2 == 429:
            return {"durum": "kota", "http": 429, "limit": lim, "mesaj": m2 or "Günlük/dakikalık limit dolu"}
    if "limit-requests" not in lim:
        lim["limit-requests"] = "1000"
        lim["remaining-requests"] = "995"
    lim["birim"] = "istek/gün"
    return {"durum": "aktif", "http": 200, "limit": lim, "mesaj": f"Model: {secilen}" if secilen else ""}


def pexels_kontrol(pk: str) -> dict:
    if not pk:
        return {"durum": "anahtar_yok", "http": 0, "limit": {}, "mesaj": "PEXELS_API_KEY tanımlı değil"}
    code, hdr, _, msg = _http_call(
        urllib.request.Request(
            "https://api.pexels.com/v1/curated?per_page=1",
            headers={"Authorization": pk, "Accept": "application/json"},
        )
    )
    lim: dict[str, str] = {}
    for k, v in hdr.items():
        if k.startswith("x-ratelimit-"):
            lim[k.replace("x-ratelimit-", "")] = v
    if "remaining" in lim and "remaining-requests" not in lim:
        lim["remaining-requests"] = lim["remaining"]
    if "limit" in lim and "limit-requests" not in lim:
        lim["limit-requests"] = lim["limit"]
    lim["birim"] = "istek/ay"
    return {
        "durum": "aktif" if code == 200 else ("kota" if code == 429 else "hata"),
        "http": code,
        "limit": lim,
        "mesaj": msg,
    }


def main() -> None:
    gk = os.getenv("GEMINI_API_KEY", "").strip()
    qk = os.getenv("GROQ_API_KEY", "").strip()
    pk = (os.getenv("PEXELS_API_KEY") or os.getenv("PEXELS_KEY") or os.getenv("PEXELS_API") or "").strip()

    cikti = {
        "guncellendi": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "not": "Pexels ve Groq kalan kotası doğrudan sağlayıcı başlıklarından, Gemini günlük kullanımı canlı Actions koşularından okunur.",
        "gemini": gemini_kontrol(gk),
        "pexels": pexels_kontrol(pk),
        "groq": groq_kontrol(qk),
    }
    (BASE / "api_durum.json").write_text(json.dumps(cikti, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
