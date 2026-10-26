#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kartal AI · Tek komutla kablosuz ADB bağlantısı (Android / Termux)
=================================================================
IP ve port ezberlemek YOK:
  1) Tabletin Wi-Fi IP'sini kendisi bulur (termux-wifi-connectioninfo -> UDP numarası -> yedek sabit)
  2) Kablosuz hata ayıklama portunu kendisi tarar (127.0.0.1, 30000-50100)
  3) Gerekirse eşleştirme (pairing) kodunu tek sefer sorar
  4) Bağlanınca hedefi ~/kartal_tablet/.env içine yazar -> bir daha sormaz

Kullanım:
  python ~/kartal_kaynak/tablet/baglan.py
  python ~/kartal_kaynak/tablet/baglan.py 10.136.3.175:41234
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

ENVF = Path.home() / "kartal_tablet" / ".env"
FALLBACK_IP = "10.136.3.175"
PORT_START, PORT_END = 30000, 61000

G, Y, R, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m"


def ok(m):
    print(f"{G}✔{X} {m}")


def info(m):
    print(f"{Y}➜{X} {m}")


def err(m):
    print(f"{R}✘{X} {m}")


def run(*args, timeout=25):
    try:
        return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    except Exception as e:  # adb yok / zaman aşımı
        return subprocess.CompletedProcess(args, 1, "", str(e))


def adb(*args, timeout=25):
    return run("adb", *args, timeout=timeout)


def devices_text():
    return adb("devices", timeout=15).stdout


def live_target():
    for line in devices_text().splitlines():
        if line.strip().endswith("\tdevice"):
            return line.split("\t")[0].strip()
    return ""


def save_target(target: str) -> None:
    ENVF.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if ENVF.exists():
        rows = [r for r in ENVF.read_text(encoding="utf-8").splitlines() if not r.startswith("ADB_TARGET=")]
    rows.append(f"ADB_TARGET={target}")
    ENVF.write_text("\n".join(rows).strip() + "\n", encoding="utf-8")
    ENVF.chmod(0o600)
    ok(f"Hedef kaydedildi: {target}")


def wifi_ip() -> str:
    """Tabletin kendi IP'si — 3 bağımsız yöntem."""
    try:
        out = run("termux-wifi-connectioninfo", timeout=10).stdout
        ip = str(json.loads(out).get("ip", "")).strip()
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip) and not ip.startswith(("0.", "127.")):
            return ip
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # paket göndermez, sadece yerel arayüzü seçer
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith(("0.", "127.")):
            return ip
    except Exception:
        pass
    try:
        out = run("ip", "-4", "-o", "addr", timeout=8).stdout
        m = re.search(r"inet (\d{1,3}(?:\.\d{1,3}){3})", out)
        if m and not m.group(1).startswith(("0.", "127.")):
            return m.group(1)
    except Exception:
        pass
    return FALLBACK_IP


def scan_ports(host: str, start: int = PORT_START, end: int = PORT_END) -> list[int]:
    """host üzerinde açık TCP portlarını hızlı tarar (loopback'te kapalı port anında RST döner)."""
    found: list[int] = []

    def check(p: int):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.28)
        try:
            if s.connect_ex((host, p)) == 0:
                return p
        except Exception:
            pass
        finally:
            s.close()
        return None

    with ThreadPoolExecutor(max_workers=500) as ex:
        for p in ex.map(check, range(start, end)):
            if p:
                found.append(p)
    return sorted(found)


def listening_ports() -> list[int]:
    """/proc/net/tcp + tcp6 içinden LISTEN (0A) durumundaki yerel portları okur — tarama gerekmez."""
    ports: set[int] = set()
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                next(f, None)
                for line in f:
                    cols = line.split()
                    if len(cols) < 4 or cols[3] != "0A":
                        continue
                    local = cols[1]
                    if ":" not in local:
                        continue
                    try:
                        port = int(local.rsplit(":", 1)[1], 16)
                    except ValueError:
                        continue
                    if 1024 <= port <= 65535:
                        ports.add(port)
        except Exception:
            continue
    return sorted(ports)


def try_connect(host: str, port: int) -> str:
    """adbd'ye bağlanmayı dener. Dönen değer: 'device' | 'unauthorized' | 'auth' | 'fail'."""
    target = f"{host}:{port}"
    adb("disconnect", target, timeout=10)
    out = (adb("connect", target, timeout=15).stdout + adb("connect", target, timeout=15).stderr).lower()
    time.sleep(1.0)
    devs = devices_text()
    for line in devs.splitlines():
        if line.startswith(target):
            if "\tdevice" in line:
                return "device"
            if "unauthorized" in line:
                return "unauthorized"
            if "offline" in line:
                return "offline"
    if "failed to authenticate" in out or "authentication" in out:
        return "auth"
    if "connected" in out:
        return "device" if "\tdevice" in devs else "auth"
    return "fail"


def pairing_flow(host: str) -> bool:
    """Android 11+ eşleştirme: tabletteki 6 haneli kodu tek sefer sorar."""
    print()
    print(f"{B}🔐 Eşleştirme gerekiyor (sadece 1 kez){X}")
    print("Tablette:")
    print("  Ayarlar → Geliştirici seçenekleri → Kablosuz hata ayıklama")
    print("  → 'Cihaz eşleştirme ile eşleştir' (Wi-Fi eşleştirme kodu) seçeneğine dokun")
    print("  Ekranda çıkan 6 haneli kodu ve portu yaz.")
    print()
    pair_port = input(f"Eşleştirme portu (ör. 41234) [{PORT_START}-{PORT_END}]: ").strip()
    code = input("6 haneli eşleştirme kodu: ").strip()
    if not pair_port.isdigit() or not code:
        err("Geçersiz giriş.")
        return False
    out = adb("pair", f"{host}:{pair_port}", code, timeout=40)
    print((out.stdout + out.stderr).strip())
    return "uccess" in (out.stdout + out.stderr)


def main() -> int:
    print(f"{B}🦅 Kartal AI · Kablosuz ADB bağlantı kurucusu{X}")
    print("-" * 60)

    if adb("version", timeout=10).returncode != 0:
        err("adb bulunamadı →  pkg install android-tools")
        return 1

    # 1) Zaten bağlı mı?
    tgt = live_target()
    if tgt:
        ok(f"Zaten bağlı: {tgt}")
        save_target(tgt)
        return 0

    adb("start-server", timeout=20)

    # 1b) Eşleştirme modu: python baglan.py pair [IP:PORT] [KOD]
    args = [a for a in sys.argv[1:] if a]
    if args and args[0].lower() in ("pair", "eslestir", "eşleştir"):
        host = wifi_ip()
        pport = args[1] if len(args) > 1 else ""
        code = args[2] if len(args) > 2 else ""
        if not pport:
            pport = input(f"Eşleştirme portu [{host}:PORT] → ").strip().split(":")[-1]
        if not code:
            code = input("6 haneli kod → ").strip()
        if pport.isdigit() and code:
            out = adb("pair", f"{host}:{pport}", code, timeout=45)
            msg = (out.stdout + out.stderr).strip()
            print(msg)
            if "uccess" in msg:
                ok("Eşleştirme tamam. Şimdi bağlanılıyor…")
                sys.argv = [sys.argv[0]]
                return main()
        err("Eşleştirme başarısız.")
        return 1

    # 2) Elle verildiyse
    if len(sys.argv) > 1 and sys.argv[1].strip():
        hp = sys.argv[1].strip()
        if ":" in hp:
            h, p = hp.rsplit(":", 1)
            if p.isdigit():
                info(f"Verilen hedef deneniyor: {hp}")
                r = try_connect(h, int(p))
                if r == "device":
                    ok(f"Bağlandı: {hp}")
                    save_target(hp)
                    return 0
                if r in ("auth", "unauthorized"):
                    pairing_flow(h)
                    r = try_connect(h, int(p))
                    if r == "device":
                        ok(f"Bağlandı: {hp}")
                        save_target(hp)
                        return 0
                    if r == "unauthorized":
                        err("Tablette 'USB hata ayıklamasına izin ver' penceresi çıktı → 'Her zaman izin ver' + 'İzin ver'.")
                        return 2
                err(f"{hp} üzerinde adbd bulunamadı.")

    # 3) IP bul
    ip = wifi_ip()
    info(f"Tabletin IP'si: {ip}")

    # 4) Portları tara
    proc_ports = [p for p in listening_ports() if PORT_START <= p <= PORT_END]
    if proc_ports:
        info("Sistemde dinleyen portlar (tarama gerekmez): " + ", ".join(str(x) for x in proc_ports))
    info(f"Kablosuz hata ayıklama portu taranıyor ({PORT_START}-{PORT_END})… 5-20 sn")
    hosts = [ip] if ip else []
    if "127.0.0.1" not in hosts:
        hosts.append("127.0.0.1")
    candidates: list[tuple[str, int]] = []
    for p in proc_ports:
        for h in hosts[:1]:
            candidates.append((h, p))
    for h in hosts:
        found = scan_ports(h)
        if found:
            info(f"{h} üzerinde açık port: " + ", ".join(str(x) for x in found))
        candidates += [(h, p) for p in found]
    if not candidates:
        info("Hiç açık port yok — kablosuz hata ayıklama kapalı olabilir.")

    if not candidates:
        err("Açık port bulunamadı. Kablosuz hata ayıklama AÇIK mı?")
        print("  Ayarlar → Geliştirici seçenekleri → Kablosuz hata ayıklama = AÇIK")
        print("  O ekranda 'IP adresi ve bağlantı noktası' yazar; portu bana yaz:")
        p = input("Port (boş = çık): ").strip()
        if p.isdigit():
            candidates = [(ip, int(p))]
        else:
            return 1

    candidates = candidates[:15]
    try:
        adb("mdns", "check", timeout=10)
        for svc in ("_adb-tls-connect._tcp", "_adb._tcp", "_adb-tls-pairing._tcp", ""):
            args = ["mdns", "services"] + ([svc] if svc else [])
            for ln in adb(*args, timeout=12).stdout.splitlines():
                toks = ln.split()
                if not toks:
                    continue
                hp = toks[-1].strip()
                if ":" in hp and hp.split(":")[-1].isdigit() and ("_adb" in ln or "." in hp):
                    h2, p2 = hp.rsplit(":", 1)
                    if (h2, int(p2)) not in candidates:
                        candidates.insert(0, (h2, int(p2)))
                        info(f"mDNS: {hp}")
    except Exception:
        pass
    try:
        mdns = adb("mdns", "services", timeout=10).stdout
        for ln in mdns.splitlines():
            if "_adb-tls-connect" in ln or "_adb._tcp" in ln:
                hp = ln.split()[-1].strip()
                if ":" in hp:
                    h2, p2 = hp.rsplit(":", 1)
                    if p2.isdigit() and (h2, int(p2)) not in candidates:
                        candidates.insert(0, (h2, int(p2)))
                        info(f"mDNS servisi: {hp}")
    except Exception:
        pass
    info("Aday portlar: " + ", ".join(f"{h}:{p}" for h, p in candidates))

    # 5) Sırayla bağlan
    need_pair = False
    for h, p in candidates:
        state = try_connect(h, p)
        if state == "device":
            ok(f"Bağlandı: {h}:{p}")
            save_target(f"{h}:{p}")
            _post_setup()
            return 0
        if state in ("auth", "unauthorized"):
            need_pair = True
            pair_host, pair_port_found = h, p
            break
        info(f"{h}:{p} adbd değil, geçildi.")

    if not need_pair:
        print()
        print()
        print(f"{B}ONCE ESLEŞTIRME (Android 11+ zorunlu){X}")
        print("  Ayarlar > Gelistirici secenekleri > Kablosuz hata ayiklama")
        print("  > 'Cihaz eslestirme ile eslestir' > 6 haneli kod + IP:PORT")
        print("  Sonra:  python baglan.py pair")
        print()
        print(f"{B}Tabletten portu oku (10 saniye){X}")
        print("  Ayarlar > Gelistirici secenekleri > 'Kablosuz hata ayiklama' YAZISINA dokun")
        print("  -> 'IP adresi ve baglanti noktasi' satirindaki sayi (or. 10.136.3.175:41234)")
        try:
            p_manual = input("Port (bos = cik): ").strip().lstrip(":")
        except EOFError:
            p_manual = ""
        if p_manual.split(":")[-1].isdigit():
            h_manual = p_manual.split(":")[0] if ":" in p_manual else ip
            p_int = int(p_manual.split(":")[-1])
            state = try_connect(h_manual, p_int)
            if state == "device":
                ok(f"Baglandi: {h_manual}:{p_int}")
                save_target(f"{h_manual}:{p_int}")
                _post_setup()
                return 0
            if state in ("auth", "unauthorized"):
                need_pair = True
                pair_host = h_manual
                candidates = [(h_manual, p_int)]

    if need_pair:
        if pairing_flow(pair_host):
            for h, p in candidates:
                if try_connect(h, p) == "device":
                    ok(f"Bağlandı: {h}:{p}")
                    save_target(f"{h}:{p}")
                    _post_setup()
                    return 0
            err("Eşleştirme oldu ama bağlantı kurulamadı. Portu tekrar tarayalım:")
            err("Komutu yeniden çalıştır: python ~/kartal_kaynak/tablet/baglan.py")
            return 1

    err("Bağlanamadım.")
    print()
    print("Elle yol:")
    print("  1) Ayarlar → Geliştirici seçenekleri → Kablosuz hata ayıklama (aç)")
    print("  2) 'Kablosuz hata ayıklama' YAZISINA dokun → 'IP adresi ve bağlantı noktası'")
    print("  3) python ~/kartal_kaynak/tablet/baglan.py 10.136.3.175:PORT")
    return 1


def _post_setup() -> None:
    """Samsung ajanı öldürmesin: pil muafiyeti + ekran açık."""
    for cmd in (
        "dumpsys deviceidle whitelist +com.termux",
        "settings put global stay_on_while_plugged_in 3",
    ):
        try:
            adb("shell", cmd, timeout=15)
        except Exception:
            pass
    ok("Pil muafiyeti ve 'şarjdayken ekran açık' ayarlandı.")
    print()
    print(f"{B}Sıradaki komut:{X}  bash ~/kartal_tablet/baslat.sh")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nİptal.")
        sys.exit(130)
