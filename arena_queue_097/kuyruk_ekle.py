"""097 Fatih videosunu yayın kuyruğuna ekler (tek seferlik, elle onaylı).

Yaptığı tek şey kuyruğa yazmaktır:
  - video -> SHORTS_VIDEO_FOLDER_ID / video_<n>.mp4
  - kapak -> SHORTS_COVER_FOLDER_ID / kapak_<n>.jpg
  - baslik.xlsx "drive" sekmesine BEKLEMEDE satırı

YouTube'a yükleme YAPMAZ. Yayın, mevcut 19:30 TR slotundaki uploader'a bırakılır.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mpt_uret as teslim  # noqa: E402
import sheets_metadata as sm  # noqa: E402
from kapak_yukle import upsert_cover  # noqa: E402

AUTH = "FATIH_097_QUEUE_APPROVED_ONCE"
BRANCH = "arena/queue-097"
SOURCE_RUN = 45661166999
NUMBER = 205
VIDEO_SHA = "6d0042481a5a76b1c1dc3bf7389c1431846f0d5de04997b75c3a35bf1042fac7"
VIDEO_BYTES = 16974021

TITLE = "Fatih'in Ressamı: Venedik'ten İstanbul'a Bir Portrenin Hikâyesi 🎨 #bilgidozu #shorts"
DESCRIPTION = (
    "1479'da Fatih Sultan Mehmet, Venedik'ten bir ressam istedi. Venedik, Gentile Bellini'yi "
    "İstanbul'a gönderdi. Bellini burada yaklaşık bir buçuk yıl kaldı ve Fatih'in portresini yaptı.\n\n"
    "Bu ziyaret yalnızca sanatla ilgili değildi: iki taraf da siyasi ve ticari ilişkilerini "
    "geliştirmek istiyordu. 1480 tarihli portrede işlemeli kumaşlar, inciler ve taçlar hükümdarın "
    "ihtişamını vurguluyor. Tablo, bir sanat eserinin aynı zamanda diplomatik bir buluşmanın izi "
    "olabileceğini gösteriyor.\n\n"
    "🖼️ Görseller tarihsel yorumdur; temsili rekonstrüksiyondur.\n\n"
    "Merakını besle, Bilgi Dozu'nu takip et! 🔔"
)
HASHTAGS = "#bilgidozu #shorts #tarih #sanat"
TAGS = ("bilgidozu, shorts, tarih, fatih sultan mehmet, gentile bellini, istanbul, venedik, "
        "sanat tarihi, portre, osmanlı")
PINNED = "Sen bu portrenin hikâyesini biliyor muydun? 👇"
CATEGORY = "Tarih"
SOURCE = "National Gallery • Open University"

OUT = ROOT / "result_queue_097"


def fail(message: str):
    raise SystemExit("097 kuyruk DURDU: " + message)


def check_context():
    if os.environ.get("GITHUB_REPOSITORY") != "benngokhan/yt_auto_uploader":
        fail("yanlış depo")
    if os.environ.get("GITHUB_REF") != "refs/heads/" + BRANCH:
        fail("yanlış dal")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_render(video: Path, cover: Path):
    if not video.is_file() or not cover.is_file():
        fail("render artifact eksik (video/kapak)")
    if video.stat().st_size != VIDEO_BYTES or sha256(video) != VIDEO_SHA:
        fail("video sha256/boyut doğrulanamadı; kuyruğa yazılmadı")
    if cover.stat().st_size > 2 * 1024 * 1024:
        fail("kapak 2 MB üstü")


def find_queued(table: dict) -> str | None:
    for fname, rec in table.items():
        if (rec.get("title") or "").strip() == TITLE:
            return fname
    return None


def load_table(drive) -> dict:
    return sm.load_table_from_drive_or_local(
        drive, sm.CEO_FOLDER_ID, sheets_id=sm.DEFAULT_SHEETS_ID
    )


def drive_file_exists(drive, folder_id: str, name: str) -> bool:
    res = drive.files().list(
        q=f"'{folder_id}' in parents and name = '{name}' and trashed = false",
        pageSize=5,
        fields="files(id, name)",
    ).execute()
    return bool(res.get("files"))


def delete_file(drive, file_id: str):
    try:
        drive.files().delete(fileId=file_id).execute()
    except Exception as exc:  # noqa: BLE001
        print("UYARI: temizlik başarısız", file_id, exc, flush=True)


def main() -> int:
    check_context()
    src = ROOT / "queue_src" / "result_097_render" / "final"
    video = src / "video.mp4"
    cover = src / "kapak.jpg"
    verify_render(video, cover)

    drive = teslim.drive_istemci()

    already = find_queued(load_table(drive))
    if already:
        result = {"state": "already_queued", "file": already, "title": TITLE,
                  "youtube_uploaded": False}
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0

    existing = {v["name"] for v in sm.list_drive_videos(drive, sm.SHORTS_VIDEO_FOLDER_ID)}
    current_max = teslim.sonraki_numara(drive) - 1
    number = NUMBER
    video_name = f"video_{number}.mp4"
    cover_name = f"kapak_{number}.jpg"
    if video_name in existing:
        fail(f"{video_name} zaten var; mükerrer yazım engellendi")
    if drive_file_exists(drive, sm.SHORTS_COVER_FOLDER_ID, cover_name):
        fail(f"{cover_name} zaten var; başka videonun kapağını ezmemek için durdu")

    video_id = teslim.drive_yukle(drive, video, video_name)
    cover_id = None
    cover_created = False
    try:
        cover_id, action = upsert_cover(drive, sm.SHORTS_COVER_FOLDER_ID, cover_name,
                                        cover.read_bytes())
        cover_created = action == "oluşturuldu"
        ok = teslim.tablo_satir_ekle(drive, video_name, TITLE, DESCRIPTION, HASHTAGS, TAGS,
                                     PINNED, CATEGORY, SOURCE)
        if not ok:
            raise RuntimeError("tablo satırı yazılamadı")
        table = load_table(drive)
        if find_queued(table) != video_name:
            raise RuntimeError("tablo satırı doğrulanamadı")
    except Exception:
        delete_file(drive, video_id)
        if cover_created and cover_id:
            delete_file(drive, cover_id)
        raise

    result = {
        "state": "queued",
        "file": video_name,
        "cover": cover_name,
        "number": number,
        "current_max_number": current_max,
        "queue_order_warning": None if number == current_max + 1 else
        f"205 sabit istendi; mevcut en yüksek numara {current_max}",
        "title": TITLE,
        "category": CATEGORY,
        "source": SOURCE,
        "video_id": video_id,
        "cover_id": cover_id,
        "video_sha256": VIDEO_SHA,
        "source_run": SOURCE_RUN,
        "youtube_uploaded": False,
        "queued_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "expected_slot_tr": "bir sonraki 19:30 TR",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "queue_097_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"097 kuyruk DURDU: {type(exc).__name__}: {exc}") from None
