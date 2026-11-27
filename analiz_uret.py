#!/usr/bin/env python3
"""YouTube analizinden gelen ilk N adayla 7 sahneli Short üretir.

Akış: yt_analiz.json -> motor/uret.py --shorts-v2 -> Telegram(video+kapak)
      -> 'onayladım' -> Drive video_<N> + baslik.xlsx satırı.

19:30 yayın saatine dokunmaz; yalnızca kuyruğa yazar.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

KOK = Path(__file__).resolve().parent
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

import mpt_uret  # noqa: E402
import short_teslim  # noqa: E402
import telegram_onay  # noqa: E402


def adaylari_yukle(yol: str | Path, adet: int) -> list[dict]:
    yol = Path(yol)
    if not yol.is_file():
        raise SystemExit(f"Analiz dosyası yok: {yol}. Önce yt_analiz.py çalıştır.")
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("Analiz dosyası okunamadı") from exc
    adaylar = [c for c in (veri.get("candidates") or []) if isinstance(c, dict) and c.get("short_handoff")]
    if not adaylar:
        raise SystemExit("Analizde Short'a uygun aday yok.")
    return [c["short_handoff"] for c in adaylar[:max(1, adet)]]


def konu_metni(handoff: dict) -> str:
    """Analiz eline geçen konuyu motorun --konu argümanına çevirir. CTA motordan gelir."""
    konu = str(handoff.get("topic") or "").strip()
    if not konu:
        raise SystemExit("Analiz elinde konu boş; motor çağrılmadı.")
    if len(konu) > 400:
        konu = konu[:397].rstrip() + "..."
    return konu


def uret_bir(handoff: dict, sirra: int, timeout_sn: int = 3600) -> Path:
    """Tek Short'u üretir ve çıktısını sabit bir adaya kopyalar (2. tur üstüne yazmaz)."""
    konu = konu_metni(handoff)
    anaklasor = KOK / "motor" / "cikti"
    gecici = anaklasor / "son" / "onay_bekleyen"
    shutil.rmtree(gecici, ignore_errors=True)
    komut = [
        sys.executable, str(KOK / "motor" / "uret.py"),
        "--konu", konu, "--shorts-v2", "--sahne", "7",
        "--sure-min", "38", "--sure-max", "45",
    ]
    print(f"ÜRET {sirra}: {konu}", flush=True)
    subprocess.run(komut, cwd=str(KOK), check=True, timeout=timeout_sn)

    hedef = anaklasor / "analiz" / f"aday_{sirra:02d}"
    if hedef.exists():
        shutil.rmtree(hedef)
    hedef.mkdir(parents=True, exist_ok=True)
    kopyalanan = []
    for ad in ("final.mp4", "kapak.jpg", "yayin_bilgisi.json"):
        kaynak = gecici / ad
        if not kaynak.is_file() or kaynak.stat().st_size == 0:
            raise SystemExit(f"Motor {ad} üretmedi; teslim durduruldu.")
        shutil.copyfile(kaynak, hedef / ad)
        kopyalanan.append(ad)
    print(f"HAZIR {sirra}: {hedef} ({', '.join(kopyalanan)})", flush=True)
    return hedef


def calistir(adet: int, analiz_yolu: str, bekleme_sn: int, kaynak: str, kuru: bool = False) -> int:
    handofflar = adaylari_yukle(analiz_yolu, adet)
    drive = None if kuru else mpt_uret.drive_istemci()
    ilk_numara = 1 if kuru else mpt_uret.sonraki_numara(drive)
    if kuru:
        print(" KURU: Drive/Telegram/tablo atlanıyor; yalnız video üretiliyor.", flush=True)
    else:
        print(f" Drive sırası: video_{ilk_numara} .. video_{ilk_numara + len(handofflar) - 1}", flush=True)

    teslim_edilen = 0
    for index, handoff in enumerate(handofflar, start=1):
        numara = ilk_numara + index - 1
        klasor = uret_bir(handoff, index)
        if kuru:
            print(f" KURU: video_{numara} üretildi; Telegram/Drive/tablo atlandı.", flush=True)
            continue
        bilgi = json.loads((klasor / "yayin_bilgisi.json").read_text(encoding="utf-8"))
        bilgi.update({
            "sahne_sayisi": 7,
            "video_numarasi": numara,
            "kaynak_video_id": handoff.get("source_video_id") or "",
            "analiz_kaniti": handoff.get("evidence") or "",
        })
        telegram_onay.gonder_onizleme(klasor / "final.mp4", klasor / "kapak.jpg", bilgi)
        kaynak_metni = kaynak or str(handoff.get("source_url") or "")
        if telegram_onay.bekle_ve_onayla(bekleme_sn):
            satir = short_teslim.teslim_et(drive, klasor, numara, kaynak_metni)
            print(f" ONAYLANDI: {satir['dosya']} -> baslik.xlsx", flush=True)
            teslim_edilen += 1
        else:
            print(f" ONAY GELMEDİ: video_{numara} kuyruğa alınmadı.", flush=True)
    print(f"ANALIZ-URET: {teslim_edilen}/{len(handofflar)} Short kuyruğa girdi.", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adet", type=int, default=2, help="Üretilecek Short sayısı")
    ap.add_argument("--analiz", default="yt_analiz.json")
    ap.add_argument("--onay-bekleme-sn", type=int, default=1800, help="Telegram onay süresi")
    ap.add_argument("--kaynak", default="", help="baslik.xlsx kaynak sütunu (boşsa analiz URL'si)")
    ap.add_argument("--kuru", action="store_true", help="Üret, ama Telegram/Drive/tablo yazma")
    args = ap.parse_args(argv)
    if args.adet < 1:
        raise SystemExit("adet en az 1 olmalı")
    return calistir(args.adet, args.analiz, args.onay_bekleme_sn, args.kaynak, kuru=args.kuru)


if __name__ == "__main__":
    raise SystemExit(main())
