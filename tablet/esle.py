#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kartal AI · Aynı cihazdan (localhost) kablosuz ADB eşleştirme + bağlanma
=======================================================================
Neden localhost? Termux da tabletin içinde çalıştığı için 127.0.0.1 her zaman
erişilebilir; mobil veri / CGNAT IP'si (10.136.x.x) sorun olmaktan çıkar.

Kullanım:
  python3 esle.py 36357                    # sadece bağlanmayı dene (port ekrandan)
  python3 esle.py 36357 41234              # 41234 = eşleştirme portu (kod sorulur)
  python3 esle.py 36357 41234 483920       # kod da verilir -> tam otomatik
"""
from __future__ import annotations

import re
import subprocess
import sys
import time

G, Y, R, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m"


def ok(m):
    print(f"{G}✔{X} {m}")


def info(m):
    print(f"{Y}➜{X} {m}")


def err(m):
    print(f"{R}✘{X} {m}")


def adb(*args, timeout=40):
    try:
        r = subprocess.run(["adb", *args], capture_output=True, text=True, timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return f"(adb hatası: {e})"


def state_of(target: str) -> str:
    for ln in adb("devices", timeout=15).splitlines():
        if ln.startswith(target):
            return ln.split()[-1].strip()
    return ""


def save(target: str) -> None:
    from pathlib import Path

    env = Path.home() / "kartal_tablet" / ".env"
    env.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in (env.read_text(encoding="utf-8").splitlines() if env.exists() else []) if not r.startswith("ADB_TARGET=")]
    rows.append(f"ADB_TARGET={target}")
    env.write_text("\n".join(rows).strip() + "\n", encoding="utf-8")
    env.chmod(0o600)
    ok(f"Hedef kaydedildi: {target}")


def try_connect(port: str) -> str:
    """127.0.0.1:port üzerinden bağlanmayı dener. 'device' | 'auth' | 'fail' döner."""
    for host in ("127.0.0.1", "localhost"):
        target = f"{host}:{port}"
        adb("disconnect", target, timeout=10)
        out = adb("connect", target, timeout=20).lower()
        time.sleep(1.0)
        st = state_of(target)
        if st == "device":
            return "device"
        if st in ("unauthorized", "offline"):
            return "auth"
        if "failed to authenticate" in out or "authentication" in out or "pair" in out:
            return "auth"
        if "cannot" in out or "unable" in out or "refused" in out:
            continue
    return "fail"


def do_pair(pair_port: str, code: str) -> bool:
    code = re.sub(r"\D", "", code or "")
    if len(code) < 6:
        err("Kod 6 haneli olmalı (ör. 483920).")
        return False
    for host in ("127.0.0.1", "localhost"):
        target = f"{host}:{pair_port}"
        info(f"Eşleştiriliyor: {target}")
        out = adb("pair", target, code, timeout=60)
        print("   " + out.replace("\n", "\n   "))
        if "uccess" in out:
            ok("Eşleştirme başarılı.")
            return True
    return False


def main() -> int:
    print(f"{B}🦅 Kartal · localhost ADB eşleştirici{X}")
    print("-" * 60)
    if adb("version", timeout=10).startswith("(adb hatası"):
        err("adb yok → pkg install android-tools")
        return 1
    adb("start-server", timeout=20)

    connect_port = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    pair_port = sys.argv[2].strip() if len(sys.argv) > 2 else ""
    code = sys.argv[3].strip() if len(sys.argv) > 3 else ""

    if not connect_port:
        connect_port = input("Tabletteki 'IP adresi ve bağlantı noktası' portu (ör. 36357): ").strip().split(":")[-1]

    # 1) Doğrudan bağlanmayı dene
    info(f"Bağlanmayı deniyorum: 127.0.0.1:{connect_port}")
    st = try_connect(connect_port)
    if st == "device":
        ok(f"Bağlandı: 127.0.0.1:{connect_port}")
        save(f"127.0.0.1:{connect_port}")
        return 0

    if st == "fail":
        err("Bu port adbd değil ya da adbd henüz dinlemiyor.")
        print("  → Tablette kablosuz hata ayıklamayı kapat-aç, portu tekrar oku.")

    # 2) Eşleştirme gerekiyor
    print()
    print(f"{B}Eşleştirme gerekiyor (Android 11+ güvenliği){X}")
    print("Tablet: Kablosuz hata ayıklama → 'Eşleme kodu ile cihaz eşle'")
    print("  → ekranda 6 haneli kod + 'IP adresi ve bağlantı noktası: 10.x.x.x:PORT'")
    print()
    if not pair_port:
        pair_port = input("Eşleştirme portu (o ekrandaki): ").strip().split(":")[-1]
    if not code:
        code = input("6 haneli kod: ").strip()

    if not do_pair(pair_port, code):
        err("Eşleştirme olmadı. Pair port'unu doğru okuduğundan emin ol (connect portundan FARKLI).")
        return 1

    # 3) Eşleştikten sonra bağlan
    for p in [connect_port]:
        for _ in range(3):
            st = try_connect(p)
            if st == "device":
                ok(f"BAĞLANDI: 127.0.0.1:{p}")
                save(f"127.0.0.1:{p}")
                print()
                print(f"{B}Sıradaki komut:{X} bash ~/kartal_tablet/baslat.sh")
                return 0
            time.sleep(2)
    err("Eşleşti ama bağlanmadı. Tablette portu yenile, bu komutu tekrar çalıştır.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
