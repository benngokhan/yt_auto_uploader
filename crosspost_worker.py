# -*- coding: utf-8 -*-
"""
Bilgi Dozu Çapraz Paylaşım İşçisi (TikTok + Instagram Reels)
-----------------------------------------------------------
Sahip onayıyla (27.11.2026) yalnızca TikTok yeniden etkindir; Instagram kapalı kalır.
Eski oturumlar kullanılmaz: gönderim için güncel TIKTOK_SESSIONID gerekir.
Önceki kapatma kararı (01.11.2026) nedeniyle global ana kilit ve platform
bayrakları birlikte kontrol edilir; kapalı olan platforma hiç istek gidilmez.

Ortam değişkenleri:
  CROSSPOST_ENABLED=false -> tüm çapraz paylaşımı anında kapatır (ana kilit)
  TIKTOK_ENABLED=true     -> TikTok paylaşımı (ayrıca TIKTOK_SESSIONID gerekli)
  INSTAGRAM_ENABLED=false -> Instagram kapalı (sahip kararı; değiştirilmez)
  TIKTOK_SESSIONID        -> TikTok sessionid çerezi (Drive keys dosyasından da okunur)
  IG_SESSIONID / IG_USERNAME / IG_PASSWORD -> Instagram kimlikleri (şu an kullanılmaz)

Kurallar:
  * Sadece 9:16 Shorts'lar paylaşılır; 16:9 uzun videolar (uzun_*) YouTube'a özeldir.
  * Herhangi bir platform hatası YouTube akışını ASLA bozmaz; sadece log + Telegram notu düşer.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("crosspost")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

# Ana klasör (active.sav81@gmail.com / Bilgi_Dozu_Yeni_Shorts)
STOCK_FOLDER_ID = "1ttP8K3VHtqaNtdSlWjqIFza8Kzf0wxpC"
KEYS_FILE_NAME = "crosspost_keys.json"

# Sahip kararı: Instagram kalıcı olarak kapalı. TikTok yalnızca açık onay sonrası,
# güncel bir oturumla ve platform bayrağı açıkken kullanılır.
INSTAGRAM_DISABLED_BY_USER = True


def _load_drive_keys(drive=None, folder_id: str = "") -> dict:
    """GitHub YAML'sine dokunmadan anahtar taşımak için Drive'daki crosspost_keys.json'u okur.
    (Kullanıcı bu küçük dosyayı telefonundan KartaL Stok klasörüne atar; bot her turda oradan okur.)"""
    if drive is None or not folder_id:
        return {}
    try:
        import io
        import json as _json

        q = f"'{folder_id}' in parents and name='{KEYS_FILE_NAME}' and trashed=false"
        res = drive.files().list(q=q, fields="files(id,name,modifiedTime)", orderBy="modifiedTime desc", pageSize=1).execute()
        files = res.get("files", [])
        if not files:
            log.info(f"Drive'da {KEYS_FILE_NAME} bulunamadı -> yalnızca env anahtarları kullanılacak.")
            return {}
        from googleapiclient.http import MediaIoBaseDownload

        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, drive.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = downloader.next_chunk()
        keys = _json.loads(buf.getvalue().decode("utf-8"))
        log.info(f"{KEYS_FILE_NAME} Drive'dan okundu (anahtarlar: {[k for k, v in keys.items() if v]})")
        return keys
    except Exception as e:
        log.warning("Drive anahtar dosyası okunamadı: %s", type(e).__name__)
        return {}


def _hydrate_env_from_keys(keys: dict) -> None:
    """Drive'dan gelen anahtarları, env'de EKSİKSE os.environ'a enjekte eder (env her zaman öncelikli)."""
    for k in ("CROSSPOST_ENABLED", "TIKTOK_ENABLED", "INSTAGRAM_ENABLED", "IG_SESSIONID", "IG_USERNAME", "IG_PASSWORD", "TIKTOK_SESSIONID", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        v = str(keys.get(k, "")).strip()
        if v and not os.getenv(k, "").strip():
            os.environ[k] = v


# Platform limitleri
TIKTOK_MAX_CAPTION = 2100  # TikTok 2200 limiti; güvenli pay bırak
IG_MAX_CAPTION = 2100      # Reels 2200 limiti; güvenli pay bırak


_FALSEY = {"0", "false", "no", "hayir", "hayır", "kapali", "kapalı"}


def _flag_on(name: str, default: str = "false") -> bool:
    """Ortam bayrağını oku; boş ve bilinmeyen değerler kapalı sayılır."""
    value = os.getenv(name, default).strip().lower()
    return bool(value) and value not in _FALSEY


def _tiktok_session() -> str:
    """TIKTOK_SESSIONID değerini oku; 'sessionid=' öneki/tırnak varsa temizle."""
    raw = os.getenv("TIKTOK_SESSIONID", "").strip()
    low = raw.lower()
    for prefix in ("sessionid=", "sessionid:"):
        if low.startswith(prefix):
            raw = raw[len(prefix):].strip()
            break
    return raw.strip('"').strip("'")


def _tiktok_ready() -> bool:
    return _flag_on("TIKTOK_ENABLED") and bool(_tiktok_session())


def _instagram_ready() -> bool:
    if INSTAGRAM_DISABLED_BY_USER or not _flag_on("INSTAGRAM_ENABLED"):
        return False
    return bool(os.getenv("IG_SESSIONID", "").strip()) or (
        bool(os.getenv("IG_USERNAME", "").strip()) and bool(os.getenv("IG_PASSWORD", "").strip())
    )


def crosspost_enabled() -> bool:
    """Ana kilit + platform bayrakları + oturumlar birlikte kontrol edilir."""
    return _flag_on("CROSSPOST_ENABLED") and (_tiktok_ready() or _instagram_ready())


def _trim_caption(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _send_telegram_note(lines: list[str]) -> None:
    """Çapraz paylaşım sonucunu Telegram'a kısa not olarak düşer (opsiyonel)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id or not lines:
        return
    try:
        import json
        import urllib.request

        msg = "🌍 <b>ÇAPRAZ PAYLAŞIM (TikTok · Instagram)</b>\n" + "\n".join(lines)
        payload = json.dumps({
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:  # URL/yanıtlar gizli bilgi içerebilir; ayrıntıyı yazdırma.
        log.warning("Telegram çapraz paylaşım notu gönderilemedi: %s", type(e).__name__)


def post_instagram(video_path: Path, caption: str) -> str | None:
    """Reels (clip) olarak Instagram'a yükler. Başarılıysa reel URL'si döner."""
    if INSTAGRAM_DISABLED_BY_USER or not _flag_on("INSTAGRAM_ENABLED"):
        log.info("Instagram paylaşımı kapalı (sahip kararı / bayrak).")
        return None
    sid = os.getenv("IG_SESSIONID", "").strip()
    user = os.getenv("IG_USERNAME", "").strip()
    pw = os.getenv("IG_PASSWORD", "").strip()
    if not (sid or (user and pw)):
        log.info("Instagram kimliği yok (IG_SESSIONID / IG_USERNAME+IG_PASSWORD) -> atlanıyor.")
        return None
    try:
        # ffmpeg zırhı: imageio-ffmpeg pip paketi binary getirir; instagrapi/moviepy onu bulsun
        try:
            import imageio_ffmpeg
            os.environ.setdefault("IMAGEIO_FFMPEG_EXE", imageio_ffmpeg.get_ffmpeg_exe())
        except Exception as ffe:
            log.warning(f"imageio-ffmpeg bulunamadı: {ffe}")
        from instagrapi import Client

        cl = Client()
        cl.delay_range = [2, 6]  # insanvari bekleme aralığı
        if sid:
            try:
                cl.login_by_sessionid(sid)
            except Exception:
                from urllib.parse import unquote
                cl.login_by_sessionid(unquote(sid))  # %3A kodlu ham çerez yedeği
            log.info("Instagram: sessionid ile giriş yapıldı.")
        else:
            cl.login(user, pw)
            log.info("Instagram: kullanıcı adı/şifre ile giriş yapıldı.")
        media = cl.clip_upload(str(video_path), _trim_caption(caption, IG_MAX_CAPTION))
        code = getattr(media, "code", "") or ""
        url = f"https://www.instagram.com/reel/{code}/" if code else "https://www.instagram.com/bilgidozuofficial/"
        log.info("Instagram yükleme yanıtı alındı; herkese açık görünürlük doğrulanmadı.")
        return url
    except Exception as e:
        log.warning("Instagram yüklemesi başarısız: %s", type(e).__name__)
        return f"HATA: {type(e).__name__}"


def _ensure_playwright_browser() -> None:
    """GitHub Actions üzerinde chromium'u ilk çalışmada kurar (idempotent)."""
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       check=True, timeout=420, capture_output=True)
    except Exception as e:
        log.warning(f"playwright chromium kurulumu: {e} (devam ediliyor, zaten kurulu olabilir)")


def post_tiktok(video_path: Path, caption: str) -> str | None:
    """sessionid çereziyle TikTok'a yükler. Başarılıysa None değil URL/ID döner."""
    if not _flag_on("TIKTOK_ENABLED"):
        log.info("TikTok bayrağı kapalı -> atlanıyor.")
        return None
    sid = _tiktok_session()
    if not sid:
        log.info("TikTok kimliği yok (TIKTOK_SESSIONID) -> atlanıyor.")
        return None
    try:
        _ensure_playwright_browser()
        from tiktok_uploader.upload import upload_video

        # tiktok-uploader 1.2.0 sessionid cookie'sini domain'siz ekleyip patlıyor;
        # domain+path içeren cookies_list formatıyla bypass ediyoruz
        cookies_list = [
            {"name": "sessionid", "value": sid, "domain": ".tiktok.com", "path": "/"},
        ]
        failed = upload_video(
            filename=str(video_path),
            description=_trim_caption(caption, TIKTOK_MAX_CAPTION),
            cookies_list=cookies_list,
            headless=True,
        )
        if failed:
            msg = "HATA: TikTok yükleme kütüphanesi başarısız sonucu döndürdü"
            log.warning(msg)
            return msg
        url = "https://www.tiktok.com/@bilgidozuofficial"
        log.info("TikTok gönderim denemesi tamamlandı; herkese açık gönderi henüz doğrulanmadı.")
        return url
    except Exception as e:
        log.warning("TikTok yüklemesi başarısız: %s", type(e).__name__)
        return f"HATA: {type(e).__name__}"


def run_crosspost(video_path: Path, file_name: str, caption: str, drive=None, folder_id: str = "") -> dict:
    """Ana giriş: uygunsa IG + TikTok'a yükler, sonuçları raporlar."""
    results = {"instagram": None, "tiktok": None}
    # Env'de ana kilit açıkça kapatılmışsa Drive anahtarları bu kararı geçersiz kılamaz.
    if os.getenv("CROSSPOST_ENABLED", "").strip() and not _flag_on("CROSSPOST_ENABLED"):
        log.info("Çapraz paylaşım ana kilidi kapalı; oturumlar okunmadı.")
        return {**results, "status": "disabled_by_user"}

    # Env'de anahtar yoksa Drive'daki crosspost_keys.json'dan hidre et (GitHub workflow YAML'si kilitli)
    if not crosspost_enabled() and drive is not None:
        _hydrate_env_from_keys(_load_drive_keys(drive, folder_id or STOCK_FOLDER_ID))

    if not _flag_on("CROSSPOST_ENABLED"):
        log.info("Çapraz paylaşım ana kilidi kapalı.")
        return {**results, "status": "disabled_by_user"}

    if not crosspost_enabled():
        log.info("Çapraz paylaşım kapalı veya kimlik eksik -> atlanıyor.")
        return results

    # 16:9 uzun videolar TikTok/Reels formatına uymaz -> YouTube'a özel kalır
    if str(file_name).lower().startswith("uzun_"):
        log.info(f"{file_name} uzun (16:9) video -> TikTok/Reels'e çıkmaz, YouTube'a özel.")
        return results

    log.info(f"Çapraz paylaşım başladı: {file_name}")
    if _instagram_ready():
        results["instagram"] = post_instagram(video_path, caption)
    if _tiktok_ready():
        results["tiktok"] = post_tiktok(video_path, caption)

    # Yalnız API yanıtı veya genel profil adresi herkese açık yayının kanıtı değildir.
    # Telegram notuna hata gövdesi veya kimlik bilgisi içerebilecek ham değer ekleme.
    from delivery_diagnostics import classify
    note_lines = [
        f"ℹ️ <b>TikTok:</b> {classify('tiktok', results['tiktok'])}",
        f"ℹ️ <b>Instagram:</b> {classify('instagram', results['instagram'])}",
    ]
    _send_telegram_note(note_lines)

    log.info(f"Çapraz paylaşım bitti: {results}")
    return results
