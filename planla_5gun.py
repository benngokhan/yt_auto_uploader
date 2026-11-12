#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Arena 5 Günlük Gözlem Serisi — YouTube Studio Planlayıcı & Yayın Sonrası Refakatçi
- video_177..181 bölümlerini doğrudan YouTube Studio'ya 'Planlandı' (private + publishAt)
  olarak 13–17 Kasım 2026 her akşam 19:30 TR (16:30 UTC) saatlerine hazırlar ve dikey 9:16
  kapaklarını (kapak_177..181.jpg) uygular.
- slot_claims.txt + uploaded.txt + baslik.xlsx (DRIVE + 1_HAFTA_GOZLEM sekmesi) kilitlerini
  işleyerek 13–17 Kasım boyunca çifte yüklemeyi önler; 18 Kasım 19:30 TR'de video_182.mp4 ile
  normal akış kesintisiz devam eder.
- companion modu:
  1) Sabah 11:08 TR (kota sıfırlaması sonrası): gece kotaya takılan kapak/video kalmışsa tamamlar.
  2) Akşam 19:32 TR (planlı yayın açıldıktan 2 dk sonra): o gün yayına giren videonun
     ilk/sabit yorumunu atar, oynatma listesine ekler, baslik.xlsx durumunu PLANLANDI -> YÜKLENDİ
     yapar ve Telegram VIP yayın kartını gönderir.
"""

from __future__ import annotations

import html
import io
import json
import os
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from sheets_metadata import (
    CEO_FOLDER_ID,
    DEFAULT_SHEETS_ID,
    SHORTS_VIDEO_FOLDER_ID,
    parse_drive_sheet,
    sanitize_title,
)
from uploader import (
    build_telegram_report,
    download_drive_file,
    ensure_named_playlist,
    add_video_to_series,
    get_google_clients,
    post_pinned_comment,
    route_short_topic,
    sanitize_public_description,
    sync_kartal_status_report,
    upload_to_youtube,
)
import sync_panel_telemetry

PLAN_FILE = BASE_DIR / "scheduled_5day_plan.json"
GOZLEM_JSON = BASE_DIR / "gozlem_1hafta_baz.json"
SLOT_CLAIMS_FILE = BASE_DIR / "slot_claims.txt"
UPLOADED_FILE = BASE_DIR / "uploaded.txt"
BASLIK_FILE = BASE_DIR / "baslik.xlsx"
MIRROR_FILE = BASE_DIR / "bilgidozu_yukleme_tablosu.xlsx"

DEFAULT_ITEMS = [
    {
        "num": 177,
        "file_name": "video_177.mp4",
        "cover_name": "kapak_177.jpg",
        "slot_key": "2026-11-13T16:30Z",
        "publish_at_utc": "2026-11-13T16:30:00Z",
        "publish_at_tr": "13.11.2026 19:30",
        "short_tr": "13.11 19:30",
        "day_label": "1. Gün · Cuma",
        "drive_video_id": "1bdsvCJYiMe6vbW63SmvmgsGF6thL6gY9",
        "drive_cover_id": "1xu3Ut3tDkqe8AH5mlXUi9LW16_oWklTT",
        "duration_sec": 33.58,
        "cut1_sec": 2.45,
        "hook_focus": "Günlük nesne X-ray merakı (Şarj adaptörü 220V->5V 100kHz)",
    },
    {
        "num": 178,
        "file_name": "video_178.mp4",
        "cover_name": "kapak_178.jpg",
        "slot_key": "2026-11-14T16:30Z",
        "publish_at_utc": "2026-11-14T16:30:00Z",
        "publish_at_tr": "14.11.2026 19:30",
        "short_tr": "14.11 19:30",
        "day_label": "2. Gün · Cumartesi",
        "drive_video_id": "1_-uIwwDBHwTVEi93emA5uNhnWKlKr92l",
        "drive_cover_id": "1JiHS6bnfapm38-5Jh_-vB2qHxI62Hfy5",
        "duration_sec": 32.44,
        "cut1_sec": 2.43,
        "hook_focus": "Anlık bedensel test (Yutkununca kulaktan gelen östaki klik sesi)",
    },
    {
        "num": 179,
        "file_name": "video_179.mp4",
        "cover_name": "kapak_179.jpg",
        "slot_key": "2026-11-15T16:30Z",
        "publish_at_utc": "2026-11-15T16:30:00Z",
        "publish_at_tr": "15.11.2026 19:30",
        "short_tr": "15.11 19:30",
        "day_label": "3. Gün · Pazar",
        "drive_video_id": "1juGBBFXpXjcpRS-wOh3SJRTZLGEnaJ2O",
        "drive_cover_id": "1295Ejotic5noYyqtORBNa4fzRs0sDFC9",
        "duration_sec": 32.01,
        "cut1_sec": 2.45,
        "hook_focus": "Sezgi karşıtı fizik (Bıçak 5.5 çizemez, kuvars kumu 7.0 çizer)",
    },
    {
        "num": 180,
        "file_name": "video_180.mp4",
        "cover_name": "kapak_180.jpg",
        "slot_key": "2026-11-16T16:30Z",
        "publish_at_utc": "2026-11-16T16:30:00Z",
        "publish_at_tr": "16.11.2026 19:30",
        "short_tr": "16.11 19:30",
        "day_label": "4. Gün · Pazartesi",
        "drive_video_id": "1S0Gp-tizsF2DPoO6bySDEQA90AGq3CG7",
        "drive_cover_id": "1XitiQAC4Os2U1y3l2bIKvwjYXoxnocS4",
        "duration_sec": 32.76,
        "cut1_sec": 2.45,
        "hook_focus": "Evrensel uyku deneyimi (İlk gece etkisi: sol yarımküre nöbette)",
    },
    {
        "num": 181,
        "file_name": "video_181.mp4",
        "cover_name": "kapak_181.jpg",
        "slot_key": "2026-11-17T16:30Z",
        "publish_at_utc": "2026-11-17T16:30:00Z",
        "publish_at_tr": "17.11.2026 19:30",
        "short_tr": "17.11 19:30",
        "day_label": "5. Gün · Salı",
        "drive_video_id": "1OYL3gF2ArpjxZFNXZpCL6JR8LHbWAykL",
        "drive_cover_id": "1fADnR77LLzgQeNctk5clAy6bmYz-Pe82",
        "duration_sec": 31.95,
        "cut1_sec": 2.45,
        "hook_focus": "Görsel mutfak fiziği (200°C+ Leidenfrost görünmez buhar yastığı)",
    },
]

BASELINE_SNAPSHOT = {
    "captured_at_tr": "12.11.2026 23:10",
    "window_plan_tr": "13.11.2026 19:30 — 19.11.2026 23:59 (5 Gün Yayın + 48s Gözlem = 1 Hafta)",
    "channel_subscribers_before": 77,
    "channel_total_views_before": 51391,
    "channel_published_videos_before": 97,
    "mature_shorts_count": 80,
    "shorts_avg_views_all80": 498.5,
    "shorts_median_views_all80": 406.0,
    "shorts_last10_avg_views": 602.9,
    "shorts_last10_median_views": 592.5,
    "shorts_last10_avg_likes": 11.5,
    "shorts_avg_duration_sec_before": 42.02,
    "shorts_avg_view_sec_before": 20.70,
    "shorts_avg_view_pct_before": 51.24,
    "arena_cohort_avg_duration_sec": 32.55,
    "arena_targets": {
        "avg_view_pct_target": "72% - 95%+",
        "swiped_vs_viewed_target": ">= 68% İzlenme (Viewed)",
        "views_per_short_48h_target": ">= 1.000+ (baz 498 -> >=2x)",
    },
}


def _load_or_init_plan() -> dict:
    if PLAN_FILE.exists():
        data = json.loads(PLAN_FILE.read_text(encoding="utf-8"))
        if data.get("items"):
            return data
    items = []
    for it in DEFAULT_ITEMS:
        row = dict(it)
        row.update({
            "youtube_video_id": "",
            "youtube_url": "",
            "studio_url": "",
            "title": "",
            "uploaded": False,
            "thumbnail_ok": False,
            "playlist_ok": False,
            "comment_posted": False,
            "published_confirmed": False,
        })
        items.append(row)
    data = {
        "cohort": "Arena_5Gun_Strateji_Serisi_177_181",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "resume_regular_queue_at": "2026-11-18T16:30Z (video_182.mp4)",
        "baseline": BASELINE_SNAPSHOT,
        "items": items,
    }
    PLAN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _save_plan(plan: dict) -> None:
    PLAN_FILE.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    GOZLEM_JSON.write_text(
        json.dumps(
            {
                "baseline": plan.get("baseline", BASELINE_SNAPSHOT),
                "cohort_items": plan.get("items", []),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _send_telegram(payload: dict) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[telegram] Token veya chat_id yok; mesaj atlandı.")
        return False
    body = dict(payload)
    body["chat_id"] = chat_id
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        ok = bool(res.get("ok"))
        print(f"[telegram] Gönderim durumu: ok={ok}")
        return ok
    except Exception as e:
        print(f"[telegram] Uyarı: {type(e).__name__}")
        return False


def _audit_channel_uploads(youtube) -> tuple[dict[str, str], list[dict]]:
    """Yalnız 3 birim kota harcayarak son 25 yüklemeyi tarar:
    - Başlığı eşleşen video zaten yüklendiyse tekrar yüklememek için {norm_title: video_id} döner.
    - Kanalda halihazırda başka 'Planlandı' (private + publishAt) video varsa listeler.
    """
    existing_by_title: dict[str, str] = {}
    other_scheduled: list[dict] = []
    ch = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = ch.get("items", [])
    if not items:
        return existing_by_title, other_scheduled
    uploads_pl = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    pl = youtube.playlistItems().list(part="contentDetails", playlistId=uploads_pl, maxResults=25).execute()
    vids = [it["contentDetails"]["videoId"] for it in pl.get("items", []) if it.get("contentDetails", {}).get("videoId")]
    if not vids:
        return existing_by_title, other_scheduled
    vr = youtube.videos().list(part="snippet,status", id=",".join(vids)).execute()
    for v in vr.get("items", []):
        vid = v["id"]
        title = (v.get("snippet", {}).get("title") or "").strip()
        st = v.get("status", {})
        existing_by_title[sanitize_title(title).casefold()] = vid
        if st.get("privacyStatus") == "private" and st.get("publishAt"):
            other_scheduled.append({
                "id": vid,
                "title": title,
                "publishAt": st.get("publishAt"),
            })
    return existing_by_title, other_scheduled


def _resolve_drive_ids_if_needed(drive, plan: dict) -> None:
    res = drive.files().list(
        q=f"'{SHORTS_VIDEO_FOLDER_ID}' in parents and trashed=false",
        pageSize=200,
        fields="files(id,name)",
    ).execute()
    by_name = {f["name"]: f["id"] for f in res.get("files", [])}
    for it in plan["items"]:
        if it["file_name"] in by_name:
            it["drive_video_id"] = by_name[it["file_name"]]
        if it["cover_name"] in by_name:
            it["drive_cover_id"] = by_name[it["cover_name"]]


def _set_cover_direct(youtube, drive, cover_id: str, cover_name: str, video_id: str) -> bool:
    from googleapiclient.http import MediaFileUpload

    with tempfile.TemporaryDirectory(prefix="arena5-cov-") as td:
        cpath = Path(td) / cover_name
        download_drive_file(drive, cover_id, cpath)
        with Image.open(cpath) as im:
            fmt = im.format
            w, h = im.size
            if not (0.53 <= (w / h) <= 0.60):
                raise RuntimeError(f"Kapak 9:16 değil: {w}x{h}")
        mime = "image/png" if fmt == "PNG" else "image/jpeg"
        media = MediaFileUpload(str(cpath), mimetype=mime, resumable=False)
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    return True


def _sync_locks_and_workbook(drive, plan: dict) -> None:
    """slot_claims.txt, uploaded.txt ve baslik.xlsx (DRIVE + 1_HAFTA_GOZLEM) dosyalarını günceller."""
    # 1) slot_claims.txt & uploaded.txt
    existing_claims = set()
    if SLOT_CLAIMS_FILE.exists():
        existing_claims = {
            ln.strip() for ln in SLOT_CLAIMS_FILE.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        }
    existing_up_text = UPLOADED_FILE.read_text(encoding="utf-8") if UPLOADED_FILE.exists() else ""
    now_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    claims_to_add = []
    up_lines_to_add = []
    for it in plan["items"]:
        if not it.get("uploaded") or not it.get("youtube_video_id"):
            continue
        sk = it["slot_key"]
        if sk not in existing_claims:
            claims_to_add.append(sk)
            existing_claims.add(sk)
        if f"| {it['file_name']} |" not in existing_up_text and f"SLOT={sk}" not in existing_up_text:
            up_lines_to_add.append(
                f"{it['drive_video_id']} | {it['file_name']} | {it['youtube_url']} | "
                f"{now_utc_str} | {it['title']} | SLOT={sk}"
            )

    if claims_to_add:
        with SLOT_CLAIMS_FILE.open("a", encoding="utf-8") as fh:
            for sk in claims_to_add:
                fh.write(sk + "\n")
    if up_lines_to_add:
        with UPLOADED_FILE.open("a", encoding="utf-8") as fh:
            for ln in up_lines_to_add:
                fh.write(ln + "\n")

    # 2) Drive'dan canlı baslik.xlsx indir (yoksa yereli kullan)
    if drive is not None:
        from googleapiclient.http import MediaIoBaseDownload
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=DEFAULT_SHEETS_ID, supportsAllDrives=True))
        done = False
        while not done:
            _, done = dl.next_chunk()
        BASLIK_FILE.write_bytes(buf.getvalue())

    wb = openpyxl.load_workbook(BASLIK_FILE)
    ws = wb["DRIVE"]

    blue_fill = PatternFill(start_color="CFE2F3", end_color="CFE2F3", fill_type="solid")
    blue_bold = Font(name="Calibri", size=10, bold=True, color="073763")
    blue_font = Font(name="Calibri", size=10, bold=False, color="073763")
    green_fill = PatternFill(start_color="B6D7A8", end_color="B6D7A8", fill_type="solid")
    green_bold = Font(name="Calibri", size=10, bold=True, color="0B3B17")
    green_font = Font(name="Calibri", size=10, bold=False, color="0B3B17")

    by_fname = {it["file_name"]: it for it in plan["items"]}
    for r in range(2, ws.max_row + 1):
        fn = str(ws.cell(r, 2).value or "").strip()
        if fn not in by_fname:
            continue
        it = by_fname[fn]
        if not it.get("uploaded") or not it.get("youtube_url"):
            continue
        if it.get("published_confirmed"):
            ws.cell(r, 1).value = "YÜKLENDİ"
            ws.cell(r, 10).value = it["youtube_url"]
            ws.cell(r, 11).value = it["publish_at_tr"]
            for c in range(1, 14):
                ws.cell(r, c).fill = green_fill
                ws.cell(r, c).font = green_bold if c in (1, 2) else green_font
        else:
            ws.cell(r, 1).value = f"PLANLANDI · {it['short_tr']}"
            ws.cell(r, 10).value = it["youtube_url"]
            ws.cell(r, 11).value = f"{it['publish_at_tr']} (Planlandı)"
            for c in range(1, 14):
                ws.cell(r, c).fill = blue_fill
                ws.cell(r, c).font = blue_bold if c in (1, 2) else blue_font

    # 3) 1_HAFTA_GOZLEM sekmesini oluştur / güncelle (DRIVE her zaman ilk/aktif sekme kalır!)
    sheet_title = "1_HAFTA_GOZLEM"
    if sheet_title in wb.sheetnames:
        del wb[sheet_title]
    gs = wb.create_sheet(title=sheet_title)
    hdr_fill = PatternFill(start_color="1C2541", end_color="1C2541", fill_type="solid")
    hdr_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    sub_fill = PatternFill(start_color="E9EEF6", end_color="E9EEF6", fill_type="solid")
    sub_font = Font(name="Calibri", size=10, bold=True, color="1C2541")
    thin = Side(border_style="thin", color="CBD5E1")
    bdr = Border(left=thin, right=thin, top=thin, bottom=thin)

    gs["A1"] = "BİLGİ DOZU — 1 HAFTALIK ARENA STRATEJİ GÖZLEM PANELİ (13 KASIM – 19 KASIM 2026)"
    gs["A1"].font = Font(name="Calibri", size=13, bold=True, color="FFFFFF")
    gs["A1"].fill = hdr_fill
    gs.merge_cells("A1:K1")

    base = plan.get("baseline", BASELINE_SNAPSHOT)
    gs["A3"] = "BAZ METRİK (TEST ÖNCESİ — 12.11.2026)"
    gs["B3"] = "BAZ DEĞER"
    gs["C3"] = "ARENA 5 GÜNLÜK HEDEF"
    gs["D3"] = "STRATEJİK FARK"
    for col_l in ("A", "B", "C", "D"):
        gs[f"{col_l}3"].fill = sub_fill
        gs[f"{col_l}3"].font = sub_font
        gs[f"{col_l}3"].border = bdr

    base_rows = [
        ("Kanal Abone / Toplam İzlenme", f"{base['channel_subscribers_before']} abone / {base['channel_total_views_before']:,} izlenme", "Organik abone ivmesi", "3D Takip Et kartı + ikili yorum sorusu"),
        ("Mevcut Shorts Ort. İzlenme (80 Video)", f"{base['shorts_avg_views_all80']} (medyan {base['shorts_median_views_all80']})", ">= 1.000+ izlenme / video", "Jargonsuz günlük fiziksel deneyim kancası"),
        ("Son 10 Shorts Ort. İzlenme", f"{base['shorts_last10_avg_views']} (medyan {base['shorts_last10_median_views']})", ">= 1.000+ izlenme / video", "0.14s ses girişi + ~2.45s ilk görsel kesim"),
        ("Shorts Ort. Süre -> Ort. İzlenme %", f"{base['shorts_avg_duration_sec_before']} sn -> %{base['shorts_avg_view_pct_before']}", "32.5 sn -> %75 - %95+", "Sıkı 32-33 sn kurgu + Türkçe bilimsel şema"),
    ]
    for idx_b, br in enumerate(base_rows, start=4):
        for ci, val in enumerate(br, start=1):
            cell = gs.cell(idx_b, ci, value=val)
            cell.border = bdr
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    cols = [
        "Gün", "Dosya", "Planlanan Yayın (TR)", "Durum", "Video Başlığı",
        "Süre / İlk Kesim", "YouTube Linki", "Studio Düzenleme Linki",
        "48s İzlenme", "Geçilme vs İzlenme %", "Ort. İzlenme %",
    ]
    for ci, cname in enumerate(cols, start=1):
        c = gs.cell(10, ci, value=cname)
        c.fill = hdr_fill
        c.font = hdr_font
        c.border = bdr
        c.alignment = Alignment(horizontal="center", vertical="center")

    for r_offset, it in enumerate(plan["items"], start=11):
        st_txt = (
            "YAYINDA ✅" if it.get("published_confirmed")
            else ("YOUTUBE'DA PLANLANDI 🗓️" if it.get("uploaded") else "KUYRUKTA ⏳")
        )
        vals = [
            it["day_label"],
            it["file_name"],
            it["publish_at_tr"],
            st_txt,
            it.get("title") or "",
            f"{it['duration_sec']}s / {it['cut1_sec']}s",
            it.get("youtube_url") or "—",
            it.get("studio_url") or "—",
            "",
            "",
            "",
        ]
        for ci, v in enumerate(vals, start=1):
            cell = gs.cell(r_offset, ci, value=v)
            cell.border = bdr
            cell.alignment = Alignment(vertical="center", wrap_text=(ci == 5))

    widths = [18, 16, 20, 24, 52, 16, 30, 38, 14, 20, 16]
    for ci, w in enumerate(widths, start=1):
        col_letter = openpyxl.utils.get_column_letter(ci)
        gs.column_dimensions[col_letter].width = w

    # KRİTİK: stats_views.py wb.active okuduğu için aktif sekme her zaman DRIVE (index 0) kalır!
    wb.active = wb.sheetnames.index("DRIVE")
    wb.save(BASLIK_FILE)
    wb.save(MIRROR_FILE)
    wb.close()

    if drive is not None:
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(
            str(BASLIK_FILE),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resumable=False,
        )
        drive.files().update(fileId=DEFAULT_SHEETS_ID, media_body=media, supportsAllDrives=True).execute()
        print(f"[baslik.xlsx] Drive ({DEFAULT_SHEETS_ID}) ve yerel kopyalar güncellendi.")


def run_schedule() -> None:
    plan = _load_or_init_plan()
    youtube, drive = get_google_clients()
    _resolve_drive_ids_if_needed(drive, plan)

    existing_by_title, other_scheduled = _audit_channel_uploads(youtube)
    if other_scheduled:
        print(f"[denetim] Kanalda mevcut planlı videolar görüldü: {other_scheduled}")
    else:
        print("[denetim] Kanalda bekleyen başka planlı video yok — önü tamamen açık.")

    # Drive baslik.xlsx'ten tam metadata oku
    records = parse_drive_sheet(BASLIK_FILE)

    # AŞAMA 1: ÖNCE 5 VİDEONUN TAMAMINI YOUTUBE STUDIO'YA PLANLI (publishAt) YÜKLE (5 x 1600 = 8000 birim)
    quota_hit = False
    for it in plan["items"]:
        fn = it["file_name"]
        rec = records.get(fn)
        if not rec:
            raise RuntimeError(f"baslik.xlsx içinde {fn} kaydı bulunamadı!")
        it["title"] = rec["title"]

        if it.get("uploaded") and it.get("youtube_video_id"):
            print(f"[planla] {fn} zaten planlanmış: {it['youtube_url']} ({it['publish_at_tr']})")
            continue

        norm_t = sanitize_title(rec["title"]).casefold()
        if norm_t in existing_by_title:
            vid_id = existing_by_title[norm_t]
            it["youtube_video_id"] = vid_id
            it["youtube_url"] = f"https://youtu.be/{vid_id}"
            it["studio_url"] = f"https://studio.youtube.com/video/{vid_id}/edit"
            it["uploaded"] = True
            _save_plan(plan)
            print(f"[planla] {fn} kanalda zaten mevcut, eşleştirildi: {it['youtube_url']}")
            continue

        meta = {
            "title": rec["title"],
            "description": sanitize_public_description(rec["description"]),
            "tags": rec["tags"],
            "categoryId": rec["categoryId"],
            "privacyStatus": "private",
            "publishAt": it["publish_at_utc"],
        }
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tmp_mp4 = Path(tf.name)
        try:
            print(f"[planla] İndiriliyor ve YouTube'a planlanıyor: {fn} -> {it['publish_at_tr']} TR ({it['publish_at_utc']})...")
            download_drive_file(drive, it["drive_video_id"], tmp_mp4)
            resp = upload_to_youtube(youtube, tmp_mp4, meta)
            vid_id = resp["id"]
            it["youtube_video_id"] = vid_id
            it["youtube_url"] = f"https://youtu.be/{vid_id}"
            it["studio_url"] = f"https://studio.youtube.com/video/{vid_id}/edit"
            it["uploaded"] = True
            _save_plan(plan)
            print(f"  [OK] {fn} YouTube Studio'da PLANLANDI -> {it['youtube_url']} | Yayın: {it['publish_at_tr']} TR")
        except Exception as e:
            if "quotaExceeded" in str(e):
                quota_hit = True
                print(f"  [KOTA SINIRI] {fn} yüklemesinde günlük 10.000 birim kotası doldu; sabah 11:08 TR sıfırlamasında otomatik tamamlanacak.")
                break
            raise
        finally:
            tmp_mp4.unlink(missing_ok=True)

    # AŞAMA 2: 9:16 ÖZEL KAPAKLARI UYGULA (5 x 50 = 250 birim)
    if not quota_hit:
        for it in plan["items"]:
            if not it.get("uploaded") or not it.get("youtube_video_id") or it.get("thumbnail_ok"):
                continue
            try:
                _set_cover_direct(youtube, drive, it["drive_cover_id"], it["cover_name"], it["youtube_video_id"])
                it["thumbnail_ok"] = True
                _save_plan(plan)
                print(f"  [KAPAK OK] {it['cover_name']} -> {it['youtube_video_id']}")
            except Exception as e:
                if "quotaExceeded" in str(e):
                    quota_hit = True
                    print(f"  [KAPAK KOTA] {it['cover_name']} günlük kota sınırına takıldı; sabah 11:08 TR'de otomatik uygulanacak.")
                    break
                print(f"  [KAPAK UYARI] {it['cover_name']}: {e}")

    # AŞAMA 3: Kilitleri, baslik.xlsx'i ve telemetriyi senkronla
    _save_plan(plan)
    _sync_locks_and_workbook(drive, plan)
    sync_panel_telemetry.build_telemetry(drive=drive, push_table_to_drive=False)

    # AŞAMA 4: Telegram 5 Günlük Planlama Özeti Kartı
    lines = [
        "🗓️ <b>BİLGİ DOZU · 5 GÜNLÜK GÖZLEM SERİSİ YOUTUBE'DA PLANLANDI!</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for it in plan["items"]:
        if it.get("uploaded"):
            cov_badge = "🖼️ Kapak Hazır" if it.get("thumbnail_ok") else "⏳ Kapak 11:08 TR"
            lines.append(
                f"✅ <b>{html.escape(it['day_label'])} ({it['short_tr']})</b>\n"
                f"🎬 {html.escape(it['title'][:68])}\n"
                f"🔗 {it['youtube_url']} · <i>{cov_badge}</i>"
            )
        else:
            lines.append(
                f"⏳ <b>{html.escape(it['day_label'])} ({it['short_tr']})</b> — Kota sıfırlamasında (11:08 TR) otomatik planlanacak"
            )
    lines.append(
        "\n📌 <i>Her akşam 19:32 TR'de yayına giren videonun sabit yorumu ve topluluk metni otomatik gönderilecek; "
        "18 Kasım'da sıra otomatik video_182.mp4'ten devam edecek.</i>"
    )
    _send_telegram({
        "text": "\n\n".join(lines[:2]) + "\n\n" + "\n\n".join(lines[2:]),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })


def run_companion() -> None:
    """Sabah 11:08 TR (eksik plan/kapak/liste tamamlama) + Akşam 19:32 TR (yayın sonrası yorum & bildirim)."""
    if not PLAN_FILE.exists():
        print("[companion] scheduled_5day_plan.json yok; çıkış.")
        return
    plan = _load_or_init_plan()
    now_utc = datetime.now(timezone.utc)

    needs_upload_or_cover = any((not it.get("uploaded")) or (not it.get("thumbnail_ok")) for it in plan["items"])
    due_for_live_post = []
    for it in plan["items"]:
        if not it.get("uploaded") or not it.get("youtube_video_id") or it.get("comment_posted"):
            continue
        pub_dt = datetime.strptime(it["publish_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if now_utc >= pub_dt - timedelta(minutes=2):
            due_for_live_post.append((pub_dt, it))

    if not needs_upload_or_cover and not due_for_live_post:
        print("[companion] Tamamlanacak eksik veya yayına yeni girmiş planlı video yok (0 API çağrısı).")
        return

    youtube, drive = get_google_clients()
    _resolve_drive_ids_if_needed(drive, plan)
    records = parse_drive_sheet(BASLIK_FILE)
    changed = False

    # 1) Eksik upload veya kapak varsa tamamla
    if needs_upload_or_cover:
        for it in plan["items"]:
            fn = it["file_name"]
            rec = records.get(fn) or {}
            if not it.get("uploaded"):
                meta = {
                    "title": rec["title"],
                    "description": sanitize_public_description(rec["description"]),
                    "tags": rec["tags"],
                    "categoryId": rec["categoryId"],
                    "privacyStatus": "private",
                    "publishAt": it["publish_at_utc"],
                }
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
                    tmp_mp4 = Path(tf.name)
                try:
                    download_drive_file(drive, it["drive_video_id"], tmp_mp4)
                    resp = upload_to_youtube(youtube, tmp_mp4, meta)
                    vid_id = resp["id"]
                    it["youtube_video_id"] = vid_id
                    it["youtube_url"] = f"https://youtu.be/{vid_id}"
                    it["studio_url"] = f"https://studio.youtube.com/video/{vid_id}/edit"
                    it["title"] = rec["title"]
                    it["uploaded"] = True
                    changed = True
                finally:
                    tmp_mp4.unlink(missing_ok=True)
            if it.get("uploaded") and not it.get("thumbnail_ok"):
                try:
                    _set_cover_direct(youtube, drive, it["drive_cover_id"], it["cover_name"], it["youtube_video_id"])
                    it["thumbnail_ok"] = True
                    changed = True
                    print(f"[companion] Eksik kapak tamamlandı: {it['cover_name']} -> {it['youtube_video_id']}")
                except Exception as e:
                    print(f"[companion] Kapak uyarısı ({it['cover_name']}): {e}")

    # 2) Yayına yeni açılan videonun ilk yorumunu + oynatma listesini + Telegram kartını işle
    for pub_dt, it in due_for_live_post:
        wait_s = (pub_dt + timedelta(seconds=65) - datetime.now(timezone.utc)).total_seconds()
        if 0 < wait_s <= 180:
            print(f"[companion] {it['file_name']} tam yayına geçmesi için {int(wait_s)}s bekleniyor...")
            time.sleep(wait_s)

        vid_id = it["youtube_video_id"]
        vr = youtube.videos().list(part="status", id=vid_id).execute()
        vitems = vr.get("items", [])
        priv = vitems[0]["status"].get("privacyStatus") if vitems else ""
        if priv != "public":
            print(f"[companion] {it['file_name']} henüz public değil (durum={priv}); sonraki çalışmada tekrar denenecek.")
            continue

        rec = records.get(it["file_name"]) or {}
        comment_ok, _ = post_pinned_comment(youtube, vid_id, rec.get("pinned_comment", ""))
        if not it.get("playlist_ok"):
            konu = route_short_topic(rec.get("title", ""), rec.get("category_name", ""))
            if konu:
                pid = ensure_named_playlist(youtube, konu)
                add_video_to_series(youtube, vid_id, pid)
            it["playlist_ok"] = True

        it["comment_posted"] = True
        it["published_confirmed"] = True
        changed = True

        build_telegram_report(
            it["file_name"],
            vid_id,
            it["youtube_url"],
            rec,
            comment_ok,
            thumbnail_ok=it.get("thumbnail_ok", True),
            thumbnail_saved=True,
        )
        payload_f = BASE_DIR / "last_upload_payload.json"
        if payload_f.exists():
            _send_telegram(json.loads(payload_f.read_text(encoding="utf-8")))

        sync_kartal_status_report(
            youtube,
            it["file_name"],
            it["youtube_url"],
            thumbnail_ok=it.get("thumbnail_ok", True),
            thumbnail_saved=True,
            comment_ok=comment_ok,
            drive=drive,
            queue_folder=CEO_FOLDER_ID,
        )

    if changed:
        _save_plan(plan)
        _sync_locks_and_workbook(drive, plan)
        sync_panel_telemetry.build_telemetry(drive=drive, push_table_to_drive=False)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "companion"
    if mode == "schedule":
        run_schedule()
    elif mode == "companion":
        run_companion()
    else:
        raise SystemExit(f"Bilinmeyen komut: {mode}")
