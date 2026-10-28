"""GÖRÜNÜMLEME RAPORU — sıfır YouTube API kotası (yt-dlp scraping).

Yapı:
  1. Tablodaki linkli satırların video ID'lerini toplar.
  2. yt-dlp ile kanal /shorts + /videos flat listelerini çeker (tek istek).
  3. Eksik kalanlar için video bazlı fallback (--skip-download).
  4. Eski Görüntülenme değeriyle farkı hesaplar, yeni değeri yazar.
  5. Özet basar (workflow Telegram'a gönderir).

KULLANIM:
  python stats_views.py            # gerçek (tabloyu günceller)
  python stats_views.py --dry-run  # sadece bas, tabloya yazma
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import openpyxl

TABLE = Path("bilgidozu_yukleme_tablosu.xlsx")
CHANNEL = "https://www.youtube.com/@bilgidozuofficial"
LINK_COL, VIEWS_COL, TITLE_COL, FILE_COL = 10, 12, 3, 2


def run_ytdlp(args: list[str], timeout: int = 90) -> str:
    try:
        r = subprocess.run(
            ["yt-dlp", *args, "--no-warnings", "--quiet"],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout
    except Exception as e:
        print(f"yt-dlp hata ({args[:4]}...): {e}", file=sys.stderr)
        return ""


def fetch_flat(tab: str) -> dict[str, int]:
    """Kanal sekmesinin flat listesi: {video_id: view_count}"""
    out = run_ytdlp(["--flat-playlist", "-J", f"{CHANNEL}/{tab}"], timeout=120)
    vids: dict[str, int] = {}
    if not out:
        return vids
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return vids
    for e in data.get("entries") or []:
        if not isinstance(e, dict):
            continue
        vid = e.get("id")
        vc = e.get("view_count")
        if vid and isinstance(vc, int):
            vids[vid] = vc
    return vids


def fetch_one(url: str) -> int | None:
    out = run_ytdlp(["--skip-download", "--no-warnings", "--print", "%(view_count)s", url], timeout=60)
    m = re.search(r"\d+", out.strip())
    return int(m.group()) if m else None


def extract_id(link: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{6,})", str(link))
    return m.group(1) if m else None


def main() -> None:
    dry = "--dry-run" in sys.argv
    wb = openpyxl.load_workbook(TABLE)
    ws = wb.active

    rows = []  # (row, file, title, old_views, video_id)
    for r in range(2, ws.max_row + 1):
        link = ws.cell(r, LINK_COL).value
        if not link:
            continue
        vid = extract_id(link)
        if not vid:
            continue
        old = ws.cell(r, VIEWS_COL).value
        try:
            old = int(old) if old not in (None, "") else 0
        except (TypeError, ValueError):
            old = 0
        rows.append((r, str(ws.cell(r, FILE_COL).value or ""), str(ws.cell(r, TITLE_COL).value or "")[:60], old, vid))

    if not rows:
        print("LINKLI SATIR YOK — rapor boş.")
        return

    # 1) flat tarama (2 istek: shorts + videos)
    views: dict[str, int] = {}
    for tab in ("shorts", "videos"):
        views.update(fetch_flat(tab))
    missing = [v for _, _, _, _, v in rows if v not in views]
    print(f"flat: {len(views)} video, {len(rows) - len(missing)}/{len(rows)} linkli satır eşleşti, eksik: {len(missing)}")

    # 2) eksikler için video bazlı fallback
    for i, (r, f, t, old, vid) in enumerate(rows):
        if vid in views:
            continue
        if i > 40:  # emniyet: en fazla ~40 tekil istek
            break
        vc = fetch_one(f"https://www.youtube.com/watch?v={vid}")
        if vc is not None:
            views[vid] = vc

    # 3) yaz + özet
    total = 0
    deltas: list[tuple[int, str, str]] = []
    written = 0
    for r, f, t, old, vid in rows:
        vc = views.get(vid)
        if vc is None:
            print(f"  UYARI: {f} ({vid}) view alınamadı — eski değer duruyor ({old})")
            total += old
            continue
        total += vc
        deltas.append((vc - old, t or f, f))
        if vc != old and not dry:
            ws.cell(r, VIEWS_COL).value = vc
            written += 1

    if not dry and written:
        wb.save(TABLE)

    deltas.sort(reverse=True)
    top = [d for d in deltas if d[0] > 0][:5]
    day_gain = sum(d[0] for d in deltas if d[0] > 0)
    print(f"TOPLAM_GORUNTULEME={total}")
    print(f"BUGUN_KAZANC={day_gain}")
    print(f"GUNCELLENEN_SATIR={written if not dry else 0} (dry_run={dry})")
    for d, t, f in top:
        print(f"TOP: +{d} | {t} | {f}")
    with open("stats_summary.json", "w", encoding="utf-8") as fh:
        json.dump({
            "total": total, "day_gain": day_gain, "updated": written if not dry else 0,
            "top": [{"delta": d, "title": t, "file": f} for d, t, f in top],
        }, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
