"""Eski sablonlu kuyruk videolarini ydk_ etiketiyle yedek klasorune tasir.

187-204 ve 207-211 numarali video/kapaklar 'Arşiv/ydk_eski_sablon_<tarih>' klasorune
'ydk_video_N.mp4' / 'ydk_kapak_N.jpg' adlariyla tasinir; baslik.xlsx'teki satirlari
ARSIV sekmesine alinir. Boylece siradaki yayin 205 (yeni sablon, 097 Fatih) olur.
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import openpyxl  # noqa: E402
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload  # noqa: E402

import mpt_uret as teslim  # noqa: E402
import sheets_metadata as sm  # noqa: E402

OUT = ROOT / "result_fix"
ESKI = list(range(187, 205)) + list(range(207, 212))  # 205 = yeni sablon (097 Fatih)
KEEP = {"video_205.mp4", "kapak_205.jpg"}


def log(msg: str) -> None:
    print(msg, flush=True)


def list_all(drive, folder_id: str) -> list[dict]:
    items, token = [], None
    while True:
        res = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            pageSize=1000,
            fields="nextPageToken, files(id,name,mimeType,size)",
            **({"pageToken": token} if token else {}),
        ).execute()
        items.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            return items


def download(drive, file_id: str) -> bytes:
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def ensure_folder(drive, parent_id: str, name: str) -> str:
    q = (f"'{parent_id}' in parents and name = '{name}' "
         "and mimeType = 'application/vnd.google-apps.folder' and trashed = false")
    res = drive.files().list(q=q, pageSize=10, fields="files(id,name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    created = drive.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
        fields="id",
    ).execute()
    return created["id"]


def move_rename(drive, file_id: str, dest_id: str, src_id: str, new_name: str) -> None:
    drive.files().update(
        fileId=file_id, addParents=dest_id, removeParents=src_id, body={"name": new_name},
        fields="id,name,parents",
    ).execute()


def main() -> int:
    kuru = os.getenv("KURU", "true").strip().lower() in {"1", "true", "yes", "evet"}
    OUT.mkdir(parents=True, exist_ok=True)
    drive = teslim.drive_istemci()
    vfolder = sm.SHORTS_VIDEO_FOLDER_ID

    table_id = sm._find_primary_table(drive, sm.CEO_FOLDER_ID)
    if not table_id:
        raise SystemExit("baslik.xlsx bulunamadi")
    raw = download(drive, table_id)
    wb = openpyxl.load_workbook(io.BytesIO(raw))
    ws = next(s for s in wb.worksheets if s.title.strip().casefold() == "drive")
    hdr = [ws.cell(1, c).value for c in range(1, 12)]

    # on kontrol: 205 Fatih satiri tek ve duruyor
    fatih = [r for r in range(2, ws.max_row + 1)
             if str(ws.cell(r, 2).value or "").strip() == "video_205.mp4"
             and "Fatih" in str(ws.cell(r, 3).value or "")]
    if len(fatih) != 1:
        raise SystemExit(f"205 Fatih satiri tekil degil: {len(fatih)}")

    files = {f["name"]: f for f in list_all(drive, vfolder)}
    targets = []
    for n in ESKI:
        for name, prefix in ((f"video_{n}.mp4", "ydk_video_"), (f"kapak_{n}.jpg", "ydk_kapak_")):
            f = files.get(name)
            if f:
                targets.append((f, f"{prefix}{n}{Path(name).suffix}"))
    if not targets:
        raise SystemExit("Tasinacak eski dosya bulunamadi")

    row_nums = []
    for r in range(2, ws.max_row + 1):
        fname = str(ws.cell(r, 2).value or "").strip()
        if not fname.lower().endswith(".mp4"):
            continue
        digits = "".join(ch for ch in fname if ch.isdigit())
        if digits.isdigit() and int(digits) in ESKI and fname == f"video_{int(digits)}.mp4":
            row_nums.append(r)
    log(f"OK  tasinacak dosya: {len(targets)}, arsivlenecek satir: {len(row_nums)}")

    if kuru:
        log("KURU: yazma yapilmadi.")
        return 0

    now_tr = datetime.now(timezone(timedelta(hours=3)))
    arsiv_id = ensure_folder(drive, sm.CEO_FOLDER_ID, "Arşiv")
    ydk_id = ensure_folder(drive, arsiv_id, f"ydk_eski_sablon_{now_tr.strftime('%Y%m%d')}")
    log(f"OK  hedef klasor: Arşiv/ydk_eski_sablon_{now_tr.strftime('%Y%m%d')}")

    for f, new_name in targets:
        move_rename(drive, f["id"], ydk_id, vfolder, new_name)
    log(f"OK  {len(targets)} dosya ydk_ etiketiyle tasindi")

    # tablo: satirlari ARSIV'e al, sonra DRIVE'dan sil
    arsiv_ws = wb["ARSIV"] if "ARSIV" in wb.sheetnames else wb.create_sheet("ARSIV")
    if arsiv_ws.max_row == 1 and not arsiv_ws.cell(1, 1).value:
        for i, h in enumerate(hdr + ["Arşiv Nedeni", "Arşiv Tarihi"], start=1):
            arsiv_ws.cell(1, i).value = h
    for r in row_nums:
        rec = [ws.cell(r, c).value for c in range(1, 12)]
        nr = arsiv_ws.max_row + 1
        for i, v in enumerate(rec, start=1):
            arsiv_ws.cell(nr, i).value = v
        arsiv_ws.cell(nr, len(hdr) + 1).value = "eski sablon (ydk_ ile arsivlendi)"
        arsiv_ws.cell(nr, len(hdr) + 2).value = now_tr.strftime("%Y-%m-%d %H:%M")
    for r in sorted(row_nums, reverse=True):
        ws.delete_rows(r, 1)

    out = io.BytesIO()
    wb.save(out)
    new_bytes = out.getvalue()
    wb.close()
    drive.files().update(
        fileId=table_id,
        media_body=MediaIoBaseUpload(
            io.BytesIO(new_bytes),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resumable=False,
        ),
    ).execute()
    (OUT / "baslik_yeni.xlsx").write_bytes(new_bytes)
    log("OK  baslik.xlsx guncellendi")

    # dogrulama: kuyrukta yalnizca 205 kalmali
    wb2 = openpyxl.load_workbook(io.BytesIO(new_bytes), data_only=True)
    ws2 = wb2["DRIVE"]
    bekleyen = [str(ws2.cell(r, 2).value or "") for r in range(2, ws2.max_row + 1)
                if str(ws2.cell(r, 1).value or "").strip() == "BEKLEMEDE"]
    kalan = [f["name"] for f in list_all(drive, vfolder) if not f["mimeType"].endswith("folder")]
    log(f"OK  kalan BEKLEMEDE: {bekleyen}")
    log(f"OK  video klasoru: {sorted(kalan)}")
    report = {"tarih": now_tr.strftime("%Y-%m-%d %H:%M"), "tasinan_dosya": len(targets),
              "arsivlenen_satir": len(row_nums), "bekleyen": bekleyen, "klasor": sorted(kalan)}
    (OUT / "rapor.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
