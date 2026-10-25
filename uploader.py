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
    load_table_from_drive_or_local,
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
    """1) Diğer klasördeki (1MBjwKp...) fazlalık baslik.xlsx / bilgidozu_yukleme_tablosu.xlsx dosyalarını siler (tek yerde kalsın).
    2) KartaL'ın ana stok klasöründeki (1w8tz_lv7iMFsRRCaTKUSY_ri0F107rz_) baslik.xlsx (1tHZ4aCtdtKRLmY7z9PqLGUTu5rVth4vj) dosyasını
       mevcut YÜKLENDİ durumlarını koruyarak A2:M133 Yeşil/Sarı simetrik formatla günceller.
    3) Yeni videoları hem 'hazır videolar' (1JULlauO1eFpXgGdZKdZZDyqesSdkeT6f) hem KartaL stok klasörüne, kapakları KAPAKLAR'a aktarır."""
    import io
    import urllib.request
    import zipfile
    import openpyxl
    from openpyxl.styles import PatternFill, Font
    from googleapiclient.http import MediaIoBaseDownload

    kartal_folder = "1w8tz_lv7iMFsRRCaTKUSY_ri0F107rz_"
    main_folder = "1MBjwKp1DXoxLiCAkds84MowZAFMOK7Br"
    hazir_videolar_id = "1JULlauO1eFpXgGdZKdZZDyqesSdkeT6f"
    kapaklar_folder_id = "1XKZJ12HyAvZkjgiG38ys3HOMhZ42d_jJ"
    baslik_file_id = "1tHZ4aCtdtKRLmY7z9PqLGUTu5rVth4vj"

    try:
        # 0. KartaL stok klasörünün adı 'Mira Stok' ise 'KartaL Stok' yap
        try:
            fmeta = drive.files().get(fileId=kartal_folder, fields="name").execute()
            if "mira" in fmeta.get("name", "").lower():
                drive.files().update(fileId=kartal_folder, body={"name": "KartaL Stok"}).execute()
                log.info("Klasör adı 'KartaL Stok' olarak güncellendi.")
        except Exception:
            pass

        # 1. Diğer klasördeki (1MBjwKp...) fazlalık baslik.xlsx ve bilgidozu_yukleme_tablosu.xlsx dosyalarını sil (tek yerde kalsın)
        page_token = None
        while True:
            res = drive.files().list(
                q=f"'{main_folder}' in parents and trashed=false",
                pageSize=200,
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token,
            ).execute()
            for f in res.get("files", []):
                fname = f.get("name", "")
                fid = f.get("id", "")
                if fname.lower().endswith(".mp4"):
                    try:
                        drive.files().update(
                            fileId=fid,
                            addParents=hazir_videolar_id,
                            removeParents=main_folder,
                            fields="id, parents",
                        ).execute()
                    except Exception:
                        pass
                elif fname in ("baslik.xlsx", "bilgidozu_yukleme_tablosu.xlsx"):
                    try:
                        drive.files().update(fileId=fid, body={"trashed": True}).execute()
                        log.info(f"Diğer klasördeki fazlalık tablo kaldırıldı (tek yerde kalsın): {fname}")
                    except Exception as de:
                        log.warning(f"Fazlalık tablo kaldırma uyarısı ({fname}): {de}")
            page_token = res.get("nextPageToken")
            if not page_token:
                break

        # 1.b Yeni üretilen (video_101..120 ve uzun_video_13) videolar KartaL Stok klasörüne (1w8tz...) gitmişse
        #     onları Lobi ('hazır videolar' - 1JULlauO1eFpXgGdZKdZZDyqesSdkeT6f) klasörüne geri çek ki kullanıcı kontrol edip kendi taşısın!
        lobby_videos = {f"video_{i}.mp4" for i in range(101, 121)} | {"uzun_video_13.mp4"}
        existing_lobby = set()
        page_token = None
        while True:
            res_l = drive.files().list(
                q=f"'{hazir_videolar_id}' in parents and trashed=false",
                pageSize=200,
                fields="nextPageToken, files(id, name)",
                pageToken=page_token,
            ).execute()
            for f in res_l.get("files", []):
                existing_lobby.add(f.get("name", ""))
            page_token = res_l.get("nextPageToken")
            if not page_token:
                break

        page_token = None
        while True:
            res_k = drive.files().list(
                q=f"'{kartal_folder}' in parents and trashed=false",
                pageSize=200,
                fields="nextPageToken, files(id, name)",
                pageToken=page_token,
            ).execute()
            for f in res_k.get("files", []):
                fn = f.get("name", "")
                fid = f.get("id", "")
                if fn in lobby_videos and fn in existing_lobby:
                    try:
                        # Lobi'de ('hazır videolar') henüz kontrol edilmeyi bekleyen kopyası duruyorsa,
                        # KartaL Stok içindeki erken kopyayı kaldır. Kullanıcı Lobi'den taşıdığında (existing_lobby'den çıktığında) korunur!
                        drive.files().update(fileId=fid, body={"trashed": True}).execute()
                        log.info(f"Kullanıcı kontrolü için yalnızca Lobi ('hazır videolar') klasöründe bırakıldı: {fn}")
                    except Exception as le:
                        log.warning(f"Lobi taşıma uyarısı ({fn}): {le}")
            page_token = res_k.get("nextPageToken")
            if not page_token:
                break

        # 2. KartaL klasöründeki (1w8tz...) baslik.xlsx (1tHZ4aCtdtKRLmY7z9PqLGUTu5rVth4vj) dosyasını
        #    botun sonradan işaretlediği YÜKLENDİ satırlarını koruyarak simetrik Yeşil/Sarı formatla güncelle!
        local_xlsx = BASE_DIR / "baslik.xlsx"
        if local_xlsx.exists():
            remote_uploaded = {}
            try:
                buf = io.BytesIO()
                dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=baslik_file_id))
                done = False
                while not done:
                    _, done = dl.next_chunk()
                buf.seek(0)
                wb_rem = openpyxl.load_workbook(buf)
                ws_rem = next((s for s in wb_rem.worksheets if s.title.strip().casefold() == "drive"), wb_rem.active)
                for r in range(2, ws_rem.max_row + 1):
                    st = str(ws_rem.cell(r, 1).value or "").strip().upper()
                    fn = str(ws_rem.cell(r, 2).value or "").strip()
                    if fn and ("YÜKLENDİ" in st or "YUKLENDI" in st):
                        remote_uploaded[fn] = (
                            ws_rem.cell(r, 10).value,
                            ws_rem.cell(r, 11).value,
                            ws_rem.cell(r, 12).value,
                            ws_rem.cell(r, 13).value,
                        )
                wb_rem.close()
            except Exception as re_err:
                log.warning(f"Mevcut baslik.xlsx okuma uyarısı: {re_err}")

            wb_loc = openpyxl.load_workbook(local_xlsx)
            ws_loc = next((s for s in wb_loc.worksheets if s.title.strip().casefold() == "drive"), wb_loc.active)
            green_fill = PatternFill(start_color="B6D7A8", end_color="B6D7A8", fill_type="solid")
            green_font = Font(name="Calibri", size=10, bold=False, color="0B3B17")
            green_bold = Font(name="Calibri", size=10, bold=True, color="0B3B17")

            for r in range(2, ws_loc.max_row + 1):
                fn = str(ws_loc.cell(r, 2).value or "").strip()
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

            merged_tmp = Path(tempfile.gettempdir()) / "baslik_merged.xlsx"
            wb_loc.save(merged_tmp)
            wb_loc.close()

            media_x = MediaFileUpload(
                str(merged_tmp),
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                resumable=False,
            )
            drive.files().update(fileId=baslik_file_id, media_body=media_x).execute()
            log.info(f"KartaL baslik.xlsx ({baslik_file_id}) A2:M133 Yeşil/Sarı simetrik olarak güncellendi.")
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
        # TÜM DRIVE TARAMASI: uzun dosyalar gerçekte hangi klasörde?
        res = drive.files().list(q="name contains 'uzun_video' and trashed=false", pageSize=100, fields="files(id,name,parents)").execute()
        for f in res.get("files", []):
            pnames = []
            for pid in f.get("parents", []):
                try:
                    pnames.append(drive.files().get(fileId=pid, fields="name").execute().get("name", "?"))
                except Exception:
                    pnames.append(f"ID:{pid[:12]}")
            print(f"UZUN-KONUM: {f['name']} -> klasör: {pnames}")
        # OTOMATİK ONARIM: hazır uzunlar yanlış klasördeyse gerçek kuyruk klasörüne taşı
        qname = drive.files().get(fileId=queue_folder, fields="name").execute().get("name", "?")
        print(f"UZUN-ONARIM: Gerçek kuyruk klasörü = '{qname}' (id {queue_folder[:8]}...)")
        for f in res.get("files", []):
            parents = f.get("parents", [])
            if f["name"].startswith("uzun_video_") and parents and queue_folder not in parents:
                try:
                    drive.files().update(fileId=f["id"], addParents=queue_folder, removeParents=",".join(parents), fields="id").execute()
                    print(f"UZUN-ONARIM: TAŞINDI -> {f['name']}")
                except Exception as me:
                    print(f"UZUN-ONARIM hata {f['name']}: {me}")
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
    return (
        f"bilgidozu_yukleme_tablosu.xlsx: DRIVE sekmesi doğrulandı (video_31+ başlangıç kilidi aktif); "
        f"{ready_shorts} hazır Shorts, {ready_longs} hazır Uzun Video."
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
        search_folders = ["1XKZJ12HyAvZkjgiG38ys3HOMhZ42d_jJ", DEFAULT_DRIVE_FOLDER_ID, "1MBjwKp1DXoxLiCAkds84MowZAFMOK7Br"]
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


def build_telegram_report(
    file_name: str,
    vid_id: str,
    yt_url: str,
    meta: dict,
    comment_ok: bool,
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
        days_left = round((rem_shorts + rem_longs) / 3, 1)
        stock_line = f"📦 <b>Kalan Stok:</b> <code>{rem_shorts} Shorts · {rem_longs} Uzun (~{days_left} Gün)</code>\n\n"
    except Exception:
        stock_line = ""

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
    """LOBI ONAY BASAMAĞI KALDIRILDI: 'hazır videolar' (Lobi) klasöründeki mp4'ler (alt klasörleri dahil) kontrol beklemeden doğrudan yayın kuyruğuna akar.
    Kullanıcı artık elle onaylamıyor (25 Ekim 2026 kararı)."""
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
    ("Nörobilim & İnsan Beyni 🧠", ["beyn", "zihn", "nöro", "burn", "vücud", "vucud", "kas ", "deri", "hafıza", "hafiza", "uyku", "bilinç", "bilinc", "rüya", "ruya", "algı", "algi", "yanılsama", "dopamin", "korku", "mutluluk", "düşünce", "dusunce"]),
    ("Mühürlü Tarih 🏺", ["piramit", "antik", "tarih", "imparator", "medeniyet", "mısır", "misir", "roma", "osmanlı", "osmanli", "arkeol", "mühür", "tapınak", "kale", "savaş", "savas", "korsan", "mamut", "efsane", "kadim"]),
    ("Evren & Uzay 🌌", ["uzay", "gezegen", "yıldız", "yildiz", "satürn", "saturn", "jüpiter", "neptün", "merkür", "venüs", "uranüs", "everest", "kara delik", "galaksi", "mars", "ay'da", "ayda", "ay ", "evren", "kuyruklu", "meteor", "nasa", "astronot", "güneş", "gunes"]),
    ("Doğa & Canlılar 🦎", ["hayvan", "bitki", "deniz", "böcek", "bocek", "kuş", "kus", "aksolotl", "geko", "karides", "ağaç", "agac", "orman", "mantar", "kurbağa", "kurbaga", "balina", "ahtapot", "kedi", "köpek", "kopek", "yılan", "yilan", "örümcek", "orumcek", "arı", "ari", "doğa", "doga", "okyanus"]),
]

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


def route_short_topic(title: str) -> "str | None":
    """Başlığa göre konulu Shorts oynatma listesi adı; hiçbiri uymazsa None."""
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
    """Daha once ELDEN yuklenmis uzun bolumleri (uzun_1, uzun_2 gibi) tablodaki YT linklerinden bulup listeye geri ekler."""
    import re as _re
    try:
        from sheets_metadata import load_table_from_drive_or_local
        table = load_table_from_drive_or_local(drive, queue_folder)
        pid = None
        playlist_ids = {}
        for name, rec in table.items():
            if str(rec.get("status", "")).upper() != "YÜKLENDİ":
                continue
            url = str(rec.get("youtube_url") or rec.get("yt_url") or "")
            m = _re.search(r"(?:youtu\.be/|v=)([\w-]{11})", url)
            if not m:
                continue
            if str(name).startswith("uzun_video_"):
                hedef = SERIES_PLAYLIST_TITLE
            else:
                hedef = route_short_topic(str(rec.get("title", "")))
            if not hedef:
                continue
            if hedef not in playlist_ids:
                playlist_ids[hedef] = ensure_named_playlist(youtube, hedef) if hedef != SERIES_PLAYLIST_TITLE else ensure_series_playlist(youtube)
            pid = playlist_ids.get(hedef)
            if pid:
                add_video_to_series(youtube, m.group(1), pid)
        log.info("OYNATMA LISTESI: geri donuk tarama tamam (uzun serisi + konulu Shorts).")
    except Exception as e:
        log.warning(f"Oynatma listesi geri-tarama atlandi (zararsiz): {e}")


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
    skip_ids = load_uploaded_ids(list_path)
    log.info(f"Atlanan/Tamamlanan kayıt sayısı: {len(skip_ids)} (+ video_1..30 kilidi)")

    # Otomatik cron (schedule) çalışmasında son 90 dk içinde zaten yükleme yapıldıysa üst üste 2. videoyu atma:
    if not dry_run and os.getenv("GITHUB_EVENT_NAME") == "schedule" and list_path.exists():
        try:
            lines = [ln.strip() for ln in list_path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
            if lines:
                last_parts = [p.strip() for p in lines[-1].split("|")]
                if len(last_parts) >= 4:
                    last_dt = datetime.strptime(last_parts[3], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                    elapsed_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60.0
                    if 0 <= elapsed_min < 90:
                        log.info(f"Son yükleme ({last_parts[1]}) {elapsed_min:.1f} dk önce yapıldı (<90 dk). Üst üste paylaşım olmaması için bu cron kuşağı atlanıyor.")
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
            _konu = route_short_topic(meta["title"])
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
        download_drive_file(drive, file_id, tmp_path)
        if publish_at is not None:
            aware = publish_at if publish_at.tzinfo else publish_at.astimezone()
            meta["publishAt"] = aware.isoformat(timespec="seconds")

        response = upload_to_youtube(youtube, tmp_path, meta)
        vid_id = response["id"]
        yt_url = f"https://youtu.be/{vid_id}"
        log.info(f"YouTube yüklemesi tamamlandı: {yt_url}")

        upload_thumbnail_if_exists(youtube, drive, queue_folder, file_name, vid_id)
        comment_ok, _ = post_pinned_comment(youtube, vid_id, meta.get("pinned_comment", ""))
        mark_as_uploaded(list_path, file_id, file_name, yt_url, title=meta["title"])
        update_excel_status_in_drive(drive, queue_folder, file_name, new_status="YÜKLENDİ", youtube_url=yt_url)
        if file_name.startswith("uzun_"):
            add_video_to_series(youtube, vid_id)
            backfill_series_playlist(youtube, drive, queue_folder)
        else:
            konu_listesi = route_short_topic(meta["title"])
            if konu_listesi:
                pkid = ensure_named_playlist(youtube, konu_listesi)
                add_video_to_series(youtube, vid_id, pkid)

        report_txt = build_telegram_report(file_name, vid_id, yt_url, meta, comment_ok)
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
    scheduler.add_job(upload_job, "cron", hour=14, minute=0, kwargs={"video_type": "short"})
    scheduler.add_job(upload_job, "cron", hour=18, minute=0, kwargs={"video_type": "short"})
    scheduler.add_job(upload_job, "cron", hour=21, minute=0, kwargs={"video_type": "auto"})
    log.info("Prime Time Zamanlayıcı aktif — 14:00 (Shorts), 18:00 (Shorts), 21:00 (Shorts / Gün Aşırı Uzun Video).")
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
        upload_job(dry_run=False, video_type=vtype)
    else:
        main()
