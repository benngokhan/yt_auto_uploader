#!/usr/bin/env python3
"""Onaylanan Short'u teslim eder: Drive video_<N> + kapak_<N>, baslik.xlsx satırı.

Yayın yapmaz. Yalnızca kullanıcı Telegram'da 'onayladım' dedikten sonra çağrılır.
Numara, canlı Drive klasöründeki son videodan (şu an 193) bir sonraki alınır.
"""
from __future__ import annotations

import json
from pathlib import Path

import mpt_uret
from sheets_metadata import SHORTS_COVER_FOLDER_ID

ZORUNLU_ALANLAR = ("baslik", "aciklama", "hashtag", "etiketler", "sabit_yorum", "kategori")


class TeslimHatasi(RuntimeError):
    pass


def hazirla_satir(metadata: dict, dosya_adi: str, kaynak: str | None = None) -> dict:
    """yayin_bilgisi.json -> baslik.xlsx satırı. Boş alan varsa teslim durur."""
    if not isinstance(metadata, dict):
        raise TeslimHatasi("Yayın bilgisi JSON nesnesi değil")
    satir = {}
    for anahtar in ZORUNLU_ALANLAR:
        deger = str(metadata.get(anahtar) or "").strip()
        if not deger:
            raise TeslimHatasi(f"Yayın bilgisinde {anahtar} boş; tabloya yazılmadı")
        satir[anahtar] = deger
    satir["dosya"] = str(dosya_adi or "").strip()
    satir["kaynak"] = str(kaynak if kaynak is not None else (metadata.get("kaynak") or "")).strip()
    if not satir["dosya"]:
        raise TeslimHatasi("Video dosya adı boş")
    return satir


def _kapak_yukle(drive, yol: Path, hedef_ad: str) -> None:
    from googleapiclient.http import MediaFileUpload

    medya = MediaFileUpload(str(yol), mimetype="image/jpeg", resumable=True)
    drive.files().create(
        body={"name": hedef_ad, "parents": [SHORTS_COVER_FOLDER_ID]},
        media_body=medya, fields="id,name",
    ).execute()


def teslim_et(drive, klasor: str | Path, numara: int, kaynak: str | None = None) -> dict:
    kok = Path(klasor).resolve()
    video, kapak, meta_yolu = kok / "final.mp4", kok / "kapak.jpg", kok / "yayin_bilgisi.json"
    for dosya in (video, kapak, meta_yolu):
        if not dosya.is_file() or dosya.stat().st_size == 0:
            raise TeslimHatasi(f"Teslim dosyası eksik/boş: {dosya.name}")
    if not isinstance(numara, int) or numara < 1:
        raise TeslimHatasi("Geçersiz video numarası")
    try:
        metadata = json.loads(meta_yolu.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TeslimHatasi("Yayın bilgisi okunamadı") from exc

    satir = hazirla_satir(metadata, f"video_{numara}.mp4", kaynak)
    mpt_uret.drive_yukle(drive, video, satir["dosya"])
    _kapak_yukle(drive, kapak, f"kapak_{numara}.jpg")
    yazildi = mpt_uret.tablo_satir_ekle(
        drive, satir["dosya"], satir["baslik"], satir["aciklama"], satir["hashtag"],
        satir["etiketler"], satir["sabit_yorum"], satir["kategori"], satir["kaynak"],
    )
    if not yazildi:
        raise TeslimHatasi("baslik.xlsx satırı yazılamadı; video Drive'da kaldı")
    return satir
