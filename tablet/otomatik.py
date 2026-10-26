#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kartal AI · TEK KOMUT — sadece 6 haneli kodu yaz, gerisini kendi bulur
=====================================================================
Port aramaya, IP yazmaya son. Bu komut:
  1) adb sunucusunu önce ayağa kaldırır (protocol fault'un sebebi buydu)
  2) Açık portları tarar, eşleştirme servisini bulur
  3) Her açık porta `adb pair` dener, doğru olanı yakalar
  4) Eşleşince bağlanma portunu bulur ve bağlanır
  5) Hedefi .env'e yazar

Kullanım (eşleştirme penceresi açıkken, bölünmüş ekranda):
  python3 otomatik.py 934777
  python3 otomatik.py            # kodu sorar
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

G, Y, R, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m"
ENVF = Path.home() / "kartal_tablet" / ".env"


def ok(m):
    print(f"{G}✔{X} {m}")


def info(m):
    print(f"{Y}➜{X} {m}")


def err(m):
    print(f"{R}✘{X} {m}")


def adb(*args, timeout=45):
    try:
        r = subprocess.run(["adb", *args], capture_output=True, text=True, timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return f"(adb hatası: {e})"


def hosts() -> list[str]:
    out = ["127.0.0.1"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        if ip not in out:
            out.append(ip)
    except Exception:
        pass
    try:
        j = json.loads(subprocess.run(["termux-wifi-connectioninfo"], capture_output=True, text=True, timeout=10).stdout)
        ip = j.get("ip", "")
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip or "") and ip not in out:
            out.append(ip)
    except Exception:
        pass
    return out


def state_of(target: str) -> str:
    for ln in adb("devices", timeout=15).splitlines():
        if ln.startswith(target):
            return ln.split()[-1].strip()
    return ""


def scan(host: str, lo=30000, hi=65535) -> list[int]:
    found = []

    def probe(p):
        s = socket.socket()
        s.settimeout(0.22)
        try:
            return p if s.connect_ex((host, p)) == 0 else None
        except Exception:
            return None
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=900) as ex:
        for p in ex.map(probe, range(lo, hi + 1)):
            if p:
                found.append(p)
    return found


def save(target: str) -> None:
    ENVF.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in (ENVF.read_text(encoding="utf-8").splitlines() if ENVF.exists() else []) if not r.startswith("ADB_TARGET=")]
    rows.append(f"ADB_TARGET={target}")
    ENVF.write_text("\n".join(rows).strip() + "\n", encoding="utf-8")
    ENVF.chmod(0o600)
    ok(f"Hedef kaydedildi: {target}")


def main() -> int:
    print(f"{B}🦅 Kartal · tek komut eşleştirici{X}")
    print("-" * 62)

    code = ""
    for a in sys.argv[1:]:
        d = re.sub(r"\D", "", a)
        if len(d) == 6:
            code = d
            break
    if not code:
        code = re.sub(r"\D", "", input("6 haneli eşleştirme kodu: "))
    if len(code) != 6:
        err("Kod 6 haneli olmalı. Örn: python3 otomatik.py 934777")
        return 1

    info("adb sunucusu hazırlanıyor…")
    adb("kill-server", timeout=20)
    time.sleep(1)
    adb("start-server", timeout=30)
    ok("hazır")

    for h in hosts():
        info(f"{h} taranıyor…")
        ports = scan(h)
        print("   açık: " + (", ".join(map(str, ports)) or "(yok)"))
        if not ports:
            continue

        paired = False
        # Önce eşleştirmeyi dene (yanlış portlar hızlı reddeder)
        for p in ports:
            out = adb("pair", f"{h}:{p}", code, timeout=45)
            low = out.lower()
            if "successfully paired" in low:
                ok(f"EŞLEŞTİ → {h}:{p}")
                paired = True
                break
            if "wrong password" in low or "failed to pair" in low:
                info(f"{h}:{p} → kod tutmadı, devam")
        if not paired:
            info("Bu arayüzde eşleştirme servisi bulunamadı, sonraki adres…")
            continue

        # Bağlanma portunu bul
        info("Bağlanma portu aranıyor…")
        for p in ports:
            t = f"{h}:{p}"
            adb("disconnect", t, timeout=8)
            adb("connect", t, timeout=20)
            time.sleep(0.7)
            st = state_of(t)
            if st == "device":
                ok(f"BAĞLANDI: {t}")
                save(t)
                print(f"\n{B}Sıradaki:{X} bash ~/kartal_tablet/baslat.sh")
                return 0
            if st:
                info(f"{t} → {st}")
        err("Eşleşti ama bağlanma portu cevap vermedi. Kablosuz hata ayıklamayı kapat-aç, tekrar dene.")
        return 1

    err("Eşleştirme servisi bulunamadı.")
    print("  • Eşleştirme penceresi AÇIK ve ekranda görünür olsun (bölünmüş ekran)")
    print("  • Kod yeni üretilmiş olsun (2 dk ömür)")
    print("  • Kablosuz hata ayıklama anahtarı AÇIK olsun")
    return 1


if __name__ == "__main__":
    sys.exit(main())
