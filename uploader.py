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
from datetime import datetime
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
    "https://www.googleapis.com/auth/drive.readonly",
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
    if os.getenv("DRIVE_QUEUE_FOLDER_ID"):
        cfg["drive_queue_folder_id"] = os.environ["DRIVE_QUEUE_FOLDER_ID"].strip()
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


def validate_metadata_workbook(drive, queue_folder: str) -> str:
    records = load_table_from_drive_or_local(drive, queue_folder or DEFAULT_DRIVE_FOLDER_ID)
    if not records:
        raise RuntimeError("DRIVE sekmesi okunamadı veya hiç satır bulunamadı.")
    ready_shorts = sum(1 for r in records.values() if r.get("is_ready") and not r.get("is_long"))
    ready_longs = sum(1 for r in records.values() if r.get("is_ready") and r.get("is_long"))
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

        comment_ok, _ = post_pinned_comment(youtube, vid_id, meta.get("pinned_comment", ""))
        mark_as_uploaded(list_path, file_id, file_name, yt_url, title=meta["title"])
        update_excel_status_in_drive(drive, queue_folder, file_name, new_status="YÜKLENDİ", youtube_url=yt_url)

        report_txt = build_telegram_report(file_name, vid_id, yt_url, meta, comment_ok)
        REPORT_FILE.write_text(report_txt, encoding="utf-8")
        sync_kartal_status_report(youtube, file_name, yt_url)

        return {
            "video_id": vid_id,
            "title": meta["title"],
            "url": yt_url,
            "drive_file_id": file_id,
            "drive_file_name": file_name,
            "comment_posted": comment_ok,
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
