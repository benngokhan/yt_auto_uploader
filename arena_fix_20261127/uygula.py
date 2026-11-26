"""20261127 tek seferlik onarim.

Yaptigi isler (sirasiyla, hepsi on-kontrol gecerse):
  1. baslik.xlsx yedegini Drive'daki Arşiv klasorune koyar.
  2. 097 Fatih renderini (Drive'daki video_206.mp4, md5 dogrulanir) video_205.mp4
     olarak kopyalar; eski 205 taslagini ve artik dosyasi olmayan satirlari arsivler.
  3. kapak_205.jpg'yi depodaki dogrulanmis kapakla gunceller.
  4. Durumlari sadeleştirir: yalnizca YÜKLENDİ / BEKLEMEDE kalir.
  5. Yayinlanmis 176-186 dosyalarini ve deneme artiklarini Arşiv'e tasir.

KURU=true ise hicbir yazma yapmaz, sadece plani ve on-kontrol sonucunu yazar.
"""
from __future__ import annotations

import hashlib
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

import kapak_yukle  # noqa: E402
import mpt_uret as teslim  # noqa: E402
import sheets_metadata as sm  # noqa: E402

FATIH_MD5 = "5c660de021b9c2c93ef849db5d9f81f1"
FATIH_SIZE = 16974021
COVER_LOCAL = Path(__file__).with_name("kapak_205.jpg")
OUT = ROOT / "result_fix"

PHANTOM = {
    "bilgi_dozu_suda_parmaklar_neden_burusur_shorts.mp4",
    "video_173.mp4",
    "video_174.mp4",
    "video_175.mp4",
    "uzun_video_22.mp4",
}
PUBLISHED_TO_ARCHIVE = range(176, 187)  # 176..186 yayinlandi
JUNK_IN_CEO = [
    "bilgi_dozu_panel_motor_v2.zip",
    "deneme6.mp4",
    "deneme7.mp4",
    "deneme8.mp4",
    "kapanis_deneme.mp4",
    "kapanis_deneme2.mp4",
]
ALLOWED_STATUS = {"YÜKLENDİ", "BEKLEMEDE"}


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
    q = f"'{parent_id}' in parents and name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res = drive.files().list(q=q, pageSize=10, fields="files(id,name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    created = drive.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
        fields="id",
    ).execute()
    return created["id"]


def move(drive, file_id: str, dest_id: str, src_id: str) -> None:
    drive.files().update(
        fileId=file_id, addParents=dest_id, removeParents=src_id, fields="id,parents"
    ).execute()


def upload(drive, parent_id: str, name: str, data: bytes, mime: str) -> str:
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)
    created = drive.files().create(
        body={"name": name, "parents": [parent_id]}, media_body=media, fields="id"
    ).execute()
    return created["id"]


def read_rows(wb) -> list[dict]:
    ws = next((s for s in wb.worksheets if s.title.strip().casefold() == "drive"), None)
    if ws is None:
        raise SystemExit("DRIVE sekmesi yok")
    hdr = [ws.cell(1, c).value for c in range(1, 12)]
    rows = []
    for r in range(2, ws.max_row + 1):
        vals = [ws.cell(r, c).value for c in range(1, 12)]
        if not any(str(v or "").strip() for v in vals):
            continue
        rows.append({"row": r, "vals": vals, "file": str(vals[1] or "").strip(),
                     "status": str(vals[0] or "").strip(),
                     "title": str(vals[2] or "").strip(),
                     "link": str(vals[9] or "").strip()})
    return hdr, rows


def archive_reason(rec: dict) -> str:
    name = rec["file"]
    if name in PHANTOM:
        return "Drive'da dosyasi yok (hayalet satir)"
    if name == "video_206.mp4":
        return "video_206 dosyasi 097 Fatih renderi; 205'e tasindi"
    if name == "video_205.mp4" and "Fatih" not in rec["title"]:
        return "eski video_205 taslagi (mukerrer)"
    return ""


def main() -> int:
    kuru = os.getenv("KURU", "true").strip().lower() in {"1", "true", "yes", "evet"}
    OUT.mkdir(parents=True, exist_ok=True)
    drive = teslim.drive_istemci()

    table_id = sm._find_primary_table(drive, sm.CEO_FOLDER_ID)
    if not table_id:
        raise SystemExit("baslik.xlsx bulunamadi")
    raw = download(drive, table_id)
    wb = openpyxl.load_workbook(io.BytesIO(raw))
    hdr, rows = read_rows(wb)

    # ---------- on kontrol (yazma yok) ----------
    vfolder = sm.SHORTS_VIDEO_FOLDER_ID
    files = {f["name"]: f for f in list_all(drive, vfolder)}
    fatih_rows = [r for r in rows if r["file"] == "video_205.mp4" and "Fatih" in r["title"]]
    if len(fatih_rows) != 1:
        raise SystemExit(f"097 Fatih satiri tekil degil: {len(fatih_rows)}")

    v206 = files.get("video_206.mp4")
    v205 = files.get("video_205.mp4")
    if v206:
        if int(v206.get("size", 0)) != FATIH_SIZE:
            raise SystemExit(f"video_206 boyutu beklenmedik: {v206.get('size')}")
        md5 = hashlib.md5(download(drive, v206["id"])).hexdigest()
        if md5 != FATIH_MD5:
            raise SystemExit(f"video_206 md5 uyusmuyor: {md5}")
        log(f"OK  video_206.mp4 = 097 Fatih (md5 {md5})")
    elif v205 and int(v205.get("size", 0)) == FATIH_SIZE:
        log("OK  video_205.mp4 zaten Fatih renderi (kopya gerekmiyor)")
    else:
        raise SystemExit("Ne video_206.mp4 ne de dogru video_205.mp4 bulundu")

    if not COVER_LOCAL.exists():
        raise SystemExit(f"Kapak depoda yok: {COVER_LOCAL}")
    cover_bytes, cw, ch, cnote = kapak_yukle.prepare_image(COVER_LOCAL, "short")
    log(f"OK  kapak_205.jpg hazir: {cw}x{ch} {cnote}")

    to_archive = [r for r in rows if archive_reason(r)]
    kept = [r for r in rows if not archive_reason(r)]
    fatih = fatih_rows[0]
    log(f"OK  tablo: {len(rows)} satir, arsive {len(to_archive)} satir")
    for r in to_archive:
        log(f"    ARSIV r{r['row']}: {r['file']} ({r['status']})")

    # yeni durumlar
    for r in kept:
        if r["status"] == "PLANLANDI":
            r["status"] = "YÜKLENDİ"
        elif r["status"] in {"ASKIDA", "ASKIDA_TASLAK"}:
            r["status"] = "BEKLEMEDE"
        if r["status"] not in ALLOWED_STATUS:
            raise SystemExit(f"Beklenmeyen durum: r{r['row']} {r['status']!r}")
    names = [r["file"] for r in kept]
    if len(names) != len(set(names)):
        dup = sorted({n for n in names if names.count(n) > 1})
        raise SystemExit(f"Mukerrer dosya adi kaldi: {dup}")
    log(f"OK  kalan satir: {len(kept)} (YÜKLENDİ={sum(1 for r in kept if r['status']=='YÜKLENDİ')}, "
        f"BEKLEMEDE={sum(1 for r in kept if r['status']=='BEKLEMEDE')})")

    if kuru:
        log("KURU: yazma yapilmadi.")
        (OUT / "plan.json").write_text(json.dumps({
            "kuru": True, "arsiv": [r["file"] for r in to_archive],
            "fatih": fatih["file"], "satir": len(kept)}, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    # ---------- yazma ----------
    now_tr = datetime.now(timezone(timedelta(hours=3)))
    stamp = now_tr.strftime("%Y%m%d_%H%M")
    arsiv_id = ensure_folder(drive, sm.CEO_FOLDER_ID, "Arşiv")
    log(f"OK  Arşiv klasoru: {arsiv_id}")

    # 1) tablo yedegi
    yedek_adi = f"baslik_yedek_{stamp}.xlsx"
    upload(drive, arsiv_id, yedek_adi, raw,
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    (OUT / yedek_adi).write_bytes(raw)
    log(f"OK  tablo yedegi: Arşiv/{yedek_adi}")

    # 2) eski 205 taslagi -> Arşiv
    if v205 and int(v205.get("size", 0)) != FATIH_SIZE:
        move(drive, v205["id"], arsiv_id, vfolder)
        log("OK  eski video_205 taslagi Arşiv'e tasindi")

    # 3) 206 -> 205 (sunucu tarafinda kopya)
    if v206:
        copied = drive.files().copy(
            fileId=v206["id"],
            body={"name": "video_205.mp4", "parents": [vfolder]},
            fields="id,name,size",
        ).execute()
        log(f"OK  video_206 -> video_205 kopyalandi ({copied['id']})")
        move(drive, v206["id"], arsiv_id, vfolder)
        log("OK  video_206 Arşiv'e tasindi")

    # 4) kapak 205 guncelle
    cid, cstate = kapak_yukle.upsert_cover(drive, vfolder, "kapak_205.jpg", cover_bytes)
    log(f"OK  kapak_205.jpg {cstate} ({cid})")
    k206 = files.get("kapak_206.jpg")
    if k206:
        move(drive, k206["id"], arsiv_id, vfolder)
        log("OK  kapak_206.jpg Arşiv'e tasindi")

    # 5) yayinlanmis 176-186 + deneme artiklari
    moved = 0
    for n in PUBLISHED_TO_ARCHIVE:
        for name in (f"video_{n}.mp4", f"kapak_{n}.jpg"):
            f = files.get(name)
            if f:
                move(drive, f["id"], arsiv_id, vfolder)
                moved += 1
    ceo_files = {f["name"]: f for f in list_all(drive, sm.CEO_FOLDER_ID)}
    for name in JUNK_IN_CEO:
        f = ceo_files.get(name)
        if f:
            move(drive, f["id"], arsiv_id, sm.CEO_FOLDER_ID)
            moved += 1
    log(f"OK  {moved} dosya Arşiv'e tasindi")

    # 6) tabloyu yeniden yaz
    ws = next(s for s in wb.worksheets if s.title.strip().casefold() == "drive")
    arsiv_ws = wb["ARSIV"] if "ARSIV" in wb.sheetnames else wb.create_sheet("ARSIV")
    if arsiv_ws.max_row == 1 and not arsiv_ws.cell(1, 1).value:
        for i, h in enumerate(hdr + ["Arşiv Nedeni", "Arşiv Tarihi"], start=1):
            arsiv_ws.cell(1, i).value = h
    for rec in to_archive:
        r = arsiv_ws.max_row + 1
        for i, v in enumerate(rec["vals"], start=1):
            arsiv_ws.cell(r, i).value = v
        arsiv_ws.cell(r, len(hdr) + 1).value = archive_reason(rec)
        arsiv_ws.cell(r, len(hdr) + 2).value = now_tr.strftime("%Y-%m-%d %H:%M")

    # arsivlenen satirlari DRIVE'dan sil (alttan yukari)
    for rec in sorted(to_archive, key=lambda x: x["row"], reverse=True):
        ws.delete_rows(rec["row"], 1)

    # kalan satirlarin durumlarini guncelle
    kept_by_file = {r["file"]: r["status"] for r in kept}
    for r in range(2, ws.max_row + 1):
        name = str(ws.cell(r, 2).value or "").strip()
        if name in kept_by_file:
            ws.cell(r, 1).value = kept_by_file[name]

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

    report = {
        "zaman": now_tr.strftime("%Y-%m-%d %H:%M:%S"),
        "arsivlenen_satir": [{"row": r["row"], "file": r["file"], "neden": archive_reason(r)} for r in to_archive],
        "kalan_satir": len(kept),
        "yuklendi": sum(1 for r in kept if r["status"] == "YÜKLENDİ"),
        "beklemede": sum(1 for r in kept if r["status"] == "BEKLEMEDE"),
        "fatih": {"dosya": "video_205.mp4", "durum": "BEKLEMEDE"},
        "arsive_tasinan_dosya": moved,
        "tablo_yedek": f"Arşiv/{yedek_adi}",
    }
    (OUT / "rapor.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
