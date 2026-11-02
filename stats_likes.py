"""BEĞENİ SAYILARI — YouTube Data API (2 kota birimi) + yt-dlp yedeği.

panel_telemetry.json içindeki video ID'leri için YouTube'dan beğeni (likeCount)
ve görüntülenme sayısını çeker, `likes.json` dosyasına yazar. Ana sayfa
sıralaması bu dosyadaki beğenilerle "beğeni + izlenme" hibrit puanına döner.

Neden API
  * `videos.list` 50 videoya kadar tek istekte istatistik verir -> 78 video = 2 istek.
  * Maliyet: istek başına 1 birim (günlük 10.000 birim kotanın çok altında).
  * yt-dlp datacenter IP'lerinde (GitHub Actions) sık sık bot kontrolüne takılıyor;
    bu yüzden API birincil, yt-dlp yalnızca yedek.

Özellikler
  * API anahtarı/OAuth: depodaki token.json (GOOGLE_TOKEN_JSON) kullanılır.
  * API hiç yoksa/başarısızsa yt-dlp ile paralel (3 iş parçacığı) devam eder.
  * Başarısız olanlar önceki likes.json değerini korur (veri kaybı olmaz).
  * Gizlenmiş beğeni (likeCount yok) -> likes: null, sıralamada sadece izlenme sayılır.

KULLANIM
  python stats_likes.py                 # hepsini tazele (en fazla 120 video)
  python stats_likes.py --limit 40      # sadece ilk 40 video
  python stats_likes.py --only-missing  # likes.json'da olmayanları çek
  python stats_likes.py --ytdlp-only    # API'yi atla, doğrudan yt-dlp
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TELEMETRY_FILE = BASE_DIR / "panel_telemetry.json"
TOKEN_FILE = BASE_DIR / "token.json"
OUT_FILE = BASE_DIR / "likes.json"
MAX_VIDEOS = 120
WORKERS = 3
TIMEOUT = 45
API_BATCH = 50
TR = timezone(timedelta(hours=3))


def _now() -> str:
    return datetime.now(TR).strftime("%Y-%m-%d %H:%M:%S")


def _youtube_client():
    """token.json ile YouTube istemcisi; mümkün değilse None."""
    if not TOKEN_FILE.exists():
        return None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE))
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                return None
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:  # noqa: BLE001 - kimlik bilgisi yoksa yt-dlp'ye düşeriz
        print(f"[likes] API istemcisi kurulamadi: {exc}")
        return None


def _api_likes(youtube, ids: list[str]) -> dict[str, dict]:
    """videos.list part=statistics -> {video_id: {likes, views}}"""
    out: dict[str, dict] = {}
    if youtube is None:
        return out
    for i in range(0, len(ids), API_BATCH):
        chunk = ids[i:i + API_BATCH]
        try:
            resp = youtube.videos().list(part="statistics", id=",".join(chunk), maxResults=API_BATCH).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"[likes] API hatasi (batch {i // API_BATCH + 1}): {exc}")
            continue
        for item in resp.get("items") or []:
            vid = item.get("id")
            stats = item.get("statistics") or {}
            if not vid:
                continue
            views = stats.get("viewCount")
            likes = stats.get("likeCount")
            if views is None and likes is None:
                continue
            out[vid] = {
                "likes": int(likes) if likes is not None else None,
                "views": int(views) if views is not None else None,
                "fetched_at": _now(),
            }
    return out


def _ytdlp_like(video_id: str) -> dict | None:
    """Tek video için beğeni + görüntülenme (yedek yol). Başarısızsa None."""
    url = f"https://youtu.be/{video_id}"
    try:
        result = subprocess.run(
            [
                "yt-dlp", "--skip-download", "--no-warnings", "--quiet",
                "--print", "%(like_count)s|%(view_count)s", url,
            ],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except Exception:
        return None
    out = (result.stdout or "").strip().splitlines()
    if not out:
        return None
    likes_s, _, views_s = out[-1].partition("|")

    def _num(value: str) -> int | None:
        m = re.search(r"\d+", value or "")
        return int(m.group()) if m else None

    likes = _num(likes_s)
    views = _num(views_s)
    if likes is None and views is None:
        return None
    return {"likes": likes, "views": views}


def _video_ids() -> list[str]:
    if not TELEMETRY_FILE.exists():
        return []
    try:
        telemetry = json.loads(TELEMETRY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    metrics = ((telemetry.get("retention") or {}).get("metrics")) or []
    ids: list[str] = []
    seen: set[str] = set()
    for row in metrics:
        vid = str(row.get("video_id") or "").strip()
        if len(vid) != 11 or vid in seen:
            continue
        seen.add(vid)
        ids.append(vid)
    return ids[:MAX_VIDEOS]


def _fetch(targets: list[str]) -> tuple[dict[str, dict], str]:
    """Önce API, kalanlar için yt-dlp. (sonuç, kullanılan yol)"""
    fetched: dict[str, dict] = {}
    sources: list[str] = []

    if "--ytdlp-only" not in sys.argv:
        api = _api_likes(_youtube_client(), targets)
        if api:
            fetched.update(api)
            sources.append("api")

    missing = [v for v in targets if v not in fetched]
    if missing:
        print(f"[likes] yt-dlp yedegi: {len(missing)} video")
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for vid, res in zip(missing, pool.map(_ytdlp_like, missing)):
                if res:
                    res["fetched_at"] = _now()
                    fetched[vid] = res
        sources.append("yt-dlp")

    if not fetched:
        return {}, "basarisiz"

    # API tamamen düştüyse ve hiçbir şey çekilemediyse kaynağı dürüst tut
    return fetched, "+".join(sources)


def main() -> int:
    only_missing = "--only-missing" in sys.argv
    limit = MAX_VIDEOS
    if "--limit" in sys.argv:
        try:
            limit = max(1, int(sys.argv[sys.argv.index("--limit") + 1]))
        except (IndexError, ValueError):
            pass

    previous: dict[str, dict] = {}
    if OUT_FILE.exists():
        try:
            previous = (json.loads(OUT_FILE.read_text(encoding="utf-8")).get("items")) or {}
        except json.JSONDecodeError:
            previous = {}

    ids = _video_ids()[:limit]
    if not ids:
        print("[likes] panel_telemetry.json icinde video ID bulunamadi; atlandi.")
        return 1

    targets = [v for v in ids if not (only_missing and v in previous)]
    print(f"[likes] hedef={len(targets)} (toplam {len(ids)} video)")

    fetched, source = _fetch(targets)

    items = dict(previous)
    items.update(fetched)
    now = datetime.now(TR)
    failed = len(targets) - len(fetched)
    payload = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "generated_at_iso": now.isoformat(),
        "source": {
            "api": "YouTube Data API v3 · videos.list?part=statistics",
            "ytdlp": "yt-dlp --print like_count|view_count",
            "used": source,
        },
        "ok": len(fetched),
        "failed": failed,
        "items": items,
    }
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[likes] yazildi: {OUT_FILE.name} · yol={source} basarili={len(fetched)} basarisiz={failed} kayit={len(items)}")
    # Hepsi başarısız olduysa workflow'u kırmayalım ama görünür olsun
    return 0 if fetched else 2


if __name__ == "__main__":
    raise SystemExit(main())
