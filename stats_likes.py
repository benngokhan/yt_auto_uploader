"""BEĞENİ SAYILARI — sıfır YouTube API kotası (yt-dlp).

panel_telemetry.json içindeki video ID'leri için YouTube'dan beğeni (like_count)
ve görüntülenme sayısını çeker, `likes.json` dosyasına yazar. Ana sayfa
sıralaması bu dosyadaki beğenilerle "beğeni + izlenme" hibrit puanına döner.

Özellikler
  * YouTube Data API kullanmaz (kota 0), OAuth/anahtar gerekmez.
  * Paralel çalışır (varsayılan 3 iş parçacığı), her istek için zaman aşımı vardır.
  * Başarısız olanlar önceki likes.json değerini korur (veri kaybı olmaz).

KULLANIM
  python stats_likes.py                 # hepsini tazele (en fazla 120 video)
  python stats_likes.py --limit 40      # sadece ilk 40 video
  python stats_likes.py --only-missing  # likes.json'da olmayanları çek
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
OUT_FILE = BASE_DIR / "likes.json"
MAX_VIDEOS = 120
WORKERS = 3
TIMEOUT = 45
TR = timezone(timedelta(hours=3))


def _ytdlp_like(video_id: str) -> dict | None:
    """Tek video için beğeni + görüntülenme. Başarısızsa None."""
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
    line = out[-1]
    likes_s, _, views_s = line.partition("|")

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
    print(f"[likes] hedef={len(targets)} (toplam {len(ids)} video, {WORKERS} paralel)")

    fetched: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for vid, res in zip(targets, pool.map(_ytdlp_like, targets)):
            if res:
                res["fetched_at"] = datetime.now(TR).strftime("%Y-%m-%d %H:%M:%S")
                fetched[vid] = res

    items = dict(previous)
    items.update(fetched)
    now = datetime.now(TR)
    payload = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "generated_at_iso": now.isoformat(),
        "source": "yt-dlp (YouTube API kotasi 0)",
        "ok": len(fetched),
        "failed": len(targets) - len(fetched),
        "items": items,
    }
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[likes] yazildi: {OUT_FILE.name} · basarili={len(fetched)} basarisiz={payload['failed']} kayit={len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
