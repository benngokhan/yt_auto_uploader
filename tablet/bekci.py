#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kartal AI · BEKÇİ (watchdog)
============================
Tablet Wi-Fi'dan düşse bile sistemi ayakta tutar:
  * ADB bağlantısı kopunca otomatik yeniden bağlanır (kayıtlı hedef -> tarama)
  * Ajan süreci öldüyse yeniden başlatır
  * Telegram'a "bağlantı gitti/geldi" notu düşer (spam yapmaz)

Kullanım:
  python3 bekci.py              # sürekli çalışır (Termux'ta bırak)
  python3 bekci.py --fix        # tek seferlik: tablet Wi-Fi ayarlarını düzelt
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOME = Path.home()
KARTAL = HOME / "kartal_tablet"
ENVF = KARTAL / ".env"
LOG = KARTAL / "bekci.log"
CHECK_EVERY = 30
SCAN_EVERY = 300  # tarama en fazla 5 dk'da bir


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def env(key: str, default: str = "") -> str:
    if ENVF.exists():
        for line in ENVF.read_text(encoding="utf-8").splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv(key, default)


def adb(*args, timeout=25) -> str:
    try:
        r = subprocess.run(["adb", *args], capture_output=True, text=True, timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return f"(adb hatası: {e})"


def tg(text: str) -> None:
    token = env("TELEGRAM_BOT_TOKEN")
    chat = env("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    try:
        body = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body, headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=20)
    except Exception:
        pass


def live_target() -> str:
    for ln in adb("devices", timeout=15).splitlines():
        if ln.strip().endswith("\tdevice"):
            return ln.split("\t")[0].strip()
    return ""


def scan_connect() -> str:
    """Kayıtlı hedef -> bilinen arayüzler -> 30000-65535 taraması."""
    saved = env("ADB_TARGET")
    if saved:
        adb("connect", saved, timeout=20)
        time.sleep(0.8)
        if live_target():
            return saved
    hosts = ["127.0.0.1"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        if ip not in hosts:
            hosts.append(ip)
    except Exception:
        pass
    if saved and ":" in saved:
        h = saved.rsplit(":", 1)[0]
        if h not in hosts:
            hosts.append(h)

    def probe(args):
        h, p = args
        sk = socket.socket()
        sk.settimeout(0.22)
        try:
            return (h, p) if sk.connect_ex((h, p)) == 0 else None
        except Exception:
            return None
        finally:
            sk.close()

    jobs = [(h, p) for h in hosts for p in range(30000, 65536)]
    open_ports = []
    with ThreadPoolExecutor(max_workers=900) as ex:
        for r in ex.map(probe, jobs):
            if r:
                open_ports.append(r)
    for h, p in open_ports:
        t = f"{h}:{p}"
        adb("disconnect", t, timeout=8)
        adb("connect", t, timeout=15)
        time.sleep(0.6)
        if live_target():
            return t
    return ""


def fix_device_settings() -> None:
    """Tablet Wi-Fi'sini uyanık tutmaya çalış (shell erişimi gerekiyor)."""
    cmd = " && ".join([
        "settings put global wifi_sleep_policy 2",
        "settings put global mobile_data 0",
        "svc wifi enable",
        "settings put global stay_on_while_plugged_in 3",
    ])
    out = adb("shell", cmd, timeout=40)
    log(f"cihaz ayarları uygulandı: {out[:120]}")


def worker_alive() -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", "kartal_tablet_worker.py"], capture_output=True, text=True, timeout=10)
        return bool(r.stdout.strip())
    except Exception:
        return False


def start_worker() -> None:
    script = KARTAL / "kartal_tablet_worker.py"
    if not script.exists():
        log("ajan dosyası yok, başlatılamadı")
        return
    subprocess.Popen(
        [sys.executable, str(script)],
        stdout=open(KARTAL / "ajan.out", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log("ajan yeniden başlatıldı")


def main() -> None:
    KARTAL.mkdir(parents=True, exist_ok=True)

    if "--fix" in sys.argv:
        t = live_target() or scan_connect()
        if t:
            log(f"bağlı: {t}")
            fix_device_settings()
        else:
            log("bağlantı yok — --fix uygulanamadı")
        return

    log(f"bekçi başladı (kontrol {CHECK_EVERY}s)")
    was_up = bool(live_target())
    last_scan = 0.0
    while True:
        try:
            t = live_target()
            if not t:
                now = time.time()
                if now - last_scan > SCAN_EVERY:
                    last_scan = now
                    t = scan_connect()
                    if t:
                        log(f"yeniden bağlandı: {t}")
                        fix_device_settings()
                        tg(f"♻️ <b>Tablet yeniden bağlandı</b>\n<code>{t}</code>")
                        was_up = True
                    else:
                        if was_up:
                            tg("⚠️ <b>Tablet bağlantısı koptu</b> — yeniden bağlanmayı deniyorum (Wi-Fi düşmüş olabilir).")
                        was_up = False
                        log("bağlantı yok, sonraki turda tekrar denenecek")
            else:
                if not was_up:
                    log(f"bağlantı geldi: {t}")
                    was_up = True
                if not worker_alive():
                    log("ajan çalışmıyor → başlatılıyor")
                    start_worker()
        except KeyboardInterrupt:
            log("bekçi durduruldu")
            return
        except Exception as e:
            log(f"hata: {e}")
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    main()
