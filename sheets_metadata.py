#!/usr/bin/env python3
"""
Bilgi Dozu (@bilgidozuofficial) — Google Drive & Excel (DRIVE Sekmesi) Metadata Eşleştirici
- Shorts kuyruğu kesin olarak video_31.mp4'ten başlar (video_1..video_30 korumalıdır).
- 'short' (video_XX.mp4) ve 'long' (uzun_video_XX.mp4) ayrımını destekler.
"""

import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import PatternFill

try:
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
except ImportError:
    MediaIoBaseDownload = MediaIoBaseUpload = None

log = logging.getLogger(__name__)

DEFAULT_DRIVE_FOLDER_ID = "1MBjwKp1DXoxLiCAkds84MowZAFMOK7Br"
DEFAULT_SHEETS_ID = "1DTXIt8wY9fDHRYRT_Kz5GVVcGe00hDaK"
MIN_SHORTS_NUMBER = 31  # 1..30 kilitli/atlandı, Shorts video_31.mp4'ten başlar

CATEGORY_MAP = {
    "uzay ve astronomi": "28",
    "fizik ve mühendislik": "28",
    "fizik ve bilim": "28",
    "tarih ve mühendislik": "28",
    "bilim ve teknoloji": "28",
    "uzun — bilim ve doğa": "28",
    "günlük hayat": "28",
    "beyin ve psikoloji": "27",
    "insan vücudu": "27",
    "doğa ve hayvanlar": "27",
    "biyoloji ve vücut": "27",
    "tarih ve arkeoloji": "27",
}


def is_long_filename(filename: str) -> bool:
    return os.path.basename(filename).lower().startswith("uzun_")


def extract_video_number(filename: str) -> int:
    nums = [int(n) for n in re.findall(r"\d+", os.path.basename(filename))]
    return nums[0] if nums else 999999


def natural_sort_key(filename: str) -> tuple:
    name = os.path.basename(filename).lower()
    is_long = 1 if is_long_filename(name) else 0
    return (is_long, extract_video_number(name), name)


def is_skipped_by_floor(filename: str) -> bool:
    name = os.path.basename(filename).lower()
    if name.startswith("video_") and extract_video_number(name) < MIN_SHORTS_NUMBER:
        return True
    if name in ("uzun_video_1.mp4", "uzun_video_2.mp4"):
        return True
    return False


def decide_prime_time_video_type(now_tr: Optional[datetime] = None) -> str:
    """
    Türkiye YouTube Prime Time Takvimi (UTC+3):
    - 14:00 TR (Öğle Kuşağı)   -> 'short' (1. Shorts)
    - 18:00 TR (Akşamüstü)     -> 'short' (2. Shorts)
    - 21:00 TR (Ana Prime Time)-> 1 gün arayla (çift günler) 'long' (Uzun Video), tek günler 'short' (3. Shorts)
    """
    tr_tz = timezone(timedelta(hours=3))
    dt = now_tr.astimezone(tr_tz) if now_tr else datetime.now(tr_tz)
    # 20:00 - 23:59 TR arası akşam ana Prime Time kuşağıdır
    if dt.hour >= 20:
        if dt.toordinal() % 2 == 0:
            return "long"
    return "short"


def sanitize_title(raw_title: str, max_len: int = 100) -> str:
    t = (raw_title or "").replace("<", "").replace(">", "").strip()
    if len(t) <= max_len:
        return t
    suffix = ""
    for tag in [" #bilgidozu #shorts", " #bilgidozu", " #shorts"]:
        if t.lower().endswith(tag):
            suffix = t[-len(tag):]
            t = t[:-len(tag)].rstrip()
            break
    budget = max_len - len(suffix)
    if len(t) > budget:
        cut = t[:budget].rsplit(" ", 1)[0]
        t = (cut if cut else t[:budget]).rstrip(" -·,:;!")
    return f"{t}{suffix}"[:max_len]


def parse_tags(raw_tags: str, max_chars: int = 450) -> list[str]:
    if not raw_tags:
        return ["bilgi dozu", "bilim", "ilginç bilgiler", "shorts"]
    parts = [p.strip().lstrip("#") for p in re.split(r"[,;\n]+", str(raw_tags)) if p.strip()]
    out, seen, total = [], set(), 0
    for p in parts:
        low = p.lower()
        if low in seen or not p:
            continue
        cost = len(p) + (3 if out else 2)
        if total + cost > max_chars:
            break
        seen.add(low)
        out.append(p)
        total += cost
    return out or ["bilgi dozu", "bilim", "shorts"]


def map_category_id(raw_cat: str, default_id: str = "27") -> str:
    c = (raw_cat or "").strip()
    if c in {"1", "2", "10", "15", "17", "19", "20", "22", "23", "24", "25", "26", "27", "28"}:
        return c
    low = c.lower()
    for k, v in CATEGORY_MAP.items():
        if k in low:
            return v
    return default_id


def parse_drive_sheet(xlsx_source) -> dict[str, dict]:
    wb = openpyxl.load_workbook(xlsx_source, data_only=True)
    ws = next((s for s in wb.worksheets if s.title.strip().casefold() == "drive"), wb.active)
    records = {}

    for r in range(2, ws.max_row + 1):
        status = str(ws.cell(r, 1).value or "").strip()
        fname = str(ws.cell(r, 2).value or "").strip()
        raw_title = str(ws.cell(r, 3).value or "").strip()
        if not fname or not fname.lower().endswith(".mp4"):
            continue
        desc = str(ws.cell(r, 4).value or "").strip()
        hashtags = str(ws.cell(r, 5).value or "").strip()
        raw_tags = str(ws.cell(r, 6).value or "").strip()
        pinned = str(ws.cell(r, 7).value or "").strip()
        raw_cat = str(ws.cell(r, 8).value or "").strip()
        source = str(ws.cell(r, 9).value or "").strip()

        full_desc = desc
        if pinned and pinned not in full_desc:
            full_desc = f"💬 {pinned}\n\n{full_desc}".strip()
        if source and "kaynak" not in full_desc.lower():
            full_desc = f"{full_desc}\n\n📚 Kaynak: {source}".strip()
        if hashtags and hashtags.split()[0].lower() not in full_desc.lower():
            full_desc = f"{full_desc}\n{hashtags}".strip()

        title = sanitize_title(raw_title) if raw_title else ""
        tags = parse_tags(raw_tags)
        cat_id = map_category_id(raw_cat)

        status_up = status.upper()
        is_done = (
            any(w in status_up for w in ("YÜKLENDİ", "YUKLENDI", "YAYINLANDI", "UPLOADED", "PUBLISHED", "TAMAM"))
            or is_skipped_by_floor(fname)
        )
        has_title = bool(title)

        records[fname] = {
            "row": r,
            "status": "YÜKLENDİ" if is_skipped_by_floor(fname) else (status or "BEKLEMEDE"),
            "file_name": fname,
            "title": title,
            "description": full_desc,
            "hashtags": hashtags,
            "tags": tags,
            "pinned_comment": pinned,
            "category_name": raw_cat,
            "categoryId": cat_id,
            "source": source,
            "is_long": is_long_filename(fname),
            "has_title": has_title,
            "is_ready": (not is_done) and has_title,
        }
    wb.close()
    return records


def _download_workbook_bytes_from_drive(drive, folder_id: str, sheets_id: str = DEFAULT_SHEETS_ID) -> Optional[tuple[io.BytesIO, str]]:
    if not drive or MediaIoBaseDownload is None:
        return None

    queries = []
    if folder_id:
        queries.append(
            f"'{folder_id}' in parents and trashed = false and "
            f"(name = 'bilgidozu_yukleme_tablosu.xlsx' or name = 'baslik.xlsx' or mimeType = 'application/vnd.google-apps.spreadsheet')"
        )
    queries.append(
        "trashed = false and (name = 'bilgidozu_yukleme_tablosu.xlsx' or name = 'baslik.xlsx')"
    )

    for q in queries:
        try:
            res = drive.files().list(
                q=q,
                pageSize=10,
                fields="files(id, name, mimeType, modifiedTime)",
            ).execute()
            files = res.get("files", [])
            if files:
                f = files[0]
                fid = f["id"]
                mime = f.get("mimeType", "")
                buf = io.BytesIO()
                if mime == "application/vnd.google-apps.spreadsheet":
                    req = drive.files().export_media(
                        fileId=fid,
                        mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                else:
                    req = drive.files().get_media(fileId=fid)
                dl = MediaIoBaseDownload(buf, req)
                done = False
                while not done:
                    _, done = dl.next_chunk()
                buf.seek(0)
                return buf, f.get("name", "Drive_XLSX")
        except Exception as e:
            log.warning(f"Drive tablo arama uyarısı ({q[:40]}...): {e}")

    if sheets_id:
        for method in ("export", "get"):
            try:
                buf = io.BytesIO()
                if method == "export":
                    req = drive.files().export_media(
                        fileId=sheets_id,
                        mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                else:
                    req = drive.files().get_media(fileId=sheets_id)
                dl = MediaIoBaseDownload(buf, req)
                done = False
                while not done:
                    _, done = dl.next_chunk()
                buf.seek(0)
                return buf, f"Sheets({sheets_id[:8]})"
            except Exception:
                continue

    return None


def load_table_from_drive_or_local(
    drive=None,
    folder_id: str = DEFAULT_DRIVE_FOLDER_ID,
    sheets_id: str = DEFAULT_SHEETS_ID,
    local_fallback: Optional[Path] = None,
) -> dict[str, dict]:
    base_records = {}
    base_dir = Path(__file__).parent
    for candidate in [
        local_fallback,
        base_dir / "bilgidozu_yukleme_tablosu.xlsx",
        base_dir / "baslik.xlsx",
        Path("/home/user/bilgidozu_yukleme_tablosu.xlsx"),
    ]:
        if candidate and Path(candidate).exists():
            try:
                base_records = parse_drive_sheet(candidate)
                break
            except Exception as e:
                log.warning(f"Yerel tablo okuma uyarısı ({candidate}): {e}")

    dl_res = _download_workbook_bytes_from_drive(drive, folder_id, sheets_id=sheets_id)
    if dl_res is not None:
        buf, src_name = dl_res
        try:
            drive_records = parse_drive_sheet(buf)
            for k, v in drive_records.items():
                if v.get("has_title") or k not in base_records:
                    base_records[k] = v
            log.info(f"Drive tablosu ({src_name}) yüklendi ve birleştirildi ({len(base_records)} satır).")
        except Exception as e:
            log.warning(f"Drive tablosu ayrıştırılamadı, yerel tablo kullanılacak: {e}")

    return base_records


def list_drive_videos(drive, folder_id: str) -> list[dict]:
    videos = []
    folders_to_visit = [folder_id]
    visited = set()

    while folders_to_visit:
        curr = folders_to_visit.pop(0)
        if curr in visited:
            continue
        visited.add(curr)

        page_token = None
        while True:
            res = drive.files().list(
                q=f"'{curr}' in parents and trashed = false",
                pageSize=200,
                fields="nextPageToken, files(id, name, mimeType, size)",
                **({"pageToken": page_token} if page_token else {}),
            ).execute()
            for f in res.get("files", []):
                mime = f.get("mimeType", "")
                name = f.get("name", "")
                if mime == "application/vnd.google-apps.folder":
                    folders_to_visit.append(f["id"])
                elif name.lower().endswith(".mp4") or "video/" in mime:
                    videos.append(f)
            page_token = res.get("nextPageToken")
            if not page_token:
                break

    videos.sort(key=lambda x: natural_sort_key(x.get("name", "")))
    return videos


def get_next_scheduled_video(
    drive,
    folder_id: str,
    skip_ids: set = None,
    sheets_id: str = DEFAULT_SHEETS_ID,
    local_xlsx: Optional[Path] = None,
    video_type: str = "auto",
) -> Optional[dict]:
    skip_ids = skip_ids or set()
    table = load_table_from_drive_or_local(drive, folder_id, sheets_id=sheets_id, local_fallback=local_xlsx)
    videos = list_drive_videos(drive, folder_id) if drive else []

    target_type = decide_prime_time_video_type() if video_type == "auto" else video_type

    def find_candidate(want_long: Optional[bool]) -> Optional[dict]:
        for v in videos:
            vid = v["id"]
            vname = v["name"]
            if is_skipped_by_floor(vname):
                continue
            if vid in skip_ids or vname in skip_ids:
                continue
            if want_long is not None and is_long_filename(vname) != want_long:
                continue
            meta = table.get(vname)
            if meta and not meta["is_ready"]:
                continue
            if meta:
                return {
                    "id": vid,
                    "name": vname,
                    "size": int(v.get("size", 0)),
                    "video": v,
                    "metadata": meta,
                    "title": meta["title"],
                    "description": meta["description"],
                    "tags": meta["tags"],
                    "categoryId": meta["categoryId"],
                    "pinned_comment": meta["pinned_comment"],
                    "row": meta["row"],
                    "video_type": "long" if is_long_filename(vname) else "short",
                }
        return None

    if target_type == "long":
        cand = find_candidate(want_long=True)
        if cand:
            return cand
        log.info("Sırada hazır uzun video bulunamadı, otomatik olarak sıradaki Shorts videosuna geçiliyor.")
        return find_candidate(want_long=False)
    elif target_type == "short":
        cand = find_candidate(want_long=False)
        if cand:
            return cand
        return find_candidate(want_long=True)
    else:
        return find_candidate(want_long=None)


def update_excel_status_in_drive(
    drive,
    folder_id: str,
    file_name: str,
    new_status: str = "YÜKLENDİ",
    youtube_url: str = "",
) -> bool:
    if not drive or not folder_id or MediaIoBaseDownload is None:
        return False
    try:
        res = drive.files().list(
            q=f"'{folder_id}' in parents and (name = 'bilgidozu_yukleme_tablosu.xlsx' or name = 'baslik.xlsx') and trashed = false",
            pageSize=1,
            fields="files(id, name)",
        ).execute()
        files = res.get("files", [])
        if not files:
            return False
        fid = files[0]["id"]
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=fid))
        done = False
        while not done:
            _, done = dl.next_chunk()
        buf.seek(0)
        wb = openpyxl.load_workbook(buf)
        ws = next((s for s in wb.worksheets if s.title.strip().casefold() == "drive"), wb.active)
        green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
        updated = False
        for r in range(2, ws.max_row + 1):
            if str(ws.cell(r, 2).value or "").strip().casefold() == file_name.casefold():
                ws.cell(r, 1).value = new_status
                if youtube_url:
                    ws.cell(r, 2).hyperlink = youtube_url
                for c in range(1, 10):
                    ws.cell(r, c).fill = green_fill
                updated = True
                break
        if not updated:
            return False
        out_buf = io.BytesIO()
        wb.save(out_buf)
        out_buf.seek(0)
        media = MediaIoBaseUpload(
            out_buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resumable=False,
        )
        drive.files().update(fileId=fid, media_body=media).execute()
        return True
    except Exception as e:
        log.warning(f"Drive XLSX güncellemesi atlandı (salt-okunur token olabilir, sorun değil): {e}")
        return False
