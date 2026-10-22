"""
YouTube Auto Uploader — Google Drive Edition
Flow: Drive folder + baslik.xlsx / DRIVE → match prepared metadata → YouTube upload
"""

import io
import json
import logging
import os
import socket
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Give Google API calls 60 s to connect — default Windows timeout is too short for Indian ISPs
socket.setdefaulttimeout(60)

from apscheduler.schedulers.blocking import BlockingScheduler
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR     = Path(__file__).parent
LOG_DIR      = BASE_DIR / "logs"
TOKEN_FILE   = BASE_DIR / "token.json"
SECRETS_FILE = BASE_DIR / "client_secrets.json"
CONFIG_FILE  = BASE_DIR / "config.json"

# Drive read-only is enough — we never move or delete files, just download them
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/drive.readonly",
]

DRIVE_VIDEO_MIME = "video/"  # matches all video/* MIME types

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            LOG_DIR / f"uploader_{datetime.now().strftime('%Y%m')}.log",
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "upload_time":          "09:00",   # HH:MM local time
    "privacy_status":       "public",   # prepared metadata defaults to public unless DRIVE row overrides it
    "default_category":     "22",      # fallback YouTube category ID
    "gemini_api_key":       "",        # aistudio.google.com/app/apikey
    "gemini_extra_prompt":  "",        # extra instructions for Gemini
    "drive_queue_folder_id": "",       # Drive folder ID where your videos live
    "drive_done_folder_id":  "",       # Drive folder ID to move uploaded videos to
}

# YouTube category IDs Gemini can choose from:
# 1 Film&Animation | 2 Autos | 10 Music | 15 Pets | 17 Sports | 19 Travel
# 20 Gaming | 22 People&Blogs | 23 Comedy | 24 Entertainment | 25 News
# 26 Howto&Style | 27 Education | 28 Science&Tech


def load_config() -> dict:
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg.update(json.load(f))
    # Environment variables override config.json for secrets
    if os.getenv("GEMINI_API_KEY"):
        cfg["gemini_api_key"] = os.getenv("GEMINI_API_KEY")
    if os.getenv("GROQ_API_KEY"):
        cfg["groq_api_key"] = os.getenv("GROQ_API_KEY")
    return cfg


# ---------------------------------------------------------------------------
# Google OAuth — single sign-in for both Drive + YouTube
# ---------------------------------------------------------------------------
def get_google_clients(token_file: Path = None, force_reauth: bool = False):
    """Returns (youtube, drive) API clients. token_file overrides default TOKEN_FILE."""
    _token = Path(token_file) if token_file else TOKEN_FILE

    if not SECRETS_FILE.exists():
        raise FileNotFoundError(
            "client_secrets.json not found.\n"
            "  1. console.cloud.google.com → create project\n"
            "  2. Enable: YouTube Data API v3  +  Google Drive API\n"
            "  3. OAuth consent screen → External → add your Gmail as test user\n"
            "  4. Credentials → Create OAuth 2.0 Client ID (Desktop app)\n"
            "  5. Download JSON → save as client_secrets.json next to uploader.py\n"
            "  OR paste it in the Settings panel at http://localhost:8000"
        )

    creds = None
    if not force_reauth and _token.exists():
        creds = Credentials.from_authorized_user_file(str(_token), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing Google token…")
            creds.refresh(Request())
        else:
            log.info("Opening browser for Google sign-in (YouTube + Drive)…")
            flow = InstalledAppFlow.from_client_secrets_file(SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        _token.parent.mkdir(parents=True, exist_ok=True)
        with open(_token, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        log.info(f"Token saved → {_token}")

    youtube = build("youtube", "v3", credentials=creds)
    drive   = build("drive",   "v3", credentials=creds)
    return youtube, drive


# ---------------------------------------------------------------------------
# Uploaded-list helpers  (local text file, one Drive file ID per line)
# ---------------------------------------------------------------------------
def load_uploaded_ids(list_path: Path) -> set:
    """Return set of Drive file IDs already uploaded, read from list_path."""
    if not list_path.exists():
        return set()
    ids = set()
    with open(list_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                ids.add(line.split("|")[0].strip())
    return ids


def mark_as_uploaded(list_path: Path, file_id: str, file_name: str, yt_url: str) -> None:
    """Append one record to the uploaded list."""
    list_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(list_path, "a", encoding="utf-8") as f:
        if list_path.stat().st_size == 0:
            f.write("# YT Auto Uploader — uploaded video log\n")
            f.write("# Format: drive_file_id | filename | youtube_url | uploaded_at\n")
            f.write("# Delete a line to allow that video to be re-uploaded.\n\n")
        f.write(f"{file_id} | {file_name} | {yt_url} | {ts}\n")


# ---------------------------------------------------------------------------
# Google Drive helpers
# ---------------------------------------------------------------------------
def get_next_drive_video(drive, folder_id: str, skip_ids: set = None) -> dict | None:
    """Return the oldest non-uploaded video in the Drive folder."""
    skip_ids   = skip_ids or set()
    page_token = None
    while True:
        for attempt in range(3):
            try:
                result = drive.files().list(
                    q=(f"'{folder_id}' in parents "
                       f"and mimeType contains '{DRIVE_VIDEO_MIME}' "
                       f"and trashed = false"),
                    orderBy="name",
                    pageSize=100,
                    fields="nextPageToken, files(id, name, mimeType, size)",
                    **( {"pageToken": page_token} if page_token else {} ),
                ).execute()
                break
            except (TimeoutError, OSError) as e:
                if attempt < 2:
                    log.warning(f"Drive API timeout (attempt {attempt+1}/3), retrying in 30s… ({e})")
                    time.sleep(30)
                else:
                    raise
        for f in result.get("files", []):
            if f["id"] not in skip_ids:
                return f
        page_token = result.get("nextPageToken")
        if not page_token:
            return None


def download_drive_file(drive, file_id: str, dest_path: Path) -> None:
    """Download a Drive file to dest_path, logging progress."""
    request    = drive.files().get_media(fileId=file_id)
    buf        = io.FileIO(str(dest_path), "wb")
    downloader = MediaIoBaseDownload(buf, request, chunksize=8 * 1024 * 1024)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            log.info(f"  Drive download: {int(status.progress() * 100)}%")
    buf.close()


# ---------------------------------------------------------------------------
# Excel metadata — read prepared metadata from baslik.xlsx / DRIVE
# ---------------------------------------------------------------------------
def _normalise_header(value) -> str:
    import re
    import unicodedata
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _find_column(headers: dict, aliases: list[str]):
    for alias in aliases:
        key = _normalise_header(alias)
        if key in headers:
            return headers[key]
    return None


def _find_metadata_workbook(drive, queue_folder: str) -> dict:
    files, page_token = [], None
    while True:
        kwargs = {"q": "name = 'baslik.xlsx' and trashed = false", "pageSize": 100,
                  "fields": "nextPageToken,files(id,name,parents,modifiedTime,mimeType)"}
        if page_token:
            kwargs["pageToken"] = page_token
        result = drive.files().list(**kwargs).execute()
        files.extend(result.get("files", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    in_queue = [f for f in files if queue_folder in f.get("parents", [])]
    if len(in_queue) == 1:
        return in_queue[0]
    if len(in_queue) > 1:
        raise RuntimeError("Video klasöründe birden fazla baslik.xlsx bulundu; yükleme durduruldu.")
    if len(files) == 1:
        return files[0]
    if not files:
        raise RuntimeError("Google Drive'da baslik.xlsx bulunamadı; yükleme durduruldu.")
    raise RuntimeError("Birden fazla baslik.xlsx bulundu; doğru tabloyu seçmek için dosyayı video klasörüne koy.")


def _load_metadata_rows(drive, queue_folder: str):
    from openpyxl import load_workbook
    workbook_file = _find_metadata_workbook(drive, queue_folder)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as temp:
        workbook_path = Path(temp.name)
    try:
        download_drive_file(drive, workbook_file["id"], workbook_path)
        workbook = load_workbook(workbook_path, read_only=True, data_only=True)
        try:
            sheet = next((ws for ws in workbook.worksheets if ws.title.strip().casefold() == "drive"), None)
            if sheet is None:
                raise RuntimeError("baslik.xlsx içinde 'DRIVE' sekmesi bulunamadı.")
            rows = list(sheet.iter_rows(values_only=True))
            for header_index, row in enumerate(rows[:10]):
                headers = {_normalise_header(v): i for i, v in enumerate(row) if v is not None and str(v).strip()}
                title_col = _find_column(headers, ["Başlık", "Baslik", "Title", "YouTube Title", "Video Başlığı"])
                file_col = _find_column(headers, ["Dosya Adı", "Dosya Adi", "Filename", "File Name", "Video Filename", "Video File Name", "Video Adı", "Video Adi", "Drive File Name"])
                id_col = _find_column(headers, ["Drive File ID", "Drive ID", "File ID", "Dosya ID", "Dosya Kimliği"])
                if title_col is not None and (file_col is not None or id_col is not None):
                    return headers, rows[header_index + 1:], workbook_file.get("name", "baslik.xlsx")
            raise RuntimeError("DRIVE sekmesinde başlık ve dosya adı/Drive ID sütunları bulunamadı; yükleme durduruldu.")
        finally:
            workbook.close()
    finally:
        try:
            workbook_path.unlink()
        except OSError:
            pass


def validate_metadata_workbook(drive, queue_folder: str) -> str:
    _, rows, workbook_name = _load_metadata_rows(drive, queue_folder)
    count = sum(1 for row in rows if any(v is not None and str(v).strip() for v in row))
    return f"{workbook_name}: DRIVE sekmesi ve eşleştirme sütunları doğrulandı; {count} veri satırı."


def load_excel_metadata(drive, queue_folder: str, file_id: str, file_name: str, config: dict) -> dict:
    headers, rows, _ = _load_metadata_rows(drive, queue_folder)
    title_col = _find_column(headers, ["Başlık", "Baslik", "Title", "YouTube Title", "Video Başlığı"])
    file_col = _find_column(headers, ["Dosya Adı", "Dosya Adi", "Filename", "File Name", "Video Filename", "Video File Name", "Video Adı", "Video Adi", "Drive File Name"])
    id_col = _find_column(headers, ["Drive File ID", "Drive ID", "File ID", "Dosya ID", "Dosya Kimliği"])
    desc_col = _find_column(headers, ["Açıklama", "Aciklama", "Description", "YouTube Description"])
    tags_col = _find_column(headers, ["Etiketler", "Etiket", "Tags", "Hashtags"])
    category_col = _find_column(headers, ["Kategori ID", "Category ID", "Category", "Kategori"])
    privacy_col = _find_column(headers, ["Gizlilik", "Privacy", "Privacy Status", "Visibility", "Görünürlük"])
    selected = None
    for row in rows:
        row_file = str(row[file_col]).strip() if file_col is not None and file_col < len(row) and row[file_col] is not None else ""
        row_id = str(row[id_col]).strip() if id_col is not None and id_col < len(row) and row[id_col] is not None else ""
        if (row_id == file_id and row_id) or (row_file.casefold() == file_name.casefold() and row_file):
            selected = row
            break
    if selected is None:
        raise RuntimeError(f"baslik.xlsx / DRIVE sekmesinde '{file_name}' eşleşmesi yok; video yüklenmedi.")
    def cell(column, default=""):
        return selected[column] if column is not None and column < len(selected) and selected[column] is not None else default
    title = str(cell(title_col)).strip()
    if not title:
        raise RuntimeError(f"baslik.xlsx içinde '{file_name}' başlığı boş; video yüklenmedi.")
    raw_tags = str(cell(tags_col)).strip()
    tags = [t.strip().lstrip("#") for t in raw_tags.replace(";", ",").replace("\n", ",").split(",") if t.strip()]
    privacy_raw = str(cell(privacy_col, config.get("privacy_status", "public"))).strip().lower()
    privacy_map = {"public":"public", "herkese açık":"public", "herkese acik":"public", "acik":"public",
                   "unlisted":"unlisted", "liste dışı":"unlisted", "liste disi":"unlisted",
                   "private":"private", "gizli":"private"}
    privacy = privacy_map.get(privacy_raw, config.get("privacy_status", "public"))
    if privacy not in {"public", "unlisted", "private"}:
        privacy = "public"
    category = str(cell(category_col, config.get("default_category", "27"))).strip() or str(config.get("default_category", "27"))
    return {"title":title, "description":str(cell(desc_col)).strip(), "tags":tags,
            "categoryId":category, "privacyStatus":privacy}


# ---------------------------------------------------------------------------
# YouTube upload
# ---------------------------------------------------------------------------
def upload_to_youtube(youtube, video_path: Path, meta: dict) -> dict:
    # YouTube requires privacyStatus="private" when publishAt is set
    privacy = "private" if meta.get("publishAt") else meta["privacyStatus"]
    body = {
        "snippet": {
            "title":       meta["title"],
            "description": meta["description"],
            "tags":        meta.get("tags", []),
            "categoryId":  meta["categoryId"],
        },
        "status": {
            "privacyStatus": privacy,
        },
    }
    if meta.get("publishAt"):
        body["status"]["publishAt"] = meta["publishAt"]

    media = MediaFileUpload(
        str(video_path),
        chunksize=4 * 1024 * 1024,
        resumable=True,
    )

    req      = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            log.info(f"  YouTube upload: {int(status.progress() * 100)}%")
    return response


# ---------------------------------------------------------------------------
# Daily job
# ---------------------------------------------------------------------------
def upload_job(channel_config: dict = None, publish_at=None) -> "dict | None":
    """Upload one video. publish_at is an aware datetime for scheduled publishing."""
    log.info("─" * 60)
    log.info("Upload job triggered")

    config       = channel_config if channel_config is not None else load_config()
    token_file   = Path(config["token_file"]) if config.get("token_file") else None
    queue_folder = config.get("drive_queue_folder_id", "").strip()
    list_path    = Path(config.get("uploaded_list", str(BASE_DIR / "uploaded.txt")))

    if not queue_folder:
        log.error(
            "drive_queue_folder_id not set.\n"
            "  Open your Drive folder → copy the ID from the URL:\n"
            "  https://drive.google.com/drive/folders/THIS_IS_THE_ID"
        )
        return None

    youtube, drive = get_google_clients(token_file=token_file)

    # Load already-uploaded IDs and skip them
    skip_ids = load_uploaded_ids(list_path)
    log.info(f"Uploaded so far: {len(skip_ids)} videos")

    video_file = get_next_drive_video(drive, queue_folder, skip_ids=skip_ids)
    if not video_file:
        log.info("No new videos in Drive folder — all have been uploaded.")
        return None

    file_id   = video_file["id"]
    file_name = video_file["name"]
    file_size = int(video_file.get("size", 0))
    log.info(f"Next video: {file_name} ({file_size / 1_048_576:.1f} MB)")

    suffix = Path(file_name).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        log.info("Downloading from Google Drive…")
        download_drive_file(drive, file_id, tmp_path)
        log.info("Download complete.")

        # Use the prepared Excel row; never invent fallback metadata.
        meta = load_excel_metadata(drive, queue_folder, file_id, file_name, config)
        log.info(f"  Title   : {meta['title']}")
        log.info(f"  Privacy : {meta['privacyStatus']}")

        if publish_at is not None:
            aware = publish_at if publish_at.tzinfo else publish_at.astimezone()
            meta["publishAt"] = aware.isoformat(timespec='seconds')
            log.info(f"  Scheduled for: {aware.strftime('%Y-%m-%d %H:%M %Z')}")

        response = upload_to_youtube(youtube, tmp_path, meta)
        vid_id   = response["id"]
        yt_url   = f"https://youtu.be/{vid_id}"
        log.info(f"YouTube upload complete! {yt_url}")

        # Record in uploaded list — video stays on Drive untouched
        mark_as_uploaded(list_path, file_id, file_name, yt_url)
        log.info(f"Recorded in uploaded list: {list_path.name}")

        return {"video_id": vid_id, "title": meta["title"], "url": yt_url,
                "drive_file_id": file_id, "drive_file_name": file_name}

    except HttpError as e:
        log.error(f"Google API error: {e}")
        raise
    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
        raise
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
            log.info("Temp file deleted.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    config       = load_config()
    upload_time  = config.get("upload_time", "09:00")
    hour, minute = map(int, upload_time.split(":"))

    log.info("=" * 60)
    log.info("YouTube Auto Uploader  (Google Drive + AI metadata)")
    log.info(f"  Drive queue folder : {config.get('drive_queue_folder_id') or 'NOT SET'}")
    log.info(f"  Upload time        : {upload_time} (local)")
    log.info(f"  Privacy            : {config['privacy_status']}")
    log.info("  Metadata source    : baslik.xlsx / DRIVE")
    log.info("=" * 60)

    log.info("Verifying Google credentials (YouTube + Drive)…")
    get_google_clients()
    log.info("Credentials OK.")

    scheduler = BlockingScheduler()
    scheduler.add_job(upload_job, "cron", hour=hour, minute=minute)
    log.info(f"Scheduler running — uploads daily at {upload_time}. Press Ctrl+C to stop.")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    if "--now" in sys.argv:
        upload_job()
    else:
        main()
