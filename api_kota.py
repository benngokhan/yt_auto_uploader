#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""api_kota.py — Panel için TÜM servislerin kalan kullanımını tek dosyada toplar.

Hepsi salt-okunur/ucretsiz çağrı, hiçbiri kota harcamaz:
  * ElevenLabs   → kalan kredi / limit / reset
  * OpenRouter   → kredi limiti + kullanım (/api/v1/key, /api/v1/credits)
  * Google Drive → depolama kotası (about.get)
  * YouTube      → günlük kota TAHMİNİ (yükleme sayısı × ~1.700 birim / 10.000)
  * Gemini       → anahtar geçerli mi (models.list)
  * Groq         → anahtar geçerli mi (models.list)
  * Telegram     → bot kimliği (getMe)
  * GitHub       → token kotası + Actions dakikası tahmini (bu ay)

Çıktı: api_telemetri.json
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

try:
    import kota_sayac  # Gemini/Groq çağrılarını sayar (kota API'de yok)
except Exception:  # sayaç yoksa da çalışsın
    kota_sayac = None
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "api_telemetri.json"
SECRET_LIST = BASE / "secret_listesi.json"

YT_GUNLUK_KOTA = 10_000        # YouTube Data API varsayılan günlük kota (birim)
YT_YUKLEME_BIRIM = 1_700       # upload ~1600 + thumbnail 50 (+ yorum/oynatma listesi payı)
ACTIONS_FREE_DK = 2_000        # private repo ücretsiz Actions dakikası

# Drive kırılımı (yalnızca active.sav81@gmail.com klasörleri)
DRIVE_KLASORLER = [
    ("Video + Kapak Kuyruğu (video kapak)", "1GK-yImpb09445uXfTUbIl7l6AfNM4BOb"),
    ("Ana Klasör & baslik.xlsx (Bilgi_Dozu_Yeni_Shorts)", "1ttP8K3VHtqaNtdSlWjqIFza8Kzf0wxpC"),
    ("Onay Bekleyenler (Onay_Bekleyen)", "1xyO_jNjbpghfR7CJ1P9DUvkzdb6eC0qf"),
]
DRIVE_ARSIV = ("OKUU (Yedek Paketler)", "12oLj4ZsIR7vRMJwe7-HHnX1R-2rI9pdA")


def now():
    return datetime.now(timezone.utc)


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def http_json(url: str, headers: dict | None = None, timeout: int = 30):
    # Groq (Cloudflare 1010) düz urllib imzasını engelliyor: gerçek tarayıcı başlıkları şart.
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def son_bilinen(ad: str) -> dict:
    """Onceki telemetriden VEYA gecmis listesinden son bilinen kotayi alir."""
    try:
        eski = json.loads((Path(__file__).parent / "api_telemetri.json").read_text(encoding="utf-8"))
        for x in eski.get("servisler", []):
            if x.get("ad") == ad and x.get("limit"):
                return {k: x.get(k) for k in ("kalan", "limit", "kullanilan") if x.get(k) is not None}
        # servis kaydi limitini kaybettiyse gecmise bak
        if ad == "ElevenLabs":
            for g in reversed(eski.get("gecmis") or []):
                kalan = g.get("elevenlabs_kalan")
                if kalan is not None:
                    limit = 10000
                    for x in eski.get("servisler", []):
                        if x.get("ad") == ad and x.get("limit"):
                            limit = x["limit"]
                            break
                    return {"kalan": kalan, "limit": limit, "kullanilan": limit - kalan}
    except Exception:
        pass
    return {}


def ok(ad, **kw):
    d = {"ad": ad, "durum": "ok"}
    d.update(kw)
    return d


def hata(ad, mesaj, durum="hata", **kw):
    d = {"ad": ad, "durum": durum, "mesaj": str(mesaj)[:220]}
    d.update(kw)
    return d


# ── ElevenLabs ──────────────────────────────────────────────────────────────
def elevenlabs():
    key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if not key:
        return hata("ElevenLabs", "Anahtar tanımlı değil (ELEVENLABS_API_KEY)", "yok",
                    panel_aksiyon="Ses & Kredi sayfasından anahtar yükle", **son_bilinen("ElevenLabs"))
    try:
        s = http_json("https://api.elevenlabs.io/v1/user/subscription", {"xi-api-key": key})
    except urllib.error.HTTPError as e:
        # 401/403 olsa bile son bilinen kotayı koru (panelde sayı boş kalmasın)
        try:
            govde = e.read().decode("utf-8", "replace")[:160]
        except Exception:
            govde = ""
        ipucu = f"anahtar {len(key)} karakter, '{key[:6]}…'"
        son = son_bilinen("ElevenLabs")
        return hata("ElevenLabs",
                    f"HTTP {e.code} · {govde.strip()} · {ipucu}".strip(" ·"),
                    "gecersiz" if e.code in (401, 403) else "hata", **son)
    except Exception as e:
        return hata("ElevenLabs", e)
    limit = int(s.get("character_limit") or 0)
    used = int(s.get("character_count") or 0)
    reset = s.get("next_character_count_reset_unix")
    return ok("ElevenLabs",
              kalan=max(limit - used, 0), limit=limit, kullanilan=used,
              birim="karakter/kredi", tier=s.get("tier"),
              reset_unix=reset,
              reset_iso=datetime.fromtimestamp(int(reset), tz=timezone.utc).isoformat(timespec="seconds") if reset else "",
              klonlama=bool(s.get("can_use_instant_voice_cloning")),
              yenilenme="aylık · fatura dönemi başında sıfırlanır (kredi devretmez)",
              not_="1 kredi = 1 karakter (v2/v3) · Flash/Turbo yarı fiyat")


# ── OpenRouter ──────────────────────────────────────────────────────────────
def openrouter():
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not key:
        return hata("OpenRouter", "Anahtar yok (OPENROUTER_API_KEY)", "yok")
    h = {"Authorization": "Bearer " + key}
    try:
        k = http_json("https://openrouter.ai/api/v1/key", h).get("data", {})
    except urllib.error.HTTPError as e:
        try:
            govde = e.read().decode("utf-8", "replace")[:180]
        except Exception:
            govde = ""
        ipucu = f"anahtar: {len(key)} karakter, '{key[:8]}…'" if key else "anahtar boş"
        return hata("OpenRouter", f"HTTP {e.code} · {govde.strip()} · {ipucu}",
                    "gecersiz" if e.code in (401, 403) else "hata")
    except Exception as e:
        return hata("OpenRouter", e)
    limit = k.get("limit")
    usage = k.get("usage") or 0
    kalan = None if limit is None else max(float(limit) - float(usage), 0)
    extra = {}
    try:
        c = http_json("https://openrouter.ai/api/v1/credits", h).get("data", {})
        extra = {"kredi_alimi": c.get("total_credits"), "kredi_kullanimi": c.get("total_usage")}
    except Exception:
        pass
    # Ücretsiz katman: kredi yoksa günlük ücretsiz model hakkı gösterilir
    say = (kota_sayac.bugun_ozet().get("openrouter") if kota_sayac else None) or {}
    if kalan is None or float(kalan or 0) <= 0:
        return ok("OpenRouter",
                  kalan=say.get("kalan"), limit=say.get("limit"), kullanilan=say.get("kullanilan"),
                  birim="istek/gün (ücretsiz modeller)", ucretsiz=True,
                  yenilenme="günlük · gece 00:00 UTC · ücretsiz model hakkı",
                  not_="ÜCRETSİZ KATMAN · kredi yüklemeden ücretsiz modeller", **extra)
    return ok("OpenRouter", kalan=kalan, limit=limit, kullanilan=usage,
              birim="USD kredi", ucretsiz=bool(k.get("is_free_tier")),
              yenilenme="aylık sıfırlanmaz · kredi yükledikçe artar",
              not_="TTS + LLM aynı bakiye", **extra)


def _klasor_boyut(drive, fid: str, derinlik: int = 2) -> tuple[int, int, set]:
    """Klasörün (alt klasörler dahil) toplam bayt, dosya sayısı ve dosya sahipleri."""
    toplam, adet, sayfa = 0, 0, None
    altlar = []
    sahipler: set = set()
    for _ in range(8):  # en fazla 800 dosya
        try:
            res = drive.files().list(
                q=f"'{fid}' in parents and trashed=false",
                pageSize=100, pageToken=sayfa,
                fields="nextPageToken,files(id,size,mimeType,owners(emailAddress))",
            ).execute()
        except Exception as e:
            print(f"  klasör listelenemedi ({fid}): {e}")
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


# ── Google: Drive depolama + YouTube kota tahmini ───────────────────────────
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
        return [hata("Google Drive", "token.json yok", "yok"), hata("YouTube", "token.json yok", "yok")]
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
        # Kendi dosyalarım (kotamı harcar) vs başkasının paylaştıkları (kota onlarda)
        gorunen, kendi, paylasilan, sayfa2 = 0, 0, 0, None
        try:
            for _ in range(10):
                r3 = drive.files().list(
                    q="trashed=false and mimeType != 'application/vnd.google-apps.folder'",
                    pageSize=1000, pageToken=sayfa2,
                    fields="nextPageToken,files(size,owners(emailAddress))",
                ).execute()
                for f in r3.get("files", []):
                    b = int(f.get("size") or 0)
                    gorunen += b
                    sahip = [o.get("emailAddress", "") for o in (f.get("owners") or [])]
                    if any(a == (q.get("user") or {}).get("emailAddress") for a in sahip):
                        kendi += b
                    else:
                        paylasilan += b
                sayfa2 = r3.get("nextPageToken")
                if not sayfa2:
                    break
        except Exception as e:
            print("drive toplamı alınamadı:", e)

        buyukler = []
        try:
            res2 = drive.files().list(
                q="trashed=false and mimeType != 'application/vnd.google-apps.folder'",
                orderBy="quotaBytesUsed desc", pageSize=8,
                fields="files(name,size,mimeType)",
            ).execute()
            buyukler = [{"ad": (f.get("name") or "")[:60], "boyut": int(f.get("size") or 0)}
                        for f in res2.get("files", [])]
        except Exception as e:
            print("büyük dosya listesi alınamadı:", e)
        # Kotayı asıl dolduran kalem: Drive dışı (Gmail + Fotoğraflar) + kendi diğer dosyalar
        drive_disi = used - kendi
        if drive_disi > 0:
            kirilim.append({
                "ad": "Gmail + Fotoğraflar (Drive dışı)",
                "boyut": drive_disi,
                "dosya": 0,
            })
        sonuc.append(ok("Google Drive", kalan=(limit - used) if limit else None, limit=limit,
                        kullanilan=used, birim="bayt", kirilim=kirilim, buyuk_dosyalar=buyukler,
                        drive_gorunen=gorunen, kendi_dosyalar=kendi, paylasilan=paylasilan,
                        disalan=used - kendi,
                        hesap=(q.get("user") or {}).get("emailAddress", ""),
                        yenilenme="yenilenmez · sadece dosya silince/artırınca değişir",
                        not_="Kota hesap bazlı: klasör başka hesaba aitse yer ONUN kotasından düşer"))
    except Exception as e:
        sonuc.append(hata("Google Drive", e))

    # YouTube: gerçek kota API'den okunamaz; günlük yükleme sayısından tahmin
    try:
        bugun = now().date().isoformat()
        bugun_adet = 0
        up = BASE / "uploaded.txt"
        if up.exists():
            for line in up.read_text(encoding="utf-8", errors="ignore").splitlines():
                if bugun in line and ".mp4" in line:
                    bugun_adet += 1
        tahmin = bugun_adet * YT_YUKLEME_BIRIM
        sonuc.append(ok("YouTube Data API",
                        kalan=max(YT_GUNLUK_KOTA - tahmin, 0), limit=YT_GUNLUK_KOTA,
                        kullanilan=tahmin, birim="birim (tahmini)",
                        bugun_yukleme=bugun_adet,
                        yenilenme="günlük · gece 00:00 Pasifik (TR 10:00) sıfırlanır",
                        not_=f"gerçek kota API'de yok; yükleme ≈ {YT_YUKLEME_BIRIM} birim sayıldı"))
    except Exception as e:
        sonuc.append(hata("YouTube Data API", e))
    return sonuc


# ── Basit anahtar doğrulama ────────────────────────────────────────────────
def gemini():
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        return hata("Gemini", "Anahtar yok (GEMINI_API_KEY)", "yok")
    try:
        d = http_json(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
        say = (kota_sayac.bugun_ozet().get("gemini") if kota_sayac else None) or {}
        return ok("Gemini",
                  limit=say.get("limit"), kalan=say.get("kalan"), kullanilan=say.get("kullanilan"),
                  birim="istek/gün (kendi sayacimiz)",
                  model_sayisi=len(d.get("models", [])),
                  yenilenme="günlük istek (RPD) · gece 00:00 Pasifik (TR 10:00)",
                  not_="LLM + TTS · kota API'de yok, yaptığımız çağrılar sayılıyor")
    except urllib.error.HTTPError as e:
        return hata("Gemini", f"HTTP {e.code}", "gecersiz" if e.code in (400, 401, 403) else "hata")
    except Exception as e:
        return hata("Gemini", e)


def groq():
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return hata("Groq", "Anahtar yok (GROQ_API_KEY)", "yok")
    try:
        d = http_json("https://api.groq.com/openai/v1/models", {"Authorization": "Bearer " + key})
        say = (kota_sayac.bugun_ozet().get("groq") if kota_sayac else None) or {}
        return ok("Groq",
                  limit=say.get("limit"), kalan=say.get("kalan"), kullanilan=say.get("kullanilan"),
                  birim="istek/gün (kendi sayacimiz)",
                  model_sayisi=len(d.get("data", [])),
                  yenilenme="dakika + günlük token · günlük kısım gece 00:00 UTC",
                  not_="ücretsiz katman · kota API'de yok, çağrılar sayılıyor")
    except urllib.error.HTTPError as e:
        try:
            govde = e.read().decode("utf-8", "replace")[:180]
        except Exception:
            govde = ""
        return hata("Groq", f"HTTP {e.code} · {govde}".strip(" ·"),
                    "gecersiz" if e.code in (401, 403) else "hata")
    except Exception as e:
        return hata("Groq", e)


def telegram():
    tok = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not tok:
        return hata("Telegram", "Token yok (TELEGRAM_BOT_TOKEN)", "yok")
    try:
        d = http_json(f"https://api.telegram.org/bot{tok}/getMe").get("result", {})
        say = (kota_sayac.bugun_ozet().get("telegram") if kota_sayac else None) or {}
        return ok("Telegram", limit=None, kalan=None, kullanilan=say.get("kullanilan"),
                  birim="mesaj/gün (limit yok pratikte)",
                  bot="@" + str(d.get("username", "")),
                  yenilenme="saniye başına limit · günlük kota yok",
                  not_="bildirim kanalı")
    except Exception as e:
        return hata("Telegram", e)


# ── GitHub: token kotası + Actions dakikası ────────────────────────────────
def github():
    tok = (os.getenv("GITHUB_TOKEN") or "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "benngokhan/yt_auto_uploader")
    h = {"Authorization": "token " + tok, "Accept": "application/vnd.github+json"}
    if not tok:
        return hata("GitHub", "GITHUB_TOKEN yok", "yok")
    try:
        rl = http_json("https://api.github.com/rate_limit", h).get("resources", {}).get("core", {})
        ek = {}
        # Actions dakikası: bu ayki koşuların süreleri
        try:
            ay = now().strftime("%Y-%m")
            dakika = 0.0
            kosu = 0
            sayfa = 1
            while sayfa <= 5:
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
                sayfa += 1
            ek = {"actions_dakika": round(dakika, 1), "actions_kosu": kosu,
                  "actions_limit": ACTIONS_FREE_DK,
                  "actions_kalan": round(max(ACTIONS_FREE_DK - dakika, 0), 1)}
        except Exception as e:
            ek = {"actions_uyari": str(e)[:120]}
        return ok("GitHub", kalan=rl.get("remaining"), limit=rl.get("limit"),
                  kullanilan=(rl.get("limit", 0) - rl.get("remaining", 0)) if rl else None,
                  birim="istek/saat",
                  yenilenme="istek kotası saatlik · Actions dakikası AYLIK (ayın 1'i)",
                  not_="panel API kotası (saatlik pencerede yenilenir)", **ek)
    except Exception as e:
        return hata("GitHub", e)


def secret_durumu():
    """Workflow 'gh secret list' çıktısını secret_listesi.json'a yazar; burada okunur."""
    gerekli = {
        "ELEVENLABS_API_KEY": "Ses üretimi (ElevenLabs)",
        "OPENROUTER_API_KEY": "Yedek LLM + TTS (OpenRouter)",
        "GEMINI_API_KEY": "Başlık/açıklama üretimi, Gemini TTS",
        "GROQ_API_KEY": "Hızlı LLM (Groq)",
        "GOOGLE_TOKEN_JSON": "Drive + YouTube OAuth",
        "GOOGLE_CLIENT_SECRETS_JSON": "Drive + YouTube OAuth",
        "TELEGRAM_BOT_TOKEN": "Telegram bildirimleri",
        "SITE_SYNC_TOKEN": "Panele veri yayını + secret yazma",
    }
    mevcut = set()
    if SECRET_LIST.exists():
        try:
            for s in json.loads(SECRET_LIST.read_text(encoding="utf-8")):
                mevcut.add(s if isinstance(s, str) else s.get("name", ""))
        except Exception:
            pass
    out = []
    for ad, aciklama in gerekli.items():
        out.append({"ad": ad, "var": ad in mevcut, "aciklama": aciklama})
    return out


YENILENME = {
    "ElevenLabs": "aylık · fatura dönemi başında sıfırlanır (kalan kredi devretmez)",
    "OpenRouter": "aylık sıfırlanmaz · kredi yükledikçe artar",
    "Gemini": "günlük istek (RPD) · gece 00:00 Pasifik (TR 10:00)",
    "Groq": "dakika + günlük token · günlük kısım 00:00 UTC",
    "Telegram": "saniye başına limit · günlük kota yok",
    "GitHub": "istek kotası saatlik · Actions dakikası AYLIK (ayın 1'i)",
    "Google Drive": "yenilenmez · sadece dosya silince/artırınca değişir",
    "YouTube Data API": "günlük · gece 00:00 Pasifik (TR 10:00) sıfırlanır",
}


def main() -> int:
    print("API kotası toplanıyor…")
    servisler = [elevenlabs(), openrouter(), gemini(), groq(), telegram(), github()]
    servisler += google()
    for s in servisler:
        if not s.get("yenilenme"):
            s["yenilenme"] = YENILENME.get(s["ad"], "")
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
    # geçmiş (küçük trend)
    gecmis = []
    if OUT.exists():
        try:
            gecmis = json.loads(OUT.read_text(encoding="utf-8")).get("gecmis", [])
        except Exception:
            gecmis = []
    gecmis = (gecmis or [])[-59:]
    el = next((s for s in servisler if s["ad"] == "ElevenLabs"), {})
    gecmis.append({"zaman": veri["zaman"], "elevenlabs_kalan": el.get("kalan")})
    veri["gecmis"] = gecmis

    OUT.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ozet:", veri["ozet"])
    for s in servisler:
        print(f"  {s['ad']:<20} {s['durum']:<9} kalan={s.get('kalan')} / {s.get('limit')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
