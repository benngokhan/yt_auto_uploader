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
OUT_FILE = BASE_DIR / "shorts_top.json"
CHANNEL_ID = "UC3bjZMPZ5FW2JQGfU41iaUg"
SHORT_MAX_SEC = 65
TOP_N = 10


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


def build_snapshot(telemetry: dict) -> dict:
    metrics = ((telemetry.get("retention") or {}).get("metrics")) or []
    items = [x for x in (_norm(r) for r in metrics) if x]
    shorts = sorted((x for x in items if x["duration_sec"] <= SHORT_MAX_SEC), key=lambda x: x["views"], reverse=True)
    longs = sorted((x for x in items if x["duration_sec"] > SHORT_MAX_SEC), key=lambda x: x["views"], reverse=True)
    return {
        "schema": 1,
        "generated_at": telemetry.get("generated_at") or "",
        "generated_at_iso": telemetry.get("generated_at_iso") or "",
        "channel_id": CHANNEL_ID,
        "channel_url": "https://www.youtube.com/@bilgidozuofficial",
        "top_shorts": shorts[:TOP_N],
        "top_longs": longs[:TOP_N],
        "totals": {
            "videos": len(items),
            "views": sum(x["views"] for x in items),
            "shorts": len(shorts),
            "longs": len(longs),
        },
    }


def main() -> int:
    if not TELEMETRY_FILE.exists():
        print("[snapshot] panel_telemetry.json bulunamadi; atlandi.")
        return 1
    telemetry = json.loads(TELEMETRY_FILE.read_text(encoding="utf-8"))
    snapshot = build_snapshot(telemetry)
    OUT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(
        f"[snapshot] shorts={len(snapshot['top_shorts'])} longs={len(snapshot['top_longs'])} "
        f"toplam_video={snapshot['totals']['videos']} -> {OUT_FILE.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
