#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ses_kredi.py — ElevenLabs kalan krediyi panel için okur (salt-okunur, kredi harcamaz).

GET /v1/user/subscription  → tier, character_limit, character_count, reset
GET /v1/voices              → hesaptaki sesler (voice_id kopyalamak için)

Çıktı: ses_telemetri.json (panel bunu okur)
  * anahtar_durumu: ok | gecersiz | yok
  * kalan kredi, yüzde, reset tarihi, kaç short daha çıkar
  * klonlama izinleri (can_use_instant_voice_cloning vb.)

API anahtarı YALNIZCA ortamdan okunur (ELEVENLABS_API_KEY / ELEVEN_API_KEY),
hiçbir yere yazılmaz. Kullanım:
    python ses_kredi.py            # ELEVENLABS_API_KEY ortamdan
    python ses_kredi.py --anahtar sk_xxx
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "ses_telemetri.json"
API = "https://api.elevenlabs.io/v1"
KARAKTER_PER_SHORT = 900      # 55 sn short ≈ 900 karakter (ölçüldü: Turkish ~1000 karakter/dk)
GECMIS_LIMIT = 60


def get(url: str, key: str):
    req = urllib.request.Request(url, headers={"xi-api-key": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anahtar", default="")
    args = ap.parse_args()
    key = (args.anahtar or os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVEN_API_KEY") or "").strip()

    eski = {}
    if OUT.exists():
        try:
            eski = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            eski = {}

    veri = {
        "zaman": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "anahtar_durumu": "yok" if not key else "ok",
    }

    if not key:
        veri["mesaj"] = "ELEVENLABS_API_KEY tanımlı değil. Panelden anahtar yükle."
        veri["gecmis"] = eski.get("gecmis", [])
        OUT.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
        print("HATA: API anahtarı yok")
        return 2

    try:
        sub = get(f"{API}/user/subscription", key)
    except urllib.error.HTTPError as e:
        kod = e.code
        veri["anahtar_durumu"] = "gecersiz" if kod in (401, 403) else "hata"
        veri["mesaj"] = f"ElevenLabs HTTP {kod}" + (" — anahtar geçersiz/iptal" if kod in (401, 403) else "")
        veri["gecmis"] = eski.get("gecmis", [])
        OUT.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
        print(veri["mesaj"])
        return 1
    except Exception as e:
        veri["anahtar_durumu"] = "hata"
        veri["mesaj"] = f"Bağlantı hatası: {e}"
        veri["gecmis"] = eski.get("gecmis", [])
        OUT.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
        print(veri["mesaj"])
        return 1

    limit = int(sub.get("character_limit") or 0)
    kullanilan = int(sub.get("character_count") or 0)
    kalan = max(limit - kullanilan, 0)
    reset = sub.get("next_character_count_reset_unix")
    reset_iso = ""
    kalan_gun = None
    if reset:
        dt = datetime.fromtimestamp(int(reset), tz=timezone.utc)
        reset_iso = dt.isoformat(timespec="seconds")
        kalan_gun = max((dt - datetime.now(timezone.utc)).days, 0)

    veri.update({
        "tier": sub.get("tier") or "?",
        "durum": sub.get("status") or "",
        "limit": limit,
        "kullanilan": kullanilan,
        "kalan": kalan,
        "yuzde_kalan": round(kalan / limit * 100, 1) if limit else 0,
        "reset_unix": reset,
        "reset_iso": reset_iso,
        "reset_gun": kalan_gun,
        "para_birimi": sub.get("currency") or "usd",
        "klonlama": {
            "instant": bool(sub.get("can_use_instant_voice_cloning")),
            "profesyonel": bool(sub.get("can_use_professional_voice_cloning")),
            "ses_slotu": sub.get("voice_limit"),
            "kullanilan_slot": sub.get("voice_slots_used"),
        },
        "tahmin": {
            "karakter_per_short": KARAKTER_PER_SHORT,
            "kac_short": kalan // KARAKTER_PER_SHORT,
            "flash_kac_short": kalan * 2 // KARAKTER_PER_SHORT,
        },
    })

    sesler = []
    try:
        v = get(f"{API}/voices", key)
        for s in v.get("voices", [])[:40]:
            sesler.append({
                "id": s.get("voice_id", ""),
                "ad": s.get("name", ""),
                "kategori": s.get("category", ""),
                "etiket": ", ".join((s.get("labels") or {}).values())[:60],
            })
    except Exception as e:
        veri["ses_uyari"] = f"Ses listesi alınamadı: {e}"
    veri["sesler"] = sesler

    gecmis = [g for g in eski.get("gecmis", []) if isinstance(g, dict)][-GECMIS_LIMIT:]
    gecmis.append({"zaman": veri["zaman"], "kalan": kalan, "kullanilan": kullanilan})
    veri["gecmis"] = gecmis[-GECMIS_LIMIT:]

    OUT.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"tier={veri['tier']} kalan={kalan}/{limit} (~{veri['tahmin']['kac_short']} short) reset={reset_iso} ses={len(sesler)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
