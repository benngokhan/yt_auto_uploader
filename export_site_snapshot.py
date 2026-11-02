"""Site için herkese açık hafif veri anlık görüntüsü (shorts_top.json).

panel_telemetry.json (özel depo) içindeki retansiyon metriklerinden
en çok izlenen Shorts ve uzun videoları seçip, herkese açık GitHub Pages
deposuna yazılacak küçük JSON'u üretir. YouTube API kotası kullanmaz.

Kullanım:
    python export_site_snapshot.py            # shorts_top.json üretir
"""
from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TELEMETRY_FILE = BASE_DIR / "panel_telemetry.json"
LIKES_FILE = BASE_DIR / "likes.json"
OUT_FILE = BASE_DIR / "shorts_top.json"
CHANNEL_ID = "UC3bjZMPZ5FW2JQGfU41iaUg"
SHORT_MAX_SEC = 65
TOP_N = 10
# Hibrit sıralama: 1 beğeni ~ LIKE_WEIGHT izlenme değerinde sayılır.
LIKE_WEIGHT = 20


def _load_likes() -> dict:
    """stats_likes.py çıktısını oku; yoksa boş sözlük döndür."""
    if not LIKES_FILE.exists():
        return {}
    try:
        data = json.loads(LIKES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    items = dict(data.get("items") or {})
    items["__generated_at__"] = data.get("generated_at") or ""
    return items


def _norm(row: dict) -> dict | None:
    vid = str(row.get("video_id") or "").strip()
    title = str(row.get("title") or "").strip()
    if len(vid) != 11 or not title:
        return None
    try:
        duration = float(row.get("duration_sec") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    try:
        views = int(row.get("views") or 0)
    except (TypeError, ValueError):
        views = 0
    return {
        "video_id": vid,
        "title": title,
        "views": views,
        "duration_sec": round(duration, 1),
        "published_date": row.get("published_date") or "",
        "url": row.get("url") or f"https://youtu.be/{vid}",
    }


def _with_likes(item: dict, likes_map: dict) -> dict:
    """Beğeni verisini (varsa) ekle ve hibrit sıralama puanını hesapla."""
    rec = likes_map.get(item["video_id"]) or {}
    likes = rec.get("likes")
    likes = int(likes) if isinstance(likes, (int, float)) else None
    views = int(rec.get("views") or 0) or item["views"]
    item = dict(item)
    item["views"] = views
    item["likes"] = likes
    item["like_rate"] = round(likes / views * 100, 2) if likes is not None and views else None
    item["rank_score"] = views + (LIKE_WEIGHT * likes if likes else 0)
    item["likes_at"] = rec.get("fetched_at") or ""
    return item


def build_snapshot(telemetry: dict, likes_map: dict | None = None) -> dict:
    likes_map = likes_map or {}
    metrics = ((telemetry.get("retention") or {}).get("metrics")) or []
    items = [x for x in (_norm(r) for r in metrics) if x]
    items = [_with_likes(x, likes_map) for x in items]
    shorts = sorted((x for x in items if x["duration_sec"] <= SHORT_MAX_SEC), key=lambda x: x["rank_score"], reverse=True)
    longs = sorted((x for x in items if x["duration_sec"] > SHORT_MAX_SEC), key=lambda x: x["rank_score"], reverse=True)
    return {
        "schema": 2,
        "generated_at": telemetry.get("generated_at") or "",
        "generated_at_iso": telemetry.get("generated_at_iso") or "",
        "channel_id": CHANNEL_ID,
        "channel_url": "https://www.youtube.com/@bilgidozuofficial",
        "top_shorts": shorts[:TOP_N],
        "top_longs": longs[:TOP_N],
        "ranking": {
            "mode": "views+likes",
            "like_weight": LIKE_WEIGHT,
            "likes_source": LIKES_FILE.name if likes_map else "",
            "likes_generated_at": likes_map.get("__generated_at__") or "",
        },
        "totals": {
            "videos": len(items),
            "views": sum(x["views"] for x in items),
            "likes": sum(x["likes"] or 0 for x in items),
            "likes_known": sum(1 for x in items if x["likes"] is not None),
            "shorts": len(shorts),
            "longs": len(longs),
        },
    }


def main() -> int:
    if not TELEMETRY_FILE.exists():
        print("[snapshot] panel_telemetry.json bulunamadi; atlandi.")
        return 1
    telemetry = json.loads(TELEMETRY_FILE.read_text(encoding="utf-8"))
    likes_map = _load_likes()
    snapshot = build_snapshot(telemetry, likes_map)
    OUT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(
        f"[snapshot] shorts={len(snapshot['top_shorts'])} longs={len(snapshot['top_longs'])} "
        f"toplam_video={snapshot['totals']['videos']} begeni_bilinen={snapshot['totals']['likes_known']} "
        f"-> {OUT_FILE.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
