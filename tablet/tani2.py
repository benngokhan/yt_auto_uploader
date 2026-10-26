#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kartal AI · ADB teşhis v2 — tüm ağ arayüzlerini bulur ve her birini tarar.
Kullanım: python3 ~/kartal_kaynak/tablet/tani2.py
"""
import os, socket, subprocess, time
from concurrent.futures import ThreadPoolExecutor

def sh(*a, t=25):
    try:
        r = subprocess.run(list(a), capture_output=True, text=True, timeout=t)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"(hata: {e})"


def local_ips():
    """Kurulu komut olmadan tüm yerel IPv4 adreslerini bulur."""
    ips = set()
    # 1) termux-api
    out = sh("termux-wifi-connectioninfo", t=10)
    if out.strip().startswith("{"):
        import json, re
        try:
            ip = json.loads(out).get("ip", "")
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip or ""):
                ips.add(ip)
        except Exception:
            pass
    # 2) UDP numarası
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    # 3) /proc/net/fib_trie (komut gerekmez)
    try:
        with open("/proc/net/fib_trie", errors="ignore") as f:
            lines = f.read().splitlines()
        for i, ln in enumerate(lines):
            if "/32 host LOCAL" in ln and i > 0:
                for j in range(i - 1, max(i - 4, -1), -1):
                    t = lines[j].strip().lstrip("|-- ")
                    parts = t.split()
                    if parts and parts[0].count(".") == 3:
                        ips.add(parts[0])
                        break
    except Exception:
        pass
    # 4) /proc/net/route -> yerel arayüz IP (ip komutu yoksa son çare)
    try:
        out = sh("ip", "-4", "-o", "addr", t=8)
        import re
        for m in re.finditer(r"inet (\d{1,3}(?:\.\d{1,3}){3})", out):
            ips.add(m.group(1))
    except Exception:
        pass
    return sorted(i for i in ips if i and not i.startswith(("0.", "127.", "169.254.")))


print("=" * 68)
print("🧪 Kartal ADB Teşhis v2")
print("=" * 68)

sh("adb", "kill-server", t=15)
time.sleep(0.5)

ips = local_ips()
print("\n1) Bulunan yerel IP'ler:")
for i in ips:
    print("   •", i)
if not ips:
    print("   (HİÇ YOK — tablet ağa bağlı değil!)")

if any(i.startswith("10.136.") for i in ips) and len(ips) == 1:
    print("\n   ⚠️ 10.136.x.x = operatörün mobil veri IP'si (CGNAT).")
    print("      Kablosuz hata ayıklama MOBİL VERİ üzerinden ÇALIŞMAZ.")
    print("      → Tableti Wi-Fi'ye bağla (hotspot ya da ev Wi-Fi'si).")

print("\n2) mDNS durumu")
sh("adb", "mdns", "check", t=10)
m = sh("adb", "mdns", "services", t=12).strip()
print("   " + (m.replace("\n", "\n   ") if m else "(boş — hotspot multicast engelliyor olabilir, normal)"))

print("\n3) Port taraması (30000-65535, her IP için ~20 sn)")
def probe(host, p):
    sk = socket.socket(); sk.settimeout(0.22)
    try:
        return p if sk.connect_ex((host, p)) == 0 else None
    except Exception:
        return None
    finally:
        sk.close()

hits = []
for host in ips:
    print(f"   → {host} taranıyor…")
    got = []
    with ThreadPoolExecutor(max_workers=800) as ex:
        for p in ex.map(lambda p: probe(host, p), range(30000, 65536)):
            if p:
                got.append(p)
    print("     " + (", ".join(map(str, got)) if got else "(açık port yok)"))
    hits += [(host, p) for p in got]

print("\n4) adb connect denemeleri")
found = ""
for host, p in hits:
    out = sh("adb", "connect", f"{host}:{p}", t=15).strip()
    time.sleep(0.5)
    devs = sh("adb", "devices")
    line = [l for l in devs.splitlines() if l.startswith(f"{host}:{p}")]
    state = line[0].split()[-1] if line else "?"
    print(f"   {host}:{p} → {state:12} | {out.splitlines()[-1] if out else ''}")
    if state == "device":
        found = f"{host}:{p}"
        break

print("\n" + "=" * 68)
if found:
    print(f"✅ BAĞLANDI: {found}")
    env = os.path.expanduser("~/kartal_tablet/.env")
    os.makedirs(os.path.dirname(env), exist_ok=True)
    rows = [r for r in (open(env).read().splitlines() if os.path.exists(env) else []) if not r.startswith("ADB_TARGET=")]
    rows.append(f"ADB_TARGET={found}")
    open(env, "w").write("\n".join(rows) + "\n")
    print("   Kaydedildi → bash ~/kartal_tablet/baslat.sh")
else:
    print("❌ Açık port yok = adbd dinlemiyor. 3 ihtimal:")
    print("   A) Kablosuz hata ayıklama ANA ANAHTARI kapalı")
    print("      Ayarlar > Geliştirici seçenekleri > Kablosuz hata ayıklama  [AÇIK olacak]")
    print("   B) Tablet Wi-Fi'ye bağlı değil (sadece mobil veri)")
    print("      Sağ üstten Wi-Fi simgesi dolu mu? Hotspot'a bağlan.")
    print("   C) Anahtar açık ama port farklı yerde:")
    print("      'Kablosuz hata ayıklama' YAZISINA dokun → alt satırda 'IP adresi ve bağlantı noktası'")
print("=" * 68)
