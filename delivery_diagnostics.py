"""Dış platform sonuçlarını olduğundan başarılı göstermeden raporla.

Bu modül ağa çıkmaz, kimlik bilgisi okumaz ve yeni bir paylaşım yapmaz.
Yalnız çalıştırıcı zaten bir sonuç döndürdüyse kısa bir durum etiketi üretir.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("delivery_diagnostics")
MARKER = "🌍 <b>ÇAPRAZ PAYLAŞIM DURUMU</b>"


def classify(platform: str, result: object) -> str:
    """Asla bir yükleme sonucunu kamuya açık yayın olarak varsayma."""
    if result is None or result == "":
        return "Atlandı veya sonuç yok; doğrulanmadı."
    if not isinstance(result, str):
        return "Sonuç anlaşılamadı; doğrulanmadı."
    value = result.strip()
    if value.upper().startswith("HATA"):
        # Hata metni URL, oturum veya kişisel veri içerebilir: aynen yansıtma.
        return "Gönderim hatası; doğrulanmadı."
    try:
        u = urlparse(value)
        host = (u.hostname or "").lower()
    except ValueError:
        return "Sonuç anlaşılamadı; doğrulanmadı."
    if platform == "instagram" and host in {"instagram.com", "www.instagram.com"} and u.path.startswith("/reel/"):
        return "Reels yanıtı alındı; herkese açık yayın doğrulanmadı."
    if platform == "tiktok" and host in {"tiktok.com", "www.tiktok.com"}:
        return "Gönderim denemesi bildirildi; video yayını doğrulanmadı."
    return "Sonuç anlaşılamadı; doğrulanmadı."


def append_to_payload(path: Path, file_name: str, result: object) -> bool:
    """Mevcut Telegram yükleme kartına güvenli/ayrı durum ekle; yeni kart oluşturma.

    Uzun videolar tasarım gereği çapraz paylaşılmaz. Eksik kart, hatalı JSON veya
    belirsiz sonuçta sessizce hiçbir şeye dokunulmaz. Tekrar çağrı idempotenttir.
    """
    if str(file_name).lower().startswith("uzun_") or not path.is_file():
        return False
    # Kullanıcının bilinçli kapattığı işçileri başarısız iş gibi karta ekleme.
    if isinstance(result, dict) and result.get("status") == "disabled_by_user":
        return False
    if not isinstance(result, dict):
        result = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            return False
        original = payload["text"]
        if MARKER in original:
            return False
        status = (
            f"\n\n{MARKER}\n"
            f"Instagram: {classify('instagram', result.get('instagram'))}\n"
            f"TikTok: {classify('tiktok', result.get('tiktok'))}"
        )
        # Telegram metin sınırına yakınsa mevcut yayın kartını riske atma.
        if len(original) + len(status) > 3900:
            log.warning("Telegram kartı uzun: çapraz durum eklenmedi.")
            return False
        payload["text"] = original + status
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except (OSError, ValueError, TypeError):
        log.warning("Çapraz paylaşım durumu karta eklenemedi.")
        return False
