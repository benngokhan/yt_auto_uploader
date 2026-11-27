#!/usr/bin/env python3
"""Telegram önizleme + onay kapısı (kuyruğa yazmaz).

Akış:
  1) Üretim bitince final.mp4 + kapak.jpg Telegram'a dosya olarak gönderilir.
  2) Kullanıcı sohbete 'onayladım' yazınca getUpdates ile okunur.
  3) Yalnızca doğru sohbetten, önizlemeden SONRA gelen mesaj onay sayılır.

Gizlilik: token/chat_id/URL asla log'a veya dosyaya yazılmaz. Durum dosyasında
yalnızca son okunan update_id saklanır.
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.telegram.org/bot"
ONAY_KELIMESI = "onayladim"
_TIMEOUT = 30
_TR_KOCALE = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
                            "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"})


def _normalize(text: str) -> str:
    return str(text or "").strip().lower().translate(_TR_KOCALE)


class TelegramOnayHatasi(RuntimeError):
    pass


def _credentials() -> tuple[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        raise TelegramOnayHatasi("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID yok; önizleme gönderilemedi.")
    return token, chat


def _call(token: str, method: str, payload: dict | None = None) -> dict:
    url = f"{API}{token}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as yanit:
            body = json.loads(yanit.read().decode("utf-8"))
    except Exception as hata:  # noqa: BLE001 — hata gövdesi token/URL sızdırabilir
        raise TelegramOnayHatasi(f"Telegram {method} çağrısı başarısız ({type(hata).__name__})") from hata
    if not body.get("ok"):
        raise TelegramOnayHatasi(f"Telegram {method} yanıtı olumsuz")
    return body


def preview_metni(bilgi: dict) -> str:
    """Kısa, sade onay mesajı. Başlık/açıklama xlsx'e onaydan sonra yazılır."""
    satirlar = ["<b>BİLGİ DOZU — ONAY BEKLİYOR</b>"]
    if bilgi.get("video_numarasi"):
        satirlar.append(f"Sıra: video_{bilgi['video_numarasi']}")
    baslik = str(bilgi.get("baslik") or "").strip()
    if baslik:
        satirlar.append(f"Başlık: {baslik}")
    if bilgi.get("sure_sn"):
        satirlar.append(f"Süre: {bilgi['sure_sn']} sn")
    if bilgi.get("sahne_sayisi"):
        satirlar.append(f"Sahne: {bilgi['sahne_sayisi']} (şablonsal 7)")
    if bilgi.get("kaynak_video_id"):
        satirlar.append(f"Kaynak: {bilgi['kaynak_video_id']}")
    satirlar.append("Video ve kapak aşağıda. Onaylıyorsan yaz: <b>onayladım</b>")
    return "\n".join(satirlar)


def _multipart(fields: dict, files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    sinir = "----bilgidozu" + uuid.uuid4().hex
    parcalar: list[bytes] = []
    for anahtar, deger in fields.items():
        parcalar.append(
            f"--{sinir}\r\nContent-Disposition: form-data; name=\"{anahtar}\"\r\n\r\n{deger}\r\n".encode("utf-8")
        )
    for anahtar, yol in files:
        if not yol.is_file() or yol.stat().st_size == 0:
            raise TelegramOnayHatasi(f"Önizleme dosyası eksik/boş: {yol.name}")
        tur = mimetypes.guess_type(yol.name)[0] or "application/octet-stream"
        parcalar.append(
            f"--{sinir}\r\nContent-Disposition: form-data; name=\"{anahtar}\"; "
            f"filename=\"{yol.name}\"\r\nContent-Type: {tur}\r\n\r\n".encode("utf-8")
        )
        parcalar.append(yol.read_bytes())
        parcalar.append(b"\r\n")
    parcalar.append(f"--{sinir}--\r\n".encode("utf-8"))
    return b"".join(parcalar), f"multipart/form-data; boundary={sinir}"


def _upload(token: str, method: str, fields: dict, dosya_alani: str, yol: Path) -> dict:
    govde, icerik_turu = _multipart(fields, [(dosya_alani, yol)])
    req = urllib.request.Request(
        f"{API}{token}/{method}", data=govde,
        headers={"Content-Type": icerik_turu},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as yanit:
            body = json.loads(yanit.read().decode("utf-8"))
    except Exception as hata:  # noqa: BLE001
        raise TelegramOnayHatasi(f"Telegram {method} yüklemesi başarısız ({type(hata).__name__})") from hata
    if not body.get("ok"):
        raise TelegramOnayHatasi(f"Telegram {method} yüklemesi olumsuz yanıt verdi")
    return body


def gonder_onizleme(video: str | Path, kapak: str | Path, bilgi: dict) -> dict:
    """Video dosyasını ve kapağı ayrı ayrı gönderir; son update_id'yi durum dosyasına yazar."""
    token, chat = _credentials()
    video_yolu, kapak_yolu = Path(video), Path(kapak)
    caption = preview_metni(bilgi)
    video_yanit = _upload(
        token, "sendVideo",
        {"chat_id": chat, "caption": caption[:1024], "parse_mode": "HTML", "supports_streaming": "true"},
        "video", video_yolu,
    )
    _upload(token, "sendPhoto", {"chat_id": chat, "caption": "Kapak"}, "photo", kapak_yolu)
    durum = {
        "offset": int(video_yanit["result"]["update_id"]) if "update_id" in video_yanit.get("result", {}) else None,
        "gonderim_zamani": datetime.now(timezone.utc).isoformat(),
        "video_dosya_adi": video_yolu.name,
        "kapak_dosya_adi": kapak_yolu.name,
    }
    if durum["offset"] is None:
        guncel = _call(token, "getUpdates", {"offset": -1, "limit": 1})
        durum["offset"] = (guncel.get("result") or [{}])[0].get("update_id", 0)
    _durum_yaz(durum)
    return durum


def _durum_yolu() -> Path:
    return Path(os.getenv("TELEGRAM_ONAY_DURUM", "telegram_onay_durumu.json")).resolve()


def _durum_yaz(durum: dict) -> None:
    _durum_yolu().write_text(json.dumps(durum, ensure_ascii=False, indent=2), encoding="utf-8")


def _durum_oku() -> dict:
    yol = _durum_yolu()
    if not yol.is_file():
        raise TelegramOnayHatasi("Önizleme durumu yok; önce video/kapak gönderilmeli.")
    try:
        return json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TelegramOnayHatasi("Önizleme durumu okunamadı.") from exc


def onay_var_mi() -> bool:
    """Yalnızca doğru sohbetten ve kayıtlı update_id'den sonraki 'onayladım' mesajını kabul eder."""
    token, chat = _credentials()
    durum = _durum_oku()
    bos = durum.get("offset")
    if not isinstance(bos, int):
        raise TelegramOnayHatasi("Önizleme offset'i geçersiz; onay okunamadı.")
    yanit = _call(token, "getUpdates", {"offset": bos + 1, "timeout": 0, "limit": 100})
    en_yeni = bos
    onaylandi = False
    for guncel in yanit.get("result") or []:
        uid = guncel.get("update_id")
        if isinstance(uid, int) and uid > en_yeni:
            en_yeni = uid
        mesaj = guncel.get("message") or guncel.get("edited_message") or {}
        sohbet = str((mesaj.get("chat") or {}).get("id") or "")
        metin = _normalize(mesaj.get("text"))
        if sohbet == chat and metin == ONAY_KELIMESI:
            onaylandi = True
    durum["offset"] = en_yeni
    durum["son_kontrol"] = datetime.now(timezone.utc).isoformat()
    durum["onaylandi"] = onaylandi
    _durum_yaz(durum)
    return onaylandi


def bekle_ve_onayla(bekleme_sn: int = 300, aralik_sn: int = 10) -> bool:
    """Belirli süre 'onayladım' bekler; süre dolarsa False (kuyruğa yazılmaz)."""
    bitis = time.monotonic() + max(0, bekleme_sn)
    while True:
        if onay_var_mi():
            return True
        if time.monotonic() + max(1, aralik_sn) > bitis:
            return False
        time.sleep(max(1, aralik_sn))
