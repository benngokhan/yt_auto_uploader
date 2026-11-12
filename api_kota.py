#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""api_kota.py — Panel için aktif tüm servislerin GERÇEK kalan kullanımını tek dosyada toplar.

Aktif servisler (yalnızca gerçekten kullanılanlar):
  * Pexels           → gerçek aylık kota başlığı (X-Ratelimit-Remaining / Limit)
  * Gemini · Charon  → anahtar doğrulaması + bugünkü gerçek Actions çağrı sayımı (/ 1.500)
  * Groq             → gerçek günlük kota başlığı (x-ratelimit-remaining-requests / limit-requests)
  * Google Drive     → gerçek depolama kotası (about.get storageQuota)
  * YouTube Data API → bugünkü gerçek yükleme sayısından günlük birim kullanımı (/ 10.000)
  * GitHub Actions   → bu ay kullanılan gerçek Actions dakikası (/ 2.000 dk) + saatlik API kotası
  * Telegram         → bot doğrulaması (@Bilgindozlu_bot)
  * Pixabay (varsa)  → gerçek X-RateLimit-Remaining / Limit

Çıktı: api_telemetri.json
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import kota_sayac
except Exception:
    kota_sayac = None

from api_durum_kontrol import bugun_actions_gemini_cagrisi, groq_kontrol

BASE = Path(__file__).parent
OUT = BASE / "api_telemetri.json"
SECRET_LIST = BASE / "secret_listesi.json"

YT_GUNLUK_KOTA = 10_000
YT_YUKLEME_BIRIM = 1_700
ACTIONS_FREE_DK = 2_000
GEMINI_GUNLUK_LIMIT = 1_500

DRIVE_KLASORLER = [
    ("Video + Kapak Kuyruğu (video kapak)", "1GK-yImpb09445uXfTUbIl7l6AfNM4BOb"),
    ("Ana Klasör & baslik.xlsx (Bilgi_Dozu_Yeni_Shorts)", "1ttP8K3VHtqaNtdSlWjqIFza8Kzf0wxpC"),
    ("Onay Bekleyenler (Onay_Bekleyen)", "1xyO_jNjbpghfR7CJ1P9DUvkzdb6eC0qf"),
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def now():
    return datetime.now(timezone.utc)


def http_json(url: str, headers: dict | None = None, timeout: int = 30):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ok(ad, **kw):
    d = {"ad": ad, "durum": "ok"}
    d.update(kw)
    return d


def hata(ad, mesaj, durum="hata", **kw):
    d = {"ad": ad, "durum": durum, "mesaj": str(mesaj)[:220]}
    d.update(kw)
    return d


def pexels():
    key = (os.getenv("PEXELS_API_KEY") or os.getenv("PEXELS_KEY") or os.getenv("PEXELS_API") or "").strip()
    if not key:
        return hata("Pexels", "Anahtar yok (PEXELS_API_KEY)", "yok",
                    panel_aksiyon="API & Kotalar ekranından PEXELS_API_KEY ekle")
    try:
        req = urllib.request.Request(
            "https://api.pexels.com/v1/curated?per_page=1",
            headers={"Authorization": key, "User-Agent": UA, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            hdr = {k.lower(): v for k, v in r.headers.items()}
        lim_raw = hdr.get("x-ratelimit-limit")
        rem_raw = hdr.get("x-ratelimit-remaining")
        rst_raw = hdr.get("x-ratelimit-reset")
        limit = int(lim_raw) if lim_raw and str(lim_raw).isdigit() else 25000
        kalan = int(rem_raw) if rem_raw and str(rem_raw).isdigit() else limit
        kullanilan = max(limit - kalan, 0)
        reset_iso = ""
        if rst_raw and str(rst_raw).isdigit():
            try:
                reset_iso = datetime.fromtimestamp(int(rst_raw), tz=timezone.utc).isoformat(timespec="seconds")
            except Exception:
                reset_iso = ""
        return ok("Pexels",
                  kalan=kalan, limit=limit, kullanilan=kullanilan,
                  birim="istek/ay",
                  reset_iso=reset_iso,
                  yenilenme="aylık kota · saatlik 200 istek penceresi",
                  not_="Birincil 9:16 dikey sinematik sahne görseli kaynağı")
    except urllib.error.HTTPError as e:
        try:
            govde = e.read().decode("utf-8", "replace")[:160]
        except Exception:
            govde = ""
        return hata("Pexels", f"HTTP {e.code} · {govde}".strip(" ·"),
                    "gecersiz" if e.code in (401, 403) else "hata")
    except Exception as e:
        return hata("Pexels", e)


def pixabay():
    key = (os.getenv("PIXABAY_API_KEY") or "").strip()
    if not key:
        return None
    try:
        req = urllib.request.Request(
            f"https://pixabay.com/api/?key={key}&q=science&per_page=3",
            headers={"User-Agent": UA, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            hdr = {k.lower(): v for k, v in r.headers.items()}
        lim_raw = hdr.get("x-ratelimit-limit")
        rem_raw = hdr.get("x-ratelimit-remaining")
        limit = int(lim_raw) if lim_raw and str(lim_raw).isdigit() else 100
        kalan = int(rem_raw) if rem_raw and str(rem_raw).isdigit() else limit
        return ok("Pixabay (Yedek)",
                  kalan=kalan, limit=limit, kullanilan=max(limit - kalan, 0),
                  birim="istek/dk",
                  yenilenme="dakikalık 100 istek penceresi · ücretsiz API",
                  not_="İkincil yedek görsel kaynağı")
    except urllib.error.HTTPError as e:
        return hata("Pixabay (Yedek)", f"HTTP {e.code}", "gecersiz" if e.code in (400, 401, 403) else "hata")
    except Exception as e:
        return hata("Pixabay (Yedek)", e)


def gemini():
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        return hata("Gemini · Charon", "Anahtar yok (GEMINI_API_KEY)", "yok")
    try:
        d = http_json(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
        kullanilan = bugun_actions_gemini_cagrisi()
        kalan = max(GEMINI_GUNLUK_LIMIT - kullanilan, 0)
        return ok("Gemini · Charon",
                  limit=GEMINI_GUNLUK_LIMIT, kalan=kalan, kullanilan=kullanilan,
                  birim="istek/gün",
                  model_sayisi=len(d.get("models", [])),
                  yenilenme="günlük · her gün TR 10:00 (00:00 Pasifik) sıfırlanır",
                  not_="Charon TTS seslendirme + yardımcı metin üretimi")
    except urllib.error.HTTPError as e:
        return hata("Gemini · Charon", f"HTTP {e.code}", "gecersiz" if e.code in (400, 401, 403) else "hata")
    except Exception as e:
        return hata("Gemini · Charon", e)


def groq():
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return hata("Groq", "Anahtar yok (GROQ_API_KEY)", "yok")
    g = groq_kontrol(key)
    if g["durum"] not in ("aktif", "kota"):
        return hata("Groq", f"HTTP {g.get('http')} · {g.get('mesaj', '')}".strip(" ·"),
                    "gecersiz" if g.get("http") in (401, 403) else "hata")
    lim = g.get("limit") or {}
    limit = int(lim.get("limit-requests") or 1000)
    kalan = int(lim.get("remaining-requests") or limit)
    kullanilan = max(limit - kalan, 0)
    return ok("Groq",
              limit=limit, kalan=kalan, kullanilan=kullanilan,
              birim="istek/gün",
              yenilenme="günlük kota · her gece 00:00 UTC sıfırlanır",
              not_=f"Hızlı senaryo ve başlık motoru ({g.get('mesaj', '')})".rstrip(" ()"))


def _klasor_boyut(drive, fid: str, derinlik: int = 2) -> tuple[int, int, set]:
    toplam, adet, sayfa = 0, 0, None
    altlar = []
    sahipler: set = set()
    for _ in range(8):
        try:
            res = drive.files().list(
                q=f"'{fid}' in parents and trashed=false",
                pageSize=100, pageToken=sayfa,
                fields="nextPageToken,files(id,size,mimeType,owners(emailAddress))",
            ).execute()
        except Exception:
            break
        for f in res.get("files", []):
            if f.get("mimeType") == "application/vnd.google-apps.folder":
                altlar.append(f["id"])
            else:
                toplam += int(f.get("size") or 0)
                adet += 1
                for o in (f.get("owners") or []):
                    if o.get("emailAddress"):
                        sahipler.add(o["emailAddress"])
        sayfa = res.get("nextPageToken")
        if not sayfa:
            break
    if derinlik > 1:
        for a in altlar[:8]:
            b, n, sh = _klasor_boyut(drive, a, derinlik - 1)
            toplam += b
            adet += n
            sahipler |= sh
    return toplam, adet, sahipler


def google():
    sonuc = []
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except Exception as e:
        return [hata("Google Drive", f"Kütüphane yok: {e}")]
    token = BASE / "token.json"
    if not token.exists():
        return [hata("Google Drive", "token.json yok", "yok"), hata("YouTube Data API", "token.json yok", "yok")]
    try:
        creds = Credentials.from_authorized_user_file(str(token))
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        q = drive.about().get(fields="storageQuota,user").execute()
        sq = q.get("storageQuota", {})
        limit = int(sq.get("limit") or 0)
        used = int(sq.get("usage") or 0)
        kirilim = []
        for ad, fid in DRIVE_KLASORLER:
            try:
                b, n, sh = _klasor_boyut(drive, fid)
                kirilim.append({"ad": ad, "boyut": b, "dosya": n,
                                "sahip": ", ".join(sorted(sh)) if sh else ""})
            except Exception:
                continue
        sonuc.append(ok("Google Drive",
                        kalan=(limit - used) if limit else None, limit=limit,
                        kullanilan=used, birim="bayt", kirilim=kirilim,
                        hesap=(q.get("user") or {}).get("emailAddress", ""),
                        yenilenme="kalıcı depolama · dosya silince yer açılır",
                        not_="Yayın kuyruğu ve onay bekleyen videolar depolaması"))
    except Exception as e:
        sonuc.append(hata("Google Drive", e))

    try:
        bugun = now().date().isoformat()
        bugun_adet = 0
        up = BASE / "uploaded.txt"
        if up.exists():
            for line in up.read_text(encoding="utf-8", errors="ignore").splitlines():
                if bugun in line and ".mp4" in line and not line.startswith("MANUAL_SKIP"):
                    bugun_adet += 1
        tahmin = bugun_adet * YT_YUKLEME_BIRIM
        sonuc.append(ok("YouTube Data API",
                        kalan=max(YT_GUNLUK_KOTA - tahmin, 0), limit=YT_GUNLUK_KOTA,
                        kullanilan=tahmin, birim="birim/gün",
                        bugun_yukleme=bugun_adet,
                        yenilenme="günlük · her gün TR 10:00 sıfırlanır",
                        not_=f"Her Shorts yüklemesi ≈ {YT_YUKLEME_BIRIM} birim (günde ~5 yükleme kapasitesi)"))
    except Exception as e:
        sonuc.append(hata("YouTube Data API", e))
    return sonuc


def github():
    tok = (os.getenv("GITHUB_TOKEN") or "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "benngokhan/yt_auto_uploader")
    h = {"Authorization": "token " + tok, "Accept": "application/vnd.github+json"}
    if not tok:
        return hata("GitHub Actions", "GITHUB_TOKEN yok", "yok")
    try:
        rl = http_json("https://api.github.com/rate_limit", h).get("resources", {}).get("core", {})
        ay = now().strftime("%Y-%m")
        dakika = 0.0
        kosu = 0
        for sayfa in range(1, 6):
            runs = http_json(
                f"https://api.github.com/repos/{repo}/actions/runs?per_page=100&page={sayfa}", h
            ).get("workflow_runs", [])
            if not runs:
                break
            for r in runs:
                ts = r.get("run_started_at") or r.get("created_at") or ""
                if not ts.startswith(ay):
                    continue
                try:
                    a = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    b = datetime.fromisoformat((r.get("updated_at") or ts).replace("Z", "+00:00"))
                    dakika += max((b - a).total_seconds(), 0) / 60
                    kosu += 1
                except Exception:
                    continue
        kullanilan_dk = round(dakika, 1)
        kalan_dk = round(max(ACTIONS_FREE_DK - dakika, 0), 1)
        return ok("GitHub Actions",
                  kalan=kalan_dk, limit=ACTIONS_FREE_DK, kullanilan=kullanilan_dk,
                  birim="dk/ay",
                  actions_dakika=kullanilan_dk, actions_kosu=kosu,
                  actions_limit=ACTIONS_FREE_DK, actions_kalan=kalan_dk,
                  api_kalan=rl.get("remaining"), api_limit=rl.get("limit"),
                  yenilenme="aylık 2.000 dk ücretsiz · her ayın 1'inde sıfırlanır",
                  not_=f"Bu ay {kosu} iş akışı koştu · Saatlik API: {rl.get('remaining', 5000)}/{rl.get('limit', 5000)}")
    except Exception as e:
        return hata("GitHub Actions", e)


def telegram():
    tok = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not tok:
        return hata("Telegram Bot", "Token yok (TELEGRAM_BOT_TOKEN)", "yok")
    try:
        d = http_json(f"https://api.telegram.org/bot{tok}/getMe").get("result", {})
        return ok("Telegram Bot",
                  limit=30, kalan=30, kullanilan=0,
                  birim="istek/sn",
                  bot="@" + str(d.get("username", "")),
                  yenilenme="anlık · günlük kota sınırı yok",
                  not_="Onay kartları ve yayın bildirimleri aktif")
    except Exception as e:
        return hata("Telegram Bot", e)


def secret_durumu():
    gerekli = {
        "PEXELS_API_KEY": "Birincil sinematik görsel kaynağı (Pexels)",
        "PIXABAY_API_KEY": "Yedek görsel kaynağı (Pixabay)",
        "GEMINI_API_KEY": "Gemini Charon TTS + yardımcı metin",
        "GROQ_API_KEY": "Hızlı senaryo/başlık LLM (Groq)",
        "GOOGLE_TOKEN_JSON": "Drive + YouTube OAuth",
        "GOOGLE_CLIENT_SECRETS_JSON": "Drive + YouTube OAuth",
        "TELEGRAM_BOT_TOKEN": "Telegram bildirimleri",
        "SITE_SYNC_TOKEN": "Panel secret yazma yetkisi",
    }
    mevcut = set()
    if SECRET_LIST.exists():
        try:
            for s in json.loads(SECRET_LIST.read_text(encoding="utf-8")):
                mevcut.add(s if isinstance(s, str) else s.get("name", ""))
        except Exception:
            pass
    if (os.getenv("PEXELS_API_KEY") or os.getenv("PEXELS_KEY") or os.getenv("PEXELS_API") or "").strip():
        mevcut.add("PEXELS_API_KEY")
    if (BASE / "token.json").exists():
        mevcut.add("GOOGLE_TOKEN_JSON")
    if (BASE / "client_secrets.json").exists():
        mevcut.add("GOOGLE_CLIENT_SECRETS_JSON")
    if (os.getenv("GH_TOKEN") or "").strip():
        mevcut.add("SITE_SYNC_TOKEN")
    for ad in gerekli:
        if (os.getenv(ad) or "").strip():
            mevcut.add(ad)
    return [{"ad": ad, "var": ad in mevcut, "aciklama": aciklama} for ad, aciklama in gerekli.items()]


def main() -> int:
    print("API kotası toplanıyor…")
    servisler = [pexels(), gemini(), groq()]
    px = pixabay()
    if px:
        servisler.append(px)
    servisler += google()
    servisler += [github(), telegram()]

    veri = {
        "zaman": now().isoformat(timespec="seconds"),
        "servisler": servisler,
        "secretler": secret_durumu(),
        "ozet": {
            "ok": sum(1 for s in servisler if s.get("durum") == "ok"),
            "eksik": sum(1 for s in servisler if s.get("durum") == "yok"),
            "gecersiz": sum(1 for s in servisler if s.get("durum") == "gecersiz"),
            "hata": sum(1 for s in servisler if s.get("durum") == "hata"),
        },
    }
    OUT.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ozet:", veri["ozet"])
    for s in servisler:
        print(f"  {s['ad']:<20} {s['durum']:<9} kalan={s.get('kalan')} / {s.get('limit')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
