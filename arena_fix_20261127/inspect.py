"""Salt-okunur envanter: canlı baslik.xlsx + iki Drive klasörü."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mpt_uret as teslim  # noqa: E402
import sheets_metadata as sm  # noqa: E402

OUT = ROOT / "inspect"
FOLDERS = {
    "kuyruk": sm.CEO_FOLDER_ID,
    "video_kapak": sm.SHORTS_VIDEO_FOLDER_ID,
}


def inventory(drive, folder_id: str) -> list[dict]:
    items, token = [], None
    while True:
        res = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            pageSize=1000,
            fields="nextPageToken, files(id,name,mimeType,size,createdTime,parents)",
            **({"pageToken": token} if token else {}),
        ).execute()
        for f in res.get("files", []):
            items.append({
                "id": f["id"],
                "name": f.get("name", ""),
                "mimeType": f.get("mimeType", ""),
                "size": int(f.get("size", 0) or 0),
                "createdTime": f.get("createdTime", ""),
                "parents": f.get("parents", []),
            })
        token = res.get("nextPageToken")
        if not token:
            break
    return items


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    drive = teslim.drive_istemci()

    table_id = sm._find_primary_table(drive, sm.CEO_FOLDER_ID)
    dl = sm._download_workbook_bytes_from_drive(drive, sm.CEO_FOLDER_ID, sm.DEFAULT_SHEETS_ID)
    if dl:
        data, name = dl
        (OUT / "baslik_live.xlsx").write_bytes(data.getvalue())
        print("tablo:", table_id, name, len(data.getvalue()))

    table = sm.load_table_from_drive_or_local(drive, sm.CEO_FOLDER_ID, sheets_id=sm.DEFAULT_SHEETS_ID)
    rows = []
    for fname, rec in table.items():
        rows.append({
            "file": fname,
            "row": rec.get("row"),
            "status": rec.get("status"),
            "title": bool(rec.get("title")),
            "description": bool(rec.get("description")),
            "hashtags": bool(rec.get("hashtags")),
            "tags": bool(rec.get("tags")),
            "pinned": bool(rec.get("pinned_comment")),
            "category": rec.get("category_name", ""),
            "source": bool(rec.get("source")),
            "link": bool(rec.get("has_youtube_link")),
            "ready": bool(rec.get("is_ready")),
        })
    rows.sort(key=lambda r: sm.natural_sort_key(r["file"]))

    inv = {}
    for label, fid in FOLDERS.items():
        inv[label] = {"folder_id": fid, "items": inventory(drive, fid)}

    report = {
        "table_id": table_id,
        "row_count": len(rows),
        "status_counts": {},
        "rows": rows,
        "drive": inv,
    }
    for r in rows:
        report["status_counts"][r["status"]] = report["status_counts"].get(r["status"], 0) + 1
    (OUT / "inventory.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"table_id": table_id, "rows": len(rows),
                      "status_counts": report["status_counts"],
                      "drive_counts": {k: len(v["items"]) for k, v in inv.items()}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
