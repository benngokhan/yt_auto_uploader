#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kartal AI · tani3 — bağlanma portunu ıskalıyorsak nedenini gösterir.
Kullanım:
  python3 tani3.py            # ekrandaki portu sorar
  python3 tani3.py 36357      # portu verir
"""
from __future__ import annotations
import json, os, re, socket, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

G, Y, R, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m"
ok = lambda m: print(f"{G}✔{X} {m}")
info = lambda m: print(f"{Y}➜{X} {m}")
err = lambda m: print(f"{R}✘{X} {m}")


def adb(*a, t=25):
    try:
        r = subprocess.run(["adb", *a], capture_output=True, text=True, timeout=t)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return f"(adb hatası: {e})"


def ips():
    out = ["127.0.0.1"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1))
        out.append(s.getsockname()[0]); s.close()
    except Exception:
        pass
    try:
        j = json.loads(subprocess.run(["termux-wifi-connectioninfo"], capture_output=True, text=True, timeout=10).stdout)
        if j.get("ip") and j["ip"] not in out:
            out.append(j["ip"])
    except Exception:
        pass
    try:
        r = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, timeout=8)
        for m in re.finditer(r"inet (\d{1,3}(?:\.\d{1,3}){3})", r.stdout):
            if m.group(1) not in out:
                out.append(m.group(1))
    except Exception:
        pass
    # /proc/net/fib_trie (ip komutu yoksa)
    try:
        lines = open("/proc/net/fib_trie", errors="ignore").read().splitlines()
        for i, ln in enumerate(lines):
            if "/32 host LOCAL" in ln:
                for j in range(i - 1, max(i - 4, -1), -1):
                    t = lines[j].strip().lstrip("|-- ").split()
                    if t and t[0].count(".") == 3 and t[0] not in out:
                        out.append(t[0]); break
    except Exception:
        pass
    return [i for i in out if i and not i.startswith(("0.", "169.254."))]


def open_p(host, port, to=1.2):
    s = socket.socket(); s.settimeout(to)
    try:
        return s.connect_ex((host, port)) == 0
    except Exception:
        return False
    finally:
        s.close()


print(f"{B}🦅 Kartal · tani3{X}")
print("=" * 66)

print("\n1) ADB sunucu sıfırlanıyor…")
adb("kill-server", t=15)
time.sleep(1)
print("   " + adb("version").splitlines()[0])
adb("start-server", t=20)

key = os.path.expanduser("~/.android/adbkey")
print(f"\n2) Eşleştirme anahtarı: {'VAR ✔ ' + key if os.path.exists(key) else 'YOK ✘ (önce esle.py çalıştır)'}")

hosts = ips()
print("\n3) Yerel adresler: " + ", ".join(hosts))

port = sys.argv[1].strip().split(":")[-1] if len(sys.argv) > 1 else ""
if not port.isdigit():
    port = input("\nTablet ekranındaki bağlanma portu (ör. 36357): ").strip().split(":")[-1]
if not port.isdigit():
    err("Port geçersiz."); sys.exit(1)

print(f"\n4) Port {port} erişilebilir mi?")
reach = [(h, open_p(h, int(port))) for h in hosts]
for h, r in reach:
    print(f"   {h}:{port} → {'AÇIK' if r else 'kapalı'}")

print("\n5) adb connect denemeleri (çıktı aynen)")
best = ""
for h in hosts:
    t = f"{h}:{port}"
    out = adb("connect", t, t=25)
    time.sleep(1)
    devs = adb("devices")
    line = [l for l in devs.splitlines() if l.startswith(t)]
    st = line[0].split()[-1] if line else "yok"
    print(f"   {t:24} → {st:13} | {out.splitlines()[-1] if out else ''}")
    if st == "device":
        best = t

print("\n6) Ekran portu kapalıysa: 30000-65535 taraması (yalnız 127.0.0.1)")
if not best:
    def probe(p):
        s = socket.socket(); s.settimeout(0.25)
        try:
            return p if s.connect_ex(("127.0.0.1", p)) == 0 else None
        except Exception:
            return None
        finally:
            s.close()
    with ThreadPoolExecutor(max_workers=900) as ex:
        cand = [p for p in ex.map(probe, range(30000, 65536)) if p]
    print("   açık: " + (", ".join(map(str, cand)) or "(yok)"))
    for p in cand[:25]:
        t = f"127.0.0.1:{p}"
        adb("connect", t, t=15); time.sleep(0.4)
        line = [l for l in adb("devices").splitlines() if l.startswith(t)]
        if line and line[0].strip().endswith("device"):
            best = t; break
    print("   sonuç: " + (best or "adbd bulunamadı"))

print("\n" + "=" * 66)
if best:
    ok(f"BAĞLANDI: {best}")
    env = os.path.expanduser("~/kartal_tablet/.env")
    os.makedirs(os.path.dirname(env), exist_ok=True)
    rows = [r for r in (open(env).read().splitlines() if os.path.exists(env) else []) if not r.startswith("ADB_TARGET=")]
    rows.append(f"ADB_TARGET={best}")
    open(env, "w").write("\n".join(rows) + "\n")
    print(f"\n{B}Sıradaki:{X} bash ~/kartal_tablet/baslat.sh")
else:
    err("Bağlanamadı. Ekran görüntüsünü ve bu çıktıyı gönder.")
print("=" * 66)
