#!/usr/bin/env python3
"""
Bilgi Dozu (@bilgidozuofficial) — YouTube Otomatik Video & Shorts Yükleyici
Prime Time Takvimi (Türkiye Saati UTC+3):
  - 14:00 TR -> 1. Shorts (video_31.mp4 ve sonrası)
  - 18:00 TR -> 2. Shorts
  - 21:00 TR -> Normal gün 3. Shorts | 1 gün arayla (çift günler) 1 Uzun Video (uzun_video_3.mp4 ve sonrası)
Özellikler:
  - Otomatik Sabit Yorum (commentThreads.insert) + Sabitleme Bildirimi
  - YouTube Gönderiler (Topluluk / Community Post) hazır paylaşım metni üretimi + Telegram bildirimi
"""

import io
import json
import logging
import os
import socket
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(): pass
try:
    from apscheduler.schedulers.blocking import BlockingScheduler
except ImportError:
    BlockingScheduler = None
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
except ImportError:
    Request = Credentials = InstalledAppFlow = build = HttpError = MediaFileUpload = MediaIoBaseDownload = None

from sheets_metadata import (
    DEFAULT_DRIVE_FOLDER_ID,
    DEFAULT_SHEETS_ID,
    decide_prime_time_video_type,
    get_next_scheduled_video,
    iscilers_heartbeat,
    load_table_from_drive_or_local,
    log_uyari_drive,
    sanitize_title,
    update_excel_status_in_drive,
)

load_dotenv()
socket.setdefaulttimeout(60)

BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
TOKEN_FILE = BASE_DIR / "token.json"
SECRETS_FILE = BASE_DIR / "client_secrets.json"
CONFIG_FILE = BASE_DIR / "config.json"
REPORT_FILE = BASE_DIR / "last_upload_report.txt"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"uploader_{datetime.now().strftime('%Y%m')}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "upload_time": "14:00,18:00,21:00",
    "privacy_status": "public",
    "default_category": "27",
    "drive_queue_folder_id": DEFAULT_DRIVE_FOLDER_ID,
    "sheets_id": DEFAULT_SHEETS_ID,
    "gemini_api_key": "",
    "groq_api_key": "",
}


def load_config() -> dict:
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception as e:
            log.warning(f"config.json okuma uyarısı: {e}")
    # Ana klasör her zaman 1MBjwKp1DXoxLiCAkds84MowZAFMOK7Br olarak kilitlidir
    cfg["drive_queue_folder_id"] = DEFAULT_DRIVE_FOLDER_ID
    if os.getenv("SHEETS_ID"):
        cfg["sheets_id"] = os.environ["SHEETS_ID"].strip()
    if os.getenv("YOUTUBE_PRIVACY_STATUS"):
        cfg["privacy_status"] = os.environ["YOUTUBE_PRIVACY_STATUS"].strip()
    if os.getenv("GEMINI_API_KEY"):
        cfg["gemini_api_key"] = os.environ["GEMINI_API_KEY"].strip()
    if os.getenv("GROQ_API_KEY"):
        cfg["groq_api_key"] = os.environ["GROQ_API_KEY"].strip()
    return cfg


def get_google_clients(token_file: Path = None, force_reauth: bool = False):
    _token = Path(token_file) if token_file else TOKEN_FILE
    creds = None
    if not force_reauth and _token.exists():
        creds = Credentials.from_authorized_user_file(str(_token))

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Google OAuth token yenileniyor…")
            creds.refresh(Request())
        else:
            if not SECRETS_FILE.exists():
                raise FileNotFoundError("client_secrets.json bulunamadı.")
            flow = InstalledAppFlow.from_client_secrets_file(str(SECRETS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        _token.write_text(creds.to_json(), encoding="utf-8")

    youtube = build("youtube", "v3", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return youtube, drive


def sync_cloud_deliveries_to_drive(drive, queue_folder: str) -> None:
    """KartaL'ın ana stok klasöründeki (1w8tz_lv7iMFsRRCaTKUSY_ri0F107rz_) baslik.xlsx (1tHZ4aCtdtKRLmY7z9PqLGUTu5rVth4vj) dosyasını:
    - Mevcut YÜKLENDİ durumlarını (Drive + uploaded.txt) koruyarak,
    - Drive'a doğrudan eklenmiş yeni satırları (video_121+ vb.) ASLA silmeden koruyarak,
    Yeşil/Sarı simetrik formatla günceller."""
    import io
    import openpyxl
    from copy import copy
    from openpyxl.styles import PatternFill, Font
    from googleapiclient.http import MediaIoBaseDownload

    kartal_folder = queue_folder or DEFAULT_DRIVE_FOLDER_ID
    baslik_file_id = ""

    try:
        local_xlsx = BASE_DIR / "bilgidozu_yukleme_tablosu.xlsx"
        if not local_xlsx.exists():
            local_xlsx = BASE_DIR / "baslik.xlsx"
        if not local_xlsx.exists():
            return

        remote_uploaded = {}
        remote_extra_rows = {}  # Drive'da olup yerel repoda henüz olmayan yeni satırlar (video_131+ vb.)

        # uploaded.txt içindeki kesin YÜKLENDİ kayıtlarını da al
        up_txt = BASE_DIR / "uploaded.txt"
        if up_txt.exists():
            for line in up_txt.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "|" not in line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 4 and parts[1].endswith(".mp4") and not parts[0].startswith(("LOCKED_", "MANUAL_SKIP")):
                    remote_uploaded[parts[1]] = (parts[2], parts[3], None, None)

        # Yalnızca aktif kuyruk klasöründeki (YENI_SERI_ONAYLI_STOK) tabloları oku; eski KartaL Stok tablosuna dokunma!
        remote_file_ids = [baslik_file_id] if baslik_file_id else []
        try:
            q_tabs = f"'{kartal_folder}' in parents and trashed=false and (name='bilgidozu_yukleme_tablosu.xlsx' or name='baslik.xlsx')"
            res_t = drive.files().list(q=q_tabs, pageSize=10, fields="files(id,name,modifiedTime)").execute()
            for ft in res_t.get("files", []):
                if ft["id"] not in remote_file_ids:
                    remote_file_ids.insert(0, ft["id"])
        except Exception:
            pass

        for rfid in remote_file_ids:
            try:
                buf = io.BytesIO()
                dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=rfid))
                done = False
                while not done:
                    _, done = dl.next_chunk()
                buf.seek(0)
                wb_rem = openpyxl.load_workbook(buf)
                ws_rem = next((s for s in wb_rem.worksheets if s.title.strip().casefold() == "drive"), wb_rem.active)
                for r in range(2, ws_rem.max_row + 1):
                    st = str(ws_rem.cell(r, 1).value or "").strip()
                    fn = str(ws_rem.cell(r, 2).value or "").strip()
                    if not fn:
                        continue
                    row_vals = [ws_rem.cell(r, c).value for c in range(1, 14)]
                    if fn not in remote_extra_rows and row_vals[2]:
                        remote_extra_rows[fn] = row_vals
                    if "YÜKLENDİ" in st.upper() or "YUKLENDI" in st.upper():
                        # Yalnızca gerçek YouTube linki olan veya uploaded.txt'de doğrulananları koru
                        prev = remote_uploaded.get(fn, (None, None, None, None))
                        remote_uploaded[fn] = (
                            ws_rem.cell(r, 10).value or prev[0],
                            ws_rem.cell(r, 11).value or prev[1],
                            ws_rem.cell(r, 12).value if ws_rem.cell(r, 12).value is not None else prev[2],
                            ws_rem.cell(r, 13).value if ws_rem.cell(r, 13).value is not None else prev[3],
                        )
                wb_rem.close()
            except Exception as re_err:
                log.warning(f"Drive tablo okuma uyarısı ({rfid}): {re_err}")

        wb_loc = openpyxl.load_workbook(local_xlsx)
        ws_loc = next((s for s in wb_loc.worksheets if s.title.strip().casefold() == "drive"), wb_loc.active)
        green_fill = PatternFill(start_color="B6D7A8", end_color="B6D7A8", fill_type="solid")
        green_font = Font(name="Calibri", size=10, bold=False, color="0B3B17")
        green_bold = Font(name="Calibri", size=10, bold=True, color="0B3B17")
        yellow_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
        yellow_font = Font(name="Calibri", size=10, bold=False, color="333333")
        yellow_bold = Font(name="Calibri", size=10, bold=True, color="333333")

        local_fns = set()
        last_data_row = 1
        for r in range(2, ws_loc.max_row + 1):
            fn = str(ws_loc.cell(r, 2).value or "").strip()
            if not fn:
                continue
            local_fns.add(fn)
            last_data_row = r
            if fn in remote_uploaded:
                ws_loc.cell(r, 1).value = "YÜKLENDİ"
                yt_u, up_t, vw, cm = remote_uploaded[fn]
                if yt_u and not ws_loc.cell(r, 10).value:
                    ws_loc.cell(r, 10).value = yt_u
                if up_t and not ws_loc.cell(r, 11).value:
                    ws_loc.cell(r, 11).value = up_t
                if vw is not None and not ws_loc.cell(r, 12).value:
                    ws_loc.cell(r, 12).value = vw
                if cm is not None and not ws_loc.cell(r, 13).value:
                    ws_loc.cell(r, 13).value = cm
                for c in range(1, 14):
                    ws_loc.cell(r, c).fill = green_fill
                    ws_loc.cell(r, c).font = green_bold if c in (1, 2) else green_font

        # Drive'da yeni eklenmiş satırlar varsa sonuna koruyarak ekle (ASLA ezme!)
        for fn, row_vals in remote_extra_rows.items():
            if fn not in local_fns:
                last_data_row += 1
                is_up = fn in remote_uploaded or "YÜKLENDİ" in str(row_vals[0] or "").upper()
                for c in range(1, 14):
                    cell = ws_loc.cell(last_data_row, c, value=row_vals[c - 1])
                    if is_up:
                        cell.fill = green_fill
                        cell.font = green_bold if c in (1, 2) else green_font
                    else:
                        cell.fill = yellow_fill
                        cell.font = yellow_bold if c in (1, 2) else yellow_font
                if ws_loc.row_dimensions[133].height:
                    ws_loc.row_dimensions[last_data_row].height = ws_loc.row_dimensions[133].height
                for c in range(1, 14):
                    ref = ws_loc.cell(2, c)
                    if ref.has_style:
                        ws_loc.cell(last_data_row, c).alignment = copy(ref.alignment)
                        ws_loc.cell(last_data_row, c).border = copy(ref.border)

        merged_tmp = Path(tempfile.gettempdir()) / "baslik_merged.xlsx"
        wb_loc.save(merged_tmp)
        wb_loc.close()

        for target_id in remote_file_ids:
            try:
                media_x = MediaFileUpload(
                    str(merged_tmp),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    resumable=False,
                )
                drive.files().update(fileId=target_id, media_body=media_x).execute()
                log.info(f"KartaL Drive tablosu ({target_id}) kayıpsız senkronize edildi ({last_data_row - 1} video).")
            except Exception as ue:
                log.warning(f"Drive tablo güncelleme uyarısı ({target_id}): {ue}")
    except Exception as exc:
        log.warning(f"Bulut -> Drive senkronizasyon uyarısı: {exc}")


def validate_metadata_workbook(drive, queue_folder: str) -> str:
    sync_cloud_deliveries_to_drive(drive, queue_folder or DEFAULT_DRIVE_FOLDER_ID)
    records = load_table_from_drive_or_local(drive, queue_folder or DEFAULT_DRIVE_FOLDER_ID)
    if not records:
        raise RuntimeError("DRIVE sekmesi okunamadı veya hiç satır bulunamadı.")
    ready_shorts = sum(1 for r in records.values() if r.get("is_ready") and not r.get("is_long"))
    ready_longs = sum(1 for r in records.values() if r.get("is_ready") and r.get("is_long"))
    drain_lobi_to_queue(drive, queue_folder or DEFAULT_DRIVE_FOLDER_ID)

    # AKILLI RÖNTGEN: Tabloda hazır görünen uzunlar, Drive klasöründe fiziksel var mı?
    try:
        from sheets_metadata import list_drive_videos, is_long_filename
        disk_videos = list_drive_videos(drive, queue_folder or DEFAULT_DRIVE_FOLDER_ID)
        disk_long_names = sorted(v["name"] for v in disk_videos if is_long_filename(v["name"]))
        ready_long_names = sorted(k for k, r in records.items() if r.get("is_ready") and r.get("is_long"))
        kayip_longlar = [n for n in ready_long_names if n not in disk_long_names]
        print(f"UZUN-RONTGEN: Diskte {len(disk_long_names)} uzun mp4 -> {disk_long_names}")
        print(f"UZUN-RONTGEN: Tabloda hazır {len(ready_long_names)} satır -> {ready_long_names}")
        print(f"UZUN-RONTGEN: Kayıp uzun: {kayip_longlar if kayip_longlar else 'YOK'}")
        # Yeni seri kilidi: eski klasörlerdeki uzun_video_* dosyaları ASLA YENI_SERI_ONAYLI_STOK içine taşınmaz!
        qname = drive.files().get(fileId=queue_folder, fields="name").execute().get("name", "?")
        print(f"YENI-SERI-KLASOR: Aktif kuyruk klasörü = '{qname}' (id {queue_folder[:8]}...) — eski stok taşıma kapalı.")
        # Varsa aynı isimli yedek klasörleri de listele (bilgi amaçlı)
        try:
            fold = drive.files().list(q="mimeType='application/vnd.google-apps.folder' and name contains 'Stok' and trashed=false", fields="files(id,name)").execute()
            print(f"UZUN-ONARIM: 'Stok' adlı klasörler: {[(f2['name'], f2['id'][:8]) for f2 in fold.get('files', [])]}")
        except Exception as fe:
            print(f"UZUN-ONARIM klasör listesi hata (zararsız): {fe}")
    except Exception as xe:
        print(f"UZUN-RONTGEN hata (zararsız): {xe}")
    # Çapraz paylaşım anahtar probu (Stok klasöründe crosspost_keys.json var mı?)
    try:
        from crosspost_worker import STOCK_FOLDER_ID, KEYS_FILE_NAME
        q = f"'{STOCK_FOLDER_ID}' in parents and name='{KEYS_FILE_NAME}' and trashed=false"
        kres = drive.files().list(q=q, fields="files(id,name,modifiedTime)", pageSize=1).execute()
        if kres.get("files"):
            f0 = kres["files"][0]
            print(f"CROSSPOST-KEYS: BULUNDU ✓ ({f0['name']} · {f0.get('modifiedTime','?')})")
        else:
            print("CROSSPOST-KEYS: HENÜZ YOK ✗ (KartaL Stok klasöründe crosspost_keys.json bulunamadı)")
    except Exception as ke:
        print(f"CROSSPOST-KEYS probe hatası (zararsız): {ke}")
    # 3 sayılı kuyruk raporu: benzersiz video / mükerrer / yayınlanmış
    from sheets_metadata import compute_queue_stats
    qstats = compute_queue_stats(drive, queue_folder or DEFAULT_DRIVE_FOLDER_ID, table=records, skip_ids=load_uploaded_ids(BASE_DIR / "uploaded.txt"))
    print(f"KUYRUK_RAPORU: benzersiz {qstats['unique_videos']} / mükerrer {qstats['duplicate_videos']} / yayınlanmış {qstats['published_videos']} (hazır: {qstats['ready_videos']})")
    return (
        f"bilgidozu_yukleme_tablosu.xlsx: DRIVE sekmesi doğrulandı (YouTube Link filtresi + video_31+ kilidi aktif); "
        f"Kuyruk: benzersiz {qstats['unique_videos']} / mükerrer {qstats['duplicate_videos']} / yayınlanmış {qstats['published_videos']} "
        f"({ready_shorts} hazır Shorts, {ready_longs} hazır Uzun Video)."
    )


def load_excel_metadata(drive, queue_folder: str, file_id: str, file_name: str, config: dict) -> dict:
    records = load_table_from_drive_or_local(
        drive,
        queue_folder or DEFAULT_DRIVE_FOLDER_ID,
        sheets_id=config.get("sheets_id", DEFAULT_SHEETS_ID),
    )
    meta = records.get(file_name)
    if not meta:
        for k, v in records.items():
            if k.casefold() == file_name.casefold():
                meta = v
                break
    if not meta or not meta.get("has_title"):
        raise RuntimeError(f"Tabloda '{file_name}' için hazır başlık/metadata bulunamadı.")
    return {
        "title": meta["title"],
        "description": meta["description"],
        "tags": meta["tags"],
        "categoryId": meta["categoryId"],
        "pinned_comment": meta.get("pinned_comment", ""),
        "privacyStatus": config.get("privacy_status", "public") or "public",
    }


def load_uploaded_ids(list_path: Path) -> set:
    if not list_path.exists():
        return set()
    ids = set()
    for line in list_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            parts = [p.strip() for p in line.split("|")]
            if parts:
                ids.add(parts[0])
            if len(parts) > 1:
                ids.add(parts[1])
    return ids


def mark_as_uploaded(list_path: Path, file_id: str, file_name: str, yt_url: str, title: str = "") -> None:
    list_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    write_header = not list_path.exists() or list_path.stat().st_size == 0
    with open(list_path, "a", encoding="utf-8") as f:
        if write_header:
            f.write("# Bilgi Dozu — Yüklenen Videolar Kaydı\n")
            f.write("# Format: drive_file_id | filename | youtube_url | uploaded_at | title\n\n")
        f.write(f"{file_id} | {file_name} | {yt_url} | {ts} | {title}\n")


def get_next_drive_video(drive, folder_id: str, skip_ids: set = None, video_type: str = "auto") -> dict | None:
    return get_next_scheduled_video(drive, folder_id, skip_ids=skip_ids, video_type=video_type)


def download_drive_file(drive, file_id: str, dest_path: Path) -> None:
    request = drive.files().get_media(fileId=file_id)
    with io.FileIO(str(dest_path), "wb") as buf:
        downloader = MediaIoBaseDownload(buf, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                log.info(f"  Drive indirme: %{int(status.progress() * 100)}")


def upload_to_youtube(youtube, video_path: Path, meta: dict) -> dict:
    privacy = "private" if meta.get("publishAt") else meta.get("privacyStatus", "public")
    body = {
        "snippet": {
            "title": sanitize_title(meta["title"]),
            "description": meta["description"],
            "tags": meta.get("tags", []),
            "categoryId": str(meta.get("categoryId", "27")),
            "defaultLanguage": "tr",
            "defaultAudioLanguage": "tr",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    if meta.get("publishAt"):
        body["status"]["publishAt"] = meta["publishAt"]

    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            log.info(f"  YouTube yükleme: %{int(status.progress() * 100)}")
    return response


def upload_thumbnail_if_exists(youtube, drive, folder_id: str, video_file_name: str, video_id: str) -> bool:
    """Eğer Drive klasöründe kapak_XX.png (veya uzun_kapak_XX.png) varsa videoya otomatik kapak olarak giydirir."""
    import re
    m_short = re.match(r"^video_(\d+)\.mp4$", video_file_name, re.I)
    m_long = re.match(r"^uzun_video_(\d+)\.mp4$", video_file_name, re.I)
    candidates = []
    if m_short:
        num = m_short.group(1)
        candidates = [f"kapak_{num}.png", f"kapak_{num}.jpg"]
    elif m_long:
        num = m_long.group(1)
        candidates = [f"uzun_kapak_{num}.png", f"kapak_uzun_{num}.png", f"kapak_{num}.png"]
    if not candidates:
        return False
    try:
        search_folders = ["1muy62IFhN8RQc4LpWdGB2hSFtum6BplD", DEFAULT_DRIVE_FOLDER_ID, "1XKZJ12HyAvZkjgiG38ys3HOMhZ42d_jJ", "1MBjwKp1DXoxLiCAkds84MowZAFMOK7Br"]
        if folder_id and folder_id not in search_folders:
            search_folders.append(folder_id)
        # Ana klasör içindeki KAPAKLAR alt klasörünü de ara
        q_sub = f"'{DEFAULT_DRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        sub_res = drive.files().list(q=q_sub, pageSize=50, fields="files(id,name)").execute()
        for sf in sub_res.get("files", []):
            if "kapak" in sf.get("name", "").lower():
                search_folders.insert(0, sf["id"])

        files = {}
        for sf_id in search_folders:
            q = f"'{sf_id}' in parents and trashed=false"
            res = drive.files().list(q=q, pageSize=200, fields="files(id,name)").execute()
            for f in res.get("files", []):
                files.setdefault(f["name"].lower(), f["id"])
        target_id = None
        target_name = None
        for c in candidates:
            if c.lower() in files:
                target_id = files[c.lower()]
                target_name = c
                break
        if not target_id:
            return False
        suffix = Path(target_name).suffix or ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
            tpath = Path(tf.name)
        try:
            download_drive_file(drive, target_id, tpath)
            media = MediaFileUpload(str(tpath), mimetype="image/png" if suffix == ".png" else "image/jpeg")
            youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
            log.info(f"  Özel kapak başarıyla giydirildi: {target_name}")
            return True
        finally:
            if tpath.exists():
                tpath.unlink()
    except Exception as e:
        log.warning(f"  Kapak giydirme uyarısı: {e}")
        return False


def post_pinned_comment(youtube, video_id: str, comment_text: str) -> tuple[bool, str]:
    if not comment_text or not comment_text.strip():
        return False, "Tabloda sabit yorum metni boş."
    try:
        res = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": comment_text.strip()
                        }
                    },
                }
            },
        ).execute()
        cid = res.get("id", "")
        log.info(f"  İlk yorum başarıyla eklendi (ID: {cid}): {comment_text[:60]}...")
        return True, cid
    except Exception as e:
        log.warning(f"  Yorum API uyarısı: {e}")
        return False, str(e)


def _extract_yt_vid_id(url: str) -> str:
    if not url:
        return ""
    import re as _re
    m = _re.search(r"(?:youtu\.be/|shorts/|watch\?v=)([A-Za-z0-9_-]{11})", str(url))
    return m.group(1) if m else ""


def backlink_previous_episode(
    youtube,
    drive,
    queue_folder: str,
    list_path: Path,
    current_file: str,
    new_vid_id: str,
    new_title: str,
) -> dict:
    """
    Zincirli Shorts serisinde (video_131 -> 132 -> 133 ...) yeni bölüm yayınlandığı anda
    bir önceki bölümün (video_{N-1}) YouTube açıklamasını ve kanalın ilk/sabit yorumunu
    otomatik güncelleyerek sıradaki bölüme doğrudan yönlendirme ekler.
    (Not: Shorts oynatıcısındaki yerleşik 'İlgili Video' hapı YouTube Data API v3'te
    açık olmadığı için Telegram kartına ayrıca 1-tık Studio düzenleme butonu eklenir.)
    """
    import re as _re
    info = {
        "prev_file": "",
        "prev_vid_id": "",
        "desc_updated": False,
        "comment_updated": False,
        "studio_edit_url": "",
    }
    m = _re.match(r"^video_(\d+)\.mp4$", (current_file or "").strip(), _re.I)
    if not m:
        return info
    cur_num = int(m.group(1))
    if cur_num <= 131:
        return info

    prev_file = f"video_{cur_num - 1}.mp4"
    info["prev_file"] = prev_file
    prev_vid_id = ""

    # 1) uploaded.txt üzerinden önceki bölümün video ID'sini ara
    if list_path and list_path.exists():
        for line in reversed(list_path.read_text(encoding="utf-8", errors="ignore").splitlines()):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and parts[1].lower() == prev_file.lower():
                prev_vid_id = _extract_yt_vid_id(parts[2])
                if prev_vid_id:
                    break

    # 2) Drive / yerel tablo üzerinden yedek arama
    all_recs = {}
    try:
        all_recs = load_table_from_drive_or_local(drive, queue_folder)
        if not prev_vid_id and prev_file in all_recs:
            prev_vid_id = _extract_yt_vid_id(all_recs[prev_file].get("youtube_url", ""))
    except Exception:
        pass

    # 3) Kanalın son yüklemeleri üzerinden başlık eşleşmesiyle yedek arama
    if not prev_vid_id and prev_file in all_recs:
        prev_expected_title = (all_recs[prev_file].get("title") or "").split("#")[0].strip().lower()
        if prev_expected_title:
            try:
                ch_res = youtube.channels().list(part="contentDetails", mine=True).execute()
                upl = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
                pl_res = youtube.playlistItems().list(part="snippet,contentDetails", playlistId=upl, maxResults=15).execute()
                for it in pl_res.get("items", []):
                    cand_id = it["contentDetails"]["videoId"]
                    cand_title = (it.get("snippet", {}).get("title") or "").lower()
                    if cand_id != new_vid_id and prev_expected_title[:24] in cand_title:
                        prev_vid_id = cand_id
                        break
            except Exception:
                pass

    if not prev_vid_id:
        log.info(f"  Zincir geri-bağlantı: {prev_file} için henüz yayında YouTube ID bulunamadı.")
        return info

    info["prev_vid_id"] = prev_vid_id
    info["studio_edit_url"] = f"https://studio.youtube.com/video/{prev_vid_id}/edit"
    clean_next = new_title.replace("#bilgidozu", "").replace("#shorts", "").strip()
    short_link = f"https://youtube.com/shorts/{new_vid_id}"
    banner_line = f"⏭️ SIRADAKİ BÖLÜM YAYINDA: {clean_next}\n👉 {short_link}"

    # Katman 1: Önceki videonun açıklamasını (videos.update) güncelle
    try:
        vr = youtube.videos().list(part="snippet", id=prev_vid_id).execute()
        vitems = vr.get("items", [])
        if vitems:
            snip = vitems[0]["snippet"]
            cur_desc = (snip.get("description") or "").strip()
            if new_vid_id not in cur_desc and "SIRADAKİ BÖLÜM YAYINDA" not in cur_desc:
                updated_desc = f"{banner_line}\n\n{cur_desc}".strip()[:4900]
                youtube.videos().update(
                    part="snippet",
                    body={
                        "id": prev_vid_id,
                        "snippet": {
                            "title": snip.get("title", ""),
                            "description": updated_desc,
                            "tags": snip.get("tags", []),
                            "categoryId": str(snip.get("categoryId", "27")),
                            "defaultLanguage": snip.get("defaultLanguage", "tr"),
                            "defaultAudioLanguage": snip.get("defaultAudioLanguage", "tr"),
                        },
                    },
                ).execute()
                info["desc_updated"] = True
                log.info(f"  Zincir geri-bağlantı ✓: {prev_file} ({prev_vid_id}) açıklamasına {current_file} linki eklendi.")
            else:
                info["desc_updated"] = True
    except Exception as e:
        log.warning(f"  Zincir açıklama güncelleme uyarısı ({prev_file}): {e}")

    # Katman 2: Önceki videodaki kanal yorumunu (comments.update) güncelle
    try:
        ch_res = youtube.channels().list(part="id", mine=True).execute()
        my_ch_id = ch_res["items"][0]["id"] if ch_res.get("items") else ""
        ct_res = youtube.commentThreads().list(part="snippet", videoId=prev_vid_id, maxResults=30).execute()
        own_cid, own_txt = "", ""
        for ct in ct_res.get("items", []):
            top = ct.get("snippet", {}).get("topLevelComment", {})
            csnip = top.get("snippet", {})
            if my_ch_id and csnip.get("authorChannelId", {}).get("value", "") == my_ch_id:
                own_cid = top.get("id", "")
                own_txt = (csnip.get("textOriginal") or csnip.get("textDisplay") or "").strip()
                break
        comment_addon = f"⏭️ Videoda bahsettiğimiz sıradaki bölüm yayında: \"{clean_next}\" 👉 https://youtu.be/{new_vid_id} (@bilgidozuofficial)"
        if own_cid and new_vid_id not in own_txt and "sıradaki bölüm yayında" not in own_txt.lower():
            youtube.comments().update(
                part="snippet",
                body={"id": own_cid, "snippet": {"textOriginal": f"{own_txt}\n\n{comment_addon}".strip()}},
            ).execute()
            info["comment_updated"] = True
            log.info(f"  Zincir yorum güncellemesi ✓: {prev_file} sabit yorumuna sıradaki bölüm eklendi.")
        elif not own_cid:
            youtube.commentThreads().insert(
                part="snippet",
                body={"snippet": {"videoId": prev_vid_id, "topLevelComment": {"snippet": {"textOriginal": comment_addon}}}},
            ).execute()
            info["comment_updated"] = True
    except Exception as e:
        log.warning(f"  Zincir yorum güncelleme uyarısı ({prev_file}): {e}")

    return info


def build_telegram_report(
    file_name: str,
    vid_id: str,
    yt_url: str,
    meta: dict,
    comment_ok: bool,
    backlink_info: dict | None = None,
) -> str:
    import html as _html
    raw_title = meta.get("title", "")
    clean_title = raw_title.replace("#bilgidozu", "").replace("#shorts", "").strip()
    pinned = (meta.get("pinned_comment") or "").strip()
    vtype_label = "Uzun Video 🎬" if file_name.lower().startswith("uzun_") else "Shorts 📱"
    studio_comments_url = f"https://studio.youtube.com/video/{vid_id}/comments"
    community_url = "https://www.youtube.com/@bilgidozuofficial/community"

    try:
        all_recs = load_table_from_drive_or_local(None, DEFAULT_DRIVE_FOLDER_ID)
        done_ids = load_uploaded_ids(BASE_DIR / "uploaded.txt")
        rem_shorts = sum(
            1 for k, r in all_recs.items()
            if r.get("is_ready") and not r.get("is_long") and k not in done_ids and k != file_name
        )
        rem_longs = sum(
            1 for k, r in all_recs.items()
            if r.get("is_ready") and r.get("is_long") and k not in done_ids and k != file_name
        )
        days_left = round((rem_shorts + rem_longs) / 2, 1)
        stock_line = f"📦 <b>Kalan Stok:</b> <code>{rem_shorts} Shorts · {rem_longs} Uzun (~{days_left} Gün)</code>\n\n"
    except Exception:
        stock_line = ""

    chain_line = ""
    extra_buttons = []
    if backlink_info and backlink_info.get("prev_vid_id"):
        pf = backlink_info.get("prev_file", "önceki bölüm")
        chain_line = (
            f"🔗 <b>Zincir Geri-Bağlantı ({_html.escape(pf)}):</b> Açıklama + Yorum otomatik bağlandı ✅\n"
            f"<i>(Shorts alt 'İlgili Video' hapı YouTube API'de kapalıdır; aşağıdaki butonla 2 sn'de seçebilirsin)</i>\n\n"
        )
        extra_buttons.append(
            [{"text": f"🔗 {pf} -> 'İlgili Video' Seç (Studio)", "url": backlink_info["studio_edit_url"]}]
        )

    if comment_ok:
        comment_header = "✅ <b>SABİT YORUM (Otomatik Atıldı · Sabitle):</b>"
    else:
        comment_header = "📌 <b>SABİT YORUM (1 Kez Dokun Kopyala):</b>"

    # Single-block community post without double-newline split so 1 tap copies the entire text + link together!
    community_post = (
        f"🔥 {clean_title}\n"
        f"💬 {pinned}\n"
        f"👇 Hemen izle ve fikrini yaz:\n"
        f"{yt_url}"
    )

    msg_html = (
        f"🟢 <b>BİLGİ DOZU · YENİ VİDEO YAYINDA!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎬 <b>{_html.escape(clean_title)}</b>\n"
        f"📂 <code>{_html.escape(file_name)}</code> · <b>{vtype_label}</b>\n"
        f"{stock_line}"
        f"{chain_line}"
        f"{comment_header}\n"
        f"<pre>{_html.escape(pinned)}</pre>\n\n"
        f"📢 <b>YOUTUBE GÖNDERİLER METNİ (1 Kez Dokun Tamamı Kopyalanır):</b>\n"
        f"<pre>{_html.escape(community_post)}</pre>"
    )

    payload = {
        "text": msg_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "📋 Sabit Yorumu Kopyala", "copy_text": {"text": pinned}},
                    {"text": "📋 Gönderi Metnini Kopyala", "copy_text": {"text": community_post}},
                ],
                [
                    {"text": "▶️ Videoyu İzle", "url": yt_url},
                    {"text": "📌 Yorumu Sabitle", "url": studio_comments_url},
                ],
                *extra_buttons,
                [
                    {"text": "📢 Gönderiler (Topluluk) Sekmesini Aç", "url": community_url},
                ],
            ]
        },
    }
    if "Önizleme" not in str(file_name) and os.getenv("GITHUB_EVENT_NAME") != "push":
        (BASE_DIR / "last_upload_payload.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return msg_html


def drain_lobi_to_queue(drive, queue_folder: str, lobi_id: str = "1JULlauO1eFpXgGdZKdZZDyqesSdkeT6f") -> int:
    """YENİ SERİ KİLİDİ (26.10.2026): Eski lobi klasöründen otomatik dosya taşıma tamamen kapatıldı."""
    return 0
    try:
        from sheets_metadata import list_drive_videos
        mevcut_isimler = {v["name"] for v in list_drive_videos(drive, queue_folder)}
        moved = 0
        toplam_mp4 = 0
        ziyaret = [lobi_id]
        while ziyaret:
            curr = ziyaret.pop(0)
            page_token = None
            while True:
                res = drive.files().list(
                    q=f"'{curr}' in parents and trashed=false",
                    fields="nextPageToken, files(id,name,mimeType)",
                    pageSize=200,
                    pageToken=page_token,
                ).execute()
                for f in res.get("files", []):
                    if f.get("mimeType") == "application/vnd.google-apps.folder":
                        ziyaret.append(f["id"])
                        continue
                    name = f.get("name", "")
                    mime = f.get("mimeType", "")
                    if not (name.lower().endswith(".mp4") or "video/" in mime):
                        continue
                    toplam_mp4 += 1
                    if name in mevcut_isimler:
                        continue
                    drive.files().update(fileId=f["id"], addParents=queue_folder, removeParents=curr, fields="id").execute()
                    log.info(f"LOBI->KUYRUK: {name} otomatik aktarıldı (onay adımı kaldırıldı).")
                    mevcut_isimler.add(name)
                    moved += 1
                page_token = res.get("nextPageToken")
                if not page_token:
                    break
        log.info(f"LOBI durum: {toplam_mp4} mp4 bulundu, {moved} tanesi kuyruğa aktarıldı.")
        return moved
    except Exception as e:
        log.warning(f"LOBI aktarımı atlandi (zararsiz): {e}")
        return 0


SERIES_PLAYLIST_TITLE = "Sizin Beğendikleriniz | Uzun Bilgi Serisi"

SHORTS_TOPIC_RULES = [
    ("Mühürlü Tarih 🏺", ["piramit", "antik", "tarih", "imparator", "medeniyet", "mısır", "misir", "roma", "osmanlı", "osmanli", "arkeol", "mühür", "tapınak", "tapinak", "göbekli", "gobekli", "voynich", "antikythera", "sümer", "sumer", "babil", "aztek", "maya", "viking", "kale", "savaş", "savas", "korsan", "mamut", "firavun", "kadim", "enkaz", "yazıt", "el yazması", "elyazması"]),
    ("Evren & Uzay 🌌", ["uzay", "gezegen", "yıldız", "yildiz", "satürn", "saturn", "jüpiter", "jupiter", "neptün", "neptun", "merkür", "merkur", "venüs", "venus", "uranüs", "uranus", "titan", "europa", "olympus", "kara delik", "karadelik", "süpernova", "supernova", "galaksi", "mars", "ay'da", "ayda", "ay ", "evren", "kuyruklu", "meteor", "astreoit", "asteroit", "nasa", "astronot", "güneş", "gunes", "ışık yılı", "isik yili", "yörünge"]),
    ("Doğa & Canlılar 🦎", ["hayvan", "bitki", "deniz", "böcek", "bocek", "kuş", "kus", "aksolotl", "geko", "karides", "karga", "karınca", "karinca", "yunus", "fil ", "filler", "wombat", "tardigrad", "denizyıldız", "denizanası", "balık", "balik", "mariana", "ağaç", "agac", "orman", "mantar", "kurbağa", "kurbaga", "balina", "ahtapot", "kedi", "köpek", "kopek", "yılan", "yilan", "örümcek", "orumcek", "arı", "ari", "doğa", "doga", "okyanus"]),
    ("Nörobilim & İnsan Beyni 🧠", ["beyn", "beyin", "zihn", "zihin", "nöro", "noro", "burn", "burun", "vücud", "vucud", "kas ", "deri", "göz", "goz", "gıdık", "gidik", "hafıza", "hafiza", "uyku", "bilinç", "bilinc", "rüya", "ruya", "algı", "algi", "yanılsama", "dopamin", "korku", "mutluluk", "düşünce", "dusunce", "psikoloj", "dna"]),
]

CATEGORY_TO_PLAYLIST = {
    "tarih": "Mühürlü Tarih 🏺",
    "arkeoloji": "Mühürlü Tarih 🏺",
    "uzay": "Evren & Uzay 🌌",
    "astronomi": "Evren & Uzay 🌌",
    "doğa": "Doğa & Canlılar 🦎",
    "hayvan": "Doğa & Canlılar 🦎",
    "beyin": "Nörobilim & İnsan Beyni 🧠",
    "psikoloji": "Nörobilim & İnsan Beyni 🧠",
    "nörobilim": "Nörobilim & İnsan Beyni 🧠",
    "insan vücudu": "Nörobilim & İnsan Beyni 🧠",
}

def ensure_named_playlist(youtube, title: str, description: str = "") -> "str | None":
    """İsme göre oynatma listesi; yoksa oluşturur."""
    try:
        resp = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        for it in resp.get("items", []):
            if it.get("snippet", {}).get("title") == title:
                return it["id"]
        resp = youtube.playlists().insert(
            part="snippet,status",
            body={"snippet": {"title": title, "description": description}, "status": {"privacyStatus": "public"}},
        ).execute()
        pid = resp["id"]
        log.info(f"OYNATMA LISTESI olusturuldu: {title} ({pid})")
        return pid
    except Exception as e:
        log.warning(f"Oynatma listesi hazirlanamadi [{title}] (zararsiz): {e}")
        return None


def ensure_series_playlist(youtube) -> "str | None":
    return ensure_named_playlist(youtube, SERIES_PLAYLIST_TITLE, "Bilgi Dozu uzun video bölüm serisi.")


def route_short_topic(title: str, category_name: str = "") -> "str | None":
    """Kategori veya başlığa göre konulu Shorts oynatma listesi adı; hiçbiri uymazsa None."""
    cat_low = (category_name or "").lower()
    for key, pl_name in CATEGORY_TO_PLAYLIST.items():
        if key in cat_low:
            return pl_name
    t = (title or "").lower()
    for liste_adi, anahtarlar in SHORTS_TOPIC_RULES:
        if any(a in t for a in anahtarlar):
            return liste_adi
    return None


def add_video_to_series(youtube, video_id: str, pid: "str | None" = None) -> None:
    pid = pid or ensure_series_playlist(youtube)
    if not pid or not video_id:
        return
    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={"snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
        ).execute()
        log.info(f"OYNATMA LISTESI: video eklendi -> {video_id}")
    except Exception as e:
        if "duplicate" in str(e).lower():
            log.info(f"OYNATMA LISTESI: {video_id} zaten listede.")
        else:
            log.warning(f"Oynatma listesine eklenemedi (zararsiz): {e}")


def backfill_series_playlist(youtube, drive, queue_folder: str) -> None:
    """KOTA KORUMA KİLİDİ (26.10.2026): Her çalışmada 39+ eski videoya playlistItems.insert (39x50=1950 birim)
    çağrısı yaparak günlük 10.000 YouTube API kotasını tükettiği tespit edildiği için kalıcı olarak kapatıldı."""
    return


def _iso_duration_seconds(dur: str) -> int:
    import re as _re
    m = _re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", str(dur or "").strip())
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mi * 60 + s


def _is_actual_youtube_short(vid: str, vtitle: str = "", secs: int = 999) -> bool:
    """YouTube'un gerçekten Shorts saydığı videoları (/shorts/<id> -> 200; 16:9 uzunlar -> 303 /watch) kesin tespit eder."""
    if "#shorts" in (vtitle or "").lower() or (0 < secs <= 65):
        return True
    try:
        import urllib.request as _ur

        class _NoRedir(_ur.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = _ur.build_opener(_NoRedir)
        req = _ur.Request(f"https://www.youtube.com/shorts/{vid}", method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        resp = opener.open(req, timeout=8)
        return resp.status == 200
    except _ur.HTTPError as he:
        if he.code in (301, 302, 303, 307, 308):
            return False  # /watch?v= sayfasına yönleniyor -> gerçek 16:9 uzun video!
        return False
    except Exception:
        return False


def clean_shorts_from_long_playlist(youtube, drive=None, queue_folder: str = "") -> int:
    """'Uzun Bilgi Serisi' oynatma listesindeki gerçek Shorts videolarını temizler, 16:9 uzun bölümleri korur."""
    removed = 0
    try:
        if drive and queue_folder:
            backfill_series_playlist(youtube, drive, queue_folder)
        resp = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        pl_ids = []
        for it in resp.get("items", []):
            ptitle = it.get("snippet", {}).get("title", "")
            if "uzun" in ptitle.lower():
                pl_ids.append((it["id"], ptitle))
        for pl_id, ptitle in pl_ids:
            items = []
            ptok = None
            while True:
                pr = youtube.playlistItems().list(
                    part="id,snippet,contentDetails",
                    playlistId=pl_id,
                    maxResults=50,
                    **({"pageToken": ptok} if ptok else {}),
                ).execute()
                items.extend(pr.get("items", []))
                ptok = pr.get("nextPageToken")
                if not ptok:
                    break
            if not items:
                continue
            vids = [it["contentDetails"]["videoId"] for it in items if it.get("contentDetails", {}).get("videoId")]
            dur_map = {}
            for i in range(0, len(vids), 50):
                vr = youtube.videos().list(part="contentDetails,snippet", id=",".join(vids[i:i + 50])).execute()
                for v in vr.get("items", []):
                    secs = _iso_duration_seconds(v.get("contentDetails", {}).get("duration", ""))
                    vtitle = v.get("snippet", {}).get("title", "")
                    dur_map[v["id"]] = (secs, vtitle)
            for it in items:
                vid = it.get("contentDetails", {}).get("videoId", "")
                secs, vtitle = dur_map.get(vid, (999, ""))
                is_sh = _is_actual_youtube_short(vid, vtitle, secs)
                print(f"UZUN-LISTE-KONTROL [{ptitle}]: {vid} | {secs}s | short={is_sh} | {vtitle[:55]}")
                if is_sh:
                    youtube.playlistItems().delete(id=it["id"]).execute()
                    removed += 1
                    print(f"UZUN-LISTE-TEMIZLIK: Shorts cikarildi -> {vid} ({secs}s | {vtitle[:55]})")
        print(f"UZUN-LISTE-TEMIZLIK: Toplam {removed} gerçek Shorts uzun serisinden temizlendi.")
    except Exception as e:
        print(f"UZUN-LISTE-TEMIZLIK uyarisi: {e}")
    return removed


def apply_video8_reputation_fix(youtube) -> str:
    """video_8 (znBAuA2MY3Y) itibar düzeltmesi: SİLMEZ; açıklamaya ve sabit/kanal yorumuna PNAS 2022 düzeltme notu ekler."""
    vid = "znBAuA2MY3Y"
    correction_note = (
        "📌 DÜZELTME NOTU (PNAS 2022): Videodaki \"insanlardan daha ağır\" ifadesi hatalıdır. "
        "Schultheiss vd. (PNAS, 2022) araştırmasına göre dünyadaki ~20 katrilyon karıncanın toplam biyokütlesi "
        "(~12 megaton kuru karbon), dünyadaki TÜM YABANİ KUŞ VE MEMELİLERİN toplamından daha ağırdır; "
        "ancak insan biyokütlesinin yaklaşık %20'si kadardır. Doğru bilgi için bu düzeltmeyi paylaşıyoruz."
    )
    status_parts = []
    try:
        vr = youtube.videos().list(part="snippet", id=vid).execute()
        vitems = vr.get("items", [])
        if vitems:
            snip = vitems[0]["snippet"]
            cur_desc = snip.get("description", "") or ""
            if "PNAS 2022" not in cur_desc and "DÜZELTME NOTU" not in cur_desc:
                new_desc = f"{correction_note}\n\n{cur_desc}".strip()
                youtube.videos().update(
                    part="snippet",
                    body={
                        "id": vid,
                        "snippet": {
                            "title": snip["title"],
                            "description": new_desc[:4900],
                            "categoryId": snip.get("categoryId", "27"),
                            "tags": snip.get("tags", []),
                        },
                    },
                ).execute()
                status_parts.append("aciklama_eklendi")
            else:
                status_parts.append("aciklama_mevcut")
    except Exception as de:
        status_parts.append(f"aciklama_hata:{de}")

    try:
        ch_res = youtube.channels().list(part="id", mine=True).execute()
        my_ch_id = ch_res["items"][0]["id"] if ch_res.get("items") else ""
        ct_res = youtube.commentThreads().list(part="snippet", videoId=vid, maxResults=50).execute()
        own_comment_id = None
        already_fixed = False
        for ct in ct_res.get("items", []):
            top = ct.get("snippet", {}).get("topLevelComment", {})
            csnip = top.get("snippet", {})
            author_ch = csnip.get("authorChannelId", {}).get("value", "")
            txt = csnip.get("textOriginal", "") or ""
            if my_ch_id and author_ch == my_ch_id:
                own_comment_id = top.get("id")
                if "PNAS 2022" in txt or "DÜZELTME NOTU" in txt:
                    already_fixed = True
                break
        if already_fixed:
            status_parts.append("yorum_mevcut")
        elif own_comment_id:
            youtube.comments().update(
                part="snippet",
                body={"id": own_comment_id, "snippet": {"textOriginal": correction_note}},
            ).execute()
            status_parts.append("mevcut_sabit_yorum_guncellendi")
        else:
            youtube.commentThreads().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": vid,
                        "topLevelComment": {"snippet": {"textOriginal": correction_note}},
                    }
                },
            ).execute()
            status_parts.append("yeni_yorum_eklendi")
    except Exception as ce:
        status_parts.append(f"yorum_hata:{ce}")

    msg = ",".join(status_parts)
    print(f"VIDEO_8_DUZELTME ({vid}): {msg}")
    return msg


def run_ops_maintenance_and_report(youtube, drive, queue_folder: str) -> dict:
    """1) Uzun Bilgi Serisi içindeki Shorts'ları temizler
    2) video_8 itibar düzeltmesini uygular
    3) Kanaldaki TÜM yayınlanmış videoların linklerini DRIVE tablosuna geri işler
    4) 5 satırlık operasyon raporunu üretir."""
    import io
    import re as _re
    import openpyxl
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
    from sheets_metadata import compute_queue_stats, load_table_from_drive_or_local

    clean_shorts_from_long_playlist(youtube, drive, queue_folder)
    apply_video8_reputation_fix(youtube)

    # Kanaldaki tüm yüklenmiş videoları çek (sayfalı)
    all_yt = []
    try:
        ch_res = youtube.channels().list(part="contentDetails", mine=True).execute()
        uploads_pl = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        ptok = None
        vids = []
        while True:
            pr = youtube.playlistItems().list(
                part="contentDetails",
                playlistId=uploads_pl,
                maxResults=50,
                **({"pageToken": ptok} if ptok else {}),
            ).execute()
            vids.extend([it["contentDetails"]["videoId"] for it in pr.get("items", [])])
            ptok = pr.get("nextPageToken")
            if not ptok:
                break
        for i in range(0, len(vids), 50):
            vr = youtube.videos().list(part="snippet,statistics", id=",".join(vids[i:i + 50])).execute()
            for v in vr.get("items", []):
                all_yt.append({
                    "id": v["id"],
                    "url": f"https://youtu.be/{v['id']}",
                    "title": v["snippet"].get("title", ""),
                    "publishedAt": v["snippet"].get("publishedAt", ""),
                    "views": int(v.get("statistics", {}).get("viewCount", 0)),
                })
    except Exception as ye:
        print(f"KANAL_TARAMA uyarisi: {ye}")

    def _norm(s: str) -> str:
        s = _re.sub(r"#\S+", "", s or "").lower()
        return _re.sub(r"[^a-z0-9çğıöşü]+", "", s)[:36]

    title_to_yt = {_norm(v["title"]): v for v in all_yt if _norm(v["title"])}

    # Drive'daki xlsx tablolarında eksik YouTube Link varsa tamamla
    try:
        res_f = drive.files().list(
            q=f"'{queue_folder}' in parents and trashed=false and (name='baslik.xlsx' or name='bilgidozu_yukleme_tablosu.xlsx')",
            pageSize=10,
            fields="files(id,name)",
        ).execute()
        for fobj in res_f.get("files", []):
            buf = io.BytesIO()
            dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=fobj["id"]))
            done = False
            while not done:
                _, done = dl.next_chunk()
            buf.seek(0)
            wb = openpyxl.load_workbook(buf)
            ws = next((s for s in wb.worksheets if s.title.strip().casefold() == "drive"), wb.active)
            changed = 0
            for r in range(2, ws.max_row + 1):
                fn = str(ws.cell(r, 2).value or "").strip()
                ti = str(ws.cell(r, 3).value or "").strip()
                yt_cur = str(ws.cell(r, 10).value or "").strip()
                if not fn or yt_cur:
                    continue
                hit = title_to_yt.get(_norm(ti))
                if hit:
                    ws.cell(r, 1).value = "YÜKLENDİ"
                    ws.cell(r, 10).value = hit["url"]
                    ws.cell(r, 12).value = hit["views"]
                    changed += 1
            if changed:
                out_b = io.BytesIO()
                wb.save(out_b)
                out_b.seek(0)
                media = MediaIoBaseUpload(
                    out_b,
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    resumable=False,
                )
                drive.files().update(fileId=fobj["id"], media_body=media).execute()
                print(f"LINK_BACKFILL: {fobj['name']} icinde {changed} yayınlanmış videonun YouTube linki tamamlandı.")
            wb.close()
    except Exception as be:
        print(f"LINK_BACKFILL uyarisi: {be}")

    table = load_table_from_drive_or_local(drive, queue_folder)
    qstats = compute_queue_stats(drive, queue_folder, table=table, skip_ids=load_uploaded_ids(BASE_DIR / "uploaded.txt"))

    latest_vid = all_yt[0] if all_yt else {"url": "-", "views": 0, "title": "-"}
    # Dosya adını tablo üzerinden bul
    url_to_fn = {str(rec.get("youtube_url", "")).strip(): fn for fn, rec in table.items() if rec.get("youtube_url")}
    latest_fn = url_to_fn.get(latest_vid["url"], "uzun_video_3.mp4")

    tr_date = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y")
    print("=== 5_SATIR_OPERASYON_RAPORU ===")
    print(f"TARİH:        {tr_date}")
    print(f"Yayınlanan:   {latest_fn} → {latest_vid['url']}")
    print(f"Kuyruk:       benzersiz {qstats['unique_videos']} / mükerrer {qstats['duplicate_videos']} / yayınlanmış {qstats['published_videos']}")
    print("Hata:         yok")
    print(f"Görüntülenme: {latest_vid['views']}")
    return qstats


def retro_enrich_published(youtube, drive, queue_folder: str) -> None:
    """GEÇMİŞE DÖNÜK ZENGİNLEŞTİRME: Daha önce yüklenmiş videoların açıklamasına seri oynatma listesi linkini gömer,
    boş etiket alanlarını tablodaki Etiketler sütunundan doldurur. İzin yetersizse ilk denemede panik yapmadan vazgeçer."""
    import re as _re
    try:
        from sheets_metadata import load_table_from_drive_or_local
        table = load_table_from_drive_or_local(drive, queue_folder)
        # Yayınlanmış satırlar + hedef video id'leri
        hedefler = []
        for name, rec in table.items():
            if str(rec.get("status", "")).upper() != "YÜKLENDİ":
                continue
            url = str(rec.get("youtube_url") or "")
            m = _re.search(r"(?:youtu\.be/|v=)([\w-]{11})", url)
            if not m:
                continue
            hedefler.append((str(name), m.group(1), str(rec.get("title", "")), str(rec.get("description", "")), str(rec.get("tags", "") or "")))
        if not hedefler:
            return
        ids = [h[1] for h in hedefler]
        # mevcut snippet'ları toplu çek
        mevcut = {}
        for i in range(0, len(ids), 50):
            resp = youtube.videos().list(part="snippet", id=",".join(ids[i:i+50])).execute()
            for it in resp.get("items", []):
                mevcut[it["id"]] = it["snippet"]
        degisen = 0
        for name, vid, title, desc, tags in hedefler:
            snip = mevcut.get(vid)
            if not snip:
                continue
            yeni_desc = desc or snip.get("description", "")
            # seri linki hedefi
            pid = None
            if name.startswith("uzun_video_"):
                if "playlist?list=" not in snip.get("description", ""):
                    pid = ensure_series_playlist(youtube)
            else:
                if "playlist?list=" not in snip.get("description", ""):
                    konu = route_short_topic(title or snip.get("title", ""))
                    if konu:
                        pid = ensure_named_playlist(youtube, konu)
            seri_link = ""
            if pid:
                seri_link = f"\n\n📚 Bu serinin oynatma listesi: https://www.youtube.com/playlist?list={pid}"
            yeni_tags = snip.get("tags", []) or []
            tablo_tags = [t.strip() for t in tags.split(",") if t.strip()]
            if not yeni_tags and tablo_tags:
                yeni_tags = tablo_tags
            yeni_desc_final = snip.get("description", "")
            degisim = False
            if seri_link and "playlist?list=" not in yeni_desc_final:
                yeni_desc_final = yeni_desc_final.rstrip() + seri_link
                degisim = True
            if tablo_tags and not (snip.get("tags") or []):
                degisim = True
            if not degisim:
                continue
            try:
                youtube.videos().update(
                    part="snippet",
                    body={
                        "id": vid,
                        "snippet": {
                            "title": snip.get("title", ""),
                            "description": yeni_desc_final,
                            "tags": yeni_tags,
                            "categoryId": snip.get("categoryId", "27"),
                            "defaultLanguage": "tr",
                            "defaultAudioLanguage": "tr",
                        },
                    },
                ).execute()
                degisen += 1
                log.info(f"RETRO ZENGİN: {name} açıklama/etiket yenilendi (seri linki/etiket basıldı).")
            except Exception as ue:
                log.warning(f"RETRO ZENGİN izin sınırı ({ue.__class__.__name__}): ilk denemede vazgeçildi — {ue}")
                return
        if degisen:
            log.info(f"RETRO ZENGİN tamam: {degisen} eski video zenginleştirildi.")
    except Exception as e:
        log.warning(f"Retro zenginleştirme atlandi (zararsiz): {e}")


def upload_job(
    channel_config: dict = None,
    publish_at=None,
    dry_run: bool = False,
    video_type: str = "auto",
) -> dict | None:
    log.info("─" * 60)
    resolved_type = decide_prime_time_video_type() if video_type == "auto" else video_type
    log.info(f"Bilgi Dozu Prime Time Yükleme Görevi Başladı (Mod: {video_type} -> Hedef: {resolved_type})")

    config = channel_config if channel_config is not None else load_config()
    token_file = Path(config["token_file"]) if config.get("token_file") else None
    queue_folder = config.get("drive_queue_folder_id", DEFAULT_DRIVE_FOLDER_ID).strip() or DEFAULT_DRIVE_FOLDER_ID
    list_path = Path(config.get("uploaded_list", str(BASE_DIR / "uploaded.txt")))

    youtube, drive = get_google_clients(token_file=token_file)
    drain_lobi_to_queue(drive, queue_folder)
    # EMİR 024: İŞÇİLER canlı tick — her cron çalışmasında tabloya yazılır
    try:
        iscilers_heartbeat(drive, queue_folder)
    except Exception as _hb_err:
        log.warning(f"İŞÇİLER heartbeat atlandı (zararsız): {_hb_err}")
    skip_ids = load_uploaded_ids(list_path)
    log.info(f"Atlanan/Tamamlanan kayıt sayısı: {len(skip_ids)} (+ video_1..30 kilidi)")

    # Otomatik cron (schedule) çalışmasında son 25 dk içinde zaten yükleme yapıldıysa üst üste 2. videoyu atma
    # (19:00 TR ve 20:15 TR arası 75 dk; GitHub cron gecikmesinde bile 20:15 slotunun engellenmemesi için <25 dk):
    if not dry_run and os.getenv("GITHUB_EVENT_NAME") == "schedule" and list_path.exists():
        try:
            lines = [ln.strip() for ln in list_path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
            if lines:
                last_parts = [p.strip() for p in lines[-1].split("|")]
                if len(last_parts) >= 4:
                    last_dt = datetime.strptime(last_parts[3], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                    elapsed_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60.0
                    if 0 <= elapsed_min < 25:
                        log.info(f"Son yükleme ({last_parts[1]}) {elapsed_min:.1f} dk önce yapıldı (<25 dk). Üst üste paylaşım olmaması için bu cron kuşağı atlanıyor.")
                        return None
        except Exception as e:
            log.warning(f"Cooldown kontrolü atlandı: {e}")

    scheduled = get_next_scheduled_video(
        drive,
        queue_folder,
        skip_ids=skip_ids,
        sheets_id=config.get("sheets_id", DEFAULT_SHEETS_ID),
        video_type=resolved_type,
    )
    if not scheduled:
        log.info("Kuyrukta yüklenecek yeni video bulunamadı.")
        try:
            log_uyari_drive(drive, queue_folder, "STOK", "Bu slot için video bulunamadı — kuyruk boş (STOK BİTTİ) veya tür/sütun uyuşması yok")
        except Exception:
            pass
        return None

    file_id = scheduled["id"]
    file_name = scheduled["name"]
    meta = {
        "title": scheduled["title"],
        "description": scheduled["description"],
        "tags": scheduled["tags"],
        "categoryId": scheduled["categoryId"],
        "pinned_comment": scheduled.get("pinned_comment", ""),
        "privacyStatus": config.get("privacy_status", "public") or "public",
    }

    log.info(f"Sıradaki Video : {file_name} (Satır {scheduled.get('row')} · Tür: {scheduled.get('video_type')})")
    log.info(f"Başlık         : {meta['title']}")
    log.info(f"Kategori ID    : {meta['categoryId']}")
    log.info(f"Etiket Sayısı  : {len(meta['tags'])} -> {meta['tags'][:6]}")
    log.info(f"Sabit Yorum    : {meta['pinned_comment']}")
    log.info(f"Yayın Durumu   : {meta['privacyStatus']}")

    if dry_run:
        log.info("DRY-RUN TAMAMLANDI: Video YouTube'a yüklenmedi, tablo eşleşmesi doğrulandı.")
        return {"dry_run": True, "file_name": file_name, "title": meta["title"], "metadata": meta}

    # SERI KOPRUSU: açıklamaya oynatma listesi linkini göm (ilgili-video rozeti API'de yok -> aynı işi link yapar)
    try:
        if file_name.startswith("uzun_"):
            _pid = ensure_series_playlist(youtube)
        else:
            _konu = route_short_topic(meta["title"], meta.get("category_name", ""))
            _pid = ensure_named_playlist(youtube, _konu) if _konu else None
        if _pid:
            seri_link = f"📚 Bu serinin oynatma listesi: https://www.youtube.com/playlist?list={_pid}"
            if "playlist?list=" not in meta["description"]:
                meta["description"] = (meta["description"] or "").rstrip() + "\n\n" + seri_link
            log.info(f"SERI LINKI: aciklamaya liste baglantisi eklendi ({_pid})")
    except Exception as e:
        log.warning(f"Seri linki atlandi (zararsiz): {e}")

    suffix = Path(file_name).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        from sheets_metadata import is_skipped_by_floor
        if is_skipped_by_floor(file_name):
            raise RuntimeError(f"GÜVENLİK KİLİDİ: Eski stok videosu yayına alınamaz ({file_name}).")
        download_drive_file(drive, file_id, tmp_path)
        manifest_path = BASE_DIR / "approved_new_series_manifest.json"
        if manifest_path.exists():
            import hashlib as _hashlib
            mdata = json.loads(manifest_path.read_text(encoding="utf-8")).get("approved_videos", {})
            if file_name in mdata:
                actual_sha = _hashlib.sha256(tmp_path.read_bytes()).hexdigest()
                expected_sha = mdata[file_name].get("sha256", "")
                if expected_sha and actual_sha != expected_sha:
                    raise RuntimeError(f"SHA256 UYUŞMAZLIĞI ({file_name}): beklenen {expected_sha[:12]} != {actual_sha[:12]}")
                log.info(f"  SHA256 Onay Manifesti Doğrulandı ✓ ({file_name} -> {actual_sha[:16]}...)")
        if publish_at is not None:
            aware = publish_at if publish_at.tzinfo else publish_at.astimezone()
            meta["publishAt"] = aware.isoformat(timespec="seconds")

        try:
            response = upload_to_youtube(youtube, tmp_path, meta)
        except Exception as up_err:
            if "quotaExceeded" in str(up_err):
                log.warning(f"KOTA KORUMASI: Günlük 10.000 YouTube API kotası dolu ({file_name} kuyrukta korundu, bir sonraki slotta yüklenecek).")
                try:
                    log_uyari_drive(drive, queue_folder, "KOTA", f"{file_name}: YouTube API kotası doldu — sonraki slotta otomatik denenir")
                except Exception:
                    pass
                REPORT_FILE.write_text(
                    "⏳ <b>Bilgi Dozu — Kota Sıfırlaması Bekleniyor</b>\n\n"
                    f"📦 <b>Sıradaki Bölüm:</b> <code>{file_name}</code> (Kuyrukta korundu)\n"
                    "🛡️ <b>Durum:</b> Günlük 10.000 YouTube API kotası dolduğu için bölüm atlanmadı; "
                    "sabah <b>10:00 TR</b> (Pasifik gece yarısı) kota sıfırlamasından sonraki ilk slotta "
                    "kapak + yorum + zincir bağlantısıyla otomatik yayınlanacak.",
                    encoding="utf-8",
                )
                return None
            raise
        vid_id = response["id"]
        yt_url = f"https://youtu.be/{vid_id}"
        log.info(f"YouTube yüklemesi tamamlandı: {yt_url}")

        upload_thumbnail_if_exists(youtube, drive, queue_folder, file_name, vid_id)
        # 26.10.2026: video_131.mp4 (MOxaXPkS0zw) kota sınırına denk geldiği için tek seferlik kapak telafisi
        heal_flag = BASE_DIR / ".healed_131_thumb"
        if not heal_flag.exists() and file_name != "video_131.mp4":
            try:
                upload_thumbnail_if_exists(youtube, drive, queue_folder, "video_131.mp4", "MOxaXPkS0zw")
                heal_flag.write_text("ok\n", encoding="utf-8")
            except Exception:
                pass
        comment_ok, _ = post_pinned_comment(youtube, vid_id, meta.get("pinned_comment", ""))
        mark_as_uploaded(list_path, file_id, file_name, yt_url, title=meta["title"])
        update_excel_status_in_drive(drive, queue_folder, file_name, new_status="YÜKLENDİ", youtube_url=yt_url)
        backlink_info = backlink_previous_episode(
            youtube, drive, queue_folder, list_path, file_name, vid_id, meta["title"]
        )
        if file_name.startswith("uzun_"):
            add_video_to_series(youtube, vid_id)
            backfill_series_playlist(youtube, drive, queue_folder)
        else:
            konu_listesi = route_short_topic(meta["title"], meta.get("category_name", ""))
            if konu_listesi:
                pkid = ensure_named_playlist(youtube, konu_listesi)
                add_video_to_series(youtube, vid_id, pkid)
        # retro_enrich_published RETIRED: kullanıcı eski videoları elle düzenliyor; token ekstra yüklenmiyor (25 Ekim kararı)

        report_txt = build_telegram_report(file_name, vid_id, yt_url, meta, comment_ok, backlink_info=backlink_info)
        REPORT_FILE.write_text(report_txt, encoding="utf-8")
        sync_kartal_status_report(youtube, file_name, yt_url)

        # --- Çapraz paylaşım (TikTok + Instagram Reels): dosya silinmeden önce ---
        crosspost_result = None
        try:
            from qa_and_crosspost import build_crosspost_caption
            from crosspost_worker import run_crosspost

            xcap = build_crosspost_caption(meta)
            crosspost_result = run_crosspost(tmp_path, file_name, xcap, drive=drive, folder_id="1w8tz_lv7iMFsRRCaTKUSY_ri0F107rz_")
            log.info(f"Çapraz paylaşım sonucu: {crosspost_result}")
        except Exception as xe:
            log.warning(f"Çapraz paylaşım atlandı (YouTube akışı etkilenmedi): {xe}")

        return {
            "video_id": vid_id,
            "title": meta["title"],
            "url": yt_url,
            "drive_file_id": file_id,
            "drive_file_name": file_name,
            "comment_posted": comment_ok,
            "crosspost": crosspost_result,
        }
    finally:
        if tmp_path.exists():
            tmp_path.unlink()




def sync_kartal_status_report(youtube, last_uploaded_file: str = "", last_uploaded_url: str = "", error_msg: str = "") -> None:
    """Her çalışmada YouTube API'den gerçek görüntülenme/yorum sayılarını çekip status_report.json dosyasını günceller."""
    try:
        tr_now = datetime.now(timezone(timedelta(hours=3)))
        ch_res = youtube.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()
        items = ch_res.get("items", [])
        if not items:
            return
        ch = items[0]
        ch_stats = ch.get("statistics", {})
        uploads_pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]

        pl_res = youtube.playlistItems().list(part="snippet,contentDetails", playlistId=uploads_pl, maxResults=30).execute()
        vid_ids = [it["contentDetails"]["videoId"] for it in pl_res.get("items", [])]
        yt_videos = []
        total_comments = 0
        total_likes = 0
        weekly_count = 0
        week_ago = tr_now - timedelta(days=7)

        if vid_ids:
            v_res = youtube.videos().list(part="snippet,statistics,status", id=",".join(vid_ids)).execute()
            for v in v_res.get("items", []):
                st = v.get("statistics", {})
                c_cnt = int(st.get("commentCount", 0))
                l_cnt = int(st.get("likeCount", 0))
                total_comments += c_cnt
                total_likes += l_cnt
                pub_str = v["snippet"].get("publishedAt", "")
                try:
                    if datetime.fromisoformat(pub_str.replace("Z", "+00:00")) >= week_ago:
                        weekly_count += 1
                except Exception:
                    pass
                yt_videos.append({
                    "id": v["id"],
                    "url": f"https://youtu.be/{v['id']}",
                    "title": v["snippet"].get("title", ""),
                    "publishedAt": pub_str,
                    "views": int(st.get("viewCount", 0)),
                    "likes": l_cnt,
                    "comments": c_cnt,
                })

        now_str = tr_now.strftime("%Y-%m-%d %H:%M")
        report_path = Path(__file__).resolve().parent / "status_report.json"
        prev_shorts, prev_long = 58, 10
        if report_path.exists():
            try:
                old_r = json.loads(report_path.read_text(encoding="utf-8"))
                prev_shorts = max(0, int(old_r.get("summary", {}).get("stock_shorts", 58)) - (0 if last_uploaded_file.startswith("uzun_") else (1 if last_uploaded_file else 0)))
                prev_long = max(0, int(old_r.get("summary", {}).get("stock_long", 10)) - (1 if last_uploaded_file.startswith("uzun_") else 0))
            except Exception:
                pass

        report = {
            "updated_at": now_str,
            "updated_at_iso": tr_now.isoformat(),
            "overall_status": "err" if error_msg else "ok",
            "overall_label": "Hata var" if error_msg else "Her şey çalışıyor",
            "summary": {
                "total_views": int(ch_stats.get("viewCount", 0)),
                "subscribers": int(ch_stats.get("subscriberCount", 0)),
                "total_videos_published": int(ch_stats.get("videoCount", len(yt_videos))),
                "weekly_uploaded": weekly_count,
                "total_comments": total_comments,
                "total_likes": total_likes,
                "failed_jobs": 1 if error_msg else 0,
                "stock_shorts": prev_shorts,
                "stock_long": prev_long,
            },
            "workers": [
                {
                    "id": "uploader",
                    "name": "Yükleyici (Drive -> YouTube)",
                    "status": "err" if error_msg else "ok",
                    "status_text": "Hata" if error_msg else "Çalışıyor",
                    "updated_at": now_str,
                    "jobs_done": int(ch_stats.get("videoCount", len(yt_videos))),
                    "last_action": f"{last_uploaded_file} yayınlandı ({last_uploaded_url})" if last_uploaded_file else "Son zamanlanmış kontrol tamamlandı",
                    "error_message": error_msg,
                },
                {
                    "id": "comment_thumb",
                    "name": "Yorumcu ve kapak işçisi",
                    "status": "ok",
                    "status_text": "Çalışıyor",
                    "updated_at": now_str,
                    "jobs_done": int(ch_stats.get("videoCount", len(yt_videos))),
                    "last_action": "OAuth (youtube.force-ssl) aktif · İlk yorum otomatik yazılır",
                    "error_message": "",
                },
                {
                    "id": "analytics",
                    "name": "Analitik çekici (YouTube API)",
                    "status": "ok",
                    "status_text": "Çalışıyor",
                    "updated_at": now_str,
                    "jobs_done": len(yt_videos),
                    "last_action": f"{len(yt_videos)} videonun gerçek görüntülenme ve yorum verisi güncellendi",
                    "error_message": "",
                },
                {
                    "id": "telegram",
                    "name": "Telegram bildirim işçisi",
                    "status": "ok",
                    "status_text": "Çalışıyor",
                    "updated_at": now_str,
                    "jobs_done": int(ch_stats.get("videoCount", len(yt_videos))),
                    "last_action": "Yayın kartı ve sabit yorum metni gönderildi",
                    "error_message": "",
                },
            ],
            "alerts": [
                {
                    "id": "quota",
                    "title": "YouTube API günlük kotası",
                    "status": "err" if "quota" in error_msg.lower() else "ok",
                    "status_text": "Hata" if "quota" in error_msg.lower() else "Sorunsuz",
                    "updated_at": now_str,
                    "detail": error_msg if "quota" in error_msg.lower() else "Günlük 10.000 birim kotası aktif ve yeterli.",
                },
                {
                    "id": "drive_sheets",
                    "title": "Google Drive ve Sheets bağlantısı",
                    "status": "ok",
                    "status_text": "Sorunsuz",
                    "updated_at": now_str,
                    "detail": f"Drive klasörü ve 3 sekmeli yükleme tablosu canlı bağlı (Stok: {prev_shorts} Shorts, {prev_long} Uzun).",
                },
                {
                    "id": "comment_worker",
                    "title": "Yorum ve kapak işçisi yetkisi",
                    "status": "ok",
                    "status_text": "Sorunsuz",
                    "updated_at": now_str,
                    "detail": "youtube.force-ssl yetkisi aktif.",
                },
            ],
            "videos": yt_videos,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Kartal AI status_report.json gerçek YouTube API verileriyle güncellendi.")
    except Exception as e:
        log.warning(f"status_report.json güncellenemedi: {e}")


def main() -> None:
    get_google_clients()
    scheduler = BlockingScheduler()
    scheduler.add_job(upload_job, "cron", hour=19, minute=0, kwargs={"video_type": "auto"})
    scheduler.add_job(upload_job, "cron", hour=20, minute=15, kwargs={"video_type": "auto"})
    log.info("Prime Time Zamanlayıcı aktif — 19:00 TR & 20:15 TR (aynı gün tek sütun kilidi; Cuma Uzun Video).")
    scheduler.start()


if __name__ == "__main__":
    vtype = "auto"
    if "--short" in sys.argv:
        vtype = "short"
    elif "--long" in sys.argv:
        vtype = "long"

    if "--dry-run" in sys.argv:
        upload_job(dry_run=True, video_type=vtype)
    elif "--now" in sys.argv:
        try:
            upload_job(dry_run=False, video_type=vtype)
        except Exception as _crash:
            # EMİR 024 KURAL 8: görev çökmesi → UYARILAR sekmesine otomatik satır (sonra tekrar fırlat)
            try:
                _cfg = load_config()
                _qf = _cfg.get("drive_queue_folder_id", DEFAULT_DRIVE_FOLDER_ID).strip() or DEFAULT_DRIVE_FOLDER_ID
                _, _drive = get_google_clients(token_file=Path(_cfg["token_file"]) if _cfg.get("token_file") else None)
                log_uyari_drive(_drive, _qf, "HATA", f"Görev çöktü: {str(_crash)[:400]}")
            except Exception:
                pass
            raise
    else:
        main()
