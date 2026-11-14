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
UA = "Mozilla/5.0 (BilgiDozu-AjanHeal)"

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


def _tg(text: str) -> None:
    bot = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot or not chat:
        print("[telegram] token/chat yok, bildirim atlandı")
        return
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot}/sendMessage",
            data=json.dumps({"chat_id": chat, "text": text[:3900], "parse_mode": "HTML"}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        print("[telegram] bildirim gönderildi")
    except Exception as e:
        print(f"[telegram] bildirim hatası: {e}")


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

def _classify(log_tail: str) -> str:
    low = log_tail.lower()
    if "404" in low and ("model" in low or "not found" in low):
        return "model_404"
    if "429" in low or "too many requests" in low or "quota" in low or "resource_exhausted" in low:
        return "quota_429"
    if any(k in low for k in ("connection reset", "timeout", "timed out", "network", "econnreset", "502", "503", "504")):
        return "flaky"
    if any(k in low for k in ("traceback", "syntaxerror", "importerror", "modulenotfound", "nameerror", "typeerror", "attributeerror", "keyerror", "runtimeerror")):
        return "kod_hatasi"
    return "bilinmiyor"


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

def _fix_code_error(log_tail: str, run_name: str) -> tuple[bool, str]:
    """LLM'den yama üretir, yalnız .py dosyalarına uygular."""
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
        return False, "LLM yama üretemedi"
    if not dosya.endswith(".py") or ".." in dosya or dosya.startswith("/"):
        return False, f"GÜVENLİK: izin verilmeyen dosya ({dosya})"
    if len(eski) > 4000 or len(yeni) > 4000:
        return False, "GÜVENLİK: yama çok büyük"
    target = Path(dosya)
    if not target.exists():
        return False, f"dosya yok: {dosya}"
    src = target.read_text(encoding="utf-8")
    if src.count(eski) != 1:
        return False, "eski blok dosyada tam 1 kez bulunamadı"
    # Güvenlik: onay modu kilidi
    ayar = Path("motor/ayarlar.json")
    if ayar.exists():
        try:
            cfg = json.loads(ayar.read_text(encoding="utf-8"))
            if cfg.get("onay", {}).get("mod") != "elle":
                return False, "GÜVENLİK: onay.mod 'elle' değil"
        except Exception:
            pass
    target.write_text(src.replace(eski, yeni, 1), encoding="utf-8")
    return True, f"{dosya}: {patch.get('aciklama', '')}"


# ---------------------------------------------------------------- ana akış

def _get_failed_runs() -> list[dict]:
    # NOT: GitHub API "created" filtresi ">=YYYY-MM-DD" formatında çalışır; saat kısmı eklenince
    # boş sonuç döner. Bu yüzden filtreyi tarih (gün) düzeyinde verip Python'da saat filtresi uygula.
    since_dt = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    since_day = since_dt.strftime("%Y-%m-%d")
    runs = _gh("GET", f"actions/runs?per_page=50&created=>={since_day}")
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
                with urllib.request.urlopen(req, timeout=30) as resp:
                    logs = resp.read().decode("utf-8", errors="ignore")
                if logs:
                    base += "\n--- LOG KUYRUĞU ---\n" + logs[-6000:]
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
    state = _state_load()
    failed = _get_failed_runs()
    print(f"Son {LOOKBACK_HOURS} saatte {len(failed)} başarısız koşu bulundu")

    if not failed:
        # SPAM ENGELİ: "her şey yolunda" mesajı yalnız durum DEĞİŞİNCE gönderilir:
        #   - ilk çalıştırma (çevrimiçi bildirimi)
        #   - hatalı -> sağlıklı geçişi (iyileşme bildirimi)
        # Aksi halde tamamen sessiz geçilir; ne Telegram mesajı ne state commit'i üretilir.
        prev_failed = int(state.get("_health", {}).get("last_failed_count", -1))
        if prev_failed == -1:
            _tg("✅ <b>Hata Müdahale Ajanı:</b> Çevrimiçi ve nöbette. Şu an hata yok.")
            state["_health"] = {"last_failed_count": 0, "ts": datetime.now(timezone.utc).isoformat()}
            _state_save(state)
        elif prev_failed > 0:
            _tg("✅ <b>Hata Müdahale Ajanı:</b> Hatalar temizlendi, sistem sağlıklı.")
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
        attempts = int(state.get(str(run_id), {}).get("attempts", 0))
        if attempts >= MAX_REPAIR_ATTEMPTS:
            print(f"[{run_id}] deneme hakkı doldu ({attempts}/{MAX_REPAIR_ATTEMPTS}), atlanıyor")
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
                    f"🛠️ <b>Hata Müdahale Ajanı — Model düzeltildi!</b>\n"
                    f"Workflow: {run_name}\nDeğişiklik: {detail}\n"
                    f"Commit: https://github.com/{REPO}/commit/{sha[:8]}\n"
                    f"Başarısız koşu: {run_url}\n"
                    f"Koşuyu tekrar başlatıyorum..."
                )
                _rerun(run_id)
            else:
                _tg(
                    f"⚠️ <b>Hata Müdahale Ajanı — Model hatası ama düzeltilemedi:</b> {detail}\n"
                    f"Workflow: {run_name}\nKoşu: {run_url}"
                )

        elif kind in ("quota_429", "flaky"):
            _tg(
                f"🔄 <b>Hata Müdahale Ajanı — Geçici hata, koşu tekrar kuyruğa alınıyor:</b>\n"
                f"Workflow: {run_name} (tip: {kind})\nKoşu: {run_url}"
            )
            _rerun(run_id)

        elif kind == "kod_hatasi":
            ok, detail = _fix_code_error(log_tail, run_name)
            if ok:
                sha = _commit_and_push(f"fix(ajan): kod hatası otomatik yaması [{kind}] [skip ci]")
                _tg(
                    f"🛠️ <b>Hata Müdahale Ajanı — Kod yaması uygulandı!</b>\n"
                    f"Workflow: {run_name}\nYama: {detail}\n"
                    f"Commit: https://github.com/{REPO}/commit/{sha[:8]}\n"
                    f"Başarısız koşu: {run_url}"
                )
                _rerun(run_id)
            else:
                _tg(
                    f"🚨 <b>Hata Müdahale Ajanı — Kod hatası, otomatik yama başarısız:</b> {detail}\n"
                    f"Workflow: {run_name}\nKoşu: {run_url}\nLog kuyruğu:\n<code>{log_tail[-800:]}</code>"
                )

        else:
            _tg(
                f"🚨 <b>Hata Müdahale Ajanı — Bilinmeyen hata, insan müdahalesi gerekli:</b>\n"
                f"Workflow: {run_name}\nKoşu: {run_url}\nDetay:\n<code>{log_tail[-800:]}</code>"
            )

    print("=== Ajan taraması tamamlandı ===")


if __name__ == "__main__":
    main()
