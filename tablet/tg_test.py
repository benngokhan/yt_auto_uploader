#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kartal AI · Telegram bağlantı testi
===================================
Ajan "menü"ye cevap vermiyorsa sebebini 4 adımda söyler:
  1) Token geçerli mi?            (getMe)
  2) Sohbet kimliği kayıtlı mı?   (.env TELEGRAM_CHAT_ID)
  3) Bot'a mesaj ULAŞIYOR mu?     (getUpdates — son 5 mesaj)
  4) Bot mesaj GÖNDEREBİLİYOR mu? (sendMessage)

Kullanım: python3 ~/kartal_kaynak/tablet/tg_test.py
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ENVF = Path.home() / "kartal_tablet" / ".env"
G, Y, R, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m"


def ok(m):
    print(f"{G}✔{X} {m}")


def info(m):
    print(f"{Y}➜{X} {m}")


def err(m):
    print(f"{R}✘{X} {m}")


def load_env() -> dict:
    d = {}
    if ENVF.exists():
        for line in ENVF.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def api(token: str, method: str, payload: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"} if data else {}
    )
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def main() -> None:
    print(f"{B}🦅 Kartal · Telegram teşhis{X}")
    print("-" * 60)

    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = env.get("TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "")

    print(f"\n1) .env: {ENVF}  ({'var' if ENVF.exists() else 'YOK'})")
    if not token:
        err("TELEGRAM_BOT_TOKEN yok → bash ~/kartal_kaynak/tablet/kur.sh")
        return
    ok(f"token: {token[:10]}…{token[-4:]}")

    try:
        me = api(token, "getMe")["result"]
        ok(f"bot: @{me.get('username')} ({me.get('first_name')})")
    except urllib.error.HTTPError as e:
        err(f"Token geçersiz (HTTP {e.code}) → @BotFather'dan yeni token al")
        return
    except Exception as e:
        err(f"internet/telegram hatası: {e}")
        return

    print(f"\n2) Kayıtlı sohbet: {chat or '(yok — ilk mesaj atan kilitlenecek)'}")

    print("\n3) Bot'a ulaşan son mesajlar (getUpdates)")
    try:
        ups = api(token, "getUpdates", {"limit": 5, "timeout": 0, "allowed_updates": ["message"]}).get("result", [])
    except urllib.error.HTTPError as e:
        err(f"getUpdates HTTP {e.code}: {e.read().decode()[:200]}")
        ups = []
    if not ups:
        err("Hiç mesaj yok → ya mesaj atmadın ya da BAŞKA bir program botu dinliyor (çakışma)")
        print("   • Telefondan botuna /start yaz, 5 sn bekle, bu komutu tekrar çalıştır")
        print("   • Termux'ta ajan çalışıyorsa, aynı anda bu test de dinleyebilir:")
        print("     (ajanı durdur → test → ajanı başlat)")
    else:
        for u in ups[-5:]:
            m = u.get("message", {})
            ok(f"{m.get('date')} | chat={m.get('chat', {}).get('id')} | '{m.get('text')}'")

    target = chat or (str(ups[-1]["message"]["chat"]["id"]) if ups else "")
    print("\n4) Mesaj gönderme testi")
    if not target:
        err("Hedef sohbet yok → önce telefondan botuna /start yaz")
        return
    try:
        r = api(token, "sendMessage", {"chat_id": target, "text": "🦅 Kartal test mesajı — bağlantı çalışıyor."})
        ok(f"Gönderildi → chat {target} (message_id {r['result']['message_id']})")
        if not chat:
            print(f"\n{B}Öneri:{X} .env'ye ekle:")
            print(f'  echo "TELEGRAM_CHAT_ID={target}" >> ~/kartal_tablet/.env')
    except urllib.error.HTTPError as e:
        err(f"Gönderilemedi HTTP {e.code}: {e.read().decode()[:200]}")

    print("\n" + "-" * 60)
    print("Sıradaki: bash ~/kartal_tablet/baslat.sh   (ajanı çalıştır)")


if __name__ == "__main__":
    main()
