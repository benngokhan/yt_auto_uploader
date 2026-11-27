# -*- coding: utf-8 -*-
"""
Bağımsız TikTok testi: YouTube'a hiç dokunmadan tek Shorts'u TikTok'a yükler.
GitHub Actions -> "TikTok Only Test" workflow'sinden çağrılır.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from uploader import (
    BASE_DIR,
    DEFAULT_DRIVE_FOLDER_ID,
    DEFAULT_SHEETS_ID,
    download_drive_file,
    get_google_clients,
    load_config,
    load_uploaded_ids,
)
from sheets_metadata import get_next_scheduled_video
from qa_and_crosspost import build_crosspost_caption
from crosspost_worker import post_tiktok


def main() -> int:
    force_file = os.getenv("INPUT_FORCE_FILE", "").strip()
    cfg = load_config()
    queue_folder = cfg.get("drive_queue_folder_id", DEFAULT_DRIVE_FOLDER_ID).strip() or DEFAULT_DRIVE_FOLDER_ID

    _youtube, drive = get_google_clients(token_file=BASE_DIR / "token.json")
    skip_ids = load_uploaded_ids(BASE_DIR / "uploaded.txt")

    scheduled = get_next_scheduled_video(
        drive,
        queue_folder,
        skip_ids=skip_ids,
        sheets_id=cfg.get("sheets_id", DEFAULT_SHEETS_ID),
        video_type="short",
        force_file=force_file,
    )
    if not scheduled:
        print("TT-TEST: Hazır short bulunamadı; YouTube'a dokunulmadı.")
        return 2

    name = scheduled["name"]
    print(f"TT-TEST: Seçilen video {name} (YouTube yüklemesi YOK)")

    meta = {
        "title": scheduled.get("title", ""),
        "description": scheduled.get("description", ""),
        "tags": scheduled.get("tags", []),
        "categoryId": scheduled.get("categoryId", "27"),
        "pinned_comment": scheduled.get("pinned_comment", ""),
    }
    caption = build_crosspost_caption(meta)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        download_drive_file(drive, scheduled["id"], path)
        result = post_tiktok(path, caption)
        print(f"TT-TEST SONUCU: {name} -> {result}")
        if not result or str(result).startswith("HATA:"):
            return 1
        return 0
    finally:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
