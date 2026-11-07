#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""api_uyari.py — API kullanım uyarılarını üretir (panel ana sayfası için).

KURAL (sahibin isteği):
  * Bir API %90'a ulaşırsa  -> ana sayfada KIRMIZI uyarı
  * Aynı uyarı SÜREKLİ yazmaz — bir kez gösterilir, o API düşene kadar tekrar etmez
  * Anahtar geçersiz/limit bitmiş -> ayrı kırmızı uyarı
  * Her şey iyiyse -> hiçbir şey görünmez

Çalışma:
  1. api_telemetri.json okunur (api_kota.py üretir, 30 dk'da bir)
  2. Her servis için doluluk yüzdesi hesaplanır
  3. %90 üstü + geçersiz olanlar uyarı listesine girer
  4. api_uyarilari.json yazılır — panel bunu okur

Kullanım:
  python3 api_uyari.py            # uyarıları üret
  python3 api_uyari.py --kontrol  # sadece göster (dosya yazmaz)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
TELEMETRI = BASE / "api_telemetri.json"
CIKTI = BASE / "api_uyarilari.json"
GECMIS = BASE / "api_uyari_gecmisi.json"   # hangi uyarı gösterildi (tekrar etmemesi için)

ESIK = 90          # %90 ve üstü -> uyarı
KRITIK = 95        # %95 ve üstü -> kritik


def _yuzde(servis: dict) -> float | None:
    """Doluluk yüzdesi. Limit/kalan yoksa None."""
    kalan = servis.get("kalan")
    limit = servis.get("limit")
    kullanilan = servis.get("kullanilan")

    try:
        if limit not in (None, 0) and kullanilan is not None:
            return round(100.0 * float(kullanilan) / float(limit), 1)
        if limit not in (None, 0) and kalan is not None:
            return round(100.0 * (float(limit) - float(kalan)) / float(limit), 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None


def uyarilari_hesapla(telemetri: dict) -> list[dict]:
    uyarilar: list[dict] = []
    servisler = telemetri.get("servisler") or []

    for s in servisler:
        ad = s.get("ad") or s.get("name") or "?"
        durum = (s.get("durum") or s.get("status") or "").lower()

        # --- 1) Geçersiz / bozuk anahtar ---
        if durum in ("gecersiz", "geçersiz", "invalid", "hata", "error", "yetkisiz"):
            uyarilar.append({
                "id": f"{ad}_gecersiz",
                "servis": ad,
                "seviye": "kritik",
                "baslik": f"{ad} anahtarı geçersiz",
                "mesaj": (s.get("mesaj") or "Anahtar reddediliyor. Yenilenmesi gerekiyor.")[:180],
                "yuzde": None,
                "islem": "Anahtarı yenile",
            })
            continue

        # --- 2) Limit bitmiş ---
        y = _yuzde(s)
        if y is None:
            continue

        if y >= ESIK:
            seviye = "kritik" if y >= KRITIK else "uyari"
            kalan, limit = s.get("kalan"), s.get("limit")
            birim = s.get("birim") or ""
            if kalan is not None and limit is not None:
                detay = f"{kalan:,} / {limit:,} {birim} kaldı".replace(",", ".")
            else:
                detay = f"%{y} dolu"

            uyarilar.append({
                "id": f"{ad}_limit",
                "servis": ad,
                "seviye": seviye,
                "baslik": f"{ad} limitin %{y}'inde",
                "mesaj": f"{detay}. {s.get('yenilenme') or ''}".strip()[:180],
                "yuzde": y,
                "islem": "Kullanımı azalt veya planı yükselt",
            })

    return uyarilar


def tekrarlari_ele(uyarilar: list[dict], gecmis: dict) -> tuple[list[dict], dict]:
    """
    Sürekli yazmasın kuralı:
      - Aynı uyarı daha önce gösterildiyse ve seviyesi değişmediyse -> gösterme
      - Seviye yükselirse (uyari -> kritik) tekrar göster
      - Uyarı ortadan kalkarsa geçmişten sil (bir sonraki sefer yine gösterilsin)
    """
    su_an = {u["id"]: u for u in uyarilar}
    yeni: list[dict] = []
    yeni_gecmis: dict = {}

    for uid, u in su_an.items():
        eski = gecmis.get(uid)
        if eski is None or eski.get("seviye") != u["seviye"]:
            yeni.append(u)                      # ilk kez veya seviye değişti
        yeni_gecmis[uid] = {"seviye": u["seviye"], "ilk": (eski or {}).get("ilk") or
                            datetime.now(timezone.utc).isoformat()}

    # ortadan kalkanlar geçmişe yazılmaz -> tekrar ortaya çıkarsa gösterilir
    return yeni, yeni_gecmis


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kontrol", action="store_true", help="dosya yazma, sadece göster")
    a = ap.parse_args()

    if not TELEMETRI.exists():
        sys.exit(f"Telemetri yok: {TELEMETRI}\n→ önce `python3 api_kota.py` çalıştır.")

    telemetri = json.loads(TELEMETRI.read_text(encoding="utf-8"))
    tum = uyarilari_hesapla(telemetri)

    gecmis = {}
    if GECMIS.exists():
        try:
            gecmis = json.loads(GECMIS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            gecmis = {}

    gosterilecek, yeni_gecmis = tekrarlari_ele(tum, gecmis)

    # --- konsol özeti ---
    toplam = len(tum)
    if toplam:
        print(f"⚠️ {toplam} API uyarısı var, {len(gosterilecek)} tanesi yeni:")
        for u in tum:
            yeni_mi = "🆕" if any(g["id"] == u["id"] for g in gosterilecek) else "  "
            print(f"  {yeni_mi} [{'KRİTİK' if u['seviye']=='kritik' else 'UYARI'}] "
                  f"{u['baslik']} — {u['mesaj'][:70]}")
    else:
        print("✅ Tüm API'ler normal — uyarı yok")

    if a.kontrol:
        return

    cikti = {
        "zaman": datetime.now(timezone.utc).isoformat(),
        "ozet": {
            "toplam": toplam,
            "kritik": sum(1 for u in tum if u["seviye"] == "kritik"),
            "yeni": len(gosterilecek),
        },
        # panel ana sayfasında gösterilecek olanlar
        "uyarilar": tum,
        # sadece bu sefer yeni olanlar (bildirim/rozet için)
        "yeni_uyarilar": gosterilecek,
    }
    CIKTI.write_text(json.dumps(cikti, ensure_ascii=False, indent=1), encoding="utf-8")
    GECMIS.write_text(json.dumps(yeni_gecmis, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {CIKTI.name} yazıldı")


if __name__ == "__main__":
    main()
