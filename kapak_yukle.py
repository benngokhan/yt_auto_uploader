#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Panelden gelen kapağı Drive'a kanonik adla yazar (ve gerekirse YouTube'a hemen uygular).

Kural: kapak yalnızca Drive'daki hazır dosyadan gelir (worker asla üretmez).
Bu araç o tek adımı panelle yapılabilir hale getirir:

  python kapak_yukle.py --tip short --no 155 --dosya kapak_gelen/kapak_155.jpg
  python kapak_yukle.py --tip short --no 155 --dosya kapak_gelen/x.jpg --video-id MgpEXhYe2-8
  python kapak_yukle.py --tip short --no 155 --dosya ... --temizle   # aynı numaralı eski/artık varyantları çöpe at

Kanonik adlar (uploader.py thumbnail_candidates ile birebir):
  short -> kapak_<no>.jpg      (aynı zamanda short_kapak_<no>.* kabul edilir)
  long  -> uzun_kapak_<no>.jpg (aynı zamanda kapak_uzun_<no>.* kabul edilir)

Çıktı: kapak_sonuc.json (panel bu dosyayı okuyup sonucu gösterir).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).parent
RESULT_FILE = BASE_DIR / "kapak_sonuc.json"

SHORTS_COVER_FOLDER_ID = "1xleUU8CO3gsJVCnZMtYxtf2r0hs2yDKS"
LONG_COVER_FOLDER_ID = "1g3QluGyaLByQgXmoXO0i1PPtr3ORjRQR"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/drive",
]

YT_LIMIT = 2 * 1024 * 1024  # YouTube kapak sınırı: 2 MB
TARGET = {"short": (1080, 1920), "long": (1920, 1080)}
RATIO_RANGE = {"short": (0.53, 0.60), "long": (1.65, 1.90)}


def log(msg: str) -> None:
    print(msg, flush=True)


def clients():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token = BASE_DIR / "token.json"
    if not token.exists():
        raise FileNotFoundError("token.json bulunamadı (GOOGLE_TOKEN_JSON secret'ı yazılmalı).")
    creds = Credentials.from_authorized_user_file(str(token))
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError("Google token geçersiz ve yenilenemedi.")
    return build("youtube", "v3", credentials=creds), build("drive", "v3", credentials=creds)


def canonical_name(tip: str, no: str) -> str:
    return f"kapak_{no}.jpg" if tip == "short" else f"uzun_kapak_{no}.jpg"


def prepare_image(src, tip: str) -> tuple[bytes, int, int, str]:
    """Path veya dosya-benzeri kaynağı doğrula, 2 MB altı JPEG'e çevir."""
    with Image.open(src) as im:
        im.load()
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        ratio = w / h
        lo, hi = RATIO_RANGE[tip]
        if not lo <= ratio <= hi:
            tw, th = TARGET[tip]
            raise ValueError(
                f"Oran hatalı: {w}x{h} ({ratio:.2f}). {tip} için {lo}-{hi} aralığı gerekli "
                f"(hedef {tw}x{th})."
            )
        if w < 640 or h < 640:
            raise ValueError(f"Çözünürlük düşük: {w}x{h}. En az 720p kısa kenar önerilir.")

        quality = 92
        data = b""
        while quality >= 70:
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
            data = buf.getvalue()
            if len(data) <= YT_LIMIT:
                break
            quality -= 6
        note = f"{w}x{h} JPEG q{quality} · {len(data)/1024:.0f} KB"
        if len(data) > YT_LIMIT:
            raise ValueError(f"Kapak 2 MB altına indirilemedi ({len(data)/1024:.0f} KB).")
        return data, w, h, note


def download_drive_file(drive, file_id: str) -> tuple[io.BytesIO, str]:
    """Drive'daki hazır kapağı belleğe indir; telefona indirme/yükleme gerekmez."""
    from googleapiclient.http import MediaIoBaseDownload

    meta = drive.files().get(fileId=file_id, fields="id,name,mimeType,size").execute()
    if not str(meta.get("mimeType", "")).startswith("image/"):
        raise ValueError("Seçilen Drive dosyası görsel değil.")
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return buf, meta.get("name", file_id)


def find_existing(drive, folder_id: str, name: str):
    q = f"'{folder_id}' in parents and name='{name}' and trashed=false"
    res = drive.files().list(q=q, pageSize=10, fields="files(id,name,size)").execute()
    files = res.get("files", [])
    return files[0] if files else None


def upsert_cover(drive, folder_id: str, name: str, data: bytes):
    from googleapiclient.http import MediaIoBaseUpload

    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="image/jpeg", resumable=False)
    mevcut = find_existing(drive, folder_id, name)
    if mevcut:
        drive.files().update(fileId=mevcut["id"], media_body=media).execute()
        return mevcut["id"], "güncellendi"
    meta = {"name": name, "parents": [folder_id], "mimeType": "image/jpeg"}
    created = drive.files().create(body=meta, media_body=media, fields="id").execute()
    return created["id"], "oluşturuldu"


def cleanup_variants(drive, folder_id: str, no: str, keep_name: str) -> list[str]:
    """Aynı numaranın kanonik olmayan varyantlarını (kapak_155_yeni.jpg gibi) çöpe atar."""
    import re

    pattern = re.compile(rf"^(kapak|short_kapak|uzun_kapak|kapak_uzun)_?{re.escape(no)}(?!\d)", re.I)
    q = f"'{folder_id}' in parents and trashed=false"
    res = drive.files().list(q=q, pageSize=1000, fields="files(id,name)").execute()
    trashed = []
    for f in res.get("files", []):
        ad = f.get("name", "")
        if ad.lower() == keep_name.lower():
            continue
        if pattern.match(ad) and re.search(r"\.(jpe?g|png)$", ad, re.I):
            drive.files().update(fileId=f["id"], body={"trashed": True}).execute()
            trashed.append(ad)
    return trashed


def apply_to_youtube(youtube, video_id: str, data: bytes) -> str:
    from googleapiclient.http import MediaIoBaseUpload

    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="image/jpeg", resumable=False)
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    return "YouTube kapak isteği kabul edildi"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tip", choices=["short", "long"], required=True)
    ap.add_argument("--no", required=True, help="Video numarası (ör. 155)")
    ap.add_argument("--dosya", default="", help="Repo içindeki kapak yolu")
    ap.add_argument("--drive-id", default="", help="Drive'dan seçilen hazır kapağın dosya ID'si")
    ap.add_argument("--video-id", default="", help="Yayınlanmış videoya hemen uygula")
    ap.add_argument("--temizle", action="store_true", help="Aynı numaralı eski varyantları çöpe at")
    args = ap.parse_args()

    no = str(args.no).strip()
    if not no.isdigit():
        log("HATA: --no sayı olmalı")
        return 2
    if bool(args.dosya) == bool(args.drive_id):
        log("HATA: --dosya veya --drive-id seçeneklerinden yalnız biri verilmeli")
        return 2

    result = {
        "zaman": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tip": args.tip,
        "no": no,
        "video_id": args.video_id,
        "ok": False,
        "adimlar": [],
    }
    try:
        youtube, drive = clients()
        if args.drive_id:
            kaynak, kaynak_adi = download_drive_file(drive, args.drive_id)
            result["kaynak"] = f"Drive: {kaynak_adi}"
            result["adimlar"].append(f"Drive'dan seçildi: {kaynak_adi}")
        else:
            kaynak = Path(args.dosya)
            if not kaynak.is_absolute():
                kaynak = BASE_DIR / kaynak
            if not kaynak.exists():
                raise FileNotFoundError(f"Dosya yok: {kaynak}")
        data, w, h, note = prepare_image(kaynak, args.tip)
        result["boyut"] = note
        log(f"Kapak hazır: {note}")
        folder = SHORTS_COVER_FOLDER_ID if args.tip == "short" else LONG_COVER_FOLDER_ID
        ad = canonical_name(args.tip, no)
        file_id, islem = upsert_cover(drive, folder, ad, data)
        result["drive_ad"] = ad
        result["drive_id"] = file_id
        result["adimlar"].append(f"Drive: {ad} ({islem})")
        log(f"Drive: {ad} ({islem}) id={file_id}")

        if args.temizle:
            trashed = cleanup_variants(drive, folder, no, ad)
            result["silinen"] = trashed
            if trashed:
                result["adimlar"].append("Çöpe atıldı: " + ", ".join(trashed))
                log("Çöpe atıldı: " + ", ".join(trashed))

        if args.video_id:
            mesaj = apply_to_youtube(youtube, args.video_id, data)
            result["adimlar"].append(mesaj + f" ({args.video_id})")
            log(mesaj + f" ({args.video_id})")

        result["ok"] = True
        log("SONUÇ: BAŞARILI")
        return 0
    except Exception as e:
        result["hata"] = str(e)
        log(f"SONUÇ: HATA — {e}")
        return 1
    finally:
        RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
