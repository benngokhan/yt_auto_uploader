#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kartal AI · Eşleştirme SONRASI otomatik bağlanıcı
=================================================
Eşleştirme yapıldıktan sonra adbd'nin bağlanma portu değişir.
Bu komut: 127.0.0.1 + cihazın tüm yerel IP'lerini tarar, bulduğu portlara
tek tek bağlanır, ilk çalışanı .env'e yazar.

Kullanım:
  python3 son.py                  # tam otomatik
  python3 son.py 36357            # sadece bu portu dene
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


def adb(*args, timeout=20):
    try:
        r = subprocess.run(["adb", *args], capture_output=True, text=True, timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return f"(adb hatası: {e})"


def state_of(target: str) -> str:
    for ln in adb("devices", timeout=12).splitlines():
        if ln.startswith(target):
            return ln.split()[-1].strip()
    return ""


def host_ips() -> list[str]:
    ips = ["127.0.0.1"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    out = adb("shell", "ip -4 -o addr", timeout=10)  # adb yoksa boş döner, zararsız
    for m in re.finditer(r"inet (\d{1,3}(?:\.\d{1,3}){3})", out):
        if m.group(1) not in ips:
            ips.append(m.group(1))
    try:
        j = subprocess.run(["termux-wifi-connectioninfo"], capture_output=True, text=True, timeout=10).stdout
        ip = json.loads(j).get("ip", "")
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip or "") and ip not in ips:
            ips.append(ip)
    except Exception:
        pass
    return ips


def scan(host: str, lo: int = 30000, hi: int = 65535) -> list[int]:
    open_ports: list[int] = []

    def probe(p: int):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.25)
        try:
            return p if s.connect_ex((host, p)) == 0 else None
        except Exception:
            return None
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=900) as ex:
        for p in ex.map(probe, range(lo, hi + 1)):
            if p:
                open_ports.append(p)
    return open_ports


def connect(target: str) -> str:
    adb("disconnect", target, timeout=8)
    out = adb("connect", target, timeout=20).lower()
    time.sleep(0.8)
    st = state_of(target)
    if st:
        return st
    if "failed to authenticate" in out or "pair" in out:
        return "auth"
    return ""


def save(target: str) -> None:
    ENVF.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in (ENVF.read_text(encoding="utf-8").splitlines() if ENVF.exists() else []) if not r.startswith("ADB_TARGET=")]
    rows.append(f"ADB_TARGET={target}")
    ENVF.write_text("\n".join(rows).strip() + "\n", encoding="utf-8")
    ENVF.chmod(0o600)
    ok(f"Hedef kaydedildi: {target}")


def main() -> int:
    print(f"{B}🦅 Kartal · eşleştirme sonrası bağlanıcı{X}")
    print("-" * 60)
    if adb("version").startswith("(adb hatası"):
        err("adb yok → pkg install android-tools")
        return 1
    adb("start-server")

    # 0) Zaten bağlı mı?
    for ln in adb("devices").splitlines():
        if ln.strip().endswith("\tdevice"):
            t = ln.split("\t")[0].strip()
            ok(f"Zaten bağlı: {t}")
            save(t)
            return 0

    manual = sys.argv[1].strip().split(":")[-1] if len(sys.argv) > 1 else ""

    if manual.isdigit():
        info(f"Verilen port deneniyor: 127.0.0.1:{manual}")
        st = connect(f"127.0.0.1:{manual}")
        if st == "device":
            ok(f"BAĞLANDI: 127.0.0.1:{manual}")
            save(f"127.0.0.1:{manual}")
            print(f"\n{B}Sıradaki:{X} bash ~/kartal_tablet/baslat.sh")
            return 0
        err(f"{manual} olmadı (durum: {st or 'kapalı'})")
        return 1

    ips = host_ips()
    info("Taranacak adresler: " + ", ".join(ips))
    found: list[tuple[str, int]] = []
    for h in ips:
        info(f"{h} taranıyor (30000-65535)… ~15 sn")
        ports = scan(h)
        if ports:
            print("   açık: " + ", ".join(map(str, ports)))
        found += [(h, p) for p in ports]

    if not found:
        err("Hiç açık port yok.")
        print("  → Tablette kablosuz hata ayıklamayı KAPAT-AÇ, ekrandaki yeni portu yaz:")
        print("     python3 ~/kartal_kaynak/tablet/son.py <PORT>")
        return 1

    for h, p in found:
        t = f"{h}:{p}"
        st = connect(t)
        if st == "device":
            ok(f"BAĞLANDI: {t}")
            save(t)
            print(f"\n{B}Sıradaki:{X} bash ~/kartal_tablet/baslat.sh")
            return 0
        info(f"{t} → {st or 'adbd değil'}")

    err("Açık portlar var ama adbd cevap vermedi.")
    print("  → Tablette kablosuz hata ayıklamayı KAPAT-AÇ (yeni port gelir), sonra:")
    print("     python3 ~/kartal_kaynak/tablet/son.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
