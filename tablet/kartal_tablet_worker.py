# -*- coding: utf-8 -*-
"""
Kartal AI · Tablet Ajanı (Samsung Galaxy Tab S7 FE / Android 11+)
================================================================
Telefonundan Telegram'a yazdığın komutla tableti kullanır:
ekran görüntüsü alır, dokunur, kaydırır, yazı yazar, uygulama açar,
video paylaşır ve doğal dilde görevleri adım adım yürütür.

Mimari:
  Telefon (Telegram)  ->  Tablet (Termux)  ->  adb shell  ->  Android UI

İki katmanlı zekâ:
  1) UIAutomator erişilebilirlik ağacı (%100 ücretsiz, koordinat kayması yok)
     -> ekrandaki gerçek buton/yazı isimlerini okur ve merkezine dokunur.
  2) Gemini görüntü modeli (opsiyonel, GEMINI_API_KEY varsa)
     -> ağaçtan bulunamayan sahnelerde ekran görüntüsünü yorumlar.

Hiçbir gizli anahtar bu dosyada tutulmaz; hepsi ~/kartal_tablet/.env içinde.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HOME = Path.home()
KARTAL_DIR = HOME / "kartal_tablet"
ENV_FILE = KARTAL_DIR / ".env"
SHOTS_DIR = KARTAL_DIR / "shots"
DOWNLOADS_DIR = KARTAL_DIR / "indirilenler"
STATE_FILE = KARTAL_DIR / "state.json"

for d in (KARTAL_DIR, SHOTS_DIR, DOWNLOADS_DIR):
    d.mkdir(parents=True, exist_ok=True)

from ses import speak, chat_turn, listen_once, tts_available, reply_brain

# Termux'ta pkg ile kurulan araçlar PATH'te olmayabilir — kendimiz ekliyoruz
for _p in ("/data/data/com.termux/files/usr/bin", "/system/bin", "/system/xbin"):
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + ":" + os.environ.get("PATH", "")

ADB = os.getenv("ADB_BIN", "adb")
TARGET = os.getenv("ADB_TARGET", "").strip()  # boşsa tek cihaz varsayılır


# --------------------------------------------------------------------------
# 1. AYARLAR
# --------------------------------------------------------------------------
def load_env() -> None:
    """~/kartal_tablet/.env dosyasını ortam değişkenlerine yükler (env her zaman öncelikli)."""
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and not os.getenv(k, "").strip():
            os.environ[k] = v


def save_env(updates: dict) -> None:
    """Anahtarları .env'e yazar (var olanı günceller)."""
    rows, seen = [], set()
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in raw and not raw.strip().startswith("#"):
                k = raw.split("=", 1)[0].strip()
                if k in updates:
                    rows.append(f"{k}={updates[k]}")
                    seen.add(k)
                    continue
            rows.append(raw)
    for k, v in updates.items():
        if k not in seen:
            rows.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(rows).strip() + "\n", encoding="utf-8")
    ENV_FILE.chmod(0o600)


def state_get(key: str, default=None):
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8")).get(key, default)
        except Exception:
            return default
    return default


def state_set(key: str, value) -> None:
    data = {}
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[key] = value
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# 2. TELEGRAM
# --------------------------------------------------------------------------
def tg(method: str, payload: dict | None = None, files: dict | None = None, timeout: int = 70) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN yok (~/kartal_tablet/.env)")
    url = f"https://api.telegram.org/bot{token}/{method}"
    if files:
        import uuid

        boundary = "----Kartal" + uuid.uuid4().hex
        body = b""
        for k, v in (payload or {}).items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for k, (fname, data, ctype) in files.items():
            body += (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n"
            ).encode() + data + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
    elif payload:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def say(text: str, chat_id=None, keyboard: list[list[dict]] | None = None) -> None:
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        print(text)
        return
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    try:
        tg("sendMessage", payload)
    except Exception as e:
        print(f"[telegram] {e}\n{text}")


def send_photo(path: Path, caption: str = "", chat_id=None) -> None:
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        print(f"[foto] {path}")
        return
    try:
        tg(
            "sendPhoto",
            {"chat_id": chat_id, "caption": caption[:1000]},
            files={"photo": (path.name, path.read_bytes(), "image/png")},
        )
    except Exception as e:
        print(f"[telegram foto] {e}")


# --------------------------------------------------------------------------
# 3. ADB KATMANI
# --------------------------------------------------------------------------
class AdbError(RuntimeError):
    pass


def _adb_raw(*args: str, timeout: int = 25, text: bool = True) -> str:
    cmd = [ADB] + (["-s", TARGET] if TARGET else []) + list(args)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise AdbError("adb bulunamadı. Termux'ta: pkg install android-tools")
    out = p.stdout if text else p.stdout
    err = p.stderr.decode("utf-8", "ignore") if isinstance(p.stderr, bytes) else (p.stderr or "")
    if isinstance(out, bytes):
        out = out.decode("utf-8", "ignore")
    if p.returncode != 0:
        raise AdbError((err or out or "adb hatası").strip())
    return out


RISH_BIN = os.getenv("RISH_BIN", "rish")


def rish_ok() -> bool:
    """Shizuku köprüsü (rish) çalışıyor mu? uid 2000 dönerse evet."""
    try:
        r = subprocess.run([RISH_BIN, "-c", "id"], capture_output=True, text=True, timeout=20)
        return "uid=2000" in (r.stdout + r.stderr)
    except Exception:
        return False


def rish(cmd: str, timeout: int = 40) -> str:
    """Shizuku üzerinden shell komutu (adb olmadan)."""
    try:
        r = subprocess.run([RISH_BIN, "-c", cmd], capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        if r.returncode != 0 and not out:
            raise AdbError(f"rish hata: exit {r.returncode}")
        return out
    except FileNotFoundError:
        # -c desteklemiyorsa: stdin ile dene
        try:
            r2 = subprocess.run([RISH_BIN], input=cmd, capture_output=True, text=True, timeout=timeout)
            return (r2.stdout + r2.stderr).strip()
        except FileNotFoundError:
            raise AdbError("rish yok (Shizuku kurulu değil)")
    except subprocess.TimeoutExpired:
        raise AdbError("rish zaman aşımı")


def shell(cmd: str, timeout: int = 40) -> str:
    """Birleşik kabuk: önce adb, olmazsa Shizuku/rish."""
    try:
        return _adb_raw("shell", cmd, timeout=timeout)
    except AdbError as e:
        if rish_ok():
            return rish(cmd, timeout=timeout)
        raise AdbError(f"{e} · rish de yok")


def adb(*args: str, timeout: int = 25, text: bool = True) -> str:
    """Geriye uyumluluk: shell çağrıları birleşik katmana yönlenir."""
    if args and args[0] == "shell":
        rest = " ".join(a for a in args[1:])
        return shell(rest, timeout=max(timeout, 40))
    return _adb_raw(*args, timeout=timeout, text=text)


def ensure_device() -> None:
    """Bağlantı yoksa son bilinen hedefe tekrar bağlanmayı dener."""
    try:
        out = adb("devices")
        if "\tdevice" in out:
            return
    except AdbError:
        pass
    target = TARGET or os.getenv("ADB_TARGET", "").strip() or state_get("last_target", "")
    if target:
        try:
            adb("connect", target)
        except AdbError:
            pass


def screenshot(name: str = "shot") -> Path:
    ensure_device()
    path = SHOTS_DIR / f"{name}_{int(time.time())}.png"
    try:
        raw = subprocess.run(
            [ADB] + (["-s", TARGET] if TARGET else []) + ["exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=40,
        )
        if raw.returncode == 0 and raw.stdout and raw.stdout[:4] == b"\x89PNG":
            path.write_bytes(raw.stdout)
            return path
    except Exception:
        pass

    # rish yedeği: /sdcard'a yaz, Termux depolamasından kopyala
    if rish_ok():
        far = "/sdcard/Download/kartal_shot.png"
        shell(f"screencap -p {far}", timeout=40)
        for src in (os.path.expanduser("~/storage/downloads/kartal_shot.png"),
                    os.path.expanduser("~/storage/shared/Download/kartal_shot.png"),
                    "/sdcard/Download/kartal_shot.png"):
            if os.path.exists(src) and os.path.getsize(src) > 1000:
                shutil.copy(src, path)
                return path
        raise AdbError("screencap yazıldı ama dosya okunamadı (termux-setup-storage çalıştır)")

    raise AdbError("Ekran görüntüsü alınamadı (adb ve rish yok)")


_XML_PATH = "/sdcard/kartal_ui.xml"


def ui_dump() -> list[dict]:
    """Ekrandaki erişilebilirlik düğümlerini (metin, içerik açıklaması, koordinat) döndürür."""
    adb("shell", "uiautomator dump " + _XML_PATH, timeout=30)
    xml_text = adb("shell", "cat " + _XML_PATH, timeout=30)
    start = xml_text.find("<?xml")
    if start > 0:
        xml_text = xml_text[start:]
    nodes: list[dict] = []
    if not xml_text.strip():
        return nodes
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return nodes
    for n in root.iter("node"):
        label = (n.get("text") or "").strip() or (n.get("content-desc") or "").strip()
        bounds = n.get("bounds") or ""
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not label or not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        if x2 <= x1 or y2 <= y1:
            continue
        nodes.append(
            {
                "label": label,
                "cx": (x1 + x2) // 2,
                "cy": (y1 + y2) // 2,
                "clickable": n.get("clickable") == "true",
                "cls": (n.get("class") or "").split(".")[-1],
                "bounds": [x1, y1, x2, y2],
            }
        )
    return nodes


def find_node(nodes: list[dict], needle: str) -> dict | None:
    """Metni en iyi eşleyen düğümü bulur: tam -> büyük/küçük harf -> parça -> ters parça."""
    q = (needle or "").strip().lower()
    if not q:
        return None
    for n in nodes:
        if n["label"].lower() == q:
            return n
    for n in nodes:
        if q in n["label"].lower():
            return n
    for n in nodes:
        if n["label"].lower() in q and len(n["label"]) >= 3:
            return n
    best, best_score = None, 0
    for n in nodes:
        low = n["label"].lower()
        score = sum(1 for w in q.split() if len(w) > 2 and w in low)
        if score > best_score:
            best, best_score = n, score
    return best


def tap(x: int, y: int) -> None:
    ensure_device()
    adb("shell", f"input tap {int(x)} {int(y)}")


def tap_text(label: str, screenshot_after: bool = True) -> str:
    nodes = ui_dump()
    node = find_node(nodes, label)
    if not node:
        return f"❌ Ekranda '{label}' bulunamadı. Görünen yazılar: {_visible_list(nodes)}"
    tap(node["cx"], node["cy"])
    if screenshot_after:
        time.sleep(0.8)
    return f"✅ '{node['label']}' dokunuldu ({node['cx']},{node['cy']})"


def swipe(direction: str = "up", duration_ms: int = 320) -> str:
    ensure_device()
    w, h = 800, 1280
    try:
        size = adb("shell", "wm size").strip().split()[-1]
        w, h = [int(v) for v in size.lower().split("x")]
    except Exception:
        pass
    cx, cy = w // 2, h // 2
    table = {
        "up": (cx, int(h * 0.72), cx, int(h * 0.28)),
        "down": (cx, int(h * 0.28), cx, int(h * 0.72)),
        "left": (int(w * 0.78), cy, int(w * 0.22), cy),
        "right": (int(w * 0.22), cy, int(w * 0.78), cy),
    }
    aliases = {
        "yukari": "up", "yukarı": "up", "up": "up", "yuxari": "up",
        "asagi": "down", "aşağı": "down", "down": "down",
        "sol": "left", "left": "left",
        "sag": "right", "sağ": "right", "right": "right",
    }
    d = aliases.get(direction.strip().lower(), "")
    if not d:
        return "❌ Yön şunlardan biri olmalı: yukari | asagi | sol | sag"
    x1, y1, x2, y2 = table[d]
    adb("shell", f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
    return f"✅ {d} kaydırıldı"


def type_text(text: str) -> str:
    ensure_device()
    safe = text.replace(" ", "%s").replace('"', '\\"').replace("&", "\\&")
    adb("shell", f'input text "{safe}"')
    return "✅ yazıldı"


def key(name: str) -> str:
    ensure_device()
    mapping = {
        "geri": "KEYCODE_BACK", "back": "KEYCODE_BACK",
        "ev": "KEYCODE_HOME", "home": "KEYCODE_HOME", "ana": "KEYCODE_HOME",
        "enter": "KEYCODE_ENTER", "giris": "KEYCODE_ENTER",
        "sil": "KEYCODE_DEL", "delete": "KEYCODE_DEL",
        "kapat": "KEYCODE_POWER", "power": "KEYCODE_POWER",
        "sesac": "KEYCODE_VOLUME_UP", "seskapa": "KEYCODE_VOLUME_DOWN",
        "son": "KEYCODE_APP_SWITCH", "bildirim": "KEYCODE_NOTIFICATION",
        "ara": "KEYCODE_SEARCH",
    }
    k = mapping.get(name.strip().lower())
    if not k:
        return f"❌ Tuş bulunamadı: {name}. Şunlar geçerli: {', '.join(sorted(mapping))}"
    adb("shell", f"input keyevent {k}")
    return f"✅ {k}"


def open_app(name: str) -> str:
    ensure_device()
    q = name.strip()
    if "." in q and " " not in q:  # doğrudan paket adı
        try:
            adb("shell", f"monkey -p {shlex.quote(q)} -c android.intent.category.LAUNCHER 1")
            return f"✅ {q} açıldı"
        except AdbError as e:
            return f"❌ {q} açılamadı: {e}"
    try:
        out = adb("shell", "pm list packages -3")
        pkgs = [ln.replace("package:", "").strip() for ln in out.splitlines() if ln.strip()]
        low = q.lower()
        hits = [p for p in pkgs if low in p.lower()]
        if not hits:
            hits = [p for p in pkgs if any(tok and tok in p.lower() for tok in low.split())]
        if not hits:
            return f"❌ '{q}' ile eşleşen uygulama yok. /uygulamalar ile listeyi gör."
        pkg = hits[0]
        adb("shell", f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        return f"✅ {pkg} açıldı"
    except AdbError as e:
        return f"❌ açma hatası: {e}"


def _visible_list(nodes: list[dict], limit: int = 18) -> str:
    seen, out = set(), []
    for n in nodes:
        lab = n["label"]
        if lab in seen or len(lab) > 40:
            continue
        seen.add(lab)
        out.append(lab)
        if len(out) >= limit:
            break
    return " · ".join(out) if out else "(boş ekran)"


# --------------------------------------------------------------------------
# 3b. TERMUX:API YEDEĞİ (adb olmadan da çalışan işler)
# --------------------------------------------------------------------------
def termux_cmd(name: str, *args: str, timeout: int = 45) -> str:
    """termux-api komutunu çalıştırır (Termux:API uygulaması kuruluysa)."""
    try:
        r = subprocess.run([name, *args], capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return f"( {name} yok — pkg install termux-api )"
    except subprocess.TimeoutExpired:
        return f"( {name} zaman aşımı )"


def open_url(url: str) -> str:
    """adb yoksa bile bir linki/uygulama derin bağlantısını açar."""
    try:
        adb("shell", f"am start -a android.intent.action.VIEW -d '{url}'", timeout=20)
        return f"✅ adb ile açıldı: {url}"
    except Exception:
        out = termux_cmd("termux-open-url", url, timeout=30)
        return f"✅ termux-open-url: {out or url}"


def share_file_termux(path: Path, title: str = "") -> str:
    """Android paylaşım menüsünü termux-share ile açar (adb gerekmez)."""
    args = ["-a", "send", "-t", "video/mp4"]
    if title:
        args += ["-c", title]
    args.append(str(path))
    out = termux_cmd("termux-share", *args, timeout=60)
    return f"✅ termux-share açıldı {path.name}" if "yok" not in out else out



# --------------------------------------------------------------------------
# 4. GEMINI GÖRÜNTÜ KATMANI (opsiyonel)
# --------------------------------------------------------------------------
def gemini_see(png: Path, question: str) -> str:
    """Ekran görüntüsünü Gemini'ye sorar; anahtar yoksa boş döner."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return ""
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={urllib.parse.quote(api_key)}"
    )
    body = {
        "contents": [
            {
                "parts": [
                    {"text": question},
                    {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(png.read_bytes()).decode()}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 512},
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except Exception as e:
        return f"(görüntü modeli hatası: {e})"


# --------------------------------------------------------------------------
# 5. GÖREV DÖNGÜSÜ (doğal dil -> adım adım eylem)
# --------------------------------------------------------------------------
ACTION_SCHEMA = """SADECE şu JSON'u döndür, başka hiçbir şey yazma:
{"action":"tap_text|tap_xy|swipe|type|key|open_app|done","label":"","x":0,"y":0,"direction":"up","text":"","app":"","note":"kısa gerekçe"}"""


def run_task(task: str, max_steps: int = 8) -> None:
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    say(f"🤖 <b>Görev alındı:</b> {task}\nAdım adım yürütüyorum…", chat)
    history: list[str] = []
    for step in range(1, max_steps + 1):
        try:
            nodes = ui_dump()
        except AdbError as e:
            say(f"❌ adb hatası: {e}", chat)
            return
        visible = _visible_list(nodes, 25)
        shot = None
        try:
            shot = screenshot(f"gorev{step}")
        except AdbError:
            pass

        action = None
        # 5a) Önce Gemini (varsa) karar verir
        if os.getenv("GEMINI_API_KEY", "").strip() and shot:
            prompt = (
                f"Android tablet ekranındasın. Görev: {task}\n"
                f"{''.join(history[-3:])}\n"
                f"Ekrandaki yazılar: {visible}\n"
                f"Ekran {shot.name} görüntüsünde. Görevi tamamlamak için SIRADAKİ TEK eylemi seç.\n"
                f"Görev bittiyse action=done.\n{ACTION_SCHEMA}"
            )
            raw = gemini_see(shot, prompt)
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                try:
                    action = json.loads(m.group(0))
                except Exception:
                    action = None

        # 5b) Gemini yoksa/başarısızsa: görev metnindeki kelimeyi ekranda ara
        if not action:
            target = find_node(nodes, task)
            if target:
                action = {"action": "tap_text", "label": target["label"], "note": "metin eşleşmesi"}
            else:
                say(
                    f"⚠️ {step}. adımda eşleşme bulamadım (Gemini anahtarı yok).\n"
                    f"Ekranda: {visible}\n\n/ekran ile bak, /tikla X Y ile elle dokun.",
                    chat,
                )
                return

        act = str(action.get("action", "")).strip()
        if act == "done":
            say(f"✅ <b>Görev tamam:</b> {action.get('note', '')[:400]}", chat)
            return

        result = "?"
        try:
            if act == "tap_text":
                result = tap_text(str(action.get("label", "")), screenshot_after=False)
            elif act == "tap_xy":
                tap(int(action.get("x", 0)), int(action.get("y", 0)))
                result = f"✅ dokunuldu ({action.get('x')},{action.get('y')})"
            elif act == "swipe":
                result = swipe(str(action.get("direction", "up")))
            elif act == "type":
                result = type_text(str(action.get("text", "")))
            elif act == "key":
                result = key(str(action.get("text", "geri")))
            elif act == "open_app":
                result = open_app(str(action.get("app", "")))
            else:
                result = f"❌ bilinmeyen eylem: {act}"
        except Exception as e:
            result = f"❌ hata: {e}"

        history.append(f"{step}) {act} -> {result}\n")
        say(f"{step}️⃣ {act} → {result[:300]}", chat)
        time.sleep(1.1)

    say("⏱ 8 adımda bitmedi. /ekran ile duruma bak, gerekirse /gorev ile devam et.", chat)


# --------------------------------------------------------------------------
# 6. VIDEO PAYLAŞIMI (Instagram Reels / TikTok)
# --------------------------------------------------------------------------
def download(url: str) -> Path:
    name = os.path.basename(urllib.parse.urlparse(url).path) or f"video_{int(time.time())}.mp4"
    dest = DOWNLOADS_DIR / name
    if dest.exists():
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return dest


def share_video(source: str, target: str = "") -> None:
    """Android paylaşım menüsünü açar; hedef uygulama verilirse onu da dokunur."""
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    path = Path(source).expanduser()
    if source.startswith("http"):
        say("⬇️ Video indiriliyor…", chat)
        try:
            path = download(source)
        except Exception as e:
            say(f"❌ indirilemedi: {e}", chat)
            return
    if not path.exists():
        say(f"❌ dosya yok: {path}", chat)
        return
    size_mb = path.stat().st_size / (1024 * 1024)
    say(f"📤 Paylaşım menüsü açılıyor: <code>{path.name}</code> ({size_mb:.1f} MB)", chat)
    try:
        adb("shell", f'am start -a android.intent.action.SEND -t video/mp4 --eu android.intent.extra.STREAM "file://{path}" --grant-read-uri-permission')
    except AdbError as e:
        say(f"⚠️ adb paylaşımı olmadı ({e}). Termux:API yolu deneniyor…", chat)
        res = share_file_termux(path, path.stem)
        say(res, chat)
        if res.startswith("✅"):
            shot = screenshot("paylasim")
            send_photo(shot, f"Ekran: {path.name} paylaşım akışı", chat)
            return
        try:
            adb("shell", f"am start -a android.intent.action.VIEW -d file://{path} -t video/mp4")
        except AdbError as e2:
            say(f"❌ paylaşım açılamadı: {e2}", chat)
            return
    time.sleep(2.0)
    if target:
        say(tap_text(target, screenshot_after=True), chat)
        time.sleep(2.0)
    shot = screenshot("paylasim")
    send_photo(shot, f"Ekran: {path.name} paylaşım akışı", chat)


# --------------------------------------------------------------------------
# 7. KOMUT YÖNLENDİRİCİ
# --------------------------------------------------------------------------
HELP = """<b>🦅 Kartal AI · Tablet Kumandası</b>

<b>Göz</b>
/ekran — canlı ekran görüntüsü
/bul &lt;yazı&gt; — ekranda ara (➕ /bul &lt;yazı&gt; tikla)
/uygulamalar — kurulu uygulamalar

<b>El</b>
/tikla 540 900 — koordinata dokun
/yaz &lt;metin&gt; — klavyeden yaz
/tus geri|ev|enter|bildirim — tuşa bas
/kaydir yukari|asagi|sol|sag — kaydır
/ac &lt;uygulama&gt; — uygulama aç

<b>Beyin</b>
/gorev &lt;ne yapılacağı&gt; — adım adım kendi yürütür
  örn: <i>/gorev Instagram'ı aç ve keşfet akışına geç</i>

<b>Kanal işleri</b>
/paylas &lt;dosya ya da https://...&gt; — paylaşım menüsü
/paylas &lt;link&gt; Instagram — menüden Instagram'ı da seçer
/studio &lt;VIDEO_ID&gt; — YouTube Studio'da videoyu açar

<b>Ses</b>
/konus &lt;metin&gt; — tableti konuştur
/dinle — 6 sn dinle, yazıya çevir
/sohbet — dinle → cevapla → konuş

<b>Bakım</b>
/bak — her şey yolunda mı (tek mesaj)
/pid — bağlantı ve pil durumu
/durum — ajan ayakta mı
"""


def _norm(t: str) -> str:
    """Turkce karakterleri sadelestirip kucuk harfe cevirir (menu -> menu)."""
    t = (t or "").strip().lower()
    for a, b in (("i", "i"), ("s", "s"), ("g", "g"), ("u", "u"), ("o", "o"), ("c", "c")):
        t = t.replace(a, b)
    return t.replace("ı", "i").replace("İ", "i").replace("ş", "s").replace("ğ", "g").replace("ü", "u").replace("ö", "o").replace("ç", "c")


def health_report() -> str:
    """Tabletin ve köprünün durumunu tek mesajda özetler."""
    lines = ["<b>🩺 Kartal Kontrol</b>"]
    try:
        devs = _adb_raw("devices", timeout=15)
        ok_adb = "\tdevice" in devs
        lines.append(("✅" if ok_adb else "❌") + " Bağlantı")
    except Exception:
        lines.append("❌ Bağlantı")
    lines.append(("✅" if rish_ok() else "➖") + " Shizuku")
    lines.append(("✅" if tts_available() else "➖") + " Ses (konuşma)")

    try:
        out = shell("dumpsys battery", timeout=25)
        lvl = re.search(r"level:\s*(\d+)", out)
        chg = re.search(r"status:\s*(\d+)", out)
        lines.append(f"🔋 Pil: %{lvl.group(1) if lvl else '?'} · {'şarjda' if chg and chg.group(1) == '2' else 'prizde değil'}")
        if chg and chg.group(1) != "2":
            lines.append("⚠️ Şarja tak — pil tasarrufu Wi-Fi'yi uyutuyor")
    except Exception:
        pass

    try:
        wifi = shell("dumpsys wifi | grep -m1 'Wi-Fi is'", timeout=20)
        if "enabled" in wifi.lower():
            lines.append("✅ Wi-Fi açık")
        elif wifi:
            lines.append("❌ Wi-Fi kapalı!")
    except Exception:
        pass

    try:
        ip = shell("ip -4 -o addr show wlan0", timeout=15)
        m = re.search(r"inet (\d{1,3}(?:\.\d{1,3}){3})", ip)
        if m:
            lines.append(f"🌐 IP: {m.group(1)}")
        elif ip:
            lines.append("❌ Wi-Fi IP yok")
    except Exception:
        pass

    lines.append("")
    lines.append("Yardım için /menu")
    return "\n".join(lines)


def handle(text: str, chat_id: str) -> None:
    raw = (text or "").strip()
    if not raw:
        return
    low = _norm(raw)
    if low in ("menu", "/menu", "merhaba", "selam", "start", "/start", "help", "/help"):
        say(HELP, chat_id)
        return

    if low in ("/yardim", "/menu", "/start", "yardim", "menu"):
        say(HELP, chat_id)
        return
    if low in ("/durum", "/status", "/kabuk"):
        lines = ["🟢 Kartal Tablet Ajanı çalışıyor."]
        try:
            devs = _adb_raw("devices")
            lines.append("adb: " + ("✅ bağlı" if "\tdevice" in devs else "❌ yok"))
        except Exception:
            lines.append("adb: ❌ yok")
        lines.append("Shizuku/rish: " + ("✅ çalışıyor" if rish_ok() else "❌ yok"))
        lines.append("Ses (TTS): " + ("✅ hazır" if tts_available() else "❌ yok (pkg install termux-api)"))
        say("\n".join(lines) + "\n/ekran ile tableti gör.", chat_id)
        return
    if low in ("/bak", "/kontrol"):
        say(health_report(), chat_id)
        return
    if low in ("/pid", "/pil", "/battery"):
        try:
            out = termux_cmd("termux-battery-status", timeout=20)
            if out.startswith("{"):
                import json as _json
                b = _json.loads(out)
                say(f"🔋 Pil: %{b.get('percentage')} · {b.get('status')}", chat_id)
                return
        except Exception:
            pass
        try:
            out = adb("shell", "dumpsys battery")
            lvl = re.search(r"level:\s*(\d+)", out)
            chg = re.search(r"status:\s*(\d+)", out)
            say(f"🔋 Pil: %{lvl.group(1) if lvl else '?'} · {'şarjda' if chg and chg.group(1) == '2' else 'prizde değil'}", chat_id)
        except AdbError as e:
            say(f"❌ adb: {e}", chat_id)
        return
    if low in ("/ekran", "/screenshot"):
        try:
            p = screenshot("ekran")
            send_photo(p, "📱 Tablet ekranı", chat_id)
            nodes = ui_dump()
            say("Görünen: " + _visible_list(nodes, 14), chat_id)
        except AdbError as e:
            say(f"❌ {e}", chat_id)
        return
    if low.startswith("/tikla"):
        parts = raw.split()
        if len(parts) < 3:
            say("Kullanım: /tikla 540 900", chat_id)
            return
        try:
            tap(int(parts[1]), int(parts[2]))
            say(f"✅ ({parts[1]},{parts[2]}) dokunuldu", chat_id)
        except Exception as e:
            say(f"❌ {e}", chat_id)
        return
    if low.startswith("/yaz"):
        say(type_text(raw[4:].strip()), chat_id)
        return
    if low.startswith("/tus"):
        say(key(raw[4:].strip()), chat_id)
        return
    if low.startswith("/kaydir"):
        say(swipe(raw[7:].strip() or "up"), chat_id)
        return
    if low.startswith("/ac"):
        say(open_app(raw[3:].strip()), chat_id)
        return
    if low.startswith("/uygulamalar"):
        try:
            out = adb("shell", "pm list packages -3")
            pkgs = sorted(ln.replace("package:", "").strip() for ln in out.splitlines() if ln.strip())
            say("📦 <b>Kurulu uygulamalar</b>\n" + "\n".join(pkgs[:60]), chat_id)
        except AdbError as e:
            say(f"❌ {e}", chat_id)
        return
    if low.startswith("/bul"):
        arg = raw[4:].strip()
        do_tap = arg.lower().endswith("tikla")
        needle = arg[:-5].strip() if do_tap else arg
        try:
            nodes = ui_dump()
            node = find_node(nodes, needle)
            if not node:
                say(f"❌ '{needle}' yok. Görünen: {_visible_list(nodes)}", chat_id)
                return
            if do_tap:
                tap(node["cx"], node["cy"])
                say(f"✅ '{node['label']}' dokunuldu", chat_id)
            else:
                say(f"🔎 '{node['label']}' → ({node['cx']},{node['cy']})", chat_id)
        except AdbError as e:
            say(f"❌ {e}", chat_id)
        return
    if low.startswith("/paylas"):
        arg = raw[7:].strip()
        target = ""
        if arg.lower().endswith("instagram"):
            arg, target = arg[:-9].strip(), "Instagram"
        elif arg.lower().endswith("tiktok"):
            arg, target = arg[:-6].strip(), "TikTok"
        share_video(arg, target)
        return
    if low.startswith("/studio"):
        vid = raw[7:].strip()
        if not vid:
            say("Kullanım: /studio MOxaXPkS0zw", chat_id)
            return
        url = f"https://studio.youtube.com/video/{vid}/edit"
        try:
            adb("shell", f"am start -a android.intent.action.VIEW -d '{url}'")
            time.sleep(3)
            send_photo(screenshot("studio"), f"YouTube Studio · {vid}", chat_id)
        except AdbError as e:
            say(f"⚠️ adb yok ({e}) — link tablete gönderiliyor…", chat_id)
            say(open_url(url), chat_id)
        return
    if low.startswith("/konus"):
        say(speak(raw[6:].strip()), chat_id)
        return
    if low.startswith("/dinle"):
        text, status = listen_once(6)
        say(status, chat_id)
        if text and not text.startswith("("):
            say(reply_brain(text), chat_id)
        return
    if low in ("/sohbet", "/konus_sohbet", "/ses"):
        for m in chat_turn(6):
            say(m, chat_id)
        return

    if low.startswith("/gorev"):
        run_task(raw[6:].strip())
        return

    # Tanınmayan /komut -> görev olarak koşturma, menüyü göster
    if low.startswith("/"):
        say("❓ Bu komutu tanımadım.\n\n" + HELP, chat_id)
        return

    # Düz metin → sesli asistan cevabı + tablet konuşur
    ans = reply_brain(raw)
    say(ans, chat_id)
    say(speak(ans), chat_id)


# --------------------------------------------------------------------------
# 8. ANA DÖNGÜ
# --------------------------------------------------------------------------
_last_net_warn = 0.0


def main() -> None:
    load_env()
    global TARGET, _last_net_warn
    TARGET = os.getenv("ADB_TARGET", "").strip()
    if TARGET:
        try:
            _adb_raw("connect", TARGET, timeout=20)
        except Exception:
            pass
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN yok. Önce: bash kur.sh")
        sys.exit(1)

    owner = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    offset = state_get("tg_offset", 0)
    print("Kartal Tablet Ajani hazir. Telegram'dan /menu yaz.")
    who = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if who:
        say("Kartal Tablet Ajani acildi. Komutlar icin /menu yaz.", who)
    else:
        print("TELEGRAM_CHAT_ID yok - telefondan botuna ilk mesaji atinca kilitlenecek.")
    try:
        ensure_device()
    except Exception:
        pass

    backoff = 3
    while True:
        try:
            res = tg("getUpdates", {"offset": offset, "timeout": 50, "allowed_updates": ["message"]}, timeout=70)
            backoff = 3
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                state_set("tg_offset", offset)
                msg = upd.get("message") or {}
                chat_id = str((msg.get("chat") or {}).get("id", ""))
                text = msg.get("text", "")
                if not chat_id or not text:
                    continue
                if not owner:
                    # İlk mesajı gönderen kilitlenir (tek seferlik eşleştirme)
                    save_env({"TELEGRAM_CHAT_ID": chat_id})
                    os.environ["TELEGRAM_CHAT_ID"] = chat_id
                    owner = chat_id
                    say("🔐 Bu sohbet sahibi olarak kilitlendi. /menu", chat_id)
                if chat_id != owner:
                    continue
                handle(text, chat_id)
        except urllib.error.HTTPError as e:
            print(f"[telegram] HTTP {e.code} — yeniden denenecek")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
        except Exception as e:
            # Ağ yoksa ekranı doldurmayalım: 30 saniyede bir tek satır
            msg = str(e)
            now = time.time()
            if now - _last_net_warn > 30:
                print(f"[ağ] internet yok — Wi-Fi'yi kontrol et ({msg[:60]})")
                _last_net_warn = now
            time.sleep(max(backoff, 5))
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    main()
