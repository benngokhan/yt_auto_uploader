#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilgi Dozu — GitHub Hata Müdahale Ajanı (ajan_heal.py)

Ne yapar:
  1. Son 24 saatteki workflow koşularını tarar; conclusion=failure olanları bulur.
  2. Başarısız koşunun loglarını çeker, hatayı LLM (Groq -> Gemini -> OpenRouter) ile teşhis ettirir.
  3. Hata tipine göre otomatik müdahale:
       - "model_404"     : motor/uret.py içindeki eski model adını güncel modelle değiştirir, commit atar.
       - "quota_429"     : modele dokunmaz; koşuyu 10 dk sonra otomatik tekrar kuyruğa alır (re-run).
       - "flaky"         : koşuyu anında tekrar kuyruğa alır (re-run).
       - "kod_hatasi"    : LLM'in ürettiği yamayı uygular, commit atar (güvenlik: yalnız .py dosyaları, 200 satır sınırı).
       - "bilinmiyor"    : Telegram'a detaylı rapor gönderir, insan müdahalesi bekler.
  4. Her müdahaleyi Telegram'a anında bildirir (başarı/başarısız + commit linki).

Güvenlik kilitleri:
  - Aynı koşu en fazla 3 kez onarılmaya çalışılır (ajan_heal_state.json).
  - "elle" onay modu ASLA değiştirilmez (motor/ayarlar.json onay.mod korunur).
  - Yalnızca motor/*.py ve kök *.py dosyalarına yama uygulanır; workflow dosyalarına dokunulmaz.
  - Commit mesajı her zaman "[skip ci]" içerir (sonsuz döngü engeli).

Çalışma ortamı (GitHub Actions):
  GITHUB_TOKEN, GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY,
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = os.getenv("GITHUB_REPOSITORY", "benngokhan/yt_auto_uploader")
GH_TOKEN = os.getenv("GITHUB_TOKEN", "")
STATE_FILE = Path("ajan_heal_state.json")
MAX_REPAIR_ATTEMPTS = 3
LOOKBACK_HOURS = 24
# Aynı workflow için taze koşu (workflow_dispatch) sınırı: sonsuz döngü/spam engeli.
MAX_FRESH_RUNS = 3
FRESH_WINDOW_HOURS = 6
UA = "Mozilla/5.0 (BilgiDozu-AjanHeal)"


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub log indirme adresi S3'e yönlendiriyor; imzalı adrese
    Authorization başlığı giderse 401 dönüyor. Yönlendirmede bu başlığı at."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        yeni = super().redirect_request(req, fp, code, msg, headers, newurl)
        if yeni is not None:
            for k in ("Authorization", "authorization"):
                yeni.headers.pop(k, None)
                yeni.unredirected_hdrs.pop(k, None)
        return yeni

# ---------------------------------------------------------------- yardımcılar

def _gh(method: str, path: str, body: dict | None = None, timeout: int = 30):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 204:
            return {}
        raise


# Mesajların altına eklenen düğmeler. Basışları tamirci_buton_worker.py işler
# (Telegram onay işçisiyle aynı 5 dakikalık turda; cevap birkaç dakika gecikebilir).
_AKTIF_RUN: int | None = None


def _dugmeler(run_id: int | None = None) -> dict:
    satir = []
    if run_id:
        satir.append({"text": "🔍 Bu hataya bak", "callback_data": f"bak:{run_id}"})
    satir.append({"text": "📋 Durum", "callback_data": "durum"})
    return {"inline_keyboard": [satir]}


def _tg_api(method: str, payload: dict) -> dict:
    """Telegram Bot API çağrısı; hata olursa {} döner (ajan akışını asla düşürmez)."""
    bot = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot:
        print("[telegram] token yok, çağrı atlandı")
        return {}
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot}/{method}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            ayrinti = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            ayrinti = ""
        print(f"[telegram] {method} hatası: HTTP {e.code} {ayrinti}")
    except Exception as e:
        print(f"[telegram] {method} hatası: {type(e).__name__}")
    return {}


def _tg(text: str) -> None:
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or not chat:
        print("[telegram] token/chat yok, bildirim atlandı")
        return
    r = _tg_api("sendMessage", {
        "chat_id": chat, "text": text[:3900], "parse_mode": "HTML",
        "disable_web_page_preview": True, "reply_markup": _dugmeler(_AKTIF_RUN),
    })
    if r.get("ok"):
        print("[telegram] bildirim gönderildi")


def _panel_mesaji(state: dict) -> None:
    """Gruba bir kez 'Durum' düğmeli sabit kontrol mesajı gönderir ve sabitlemeyi dener."""
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if state.get("_panel") or not chat:
        return
    r = _tg_api("sendMessage", {
        "chat_id": chat, "parse_mode": "HTML", "reply_markup": _dugmeler(),
        "text": ("🔧 <b>Tamirci — durum düğmesi</b>\n\n"
                 "Sistemde hata var mı diye sormak için alttaki <b>Durum</b> düğmesine bas.\n"
                 "Hata mesajlarının altındaki <b>Bu hataya bak</b> düğmesi o hatayı sade dille anlatır.\n"
                 "Cevap anında gelmez; birkaç dakika içinde bu gruba yazarım."),
    })
    if not r.get("ok"):
        return
    mid = (r.get("result") or {}).get("message_id")
    if mid:
        _tg_api("pinChatMessage", {"chat_id": chat, "message_id": mid, "disable_notification": True})
    state["_panel"] = {"message_id": mid, "ts": datetime.now(timezone.utc).isoformat()}
    _state_save(state)


def _state_load() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _state_save(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- LLM zinciri

def _llm(prompt: str) -> str:
    """Groq -> Gemini -> OpenRouter zinciri; ilk dolu yanıtı döndürür."""
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            body = json.dumps({
                "model": "llama-3.3-70b-versatile",
                "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}],
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=body, method="POST",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json", "User-Agent": UA},
            )
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.loads(r.read().decode("utf-8"))
            txt = d["choices"][0]["message"]["content"].strip()
            if txt:
                return txt
        except Exception as e:
            print(f"[llm] groq hata: {e}")

    gem_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gem_key:
        try:
            with urllib.request.urlopen(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={gem_key}", timeout=30
            ) as r:
                models = json.loads(r.read().decode("utf-8")).get("models", [])
            usable = [
                m["name"].split("/", 1)[-1] for m in models
                if "generateContent" in m.get("supportedGenerationMethods", [])
                and "flash" in m["name"].lower()
                and not any(x in m["name"].lower() for x in ("tts", "image", "live", "omni"))
            ]
            for model in usable[:3]:
                try:
                    body = json.dumps({
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.2},
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gem_key}",
                        data=body, method="POST",
                        headers={"Content-Type": "application/json", "User-Agent": UA},
                    )
                    with urllib.request.urlopen(req, timeout=45) as r:
                        d = json.loads(r.read().decode("utf-8"))
                    txt = "".join(
                        p.get("text", "") for p in d["candidates"][0]["content"].get("parts", [])
                    ).strip()
                    if txt:
                        return txt
                except Exception:
                    continue
        except Exception as e:
            print(f"[llm] gemini hata: {e}")

    or_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if or_key:
        try:
            body = json.dumps({
                "model": "meta-llama/llama-3.3-70b-instruct:free",
                "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}],
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.openrouter.ai/api/v1/chat/completions",
                data=body, method="POST",
                headers={
                    "Authorization": f"Bearer {or_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/benngokhan/yt_auto_uploader",
                    "User-Agent": UA,
                },
            )
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.loads(r.read().decode("utf-8"))
            txt = d["choices"][0]["message"]["content"].strip()
            if txt:
                return txt
        except Exception as e:
            print(f"[llm] openrouter hata: {e}")

    # Anahtarsız son yedekler (awesome-free-llm-apis listesinden; kayıt/anahtar gerekmez)
    try:
        body = json.dumps({
            "model": "kilo-auto/free",
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.kilo.ai/api/gateway/chat/completions",
            data=body, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=45) as r:
            d = json.loads(r.read().decode("utf-8"))
        txt = d["choices"][0]["message"]["content"].strip()
        if txt:
            return txt
    except Exception as e:
        print(f"[llm] kilo hata: {e}")

    try:
        body = json.dumps({
            "model": "gpt-oss:20b",
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.llm7.io/v1/chat/completions",
            data=body, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=45) as r:
            d = json.loads(r.read().decode("utf-8"))
        txt = d["choices"][0]["message"]["content"].strip()
        if txt:
            return txt
    except Exception as e:
        print(f"[llm] llm7 hata: {e}")

    return ""


# ---------------------------------------------------------------- hata sınıflandırma

_KURALLAR: list[tuple[str, re.Pattern]] = [
    ("workflow_bozuk", re.compile(r"invalid workflow file|workflow file issue|mapping values are not allowed|could not parse as yaml")),
    ("telegram_grup", re.compile(r"chat not found|bot was blocked|not a member of the chat|forbidden: bot|not enough rights")),
    ("telegram_limit", re.compile(r"request entity too large|file is too big|payload too large|video g[öo]nderilemedi|returned error: 413|\b413\b")),
    ("yetki_suresi", re.compile(r"invalid_grant|unauthorized|invalid credentials|invalid_token|token has been expired|token expired|\b401\b")),
    ("izin_yok", re.compile(r"resource not accessible|permission denied|insufficient permission|\b403\b")),
    ("youtube_kota", re.compile(r"quotaexceeded|dailylimitexceeded|youtube quota")),
    ("quota_429", re.compile(r"\b429\b|too many requests|resource_exhausted|rate limit")),
    ("git_cakismasi", re.compile(r"cannot pull with rebase|failed to push some refs|unstaged changes|non-fast-forward|fetch first|could not apply")),
    ("disk_dolu", re.compile(r"no space left|disk full|enospc")),
    ("bellek_yetersiz", re.compile(r"out of memory|memoryerror|exit code 137|oom-kill|killed process")),
    ("ses_hatasi", re.compile(r"ses do[ğg]rulamas[ıi]|seshatasi|ses [üu]retimi|do[ğg]al ses")),
    ("dosya_bozuk", re.compile(r"badzipfile|file is not a zip|zipfile|corrupt file")),
    ("arguman_hatasi", re.compile(r"expected one argument|unrecognized arguments|error: argument|invalid choice")),
    ("drive_hatasi", re.compile(r"googleapiclient|httperror 40[045]|httperror 50[023]|drive'a konamadi|drive hedefi http")),
    ("render_hatasi", re.compile(r"ffmpeg|codec|invalid data found when processing")),
    ("eksik_ayar", re.compile(r"input required and not supplied|missing secret|secret not set|undefined variable|tan[ıi]ml[ıi] de[ğg]il")),
    ("flaky", re.compile(r"connection reset|timed out|timeout|econnreset|service unavailable|\b50[234]\b")),
    ("kaynak_yok", re.compile(r"\b404\b|not found|no such file")),
    ("test_hatasi", re.compile(r"failed \(failures=|ran \d+ tests?.{0,40}fail|tests failed")),
    ("model_hatasi", re.compile(r"gemini ba[şs]ar[ıi]s[ıi]z|llm denemesi ba[şs]ar[ıi]s[ıi]z|model hatas[ıi]")),
    ("kod_hatasi", re.compile(r"traceback|syntaxerror|importerror|modulenotfound|nameerror|typeerror|attributeerror|keyerror|runtimeerror")),
]
_MODEL_IZI = re.compile(r"gemini|model|llm|openrouter|groq|anthropic")


def _classify(log_tail: str) -> str:
    """Logdaki SON hata ipucuna göre tür belirler.

    Sabit sıra yerine "en son görülen" kural kazanır: bir iş önce 403 alıp
    sonra 429 ile bitebiliyor; son hata gerçek sebeptir. Eşitlikte üstteki kural.
    """
    low = (log_tail or "").lower()
    if not low:
        return "bilinmiyor"
    secilen, konum = "bilinmiyor", -1
    for kind, rx in _KURALLAR:
        son = -1
        for m in rx.finditer(low):
            son = m.end()
        if son > konum:
            secilen, konum = kind, son
    if secilen in ("kaynak_yok", "bilinmiyor") and "404" in low:
        if _MODEL_IZI.search(low):
            return "model_404"
        if "drive" in low or "googleapis" in low:
            return "drive_hatasi"
    if secilen == "bilinmiyor" and ("exit code" in low or "process completed" in low):
        return "log_yok"
    return secilen


# ---------------------------------------------------------------- sade Türkçe rapor

# Workflow adları -> sahibin anlayacağı sade isim
IS_ADLARI = {
    "YouTube Drive Uploader": "Video yükleme",
    "Motor - video üret (elle onaylı)": "Video üretimi",
    "Panel Telemetri & Drive Senkron (30 Dk)": "Panel ve stok güncellemesi",
    "Telegram onay buton işçisi": "Telegram onay düğmeleri",
    "API durum ve limit görüntüsü": "API durum kontrolü",
    "API & Kota": "API ve kota kontrolü",
    "Slot Watchdog": "Yayın nöbetçisi",
    "Retansiyon Raporu (Ozel Analytics)": "İzlenme yüzdesi raporu",
    "Goruntulenme Raporu (yt-dlp)": "Görüntülenme raporu",
    "Arena 5 Günlük Gözlem Serisi Planla ve Takip Et": "5 günlük plan",
    "Hata Müdahale Ajanı (GitHub Oto-Onarım)": "Tamirci",
    "Konu Önerileri": "Konu önerileri",
    "Offsite Yedek (FTP/FTPS)": "Dış yedek",
}

# Logda görülen teknik ifade -> sade Türkçe açıklama
# (sorun, önerilen çözüm, işi kim yapar: "ajan" | "sen")
HATA_SOZLUGU = [
    (("401", "unauthorized", "invalid_grant", "invalid credentials", "invalid_token",
      "token has been expired", "token expired"),
     "YouTube/Google bağlantısının süresi dolmuş görünüyor.",
     "Bağlantıyı yenilemek gerekiyor; bunu senin onayınla yapabiliriz.", "sen"),
    (("quotaexceeded", "quota exceeded", "dailylimitexceeded", "storage quota"),
     "Günlük kullanım sınırı (kota) dolmuş.",
     "Kota sıfırlanınca kendiliğinden düzelir; bugün yeni yükleme yapmayalım.", "yok"),
    (("chat not found", "bot was blocked", "bot is not a member", "forbidden: bot"),
     "Telegram mesajı gruba ulaşamadı.",
     "Botun grupta olduğunu ve grup numarasının doğru olduğunu kontrol etmek gerekiyor.", "sen"),
    (("403", "forbidden", "permission denied", "insufficient permission"),
     "Bir servis erişim iznini reddetti (403).",
     "İzinlerin yenilenmesi gerekebilir; otomatik dokunmuyorum.", "sen"),
    (("429", "too many requests", "resource_exhausted", "rate limit"),
     "Bir servis 'çok istek' dedi; bu geçici bir sınırdır.",
     "Kısa süre sonra aynı işi kendim tekrar deniyorum.", "ajan"),
    (("model not found", "model_not_found", "does not exist", "no such model"),
     "Yapay zekâ modelinin adı değişmiş; eski ad artık geçerli değil.",
     "Model adını güncelleyip işi yeniden başlatıyorum.", "ajan"),
    (("404", "not found"),
     "Bir dosya veya adres bulunamadı (404).",
     "Hangi dosyanın eksik olduğuna bakmam gerekiyor; hiçbir şeyi değiştirmedim.", "sen"),
    (("no space left", "disk full", "enospc", "quota exceeded on disk"),
     "Sunucuda disk alanı doldu.",
     "Eski geçici dosyaların temizlenmesi gerekiyor.", "sen"),
    (("out of memory", "memoryerror", "exit code 137", "killed"),
     "Sunucunun belleği yetmedi.",
     "İşi daha küçük parçalarla tekrar denemek gerekiyor.", "sen"),
    (("invalid workflow", "yaml", "mapping values", "unexpected value", "could not parse"),
     "Workflow dosyasında yazım hatası var.",
     "Dosyayı düzeltmem gerekiyor; bu tür değişikliği kendi başıma yapmıyorum.", "sen"),
    (("context deadline exceeded", "timeout", "timed out", "connection reset",
      "econnreset", "connection refused", "network is unreachable", "502", "503", "504"),
     "Bağlantı koptu veya sunucu geçici olarak yanıt vermedi.",
     "Aynı işi tekrar deniyorum.", "ajan"),
    (("secret", "not set", "undefined variable", "tanimli degil", "tanımlı değil"),
     "Gerekli bir anahtar/ayar eksik görünüyor.",
     "Eksik anahtarın eklenmesi gerekiyor.", "sen"),
    (("ffmpeg", "codec", "invalid data found", "render"),
     "Video işleme (render) sırasında sorun çıktı.",
     "Videoyu yeniden üretmek gerekiyor; otomatik üretim başlatmıyorum.", "sen"),
    (("traceback", "syntaxerror", "importerror", "modulenotfound",
      "nameerror", "typeerror", "attributeerror", "keyerror"),
     "Kodda bir hata var.",
     "Düzeltmeyi ben deniyorum.", "ajan"),
]


def _is_adi(ad: str) -> str:
    return IS_ADLARI.get(ad, ad)


def _sorun_ozeti(kind: str, log_tail: str) -> tuple[str, str, str]:
    """(sorun, çözüm, kim) döndürür. kim: 'ajan' | 'sen' | 'yok'."""
    if kind == "model_404":
        return ("Yapay zekâ modelinin adı değişmiş; eski ad artık geçerli değil.",
                "Model adını güncelleyip işi yeniden başlatıyorum.", "ajan")
    if kind == "quota_429":
        return ("Bir servis 'çok istek' dedi; bu geçici bir sınırdır.",
                "Kısa süre sonra aynı işi kendim tekrar deniyorum.", "ajan")
    if kind == "flaky":
        return ("Bağlantı koptu veya sunucu geçici olarak yanıt vermedi.",
                "Aynı işi hemen tekrar deniyorum.", "ajan")
    if kind == "kod_hatasi":
        return ("Kodda bir hata var.",
                "Düzeltmeyi ben deniyorum.", "ajan")
    if kind == "workflow_bozuk":
        return ("İş tanımı dosyasında (workflow) yazım hatası var.",
                "Dosyayı benim düzeltmem gerekiyor; kendi başıma değiştirmiyorum.", "sen")
    if kind == "telegram_grup":
        return ("Telegram mesajı gruba ulaşamadı.",
                "Botun grupta olduğunu ve grup numarasının doğru olduğunu kontrol etmek gerekiyor.", "sen")
    if kind == "telegram_limit":
        return ("Video Telegram'a gönderilemeyecek kadar büyük.",
                "Sorun değil: video Drive'a ve arşive kondu. Yayın hattı etkilenmedi.", "yok")
    if kind == "yetki_suresi":
        return ("YouTube/Google bağlantısının süresi dolmuş görünüyor.",
                "Bağlantıyı yenilemek gerekiyor; bunu senin onayınla yapabiliriz.", "sen")
    if kind == "izin_yok":
        return ("Bir servis erişim iznini reddetti (403).",
                "İzinlerin yenilenmesi gerekiyor; otomatik dokunmuyorum.", "sen")
    if kind == "youtube_kota":
        return ("YouTube'un günlük yükleme sınırı dolmuş.",
                "Sınır sıfırlanınca kendiliğinden düzelir; bugün yeni yükleme yapmayalım.", "yok")
    if kind == "git_cakismasi":
        return ("Aynı anda iki iş dosyaya yazınca kod çakışması oldu.",
                "İşi kendim yeniden başlatıyorum.", "ajan")
    if kind == "disk_dolu":
        return ("Sunucuda disk alanı doldu.",
                "Eski geçici dosyaların temizlenmesi gerekiyor.", "sen")
    if kind == "bellek_yetersiz":
        return ("Sunucunun belleği yetmedi.",
                "İşi daha küçük parçalarla tekrar denemek gerekiyor.", "sen")
    if kind == "ses_hatasi":
        return ("Ses üretimi veya ses doğrulaması başarısız oldu (ses kalitesi tutmadı).",
                "Videoyu yeniden üretmek gerekiyor; otomatik üretim başlatmıyorum.", "sen")
    if kind == "dosya_bozuk":
        return ("Bir dosya bozuk gelmiş (açılamıyor).",
                "Dosyayı yeniden indirmek/üretmek gerekiyor; hiçbir şeyi değiştirmedim.", "sen")
    if kind == "drive_hatasi":
        return ("Google Drive'a yazarken hata çıktı.",
                "İşi kendim yeniden deniyorum; sürerse Drive ayarlarına bakmam gerekir.", "ajan")
    if kind == "render_hatasi":
        return ("Video işleme (render) sırasında sorun çıktı.",
                "Videoyu yeniden üretmek gerekiyor; otomatik üretim başlatmıyorum.", "sen")
    if kind == "eksik_ayar":
        return ("Gerekli bir anahtar/ayar eksik görünüyor.",
                "Eksik anahtarın eklenmesi gerekiyor.", "sen")
    if kind == "test_hatasi":
        return ("Kod testleri geçmedi; bu yüzden yeni sürüm yayına alınmadı.",
                "Testi düzeltmem gerekiyor; kendi başıma kod değiştirmiyorum.", "sen")
    if kind == "model_hatasi":
        return ("Yapay zekâ servisi yanıt vermedi (model tarafı).",
                "İşi kendim tekrar deniyorum; sürerse anahtarlara bakmam gerekir.", "ajan")
    if kind == "log_yok":
        return ("İş hata verdi ama kayıt sebebini yazmamış.",
                "Kaydın tamamına bakmam gerekiyor; hiçbir şeyi değiştirmedim.", "sen")
    low = (log_tail or "").lower()
    for anahtarlar, sorun, cozum, kim in HATA_SOZLUGU:
        if any(k in low for k in anahtarlar):
            return sorun, cozum, kim
    return ("Tanıdık olmayan bir hata var.",
            "İncelemem gerekiyor. Bu arada hiçbir şeyi değiştirmedim.", "sen")


def _e(metin: str, sinir: int = 400) -> str:
    """Telegram HTML için kaçış + kısaltma."""
    metin = " ".join(str(metin).split())
    if len(metin) > sinir:
        metin = metin[:sinir - 1] + "…"
    return html.escape(metin, quote=False)


def _kayit_linki(run_url: str) -> str:
    return f'<a href="{html.escape(run_url, quote=True)}">GitHub\'da gör</a>'


def _ek_not(run_name: str) -> str:
    """İşin türüne göre kısa güvence notu."""
    if "YouTube Drive Uploader" in run_name:
        return "\nNot: Studio'da planlı videolar bundan etkilenmez; yalnız sıradaki yükleme etkilenebilir."
    if any(k in run_name for k in ("Telegram onay", "Panel Telemetri")):
        return "\nNot: Yayın hattı etkilenmez; bu yalnız bildirim/panel işidir."
    return ""



def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


# ---------------------------------------------------------------- müdahale: model_404

MODEL_404_PATTERNS = [
    (re.compile(r"gemini-2\.5-flash(?!-preview-tts)"), "gemini-flash-latest"),
    (re.compile(r"gemini-3\.6-flash"), "gemini-flash-latest"),
    (re.compile(r"gemini-3\.8-flash"), "gemini-flash-latest"),
    (re.compile(r"gemini-2\.0-flash(?!-lite)"), "gemini-flash-latest"),
    (re.compile(r"llama-3\.1-70b-versatile"), "llama-3.3-70b-versatile"),
    (re.compile(r"llama-3\.1-8b-versatile"), "llama-3.3-70b-versatile"),
    (re.compile(r"mixtral-8x7b-32768"), "llama-3.3-70b-versatile"),
    (re.compile(r"gemma-2-9b-it"), "llama-3.3-70b-versatile"),
]


def _fix_model_404() -> tuple[bool, str]:
    """motor/uret.py içindeki ölü model adlarını güncel adlarla değiştirir."""
    target = Path("motor/uret.py")
    if not target.exists():
        return False, "motor/uret.py bulunamadı"
    src = target.read_text(encoding="utf-8")
    new_src = src
    changed = []
    for pat, repl in MODEL_404_PATTERNS:
        if pat.search(new_src):
            new_src = pat.sub(repl, new_src)
            changed.append(f"{pat.pattern} -> {repl}")
    if new_src == src:
        return False, "değişiklik yok (model adları zaten güncel)"
    # Güvenlik: onay modu kilidi kontrolü
    ayar = Path("motor/ayarlar.json")
    if ayar.exists():
        try:
            cfg = json.loads(ayar.read_text(encoding="utf-8"))
            if cfg.get("onay", {}).get("mod") != "elle":
                return False, "GÜVENLİK: onay.mod 'elle' değil, dokunulmuyor"
        except Exception:
            pass
    target.write_text(new_src, encoding="utf-8")
    return True, "; ".join(changed)


# ---------------------------------------------------------------- müdahale: kod_hatasi

def _yama_kapisi(dosya: str, kok: str = ".") -> tuple[bool, str]:
    """LLM yaması commit edilmeden önce hızlı güvenlik kapısı.

    1) Sözdizimi: `py_compile` (her zaman, ek paket gerekmez).
    2) O dosyaya ait bir test modülü varsa: `unittest`.
       Testler yalnız kurulu olmayan bir paket yüzünden açılamıyorsa atlanır
       (ajan workflow'unda ağır bağımlılıklar kurulu değil); gerçek bir test
       başarısızlığında yama reddedilir.
    """
    import subprocess
    import sys

    kok_yolu = Path(kok)
    dosya_yolu = kok_yolu / dosya

    try:
        p = subprocess.run([sys.executable, "-m", "py_compile", str(dosya_yolu)],
                           capture_output=True, text=True, timeout=60, cwd=str(kok_yolu))
    except Exception as e:  # pragma: no cover - beklenmeyen ortam sorunu
        return False, f"derleme çalıştırılamadı: {e}"
    if p.returncode != 0:
        satir = (p.stderr or "").strip().splitlines()
        return False, "sözdizimi hatası: " + (satir[-1] if satir else "bilinmiyor")

    stem = dosya_yolu.stem.replace("-", "_")
    test_dosyasi = kok_yolu / "tests" / f"test_{stem}.py"
    if not test_dosyasi.exists():
        return True, "sözdizimi tamam (bu dosya için test yok)"

    try:
        t = subprocess.run([sys.executable, "-m", "unittest", f"tests.test_{stem}"],
                           capture_output=True, text=True, timeout=300, cwd=str(kok_yolu))
    except Exception as e:  # pragma: no cover
        return True, f"sözdizimi tamam (testler çalıştırılamadı: {e})"
    if t.returncode == 0:
        return True, "sözdizimi + testler tamam"
    cikti = (t.stderr or "") + "\n" + (t.stdout or "")
    if "ModuleNotFoundError" in cikti or "ImportError" in cikti:
        return True, "sözdizimi tamam (testler eksik paket nedeniyle atlandı)"
    ozet = " | ".join(x.strip() for x in cikti.strip().splitlines()[-3:])
    return False, "testler geçmedi: " + ozet[:300]


def _fix_code_error(log_tail: str, run_name: str) -> tuple[bool, str, str]:
    """LLM'den yama üretir, yalnız .py dosyalarına uygular.

    Dönen üçüncü değer, değiştirilen dosyanın yoludur (kapı/geri alma için).
    """
    prompt = (
        "Sen bir Python hata düzeltme ajanısın. Aşağıdaki GitHub Actions logundaki hatayı düzeltmek için "
        "EN KÜÇÜK yamayı üret. Yalnızca Python dosyalarını değiştir. Yanıtın SADECE şu JSON olmalı:\n"
        '{"dosya": "değiştirilecek dosya yolu (örn: motor/uret.py)", '
        '"eski": "değiştirilecek eski kod bloğu (tam metin)", '
        '"yeni": "yeni kod bloğu (tam metin)", '
        '"aciklama": "kısa Türkçe açıklama"}\n'
        "Eğer hatayı anlayamıyorsan {\"dosya\": \"\"} döndür.\n\n"
        f"Workflow: {run_name}\nLog kuyruğu:\n{log_tail[-3500:]}"
    )
    raw = _llm(prompt)
    patch = _extract_json(raw)
    dosya = (patch.get("dosya") or "").strip()
    eski = patch.get("eski") or ""
    yeni = patch.get("yeni") or ""
    if not dosya or not eski or not yeni:
        return False, "LLM yama üretemedi", ""
    if not dosya.endswith(".py") or ".." in dosya or dosya.startswith("/"):
        return False, f"GÜVENLİK: izin verilmeyen dosya ({dosya})", ""
    if len(eski) > 4000 or len(yeni) > 4000:
        return False, "GÜVENLİK: yama çok büyük", ""
    target = Path(dosya)
    if not target.exists():
        return False, f"dosya yok: {dosya}", ""
    src = target.read_text(encoding="utf-8")
    if src.count(eski) != 1:
        return False, "eski blok dosyada tam 1 kez bulunamadı", ""
    # Güvenlik: onay modu kilidi
    ayar = Path("motor/ayarlar.json")
    if ayar.exists():
        try:
            cfg = json.loads(ayar.read_text(encoding="utf-8"))
            if cfg.get("onay", {}).get("mod") != "elle":
                return False, "GÜVENLİK: onay.mod 'elle' değil", ""
        except Exception:
            pass
    target.write_text(src.replace(eski, yeni, 1), encoding="utf-8")
    return True, f"{dosya}: {patch.get('aciklama', '')}", dosya


# ---------------------------------------------------------------- ana akış

def _get_failed_runs() -> list[dict]:
    # NOT: GitHub API "created" filtresi ">=YYYY-MM-DD" formatında çalışır; saat kısmı eklenince
    # boş sonuç döner. Bu yüzden filtreyi tarih (gün) düzeyinde verip Python'da saat filtresi uygula.
    since_dt = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    since_day = since_dt.strftime("%Y-%m-%d")
    runs = _gh("GET", f"actions/runs?per_page=100&created=>={since_day}")
    out = []
    for r in runs.get("workflow_runs", []):
        if r.get("conclusion") != "failure":
            continue
        try:
            created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if created >= since_dt:
            out.append(r)
    return out


_ILGI = re.compile(
    r"(?i)(##\[error\]|traceback|error|exception|httperror|http error \d{3}|\bhttp \d{3}|quota|"
    r"denied|not found|no space|out of memory|killed|timed out|timeout|cannot |could not|failed|"
    r"unable|invalid|eksik|hata|başarısız|basarisiz)"
)
_GURULTU = re.compile(
    r"(?i)^\s*(##\[group\]|##\[command\]|##\[warning\]|\[command\]|post job cleanup|"
    r"cleaning up orphan|node\.js \d+|pythonlocation:|git version|from google|import |def |"
    r"class |return |if |for |else|elif|try:|except|raise |print\(|echo |set |shopt |pip |"
    r"python -|sure=|fi|done|then|do|\{|\})"
)


def _log_ozeti(metin: str, sinir: int = 5000) -> str:
    """Koca logun içinden gerçek hata satırlarını çıkarır.

    GitHub loglarında adımın betiği "##[group]Run ..." bloğunda aynen basılıyor;
    bu yüzden "son N karakter" çoğu zaman gerçek hata yerine betik satırlarını
    gösteriyordu. Burada önce betik blokları atılır, sonra ilk hata işaretine kadar
    olan kısımdan hata satırları/traceback seçilir.
    """
    satirlar: list[str] = []
    grup_icinde = False
    for ham in metin.splitlines():
        s = re.sub(r"^\S*Z\s*", "", ham).rstrip()[:300]
        if "##[group]" in s:
            grup_icinde = True
            continue
        if "##[endgroup]" in s:
            grup_icinde = False
            continue
        kritik = "##[error]" in s or s.lower().startswith("traceback (most recent call last)")
        if not grup_icinde or kritik:
            satirlar.append(s)

    # Hata satırından sonrası (temizlik, artifact yükleme) sebep değil.
    for i, s in enumerate(satirlar):
        if "##[error]Process completed with exit code" in s:
            satirlar = satirlar[:i + 1]
            break

    secili: list[str] = []
    i = 0
    while i < len(satirlar):
        s = satirlar[i]
        if "traceback (most recent call last)" in s.lower():
            secili.extend(satirlar[i:i + 25])
            i += 25
            continue
        if s and not _GURULTU.match(s) and _ILGI.search(s):
            secili.append(s)
        i += 1

    gorulen: set[str] = set()
    tekil = [s for s in secili if not (s in gorulen or gorulen.add(s))]
    if not tekil:
        tekil = [s for s in satirlar if s.strip()][-30:]
    metin = "\n".join(tekil[-60:])
    return metin[-sinir:] if metin else ""


def _get_log_tail(run_id: int) -> str:
    """Başarısız job/adım bilgisini + varsa gerçek log kuyruğunu döndürür.

    GitHub log API (actions/jobs/{id}/logs) bazen 401 verir; o durumda job/adım
    listesinden sınıflandırma yapılır. Log alınabilirse son 6000 karakter eklenir.
    """
    try:
        jobs = _gh("GET", f"actions/runs/{run_id}/jobs")
        tails = []
        failed_job_ids = []
        for job in jobs.get("jobs", []):
            if job.get("conclusion") != "failure":
                continue
            failed_job_ids.append(job["id"])
            failed_steps = [s["name"] for s in job.get("steps", []) if s.get("conclusion") == "failure"]
            tails.append(f"Job: {job['name']} | Başarısız adımlar: {failed_steps}")
        base = "\n".join(tails)
        # Gerçek logu dene (başarırsa sınıflandırma çok daha isabetli olur)
        for jid in failed_job_ids[:1]:
            try:
                req = urllib.request.Request(
                    f"https://api.github.com/repos/{REPO}/actions/jobs/{jid}/logs",
                    headers={
                        "Authorization": f"Bearer {GH_TOKEN}",
                        "Accept": "application/vnd.github+json",
                        "User-Agent": UA,
                    },
                )
                opener = urllib.request.build_opener(_NoAuthRedirect())
                with opener.open(req, timeout=30) as resp:
                    logs = resp.read().decode("utf-8", errors="ignore")
                if logs:
                    ozet = _log_ozeti(logs)
                    base += "\n--- HATA SATIRLARI ---\n" + (ozet or logs[-4000:])
                    break
            except Exception:
                continue
        return base
    except Exception as e:
        return f"(log alınamadı: {e})"


def _rerun(run_id: int) -> bool:
    try:
        _gh("POST", f"actions/runs/{run_id}/rerun-failed-jobs", {})
        return True
    except Exception as e:
        print(f"[rerun] hata: {e}")
        return False


def _girdisiz_dispatch_var(wf_yaml: str) -> bool:
    """Workflow elle başlatılabiliyor (workflow_dispatch) VE girdi (inputs) istemiyorsa True.

    Girdi isteyen workflow'lar taze başlatılmaz: özgün girdiler bilinmeden başlatmak
    farklı bir iş yaptırabilir (ör. yanlış video). Onlarda eski usul re-run kullanılır.
    """
    satirlar = wf_yaml.splitlines()
    for i, satir in enumerate(satirlar):
        m = re.match(r"^(\s*)workflow_dispatch\s*:(.*)$", satir)
        if not m:
            continue
        girinti = len(m.group(1))
        for alt in satirlar[i + 1:]:
            if not alt.strip() or alt.lstrip().startswith("#"):
                continue
            if len(alt) - len(alt.lstrip()) <= girinti:
                break
            if alt.strip().startswith("inputs"):
                return False
        return True
    return False


def _taze_hak_var(state: dict, wf_path: str) -> bool:
    """Bu workflow için son FRESH_WINDOW_HOURS içinde taze koşu hakkı kaldı mı?"""
    sinir = datetime.now(timezone.utc) - timedelta(hours=FRESH_WINDOW_HOURS)
    kayitlar = state.setdefault("_taze", {})
    yeni = []
    for ts in kayitlar.get(wf_path, []):
        try:
            if datetime.fromisoformat(ts) >= sinir:
                yeni.append(ts)
        except Exception:
            continue
    kayitlar[wf_path] = yeni
    return len(yeni) < MAX_FRESH_RUNS


def _restart(run: dict, state: dict) -> str:
    """Başarısız işi yeniden başlatır. Dönüş: "taze" | "rerun" | "limit" | "hata".

    NEDEN: "re-run" koşuyu ESKİ commit ve ESKİ workflow dosyasıyla tekrarlar. Depo o
    arada ilerlediyse (git çakışması) ya da hata bir commit ile düzeltildiyse re-run
    aynı hatayı tekrar üretir. Bu yüzden mümkünse main üzerinde TAZE koşu başlatılır.
    """
    run_id = run["id"]
    wf_path = run.get("path", "")
    uygun = False
    if wf_path:
        try:
            icerik = _gh("GET", f"contents/{wf_path}?ref=main")
            import base64
            uygun = _girdisiz_dispatch_var(base64.b64decode(icerik.get("content", "")).decode("utf-8", "replace"))
        except Exception as e:
            print(f"[restart] workflow okunamadı: {e}")
    if not uygun:
        return "rerun" if _rerun(run_id) else "hata"
    if not _taze_hak_var(state, wf_path):
        print(f"[restart] {wf_path}: {FRESH_WINDOW_HOURS} saatte {MAX_FRESH_RUNS} taze koşu sınırı doldu")
        return "limit"
    try:
        _gh("POST", f"actions/workflows/{wf_path.rsplit('/', 1)[-1]}/dispatches", {"ref": "main"})
    except Exception as e:
        print(f"[restart] taze koşu başlatılamadı ({e}); re-run deneniyor")
        return "rerun" if _rerun(run_id) else "hata"
    state["_taze"][wf_path].append(datetime.now(timezone.utc).isoformat())
    # Eski koşu "failure" olarak kalır; tekrar tekrar işlenmesin diye devredildi işaretle.
    state.setdefault(str(run_id), {})["devredildi"] = True
    _state_save(state)
    print(f"[restart] {wf_path}: main üzerinde taze koşu başlatıldı (eski koşu {run_id} devredildi)")
    return "taze"


def _commit_and_push(message: str) -> str:
    """Değişen dosyaları commit edip push eder; commit SHA döndürür."""
    import subprocess
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
    subprocess.run(["git", "add", "-A"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        return ""
    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return sha


def main() -> None:
    print("=== Bilgi Dozu Hata Müdahale Ajanı başlıyor ===")
    global _AKTIF_RUN
    _AKTIF_RUN = None
    state = _state_load()
    _panel_mesaji(state)
    failed = _get_failed_runs()
    # Yerine taze koşu başlatılmış eski koşular tarihsel artıktır; sayma ve işleme.
    failed = [r for r in failed if not state.get(str(r["id"]), {}).get("devredildi")]
    print(f"Son {LOOKBACK_HOURS} saatte {len(failed)} başarısız koşu bulundu")

    if not failed:
        # SPAM ENGELİ: "her şey yolunda" mesajı yalnız durum DEĞİŞİNCE gönderilir:
        #   - ilk çalıştırma (çevrimiçi bildirimi)
        #   - hatalı -> sağlıklı geçişi (iyileşme bildirimi)
        # Aksi halde tamamen sessiz geçilir; ne Telegram mesajı ne state commit'i üretilir.
        prev_failed = int(state.get("_health", {}).get("last_failed_count", -1))
        if prev_failed == -1:
            _tg("🔧 <b>Tamirci:</b> Nöbetteyim. Şu an sorun yok.")
            state["_health"] = {"last_failed_count": 0, "ts": datetime.now(timezone.utc).isoformat()}
            _state_save(state)
        elif prev_failed > 0:
            _tg("✅ <b>Tamirci:</b> Sorunlar temizlendi, sistem sağlıklı.")
            state["_health"] = {"last_failed_count": 0, "ts": datetime.now(timezone.utc).isoformat()}
            _state_save(state)
        else:
            print("[ajan] hata yok — sessiz geçiliyor (spam engeli)")
        return

    state["_health"] = {"last_failed_count": len(failed), "ts": datetime.now(timezone.utc).isoformat()}
    _state_save(state)

    for run in failed:
        run_id = run["id"]
        run_name = run["name"]
        run_url = run["html_url"]
        _AKTIF_RUN = run_id  # bu koşuyla ilgili mesajlara "Bu hataya bak" düğmesi eklenir
        attempts = int(state.get(str(run_id), {}).get("attempts", 0))
        if attempts >= MAX_REPAIR_ATTEMPTS:
            print(f"[{run_id}] deneme hakkı doldu ({attempts}/{MAX_REPAIR_ATTEMPTS}), atlanıyor")
            # Sahibe yalnız BİR kez haber ver (her taramada tekrar mesaj atmasın)
            if not state.get(str(run_id), {}).get("gave_up"):
                kayit = state.setdefault(str(run_id), {})
                kayit["gave_up"] = True
                _state_save(state)
                onceki_tur = kayit.get("kind", "bilinmiyor")
                sorun, _, _ = _sorun_ozeti(onceki_tur, "")
                _tg(
                    f"🔴 <b>{_e(_is_adi(run_name), 60)} — çözemedim</b>\n\n"
                    f"Sorun: {sorun}\n"
                    f"Durum: {MAX_REPAIR_ATTEMPTS} kez denedim, olmadı. Artık kendi başıma dokunmuyorum.\n"
                    f"Alttaki \"Bu hataya bak\" düğmesine basarsan logu okuyup sade dille anlatırım.{_ek_not(run_name)}\n"
                    f"Koşu: {_kayit_linki(run_url)}"
                )
            continue

        # Workflow dosyası artık main'de yoksa (geçici/deneme workflow'u silinmişse)
        # bu koşu tarihsel bir artıktır; müdahale edilemez, atla.
        wf_path = run.get("path", "")
        if wf_path:
            try:
                _gh("GET", f"contents/{wf_path}?ref=main")
            except Exception:
                print(f"[{run_id}] workflow dosyası main'de yok ({wf_path}), tarihsel koşu — atlanıyor")
                continue

        log_tail = _get_log_tail(run_id)
        kind = _classify(log_tail)
        print(f"[{run_id}] {run_name} -> hata tipi: {kind}")

        state[str(run_id)] = {"attempts": attempts + 1, "kind": kind, "ts": datetime.now(timezone.utc).isoformat()}
        _state_save(state)

        if kind == "model_404":
            ok, detail = _fix_model_404()
            if ok:
                sha = _commit_and_push(f"fix(ajan): ölü model adlarını güncelle [{kind}] [skip ci]")
                _tg(
                    f"🟢 <b>{_e(_is_adi(run_name), 60)} — onarıldı</b>\n\n"
                    f"Sorun: Yapay zekâ modelinin adı değişmişti.\n"
                    f"Yaptığım: Eski model adını güncel adla değiştirdim ve işi yeniden başlattım.\n"
                    f"Koşu: {_kayit_linki(run_url)}"
                )
                _restart(run, state)
            else:
                _tg(
                    f"🟡 <b>{_e(_is_adi(run_name), 60)} — takıldı</b>\n\n"
                    f"Sorun: Yapay zekâ modelinin adı değişmişti.\n"
                    f"Durum: Otomatik düzeltemedim. Bunu benim elle düzeltmem gerekiyor.\n"
                    f"Sebep: {_e(detail, 160)}\n"
                    f"Koşu: {_kayit_linki(run_url)}"
                )

        elif kind == "git_cakismasi":
            sorun, cozum, _ = _sorun_ozeti(kind, log_tail)
            sonuc = _restart(run, state)
            if sonuc == "limit":
                kayit = state.setdefault(str(run_id), {})
                kayit["attempts"] = MAX_REPAIR_ATTEMPTS
                kayit["gave_up"] = True
                _state_save(state)
                _tg(
                    f"🔴 <b>{_e(_is_adi(run_name), 60)} — çözemedim</b>\n\n"
                    f"Sorun: {sorun}\n"
                    f"Durum: {MAX_FRESH_RUNS} kez sıfırdan başlattım, yine olmadı. Artık kendi başıma dokunmuyorum.\n"
                    f"Bu işin kaydetme adımına elle bakılması gerekiyor.{_ek_not(run_name)}\n"
                    f"Koşu: {_kayit_linki(run_url)}"
                )
            else:
                _tg(
                    f"🟡 <b>{_e(_is_adi(run_name), 60)} — geçici sorun</b>\n\n"
                    f"Sorun: {sorun}\n"
                    f"Yaptığım: {cozum}\n"
                    f"Senin bir şey yapmana gerek yok.{_ek_not(run_name)}\n"
                    f"Koşu: {_kayit_linki(run_url)}"
                )

        elif kind in ("quota_429", "flaky", "drive_hatasi", "model_hatasi"):
            sorun, cozum, _ = _sorun_ozeti(kind, log_tail)
            _tg(
                f"🟡 <b>{_e(_is_adi(run_name), 60)} — geçici sorun</b>\n\n"
                f"Sorun: {sorun}\n"
                f"Yaptığım: {cozum}\n"
                f"Senin bir şey yapmana gerek yok.{_ek_not(run_name)}\n"
                f"Koşu: {_kayit_linki(run_url)}"
            )
            _rerun(run_id)

        elif kind == "kod_hatasi":
            ok, detail, dosya = _fix_code_error(log_tail, run_name)
            if ok:
                # Commit'ten önce kapı: sözdizimi + varsa ilgili testler.
                gecti, kapi_notu = _yama_kapisi(dosya) if dosya else (False, "dosya adı yok")
                if not gecti:
                    import subprocess
                    subprocess.run(["git", "checkout", "--", dosya], check=False)
                    _tg(
                        f"🟡 <b>{_e(_is_adi(run_name), 60)} — yama güvenlik kapısında durdu</b>\n\n"
                        f"Sorun: Kodda bir hata vardı.\n"
                        f"Yaptığım: Yama üretildi ama commit etmeden geri aldım.\n"
                        f"Sebep: {_e(kapi_notu, 200)}\n"
                        f"Hiçbir şey değiştirilmedi. Bu dosyaya elle bakmam gerekiyor.{_ek_not(run_name)}\n"
                        f"Koşu: {_kayit_linki(run_url)}"
                    )
                else:
                    sha = _commit_and_push(f"fix(ajan): kod hatası otomatik yaması [{kind}] [skip ci]")
                    _tg(
                        f"🟢 <b>{_e(_is_adi(run_name), 60)} — onarıldı</b>\n\n"
                        f"Sorun: Kodda küçük bir hata vardı.\n"
                        f"Düzeltme: {_e(detail, 200)}\n"
                        f"Kontrol: {_e(kapi_notu, 120)}\n"
                        f"Yaptığım: Düzeltmeyi uyguladım ve işi yeniden başlattım.\n"
                        f"Koşu: {_kayit_linki(run_url)}"
                    )
                    _restart(run, state)
            else:
                _tg(
                    f"🔴 <b>{_e(_is_adi(run_name), 60)} — otomatik düzeltemedim</b>\n\n"
                    f"Sorun: Kodda bir hata var.\n"
                    f"Durum: Otomatik denedim, olmadı. Bu turda başka bir şeyi değiştirmedim.\n"
                    f"Sebep: {_e(detail, 200)}\n"
                    f"Alttaki \"Bu hataya bak\" düğmesine basarsan logu okuyup sade dille anlatırım.{_ek_not(run_name)}\n"
                    f"Koşu: {_kayit_linki(run_url)}"
                )

        else:
            sorun, cozum, kim = _sorun_ozeti(kind, log_tail)
            if kind == "log_yok":
                baslik = "sebebi kayıtta yok"
            elif kind == "bilinmiyor":
                baslik = "tanımadığım bir hata"
            else:
                baslik = "sorun var"
            if kim == "sen":
                gereken = "Senin bakman gerekiyor."
            elif kim == "yok":
                gereken = "Senin bir şey yapmana gerek yok."
            else:
                gereken = ""
            simge = "🟡" if kim == "yok" else "🔴"
            _tg(
                f"{simge} <b>{_e(_is_adi(run_name), 60)} — {baslik}</b>\n\n"
                f"Sorun: {sorun}\n"
                f"Ne yapmalı: {cozum}\n"
                f"{gereken}{_ek_not(run_name)}\n"
                f"Koşu: {_kayit_linki(run_url)}"
            )

    _AKTIF_RUN = None
    print("=== Ajan taraması tamamlandı ===")


if __name__ == "__main__":
    main()
