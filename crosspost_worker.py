# -*- coding: utf-8 -*-
"""
Bilgi Dozu Çapraz Paylaşım İşçisi (TikTok + Instagram Reels)
-----------------------------------------------------------
YouTube'a yüklenen her Shorts'u aynı anda TikTok ve Instagram Reels'e de atar.

Gerekli ortam değişkenleri (GitHub Secrets):
  IG_SESSIONID    -> Instagram sessionid çerezi (öncelikli)
  IG_USERNAME / IG_PASSWORD -> sessionid yoksa klasik giriş
  TIKTOK_SESSIONID -> TikTok sessionid çerezi
  CROSSPOST_ENABLED=false -> tüm çapraz paylaşımı anında kapatır (kilit anahtar)

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

# Platform limitleri
TIKTOK_MAX_CAPTION = 2100  # TikTok 2200 limiti; güvenli pay bırak
IG_MAX_CAPTION = 2100      # Reels 2200 limiti; güvenli pay bırak


def crosspost_enabled() -> bool:
    """Kilit anahtarı + en az bir platform kimliği var mı?"""
    flag = os.getenv("CROSSPOST_ENABLED", "true").strip().lower()
    if flag in ("0", "false", "no", "hayir", "hayır", "kapali", "kapalı"):
        return False
    has_ig = bool(os.getenv("IG_SESSIONID", "").strip()) or (
        bool(os.getenv("IG_USERNAME", "").strip()) and bool(os.getenv("IG_PASSWORD", "").strip())
    )
    has_tt = bool(os.getenv("TIKTOK_SESSIONID", "").strip())
    return has_ig or has_tt


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
    except Exception as e:  # Telegram hatası bile akışı bozmasın
        log.warning(f"Telegram çapraz paylaşım notu gönderilemedi: {e}")


def post_instagram(video_path: Path, caption: str) -> str | None:
    """Reels (clip) olarak Instagram'a yükler. Başarılıysa reel URL'si döner."""
    sid = os.getenv("IG_SESSIONID", "").strip()
    user = os.getenv("IG_USERNAME", "").strip()
    pw = os.getenv("IG_PASSWORD", "").strip()
    if not (sid or (user and pw)):
        log.info("Instagram kimliği yok (IG_SESSIONID / IG_USERNAME+IG_PASSWORD) -> atlanıyor.")
        return None
    try:
        from instagrapi import Client

        cl = Client()
        cl.delay_range = [2, 6]  # insanvari bekleme aralığı
        if sid:
            cl.login_by_sessionid(sid)
            log.info("Instagram: sessionid ile giriş yapıldı.")
        else:
            cl.login(user, pw)
            log.info("Instagram: kullanıcı adı/şifre ile giriş yapıldı.")
        media = cl.clip_upload(str(video_path), _trim_caption(caption, IG_MAX_CAPTION))
        code = getattr(media, "code", "") or ""
        url = f"https://www.instagram.com/reel/{code}/" if code else "https://www.instagram.com/bilgidozuofficial/"
        log.info(f"Instagram Reels yüklendi: {url}")
        return url
    except Exception as e:
        log.warning(f"Instagram yüklemesi başarısız: {e}")
        return f"HATA: {e}"


def _ensure_playwright_browser() -> None:
    """GitHub Actions üzerinde chromium'u ilk çalışmada kurar (idempotent)."""
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       check=True, timeout=420, capture_output=True)
    except Exception as e:
        log.warning(f"playwright chromium kurulumu: {e} (devam ediliyor, zaten kurulu olabilir)")


def post_tiktok(video_path: Path, caption: str) -> str | None:
    """sessionid çereziyle TikTok'a yükler. Başarılıysa None değil URL/ID döner."""
    sid = os.getenv("TIKTOK_SESSIONID", "").strip()
    if not sid:
        log.info("TikTok kimliği yok (TIKTOK_SESSIONID) -> atlanıyor.")
        return None
    try:
        _ensure_playwright_browser()
        from tiktok_uploader.upload import upload_video

        failed = upload_video(
            filename=str(video_path),
            description=_trim_caption(caption, TIKTOK_MAX_CAPTION),
            sessionid=sid,
            headless=True,
        )
        if failed:
            msg = f"HATA: tiktok-uploader başarısız liste döndü: {failed}"
            log.warning(msg)
            return msg
        url = "https://www.tiktok.com/@bilgidozuofficial"
        log.info(f"TikTok yüklendi: {url}")
        return url
    except Exception as e:
        log.warning(f"TikTok yüklemesi başarısız: {e}")
        return f"HATA: {e}"


def run_crosspost(video_path: Path, file_name: str, caption: str) -> dict:
    """Ana giriş: uygunsa IG + TikTok'a yükler, sonuçları raporlar."""
    results = {"instagram": None, "tiktok": None}

    if not crosspost_enabled():
        log.info("Çapraz paylaşım kapalı veya kimlik eksik -> atlanıyor.")
        return results

    # 16:9 uzun videolar TikTok/Reels formatına uymaz -> YouTube'a özel kalır
    if str(file_name).lower().startswith("uzun_"):
        log.info(f"{file_name} uzun (16:9) video -> TikTok/Reels'e çıkmaz, YouTube'a özel.")
        return results

    log.info(f"Çapraz paylaşım başladı: {file_name}")
    results["instagram"] = post_instagram(video_path, caption)
    results["tiktok"] = post_tiktok(video_path, caption)

    note_lines = []
    tt = results["tiktok"]
    ig = results["instagram"]
    if tt:
        ok = isinstance(tt, str) and not tt.startswith("HATA")
        note_lines.append(f"{'✅' if ok else '⚠️'} <b>TikTok:</b> {tt}")
    if ig:
        ok = isinstance(ig, str) and not ig.startswith("HATA")
        note_lines.append(f"{'✅' if ok else '⚠️'} <b>Instagram:</b> {ig}")
    _send_telegram_note(note_lines)

    log.info(f"Çapraz paylaşım bitti: {results}")
    return results
