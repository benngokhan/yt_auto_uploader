#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kartal AI · eşleştir + bağlan (tek komut, Samsung One UI uyumlu)
===============================================================
One UI, eşleştirme penceresinden çıkınca kodu iptal eder. Bu yüzden:
  1) adb sunucusu ÖNCE başlatılır (daemon yarışı = 'protocol fault' sebebi)
  2) Pencerenin IP'si + localhost sırayla denenir
  3) Eşleşince bağlanma portu otomatik taranır (elle port gerekmez)

Kullanım (eşleştirme penceresi AÇIKKEN, bölünmüş ekranda):
  python3 esle2.py 39761 934777
  python3 esle2.py            # port + kod sorulur
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


def tcp_open(host: str, port: int, to: float = 3.0) -> bool:
    s = socket.socket()
    s.settimeout(to)
    try:
        return s.connect_ex((host, port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def state_of(target: str) -> str:
    for ln in adb("devices", timeout=15).splitlines():
        if ln.startswith(target):
            return ln.split()[-1].strip()
    return ""


def do_pair(port: str, code: str) -> str:
    """Döner: 'paired' | 'bad_code' | 'unreachable'"""
    tried = []
    for h in hosts():
        if not tcp_open(h, int(port)):
            tried.append(f"{h}:{port} (kapalı)")
            continue
        info(f"Eşleştiriliyor → {h}:{port}")
        out = adb("pair", f"{h}:{port}", code, timeout=60)
        low = out.lower()
        first = out.splitlines()[-1] if out else ""
        if "successfully paired" in low:
            ok(f"EŞLEŞTİ → {h}:{port}")
            return "paired"
        if "wrong password" in low or "failed" in low:
            err(f"Kod reddedildi: {first}")
            tried.append(f"{h}:{port} → kod reddedildi")
        else:
            err(f"Yanıt: {first}")
            tried.append(f"{h}:{port} → {first}")
    print("   denenen: " + "; ".join(tried))
    return "bad_code"


def scan_ports(host: str, lo=30000, hi=65535) -> list[int]:
    found = []

    def probe(p):
        s = socket.socket()
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
                found.append(p)
    return found


def connect_any(prefer: str = "") -> str:
    """Açık portları tarayıp ilk çalışan adb bağlantısını kurar."""
    cands: list[tuple[str, int]] = []
    if prefer.isdigit():
        for h in hosts():
            cands.append((h, int(prefer)))
    for h in hosts():
        info(f"{h} taranıyor…")
        ports = scan_ports(h)
        if ports:
            print("   açık: " + ", ".join(map(str, ports[:20])))
        cands += [(h, p) for p in ports]

    seen = set()
    for h, p in cands:
        t = f"{h}:{p}"
        if t in seen:
            continue
        seen.add(t)
        adb("disconnect", t, timeout=8)
        adb("connect", t, timeout=20)
        time.sleep(0.8)
        st = state_of(t)
        if st == "device":
            return t
        if st:
            info(f"{t} → {st}")
    return ""


def save(target: str) -> None:
    ENVF.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in (ENVF.read_text(encoding="utf-8").splitlines() if ENVF.exists() else []) if not r.startswith("ADB_TARGET=")]
    rows.append(f"ADB_TARGET={target}")
    ENVF.write_text("\n".join(rows).strip() + "\n", encoding="utf-8")
    ENVF.chmod(0o600)
    ok(f"Hedef kaydedildi: {target}")


def main() -> int:
    print(f"{B}🦅 Kartal · eşleştir + bağlan{X}")
    print("-" * 62)

    # 0) Sunucuyu ÖNCE ayağa kaldır (protocol fault'un asıl sebebi: yarış)
    adb("kill-server", timeout=20)
    time.sleep(1)
    adb("start-server", timeout=30)
    ok("adb sunucusu hazır")

    pair_port = sys.argv[1].strip().split(":")[-1] if len(sys.argv) > 1 else ""
    code = re.sub(r"\D", "", sys.argv[2]) if len(sys.argv) > 2 else ""

    if not pair_port.isdigit():
        pair_port = input("Eşleştirme portu (pencerede 10.x.x.x:PORT → PORT): ").strip().split(":")[-1]
    if len(code) != 6:
        code = re.sub(r"\D", "", input("6 haneli kod: "))

    if not pair_port.isdigit() or len(code) != 6:
        err("Geçersiz giriş.")
        return 1

    res = do_pair(pair_port, code)
    if res != "paired":
        print()
        err("Eşleşme olmadı. En sık 3 sebep:")
        print("  1) Kod/pencere kapandı → pencereyi AÇ, kodu DEĞİŞTİĞİ AN yaz")
        print("  2) 'adb start-server' önce çalışmadı → bu komut artık kendi yapıyor, tekrar dene")
        print("  3) Yanlış port → penceredeki PORT'u kullan (bağlanma portu DEĞİL)")
        return 1

    print()
    info("Bağlanma portu aranıyor (eşleşme sonrası port değişir)…")
    target = connect_any()
    if not target:
        err("Eşleşti ama bağlanma portu bulunamadı.")
        print("  Penceredeki 'IP adresi ve bağlantı noktası' portunu oku:")
        print("  python3 ~/kartal_kaynak/tablet/esle2.py ile tekrar dene ya da")
        print("  adb connect 127.0.0.1:PORT")
        return 1

    ok(f"BAĞLANDI: {target}")
    save(target)
    print()
    print(f"{B}Sıradaki:{X} bash ~/kartal_tablet/baslat.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
