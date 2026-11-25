"""Salt-okunur kuyruk raporu: 195+ numaralı shortslar ve sıradaki video."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mpt_uret as teslim  # noqa: E402
import sheets_metadata as sm  # noqa: E402


def main() -> int:
    drive = teslim.drive_istemci()
    table = sm.load_table_from_drive_or_local(
        drive, sm.CEO_FOLDER_ID, sheets_id=sm.DEFAULT_SHEETS_ID
    )
    rows = []
    for video in sm.list_drive_videos(drive, sm.SHORTS_VIDEO_FOLDER_ID):
        number = sm.extract_video_number(video["name"])
        if number < 195:
            continue
        rec = table.get(video["name"], {})
        rows.append({
            "name": video["name"],
            "number": number,
            "status": rec.get("status", "(tabloda yok)"),
            "ready": bool(rec.get("is_ready")),
            "published": bool(rec.get("has_youtube_link") or rec.get("youtube_url")),
            "title": (rec.get("title") or "")[:70],
        })
    rows.sort(key=lambda r: r["number"])
    nxt = sm.get_next_scheduled_video(drive, sm.CEO_FOLDER_ID, video_type="short")
    report = {
        "videos_195_plus": rows,
        "next_short": None if not nxt else {
            "name": nxt.get("name"),
            "row": nxt.get("row"),
            "title": nxt.get("title"),
        },
    }
    out = ROOT / "result_queue_097" / "queue_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
