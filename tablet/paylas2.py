# -*- coding: utf-8 -*-
"""Kartal AI · Video yukleme/paylasim motoru
Link indirir -> galeriye kaydeder -> gercek content:// URI ile paylasim menusu acar.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

GALERI = Path("/sdcard/Movies")
INDIR = Path.home() / "kartal_tablet" / "indirilenler"


def _sh(cmd: str, timeout: int = 60) -> str:
    try:
        r = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return f"(hata: {e})"


def adb_shell(cmd: str, timeout: int = 60) -> str:
    try:
        r = subprocess.run(["adb", "shell", cmd], capture_output=True, text=True, timeout=timeout)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode != 0 and not out:
            raise RuntimeError("adb basarisiz")
        return out
    except Exception:
        return _sh(cmd, timeout)  # adb yoksa dogrudan dene (Termux icinde)


def drive_direct(url: str) -> str:
    """Google Drive paylasim linkini dogrudan indirme linkine cevirir."""
    m = re.search(r"/file/d/([A-Za-z0-9_-]{20,})", url) or re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", url)
    if not m:
        return url
    fid = m.group(1)
    return f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t"


def download(url: str, ad: str = "") -> Path | None:
    ad = ad or os.path.basename(urllib.parse.urlparse(url).path) or f"video_{int(time.time())}.mp4"
    if not ad.endswith(".mp4"):
        ad += ".mp4"
    INDIR.mkdir(parents=True, exist_ok=True)
    hedef = INDIR / ad
    if hedef.exists() and hedef.stat().st_size > 100_000:
        return hedef
    if "drive.google.com" in url:
        url = drive_direct(url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=180) as r, open(hedef, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        return hedef if hedef.stat().st_size > 50_000 else None
    except Exception:
        return None


def galeriye_kopyala(path: Path) -> Path:
    GALERI.mkdir(parents=True, exist_ok=True)
    hedef = GALERI / path.name
    _sh(f'cp -f "{path}" "{hedef}"')
    # medya tarayiciyi tetikle
    adb_shell(f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://{hedef}"', timeout=30)
    return hedef


def content_uri(dosya: Path) -> str:
    """Galerideki dosyanin content:// URI'sini bulur (share icin file:// yasak)."""
    for _ in range(6):
        out = adb_shell(
            "content query --uri content://media/external/video/media "
            "--projection _id:_data", timeout=40
        )
        for line in out.splitlines():
            if str(dosya) in line:
                m = re.search(r"_id=(\d+)", line)
                if m:
                    return f"content://media/external/video/media/{m.group(1)}"
        time.sleep(2)
        adb_shell(f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://{dosya}"', timeout=20)
    return ""


def paylas(path: Path) -> str:
    """Paylasim menusunu acar. Donen: durum metni."""
    uri = content_uri(path)
    if uri:
        out = adb_shell(
            f'am start -a android.intent.action.SEND -t video/mp4 '
            f'--eu android.intent.extra.STREAM "{uri}" --grant-read-uri-permission',
            timeout=45,
        )
        if "Error" not in out and "Exception" not in out:
            return f"OK|{uri}"
    # yedek: termux-share
    out = _sh(f'termux-share -a send -t video/mp4 "{path}"', timeout=90)
    if "yok" in out:
        return f"HATA|{out}"
    return f"OK|termux-share"


def ac_uygulama(paket: str) -> str:
    return adb_shell(f"monkey -p {paket} -c android.intent.category.LAUNCHER 1", timeout=40)


PAKETLER = {
    "youtube": "com.google.android.youtube",
    "studio": "com.google.android.apps.youtube.creator",
    "tiktok": "com.zhiliaoapp.musically",
    "instagram": "com.instagram.android",
}


# ---------------------------------------------------------------------------
# Yerel videolar: tablette zaten olan dosyalar (galeri/indirilenler)
# ---------------------------------------------------------------------------
ARAMA_YERLERI = [
    "/sdcard/Download",
    "/sdcard/Downloads",
    "/sdcard/Movies",
    "/sdcard/DCIM/Camera",
    "/sdcard/DCIM",
    "/sdcard/WhatsApp/Media/WhatsApp Video",
    "/sdcard/Telegram",
    "/sdcard/Video",
]
UZANTI = (".mp4", ".mkv", ".mov", ".webm", ".m4v", ".3gp")


def yerel_videolar(limit: int = 40) -> list[Path]:
    """Tablet hafizasindaki videolari bulur (yeni -> eski)."""
    bulunan: list[Path] = []
    for yer in ARAMA_YERLERI:
        kok = Path(yer)
        if not kok.exists():
            continue
        try:
            for f in kok.rglob("*"):
                try:
                    if f.is_file() and f.suffix.lower() in UZANTI and f.stat().st_size > 200_000:
                        bulunan.append(f)
                except Exception:
                    continue
        except Exception:
            continue
        if len(bulunan) >= limit * 4:
            break
    bulunan.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    # tekrarlari at
    gorulen, tekil = set(), []
    for f in bulunan:
        if f.name in gorulen:
            continue
        gorulen.add(f.name)
        tekil.append(f)
    return tekil[:limit]


def yerel_sec(sira: int) -> Path | None:
    liste = yerel_videolar()
    if not liste:
        return None
    if 1 <= sira <= len(liste):
        return liste[sira - 1]
    return None


def boyut_mb(p: Path) -> float:
    try:
        return round(p.stat().st_size / (1024 * 1024), 1)
    except Exception:
        return 0.0
