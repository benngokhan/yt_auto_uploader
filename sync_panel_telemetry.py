#!/usr/bin/env python3
"""Bilgi Dozu Admin Paneli — Canlı Telemetri, Drive Stok Envanteri ve Retansiyon Senkronizasyonu.

0 YouTube Data API kotası harcar. Google Drive'daki YOUTUBE_OTOMASYON alt klasörlerini
(CEO, Kısa Video/Video, Kısa Video/Kapak, Uzun Video/Video, Uzun Video/Kapak) ve
Bilgi_Dozu_Retansiyon_Raporu.xlsx dosyasını okuyarak panel_telemetry.json üretir.
"""
from __future__ import annotations

import io
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import openpyxl

from sheets_metadata import (
    CEO_FOLDER_ID,
    DEFAULT_SHEETS_ID,
    KNOWN_PUBLISHED_NAMES,
    LONG_COVER_FOLDER_ID,
    LONG_VIDEO_FOLDER_ID,
    MIN_LONG_NUMBER,
    MIN_SHORTS_NUMBER,
    SHORTS_COVER_FOLDER_ID,
    SHORTS_VIDEO_FOLDER_ID,
    YOUTUBE_OTOMASYON_FOLDER_ID,
    _download_workbook_bytes_from_drive,
    get_next_scheduled_video,
    is_skipped_by_floor,
    load_table_from_drive_or_local,
)
from uploader import get_google_clients, load_uploaded_ids

BASE_DIR = Path(__file__).resolve().parent
RETENTION_FOLDER_ID = "1gwtRBik2Dpvdz1VRaosBx9wokqT53Dzk"  # active.sav81@gmail.com / Retansiyon
RETENTION_REPORT_ID = "1EjCcuxkwdxRYTlQ60OLPWbo6CQWnh_cO"  # active.sav81@gmail.com / Bilgi_Dozu_Retansiyon_Raporu.xlsx
TELEMETRY_FILE = BASE_DIR / "panel_telemetry.json"


def _list_folder_files(drive, folder_id: str) -> list[dict]:
    if drive is None:
        return []
    out = []
    page_token = None
    while True:
        res = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            pageSize=100,
            pageToken=page_token,
            orderBy="name",
            fields="nextPageToken,files(id,name,mimeType,size,modifiedTime)",
        ).execute()
        for f in res.get("files", []):
            out.append({
                "id": f.get("id", ""),
                "name": f.get("name", ""),
                "mimeType": f.get("mimeType", ""),
                "size": int(f.get("size") or 0),
                "modifiedTime": f.get("modifiedTime", ""),
            })
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return out


def _parse_retention_workbook(raw_bytes: bytes) -> dict:
    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
    info = {}
    if "Rapor Bilgisi" in wb.sheetnames:
        ws = wb["Rapor Bilgisi"]
        for r in range(2, ws.max_row + 1):
            k = str(ws.cell(r, 1).value or "").strip()
            v = ws.cell(r, 2).value
            if k:
                info[k] = v

    metrics = []
    if "Video Metrikleri" in wb.sheetnames:
        ws = wb["Video Metrikleri"]
        for r in range(2, ws.max_row + 1):
            title = str(ws.cell(r, 1).value or "").strip()
            if not title:
                continue
            url = str(ws.cell(r, 10).value or "").strip()
            m_id = re.search(r"(?:youtu\.be/|v=|shorts/)([A-Za-z0-9_-]{11})", url)
            vid_id = m_id.group(1) if m_id else ""
            metrics.append({
                "title": title,
                "published_date": str(ws.cell(r, 2).value or ""),
                "duration_sec": float(ws.cell(r, 3).value or 0),
                "views": int(ws.cell(r, 4).value or 0),
                "avg_view_sec": float(ws.cell(r, 5).value or 0),
                "avg_view_pct": float(ws.cell(r, 6).value or 0),
                "watch_time_min": float(ws.cell(r, 7).value or 0),
                "hook_3s_pct": float(ws.cell(r, 8).value) if ws.cell(r, 8).value is not None else None,
                "curve_status": str(ws.cell(r, 9).value or ""),
                "url": url,
                "video_id": vid_id,
            })

    curves: dict[str, dict] = {}
    if "Eğri Verileri" in wb.sheetnames:
        ws = wb["Eğri Verileri"]
        for r in range(2, ws.max_row + 1):
            vtitle = str(ws.cell(r, 1).value or "").strip()
            vid = str(ws.cell(r, 2).value or "").strip()
            ratio = ws.cell(r, 3).value
            sec = ws.cell(r, 4).value
            pct = ws.cell(r, 5).value
            if not vid or ratio is None or pct is None:
                continue
            if vid not in curves:
                curves[vid] = {"video_id": vid, "title": vtitle, "points": []}
            curves[vid]["points"].append({
                "ratio": round(float(ratio) * 100, 1),
                "sec": round(float(sec or 0), 2),
                "pct": round(float(pct), 2),
            })

    # Attach hook_3s_pct from curves if missing in metrics
    for m in metrics:
        vid = m["video_id"]
        if m["hook_3s_pct"] is None and vid in curves and curves[vid]["points"]:
            pts = curves[vid]["points"]
            closest = min(pts, key=lambda p: abs(p["sec"] - 3.0))
            m["hook_3s_pct"] = closest["pct"]

    return {
        "info": info,
        "video_count": len(metrics),
        "curve_count": len(curves),
        "metrics": metrics,
        "curves": list(curves.values()),
    }


def _resolve_table_file_id(drive) -> str:
    """Ana yukleme tablosunun Drive dosya kimligini bulur (active.sav81@gmail.com / baslik.xlsx)."""
    try:
        resp = (
            drive.files()
            .list(
                q=f"'{CEO_FOLDER_ID}' in parents and trashed=false",
                fields="files(id,name,mimeType)",
                pageSize=100,
            )
            .execute()
        )
        files = resp.get("files", [])
        for f in files:
            if (f.get("name") or "").lower() == "baslik.xlsx":
                return f["id"]
        for f in files:
            name = (f.get("name") or "").lower()
            if name.startswith("bilgidozu") and name.endswith((".xlsx", ".xlsm")):
                return f["id"]
    except Exception as e:
        print(f"[telemetry] Tablo kimligi okunamadi: {e}")
    return DEFAULT_SHEETS_ID or ""


def cover_candidates(num: int, is_long: bool) -> list[str]:
    """Hazır kapak adayları — uploader.thumbnail_candidates ile AYNI sıra.

    Kapaklar .jpg / .png / .jpeg uzantılarıyla gelebiliyor (ör. kapak_164.jpeg).
    Eski kod yalnızca kapak_N.jpg aradığı için panelde yanlış "kapak eksik"
    uyarısı çıkıyordu.
    """
    if is_long:
        stems = (f"uzun_kapak_{num}", f"kapak_uzun_{num}")
        exts = ("png", "jpg", "jpeg")
    else:
        stems = (f"kapak_{num}", f"short_kapak_{num}")
        exts = ("jpg", "png", "jpeg")
    return [f"{stem}.{ext}" for stem in stems for ext in exts]


def pick_cover(cover_map: dict, num: int, is_long: bool) -> tuple[str, dict | None]:
    """(beklenen/mevcut kapak adı, Drive dosyası) — uzantıdan bağımsız eşleşme."""
    candidates = cover_candidates(num, is_long)
    for name in candidates:
        found = cover_map.get(name.lower())
        if found:
            return found["name"], found
    return candidates[0], None


def build_telemetry(drive=None, local_retention_xlsx: Path | None = None, push_table_to_drive: bool = False) -> dict:
    tr_now = datetime.now(timezone(timedelta(hours=3)))
    now_str = tr_now.strftime("%Y-%m-%d %H:%M:%S")

    # Sync workbook between GitHub and Drive (active.sav81@gmail.com / baslik.xlsx)
    if drive is not None:
        try:
            wb_baslik_path = BASE_DIR / "baslik.xlsx"
            wb_local_path = BASE_DIR / "bilgidozu_yukleme_tablosu.xlsx"
            src_push = wb_baslik_path if wb_baslik_path.exists() else wb_local_path
            if push_table_to_drive and src_push.exists():
                from googleapiclient.http import MediaFileUpload
                table_id = _resolve_table_file_id(drive)
                if not table_id:
                    raise RuntimeError("Yukleme tablosu Drive'da bulunamadi")
                media = MediaFileUpload(
                    str(src_push),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    resumable=False,
                )
                drive.files().update(fileId=table_id, media_body=media).execute()
                print(f"[telemetry] GitHub tablosu Drive'a yazildi (fileId={table_id}).")
            else:
                dl_wb = _download_workbook_bytes_from_drive(drive, CEO_FOLDER_ID)
                if dl_wb is not None:
                    raw_buf, _wb_name = dl_wb
                    raw_bytes = raw_buf.getvalue()
                    wb_baslik_path.write_bytes(raw_bytes)
                    wb_local_path.write_bytes(raw_bytes)
        except Exception as e:
            print(f"[telemetry] Drive tablo senkron uyarısı: {e}")

    shorts_videos = _list_folder_files(drive, SHORTS_VIDEO_FOLDER_ID) if drive else []
    shorts_covers = _list_folder_files(drive, SHORTS_COVER_FOLDER_ID) if drive else []
    long_videos = _list_folder_files(drive, LONG_VIDEO_FOLDER_ID) if drive else []
    long_covers = _list_folder_files(drive, LONG_COVER_FOLDER_ID) if drive else []

    # Bu kurulumda tüm klasör kimlikleri aynı klasörü gösteriyor (karışık klasör).
    # Dosyaları türüne göre ayır: resimler kapak, mp4'ler video. Böylece
    # kapak_N.jpg yanlışlıkla "video" sayılmıyor ve kapak eşleşmesi çalışıyor.
    def _ayir(video_list, cover_list):
        _v = [f for f in video_list
              if not str(f.get("mimeType", "")).startswith("image/")
              and not str(f.get("name", "")).lower().startswith(("kapak", "uzun_kapak", "short_kapak", "kapak_uzun"))]
        _c = [f for f in cover_list
              if str(f.get("mimeType", "")).startswith("image/")
              or str(f.get("name", "")).lower().startswith(("kapak", "uzun_kapak", "short_kapak", "kapak_uzun"))]
        return _v, _c

    def _tekil(lst):
        _g, _s = [], set()
        for f in lst:
            _k = str(f.get("id") or f.get("name"))
            if _k not in _s:
                _s.add(_k); _g.append(f)
        return _g

    shorts_videos, shorts_covers = _ayir(shorts_videos, shorts_covers)
    long_videos, long_covers = _ayir(long_videos, long_covers)
    # Aynı klasör olduğu için iki liste aynı; tekilleştir.
    shorts_videos = _tekil(shorts_videos)
    long_videos = [f for f in _tekil(long_videos)
                   if str(f.get("name", "")).lower().startswith("uzun_video_")
                   or str(f.get("name", "")).lower().startswith("long_video_")]
    _tum_kapaklar = _tekil(shorts_covers + long_covers)
    shorts_covers = [f for f in _tum_kapaklar
                     if not str(f.get("name", "")).lower().startswith(("uzun_kapak", "kapak_uzun", "long_"))]
    long_covers = [f for f in _tum_kapaklar
                   if str(f.get("name", "")).lower().startswith(("uzun_kapak", "kapak_uzun", "long_"))]
    ceo_files = _list_folder_files(drive, CEO_FOLDER_ID) if drive else []

    # Fallback to existing telemetry drive inventory if running offline
    if not shorts_videos and TELEMETRY_FILE.exists():
        try:
            prev = json.loads(TELEMETRY_FILE.read_text(encoding="utf-8"))
            inv = prev.get("drive_inventory", {})
            shorts_videos = inv.get("shorts_videos", [])
            shorts_covers = inv.get("shorts_covers", [])
            long_videos = inv.get("long_videos", [])
            long_covers = inv.get("long_covers", [])
            ceo_files = inv.get("ceo_files", [])
        except Exception:
            pass

    shorts_video_map = {f["name"].lower(): f for f in shorts_videos}
    shorts_cover_map = {f["name"].lower(): f for f in shorts_covers}
    long_video_map = {f["name"].lower(): f for f in long_videos}
    long_cover_map = {f["name"].lower(): f for f in long_covers}

    # drive=None verilirse fonksiyon Drive'a hiç bakmaz, repodaki BAYAT yerel
    # xlsx'i okur. Tablo mutlaka canlı Drive dosyasından okunmalı.
    if drive is not None:
        try:
            _, _tablo_adi = _download_workbook_bytes_from_drive(drive, CEO_FOLDER_ID)
            print(f"[telemetry] Canlı tablo okundu: {_tablo_adi}")
        except Exception as _te:
            print(f"[telemetry] Canlı tablo uyarısı: {_te}")
    records = load_table_from_drive_or_local(drive, CEO_FOLDER_ID)
    done_ids = load_uploaded_ids(BASE_DIR / "uploaded.txt")

    next_short = None
    next_long = None
    if drive is not None:
        try:
            next_short = get_next_scheduled_video(drive, CEO_FOLDER_ID, skip_ids=done_ids, video_type="short")
            next_long = get_next_scheduled_video(drive, CEO_FOLDER_ID, skip_ids=done_ids, video_type="long")
        except Exception:
            pass

    # Build enriched active queue items (Shorts >= 155, Long >= 8)
    queue_items = []
    for fname, rec in records.items():
        if is_skipped_by_floor(fname) and fname not in KNOWN_PUBLISHED_NAMES:
            continue
        is_long = bool(rec.get("is_long"))
        m_num = re.match(r"^(?:uzun_)?video_(\d+)\.mp4$", fname, re.IGNORECASE)
        num = int(m_num.group(1)) if m_num else 0
        if is_long and num < MIN_LONG_NUMBER:
            continue
        if not is_long and num < MIN_SHORTS_NUMBER:
            continue

        v_file = long_video_map.get(fname.lower()) if is_long else shorts_video_map.get(fname.lower())
        expected_cover, c_file = pick_cover(long_cover_map if is_long else shorts_cover_map, num, is_long)
        is_published = (
            rec.get("has_youtube_link")
            or fname in done_ids
            or fname in KNOWN_PUBLISHED_NAMES
            or str(rec.get("status", "")).upper() in ("YÜKLENDİ", "YUKLENDI", "PUBLISHED")
        )
        queue_items.append({
            "row": rec.get("row"),
            "file_name": fname,
            "number": num,
            "type": "long" if is_long else "short",
            "status": "YÜKLENDİ" if is_published else rec.get("status", "BEKLEMEDE"),
            "is_ready": bool(rec.get("is_ready")) and not is_published,
            "is_published": bool(is_published),
            "title": rec.get("title", ""),
            "description": rec.get("description", ""),
            "tags": rec.get("tags", []),
            "category_name": rec.get("category_name", ""),
            "pinned_comment": rec.get("pinned_comment", ""),
            "youtube_url": rec.get("youtube_url", ""),
            "has_drive_video": v_file is not None,
            "drive_video_id": v_file["id"] if v_file else "",
            "drive_video_size_mb": round(v_file["size"] / (1024 * 1024), 2) if v_file and v_file.get("size") else 0,
            "expected_cover": expected_cover,
            "has_drive_cover": c_file is not None,
            "drive_cover_id": c_file["id"] if c_file else "",
        })

    # ── Drive'da olup TABLODA OLMAYAN videolar da sayılır ─────────────────
    # Tablo kayması (satır BEKLEMEDE kalmış / hiç eklenmemiş) stoğu 0
    # gösteriyordu. Gerçek kaynak: Drive'daki dosya + uploaded.txt.
    def _num(ad):
        m = re.match(r"^(?:uzun_)?video_(\d+)\.mp4$", ad, re.IGNORECASE)
        return int(m.group(1)) if m else None

    _yayin_adlari = set()
    try:
        for _l in (BASE_DIR / "uploaded.txt").read_text(encoding="utf-8").splitlines():
            for _p in _l.split("|"):
                _p = _p.strip().lower()
                if _p.endswith(".mp4"):
                    _yayin_adlari.add(_p)
    except Exception:
        pass

    _var = {x["file_name"].lower() for x in queue_items}
    _eklenen = set(_var)  # aynı video iki kez eklenmesin (shorts ve long klasörü aynı olabiliyor)
    for _map, _uzun, _esik in ((shorts_video_map, False, MIN_SHORTS_NUMBER),
                               (long_video_map, True, MIN_LONG_NUMBER)):
        _covers = long_cover_map if _uzun else shorts_cover_map
        for ad, vf in list(_map.items()):
            if ad in _var or ad in _eklenen or not ad.endswith(".mp4"):
                continue
            n = _num(ad)
            if n is None or n < _esik:
                continue
            yayinda = (ad in done_ids or ad in _yayin_adlari
                       or ad in {k.lower() for k in KNOWN_PUBLISHED_NAMES})
            kapak, c_file = pick_cover(_covers, n, _uzun)
            _eklenen.add(ad)
            queue_items.append({
                "row": None,
                "file_name": ad,
                "number": n,
                "type": "long" if _uzun else "short",
                "status": "YÜKLENDİ" if yayinda else "TABLO DIŞI",
                "is_ready": (not yayinda) and (c_file is not None),
                "is_published": yayinda,
                "title": "", "description": "", "tags": [], "category_name": "",
                "pinned_comment": "", "youtube_url": "",
                "has_drive_video": True,
                "drive_video_id": vf["id"],
                "drive_video_size_mb": round(vf["size"] / (1024 * 1024), 2) if vf.get("size") else 0,
                "expected_cover": kapak,
                "has_drive_cover": c_file is not None,
                "drive_cover_id": c_file["id"] if c_file else "",
            })

    queue_items.sort(key=lambda x: (0 if x["type"] == "short" else 1, x["number"]))

    ready_shorts_queue = [x for x in queue_items if x["type"] == "short" and x["is_ready"] and x["has_drive_video"]]
    ready_long_queue = [x for x in queue_items if x["type"] == "long" and x["is_ready"] and x["has_drive_video"]]
    if next_short is None and ready_shorts_queue:
        next_short = {"name": ready_shorts_queue[0]["file_name"], "title": ready_shorts_queue[0]["title"], "row": ready_shorts_queue[0]["row"]}
    if next_long is None and ready_long_queue:
        next_long = {"name": ready_long_queue[0]["file_name"], "title": ready_long_queue[0]["title"], "row": ready_long_queue[0]["row"]}

    # Read ISCILER & UYARILAR from workbook (baslik.xlsx birincil kaynak)
    isciler_rows = []
    uyarilar_rows = []
    wb_path = BASE_DIR / "baslik.xlsx"
    if not wb_path.exists():
        wb_path = BASE_DIR / "bilgidozu_yukleme_tablosu.xlsx"
    if wb_path.exists():
        wb = openpyxl.load_workbook(wb_path, data_only=True)
        for sname in ("ISCILER", "İŞÇİLER"):
            if sname in wb.sheetnames:
                ws = wb[sname]
                for r in range(2, ws.max_row + 1):
                    wname = str(ws.cell(r, 1).value or "").strip()
                    if wname:
                        isciler_rows.append({
                            "row": r,
                            "name": wname,
                            "status": str(ws.cell(r, 2).value or ""),
                            "updated_at": str(ws.cell(r, 3).value or ""),
                            "error_message": str(ws.cell(r, 4).value or ""),
                            "jobs_done": ws.cell(r, 5).value,
                            "last_action": str(ws.cell(r, 6).value or ""),
                        })
                break
        if "UYARILAR" in wb.sheetnames:
            ws = wb["UYARILAR"]
            for r in range(2, ws.max_row + 1):
                u_title = str(ws.cell(r, 1).value or "").strip()
                if u_title:
                    uyarilar_rows.append({
                        "row": r,
                        "title": u_title,
                        "status": str(ws.cell(r, 2).value or ""),
                        "updated_at": str(ws.cell(r, 3).value or ""),
                        "detail": str(ws.cell(r, 4).value or ""),
                    })

    # Retention report
    retention_data = {}
    ret_bytes = None
    if local_retention_xlsx and local_retention_xlsx.exists():
        ret_bytes = local_retention_xlsx.read_bytes()
    elif drive is not None:
        try:
            from googleapiclient.http import MediaIoBaseDownload
            buf = io.BytesIO()
            req = drive.files().get_media(fileId=RETENTION_REPORT_ID)
            dl = MediaIoBaseDownload(buf, req)
            done = False
            while not done:
                _, done = dl.next_chunk()
            ret_bytes = buf.getvalue()
        except Exception as e:
            print(f"[telemetry] Retansiyon raporu indirme uyarısı: {e}")

    if ret_bytes:
        try:
            retention_data = _parse_retention_workbook(ret_bytes)
        except Exception as e:
            print(f"[telemetry] Retansiyon parse uyarısı: {e}")
    elif TELEMETRY_FILE.exists():
        try:
            retention_data = json.loads(TELEMETRY_FILE.read_text(encoding="utf-8")).get("retention", {})
        except Exception:
            pass

    missing_covers = [
        x["file_name"] for x in queue_items
        if not x["is_published"] and x["has_drive_video"] and not x["has_drive_cover"]
    ]

    payload = {
        "generated_at": now_str,
        "generated_at_iso": tr_now.isoformat(),
        "folders": {
            "youtube_otomasyon": YOUTUBE_OTOMASYON_FOLDER_ID,
            "ceo": CEO_FOLDER_ID,
            "table_file_id": _resolve_table_file_id(drive) if drive else "",
            "shorts_video": SHORTS_VIDEO_FOLDER_ID,
            "shorts_cover": SHORTS_COVER_FOLDER_ID,
            "long_video": LONG_VIDEO_FOLDER_ID,
            "long_cover": LONG_COVER_FOLDER_ID,
            "retention_folder": RETENTION_FOLDER_ID,
            "retention_report": RETENTION_REPORT_ID,
        },
        "schedule_rules": {
            "daily_slots_tr": ["19:30"],
            "prewarm_tr": ["19:12"],
            "watchdog_tr": ["19:50", "20:00"],
            "friday_1930": "short",
            "other_days": "short",
            "shorts_only": True,
            "min_shorts_number": MIN_SHORTS_NUMBER,
            "min_long_number": MIN_LONG_NUMBER,
            "cover_fallback_generation": False,
            "crosspost_enabled": False,
        },
        "queue_summary": {
            "ready_shorts": len(ready_shorts_queue),
            "ready_longs": 0,
            "total_ready": len(ready_shorts_queue),
            "days_of_stock": len(ready_shorts_queue),
            "next_short": next_short["name"] if next_short else None,
            "next_short_title": next_short.get("title", "") if next_short else "",
            "next_long": None,
            "next_long_title": "",
            "missing_covers": [m for m in missing_covers if not m.lower().startswith("uzun_")],
        },
        "drive_inventory": {
            "shorts_videos": shorts_videos,
            "shorts_covers": shorts_covers,
            "long_videos": long_videos,
            "long_covers": long_covers,
            "ceo_files": ceo_files,
        },
        "active_queue": queue_items,
        "isciler": isciler_rows,
        "uyarilar": uyarilar_rows,
        "retention": retention_data,
    }
    TELEMETRY_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    import sys
    push_table = "--push-table-to-drive" in sys.argv
    drive = None
    if (BASE_DIR / "token.json").exists():
        try:
            _, drive = get_google_clients()
        except Exception as e:
            print(f"[telemetry] Drive istemcisi açılamadı, yerel mod kullanılıyor: {e}")
    local_ret = Path("/home/user/google_drive/Bilgi_Dozu_Retansiyon_Raporu.xlsx")
    data = build_telemetry(
        drive=drive,
        local_retention_xlsx=local_ret if local_ret.exists() else None,
        push_table_to_drive=push_table,
    )
    qs = data["queue_summary"]
    print(
        f"[telemetry] panel_telemetry.json güncellendi: "
        f"Hazır={qs['total_ready']} ({qs['ready_shorts']} Shorts, {qs['ready_longs']} Uzun) · "
        f"Sıradaki Short={qs['next_short']} · Sıradaki Uzun={qs['next_long']} · "
        f"Eksik Kapak={qs['missing_covers']} · Retansiyon Video={data.get('retention', {}).get('video_count', 0)}"
    )


if __name__ == "__main__":
    main()
