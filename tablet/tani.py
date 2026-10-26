#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kartal AI · ADB teşhis (tek komut, her şeyi ekrana döker)
Kullanım: python3 ~/kartal_kaynak/tablet/tani.py
"""
import os, re, socket, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

def sh(*a, t=25):
    try:
        r = subprocess.run(list(a), capture_output=True, text=True, timeout=t)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"(hata: {e})"

print("=" * 64)
print("1) adb sürümü / sunucu")
print(sh("adb", "version").strip().splitlines()[0] if sh("adb", "version").strip() else "adb YOK")
sh("adb", "kill-server", t=15)
time.sleep(0.5)

print("\n2) Cihaz IP'leri")
print(sh("termux-wifi-connectioninfo")[:400] if sh("termux-wifi-connectioninfo", t=10).startswith("{") else "(termux-api yok)")
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1))
    ip = s.getsockname()[0]; s.close()
except Exception:
    ip = "?"
print(f"   yerel IP: {ip}")

print("\n3) Termux içinde dinleyen portlar (/proc/net/tcp)")
ports = set()
for f in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        with open(f, errors="ignore") as fh:
            next(fh, None)
            for ln in fh:
                c = ln.split()
                if len(c) > 3 and c[3] == "0A":
                    try:
                        p = int(c[1].rsplit(":", 1)[1], 16)
                        if 1024 <= p <= 65535:
                            ports.add(p)
                    except Exception:
                        pass
    except Exception:
        pass
print("   " + (", ".join(map(str, sorted(ports))) or "(yok)"))

print("\n4) mDNS")
sh("adb", "mdns", "check", t=10)
print("   " + (sh("adb", "mdns", "services", t=12).strip() or "(boş)").replace("\n", "\n   "))

print(f"\n5) {ip} üzerinde 30000-65535 taraması (25 sn)")
open_ports = []
def probe(p):
    sk = socket.socket(); sk.settimeout(0.25)
    try:
        return p if sk.connect_ex((ip, p)) == 0 else None
    except Exception:
        return None
    finally:
        sk.close()
with ThreadPoolExecutor(max_workers=600) as ex:
    for p in ex.map(probe, range(30000, 65536)):
        if p:
            open_ports.append(p)
print("   açık portlar: " + (", ".join(map(str, open_ports)) or "(HİÇ YOK)"))

print("\n6) Her açık porta adb connect denemesi")
found = ""
for p in open_ports:
    out = sh("adb", "connect", f"{ip}:{p}", t=15).strip()
    time.sleep(0.6)
    devs = sh("adb", "devices")
    line = [l for l in devs.splitlines() if l.startswith(f"{ip}:{p}")]
    state = line[0].split()[-1] if line else "?"
    print(f"   {ip}:{p} → {state:12} | {out.splitlines()[-1] if out else ''}")
    if state == "device":
        found = f"{ip}:{p}"
        break

print("\n7) SONUÇ")
if found:
    print(f"   ✅ BAĞLANDI: {found}")
    env = os.path.expanduser("~/kartal_tablet/.env")
    os.makedirs(os.path.dirname(env), exist_ok=True)
    rows = [r for r in (open(env).read().splitlines() if os.path.exists(env) else []) if not r.startswith("ADB_TARGET=")]
    rows.append(f"ADB_TARGET={found}")
    open(env, "w").write("\n".join(rows) + "\n")
    print("   Hedef kaydedildi → bash ~/kartal_tablet/baslat.sh")
else:
    print("   ❌ Bağlantı yok. Şunları kontrol et:")
    print("      • Kablosuz hata ayıklama anahtarı AÇIK mı?")
    print("      • Anahtarın altındaki küçük yazıda 'IP adresi ve bağlantı noktası' var mı? (varsa portu yaz)")
    print("      • Ekranda 'Cihaz eşleştirme' tamamlandı mı? (Successfully paired)")
print("=" * 64)
