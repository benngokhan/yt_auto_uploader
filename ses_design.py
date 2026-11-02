#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ses_design.py — Yapay ses ÜRET (Voice Design) ve kaydet.

İki mod:
  1) Önizleme üret:
       python ses_design.py olustur --aciklama "..." --ornek "..." [--model eleven_multilingual_ttv_v2]
     → POST /v1/text-to-voice/design → 3 aday ses
     → mp3'ler  ses/onizleme/<generated_voice_id>.mp3
     → özet      ses_onizleme.json

  2) Beğenileni kütüphaneye kaydet + sesi kilitle:
       python ses_design.py kaydet --id <generated_voice_id> --ad "Bilgi Dozu Anlatıcı" --aciklama "..."
     → POST /v1/text-to-voice → voice_id
     → ses/voice.json  kilit.voice_id / model = eleven_multilingual_v2

API anahtarı yalnızca ortamdan: ELEVENLABS_API_KEY
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
ONIZLEME_DIR = BASE / "ses" / "onizleme"
ONIZLEME_JSON = BASE / "ses_onizleme.json"
SONUC_JSON = BASE / "ses_uretim_sonuc.json"
VOICE_JSON = BASE / "ses" / "voice.json"
API = "https://api.elevenlabs.io/v1"


def key() -> str:
    k = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if not k:
        raise SystemExit("ELEVENLABS_API_KEY yok")
    return k


def cagri(url: str, body: dict, method: str = "POST"):
    req = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode(),
        headers={"xi-api-key": key(), "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detay = e.read().decode("utf-8", "ignore")[:300]
        raise SystemExit(f"ElevenLabs HTTP {e.code}: {detay}")


def kalan_kredi():
    try:
        req = urllib.request.Request(f"{API}/user/subscription", headers={"xi-api-key": key()})
        with urllib.request.urlopen(req, timeout=45) as r:
            d = json.loads(r.read().decode())
        return int(d.get("character_limit") or 0) - int(d.get("character_count") or 0)
    except Exception:
        return None


def yaz_sonuc(d: dict):
    SONUC_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def olustur(args) -> int:
    aciklama = (args.aciklama or "").strip()
    ornek = (args.ornek or "").strip()
    if not (20 <= len(aciklama) <= 1000):
        raise SystemExit("Açıklama 20-1000 karakter olmalı")
    if ornek and not (100 <= len(ornek) <= 1000):
        raise SystemExit("Örnek metin 100-1000 karakter olmalı")

    once = kalan_kredi()
    govde = {"voice_description": aciklama, "model_id": args.model}
    if ornek:
        govde["text"] = ornek
    print("Ses tasarlanıyor:", args.model)
    d = cagri(f"{API}/text-to-voice/design", govde)
    sonra = kalan_kredi()

    ONIZLEME_DIR.mkdir(parents=True, exist_ok=True)
    onizlemeler = []
    for p in d.get("previews", []):
        gid = p.get("generated_voice_id", "")
        if not gid:
            continue
        b64 = p.get("audio_base_64") or ""
        dosya = f"ses/onizleme/{gid}.mp3"
        if b64:
            (BASE / dosya).write_bytes(base64.b64decode(b64))
        onizlemeler.append({
            "id": gid,
            "dosya": dosya,
            "dil": p.get("language", ""),
            "boyut": len(b64) * 3 // 4,
        })
    ONIZLEME_JSON.write_text(json.dumps({
        "zaman": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "aciklama": aciklama,
        "model": args.model,
        "onizlemeler": onizlemeler,
        "kredi_once": once, "kredi_sonra": sonra,
        "kredi_farki": (once - sonra) if (once is not None and sonra is not None) else None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    yaz_sonuc({"ok": True, "asama": "onizleme", "adet": len(onizlemeler)})
    print(f"{len(onizlemeler)} önizleme üretildi · kredi farkı: {(once - sonra) if once is not None and sonra is not None else '?'}")
    return 0


def kaydet(args) -> int:
    if not args.id:
        raise SystemExit("--id (generated_voice_id) gerekli")
    ad = (args.ad or "Bilgi Dozu Anlatıcı").strip()
    aciklama = (args.aciklama or "Bilgi Dozu kanalı için üretilmiş anlatıcı sesi").strip()
    govde = {"voice_name": ad, "voice_description": aciklama, "generated_voice_id": args.id}
    print("Ses kütüphaneye ekleniyor:", ad)
    try:
        d = cagri(f"{API}/text-to-voice", govde)
    except SystemExit:
        d = cagri(f"{API}/text-to-voice/create-voice-from-preview", govde)

    vid = d.get("voice_id") or d.get("voice", {}).get("voice_id") or ""
    if not vid:
        yaz_sonuc({"ok": False, "asama": "kaydet", "yanit": str(d)[:400]})
        raise SystemExit("voice_id dönmedi")

    v = {}
    if VOICE_JSON.exists():
        try:
            v = json.loads(VOICE_JSON.read_text(encoding="utf-8"))
        except Exception:
            v = {}
    k = v.get("kilit", {})
    k.update({
        "saglayici": "elevenlabs",
        "voice_id": vid,
        "model": args.tts_model or "eleven_multilingual_v2",
    })
    v["kilit"] = k
    v["kanonik"] = v.get("kanonik", {})
    v["kanonik"].update({
        "ad": ad,
        "kaynak": "Voice Design (yapay üretim, " + datetime.now(timezone.utc).strftime("%Y-%m-%d") + ")",
        "aciklama": aciklama,
    })
    VOICE_JSON.parent.mkdir(parents=True, exist_ok=True)
    VOICE_JSON.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    yaz_sonuc({"ok": True, "asama": "kaydet", "voice_id": vid, "ad": ad, "model": k["model"]})
    print("KİLİTLENDİ:", vid, "·", k["model"])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mod", required=True)

    a = sub.add_parser("olustur")
    a.add_argument("--aciklama", required=True)
    a.add_argument("--ornek", default="")
    a.add_argument("--model", default="eleven_multilingual_ttv_v2",
                   choices=["eleven_multilingual_ttv_v2", "eleven_ttv_v3"])

    b = sub.add_parser("kaydet")
    b.add_argument("--id", required=True)
    b.add_argument("--ad", default="Bilgi Dozu Anlatıcı")
    b.add_argument("--aciklama", default="")
    b.add_argument("--tts-model", default="eleven_multilingual_v2")

    args = ap.parse_args()
    return olustur(args) if args.mod == "olustur" else kaydet(args)


if __name__ == "__main__":
    sys.exit(main())
