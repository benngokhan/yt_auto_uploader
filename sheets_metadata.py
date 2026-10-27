#!/usr/bin/env python3
"""
Bilgi Dozu (@bilgidozuofficial) — Google Drive & Excel (DRIVE Sekmesi) Metadata Eşleştirici
- Shorts kuyruğu kesin olarak video_31.mp4'ten başlar (video_1..video_30 korumalıdır).
- 'short' (video_XX.mp4) ve 'long' (uzun_video_XX.mp4) ayrımını destekler.
"""

import io
import logging
import os
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import PatternFill

try:
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
except ImportError:
    MediaIoBaseDownload = MediaIoBaseUpload = None

log = logging.getLogger(__name__)

DEFAULT_DRIVE_FOLDER_ID = "1w8tz_lv7iMFsRRCaTKUSY_ri0F107rz_"  # KartaL Stok (27.10 karar: TEK kuyruk klasörü — eski YENI_SERI_ONAYLI_STOK buraya taşındı)
DEFAULT_SHEETS_ID = ""
MIN_SHORTS_NUMBER = 47   # CEO kararı 28.10: video_47+ kullanılabilir; 1..46 arşivde (zaten yayınlanmış)
MIN_LONG_NUMBER = 101    # Eski uzun_video_1..100 silinmeden askıda; yalnız yeni onaylı uzun seri (101+) sürüme girer

CATEGORY_MAP = {
    "uzay ve astronomi": "28",
    "fizik ve mühendislik": "28",
    "fizik ve bilim": "28",
    "tarih ve mühendislik": "28",
    "bilim ve teknoloji": "28",
    "uzun — bilim ve doğa": "28",
    "günlük hayat": "28",
    "beyin ve psikoloji": "27",
    "insan vücudu": "27",
    "doğa ve hayvanlar": "27",
    "biyoloji ve vücut": "27",
    "tarih ve arkeoloji": "27",
}


def is_long_filename(filename: str) -> bool:
    return os.path.basename(filename).lower().startswith("uzun_")


def extract_video_number(filename: str) -> int:
    nums = [int(n) for n in re.findall(r"\d+", os.path.basename(filename))]
    return nums[0] if nums else 999999


def natural_sort_key(filename: str) -> tuple:
    name = os.path.basename(filename).lower()
    is_long = 1 if is_long_filename(name) else 0
    return (is_long, extract_video_number(name), name)


def is_skipped_by_floor(filename: str) -> bool:
    name = os.path.basename(filename).lower()
    if name.startswith("video_") and extract_video_number(name) < MIN_SHORTS_NUMBER:
        return True
    if name.startswith("uzun_") and extract_video_number(name) < MIN_LONG_NUMBER:
        return True
    return False


BEDEN_BEYIN_FILES = {
    "video_47.mp4", "video_52.mp4", "video_57.mp4", "video_62.mp4",
    "video_67.mp4", "video_72.mp4", "video_77.mp4",
    "video_106.mp4", "video_107.mp4", "video_108.mp4", "video_109.mp4", "video_110.mp4",
    "video_83.mp4", "video_91.mp4", "video_100.mp4", "video_121.mp4",
    "video_131.mp4", "video_132.mp4", "video_133.mp4", "video_134.mp4", "video_135.mp4",
    "video_136.mp4", "video_137.mp4", "video_138.mp4",
}


def classify_strategy_column(filename: str, raw_cat: str = "") -> str:
    """Strateji Masası 3 sütun kuralı: 'uzun' | 'beden_beyin' | 'doz_disi'."""
    fn = os.path.basename(filename).strip()
    if is_long_filename(fn):
        return "uzun"
    if fn in BEDEN_BEYIN_FILES:
        return "beden_beyin"
    cl = (raw_cat or "").lower()
    if any(k in cl for k in ("beyin", "psikoloj", "vücut", "vucut", "nörobilim", "norobilim", "insan bedeni", "insan vücudu")):
        return "beden_beyin"
    return "doz_disi"


def classify_doz_disi_subcat(raw_cat: str = "", title: str = "") -> str:
    """Doz Dışı gününde aynı gün 2 slotun aynı alt kategoride kalması için alt sütun."""
    c = f"{raw_cat} {title}".lower()
    if any(k in c for k in ("tarih", "arkeol", "antik", "piramit", "roma")):
        return "tarih"
    if any(k in c for k in ("uzay", "evren", "astronomi", "gezegen", "yıldız", "güneş", "ay ")):
        return "uzay"
    if any(k in c for k in ("doğa", "doga", "hayvan", "canlı", "okyanus")):
        return "doga"
    return "fizik"


def decide_daily_column(now_tr: Optional[datetime] = None) -> str:
    """
    Strateji Masası Haftalık Sıralama Kuralı (26.10.2026):
    - Cuma (weekday==4)                        -> 'uzun' (haftada 1)
    - Pazar (weekday==6)                       -> 'doz_disi' (haftada 1, etiketli)
    - Pzt, Sal, Çar, Per, Cmt (haftada 5 gün) -> 'beden_beyin'
    """
    tr_tz = timezone(timedelta(hours=3))
    dt = now_tr.astimezone(tr_tz) if now_tr else datetime.now(tr_tz)
    if dt.weekday() == 4:
        return "uzun"
    if dt.weekday() == 6:
        return "doz_disi"
    return "beden_beyin"


def decide_prime_time_video_type(now_tr: Optional[datetime] = None) -> str:
    """Cuma günü 'long', diğer 6 gün 'short'."""
    return "long" if decide_daily_column(now_tr) == "uzun" else "short"


def sanitize_title(raw_title: str, max_len: int = 100) -> str:
    t = (raw_title or "").replace("<", "").replace(">", "").strip()
    if len(t) <= max_len:
        return t
    suffix = ""
    for tag in [" #bilgidozu #shorts", " #bilgidozu", " #shorts"]:
        if t.lower().endswith(tag):
            suffix = t[-len(tag):]
            t = t[:-len(tag)].rstrip()
            break
    budget = max_len - len(suffix)
    if len(t) > budget:
        cut = t[:budget].rsplit(" ", 1)[0]
        t = (cut if cut else t[:budget]).rstrip(" -·,:;!")
    return f"{t}{suffix}"[:max_len]


def parse_tags(raw_tags: str, max_chars: int = 450) -> list[str]:
    if not raw_tags:
        return ["bilgi dozu", "bilim", "ilginç bilgiler", "shorts"]
    parts = [p.strip().lstrip("#") for p in re.split(r"[,;\n]+", str(raw_tags)) if p.strip()]
    out, seen, total = [], set(), 0
    for p in parts:
        low = p.lower()
        if low in seen or not p:
            continue
        cost = len(p) + (3 if out else 2)
        if total + cost > max_chars:
            break
        seen.add(low)
        out.append(p)
        total += cost
    return out or ["bilgi dozu", "bilim", "shorts"]


def map_category_id(raw_cat: str, default_id: str = "27") -> str:
    c = (raw_cat or "").strip()
    if c in {"1", "2", "10", "15", "17", "19", "20", "22", "23", "24", "25", "26", "27", "28"}:
        return c
    low = c.lower()
    for k, v in CATEGORY_MAP.items():
        if k in low:
            return v
    return default_id


def parse_drive_sheet(xlsx_source) -> dict[str, dict]:
    wb = openpyxl.load_workbook(xlsx_source, data_only=True)
    ws = next((s for s in wb.worksheets if s.title.strip().casefold() == "drive"), wb.active)
    records = {}

    for r in range(2, ws.max_row + 1):
        status = str(ws.cell(r, 1).value or "").strip()
        fname = str(ws.cell(r, 2).value or "").strip()
        raw_title = str(ws.cell(r, 3).value or "").strip()
        if not fname or not fname.lower().endswith(".mp4"):
            continue
        desc = str(ws.cell(r, 4).value or "").strip()
        hashtags = str(ws.cell(r, 5).value or "").strip()
        raw_tags = str(ws.cell(r, 6).value or "").strip()
        pinned = str(ws.cell(r, 7).value or "").strip()
        raw_cat = str(ws.cell(r, 8).value or "").strip()
        source = str(ws.cell(r, 9).value or "").strip()

        full_desc = desc
        has_structured_chapters = ("bölümler" in full_desc.lower() or "00:00" in full_desc)
        if pinned and pinned not in full_desc and not has_structured_chapters:
            full_desc = f"💬 {pinned}\n\n{full_desc}".strip()
        if source and "kaynak" not in full_desc.lower():
            full_desc = f"{full_desc}\n\n📚 Kaynak: {source}".strip()
        if hashtags and hashtags.split()[0].lower() not in full_desc.lower():
            full_desc = f"{full_desc}\n{hashtags}".strip()

        title = sanitize_title(raw_title) if raw_title else ""
        tags = parse_tags(raw_tags)
        cat_id = map_category_id(raw_cat)

        status_up = status.upper()
        yt_url = str(ws.cell(r, 10).value or "").strip()
        has_yt_link = bool(yt_url and ("youtu" in yt_url.lower() or yt_url.startswith("http")))
        col_group = classify_strategy_column(fname, raw_cat)
        if col_group == "doz_disi" and "doz dışı" not in [t.lower() for t in tags]:
            tags = (tags + ["doz dışı"])[:25]

        # KESİN KURAL: YouTube Link dolu olan, YÜKLENDİ veya ASKIDA olan dosya adları ASLA kuyruğa alınmaz!
        is_done = (
            has_yt_link
            or any(w in status_up for w in ("YÜKLENDİ", "YUKLENDI", "YAYINLANDI", "UPLOADED", "PUBLISHED", "TAMAM", "ASKIDA"))
            or is_skipped_by_floor(fname)
        )
        has_title = bool(title)

        records[fname] = {
            "row": r,
            "status": "YÜKLENDİ" if is_done else (status or "BEKLEMEDE"),
            "file_name": fname,
            "title": title,
            "description": full_desc,
            "hashtags": hashtags,
            "tags": tags,
            "pinned_comment": pinned,
            "category_name": raw_cat,
            "categoryId": cat_id,
            "source": source,
            "youtube_url": yt_url,
            "has_youtube_link": has_yt_link,
            "column_group": col_group,
            "is_long": is_long_filename(fname),
            "has_title": has_title,
            "is_ready": (not is_done) and has_title,
        }
    wb.close()
    return records


def _download_workbook_bytes_from_drive(drive, folder_id: str, sheets_id: str = DEFAULT_SHEETS_ID) -> Optional[tuple[io.BytesIO, str]]:
    if not drive or MediaIoBaseDownload is None:
        return None

    queries = []
    if folder_id:
        queries.append(
            f"'{folder_id}' in parents and trashed = false and "
            f"(name = 'bilgidozu_yukleme_tablosu.xlsx' or name = 'baslik.xlsx' or mimeType = 'application/vnd.google-apps.spreadsheet')"
        )

    for q in queries:
        try:
            res = drive.files().list(
                q=q,
                pageSize=10,
                fields="files(id, name, mimeType, modifiedTime)",
            ).execute()
            files = res.get("files", [])
            if files:
                # EMİR 024: ana tablo her zaman bilgidozu_yukleme_tablosu.xlsx (baslik.xlsx = arşiv, dokunulmaz)
                preferred = [x for x in files if x.get("name") == "bilgidozu_yukleme_tablosu.xlsx"]
                f = preferred[0] if preferred else files[0]
                fid = f["id"]
                mime = f.get("mimeType", "")
                buf = io.BytesIO()
                if mime == "application/vnd.google-apps.spreadsheet":
                    req = drive.files().export_media(
                        fileId=fid,
                        mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                else:
                    req = drive.files().get_media(fileId=fid)
                dl = MediaIoBaseDownload(buf, req)
                done = False
                while not done:
                    _, done = dl.next_chunk()
                buf.seek(0)
                return buf, f.get("name", "Drive_XLSX")
        except Exception as e:
            log.warning(f"Drive tablo arama uyarısı ({q[:40]}...): {e}")

    if sheets_id:
        for method in ("export", "get"):
            try:
                buf = io.BytesIO()
                if method == "export":
                    req = drive.files().export_media(
                        fileId=sheets_id,
                        mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                else:
                    req = drive.files().get_media(fileId=sheets_id)
                dl = MediaIoBaseDownload(buf, req)
                done = False
                while not done:
                    _, done = dl.next_chunk()
                buf.seek(0)
                return buf, f"Sheets({sheets_id[:8]})"
            except Exception:
                continue

    return None


def load_table_from_drive_or_local(
    drive=None,
    folder_id: str = DEFAULT_DRIVE_FOLDER_ID,
    sheets_id: str = DEFAULT_SHEETS_ID,
    local_fallback: Optional[Path] = None,
) -> dict[str, dict]:
    base_records = {}
    base_dir = Path(__file__).parent
    for candidate in [
        local_fallback,
        base_dir / "bilgidozu_yukleme_tablosu.xlsx",
        base_dir / "baslik.xlsx",
        Path("/home/user/bilgidozu_yukleme_tablosu.xlsx"),
    ]:
        if candidate and Path(candidate).exists():
            try:
                base_records = parse_drive_sheet(candidate)
                break
            except Exception as e:
                log.warning(f"Yerel tablo okuma uyarısı ({candidate}): {e}")

    dl_res = _download_workbook_bytes_from_drive(drive, folder_id, sheets_id=sheets_id)
    if dl_res is not None:
        buf, src_name = dl_res
        try:
            drive_records = parse_drive_sheet(buf)
            for k, v in drive_records.items():
                if v.get("has_title") or k not in base_records:
                    base_records[k] = v
            log.info(f"Drive tablosu ({src_name}) yüklendi ve birleştirildi ({len(base_records)} satır).")
        except Exception as e:
            log.warning(f"Drive tablosu ayrıştırılamadı, yerel tablo kullanılacak: {e}")

    return base_records


def list_drive_videos_with_stats(drive, folder_id: str) -> tuple[list[dict], int]:
    """KartaL Stok klasöründeki .mp4 dosyalarını tarar, mükerrer dosya sayısını hesaplar ve
    aynı dosya adından birden fazla varsa yalnızca EN ESKİ (orijinal) kopyayı tutar."""
    raw_videos = []
    if not drive or not folder_id:
        return [], 0

    page_token = None
    while True:
        res = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            pageSize=200,
            fields="nextPageToken, files(id, name, mimeType, size, createdTime)",
            **({"pageToken": page_token} if page_token else {}),
        ).execute()
        for f in res.get("files", []):
            mime = f.get("mimeType", "")
            name = f.get("name", "")
            if mime == "application/vnd.google-apps.folder":
                continue  # KAPAKLAR veya karantina alt klasörlerine inme
            if name.lower().endswith(".mp4") or "video/" in mime:
                raw_videos.append(f)
        page_token = res.get("nextPageToken")
        if not page_token:
            break

    by_name: dict[str, list[dict]] = {}
    for f in raw_videos:
        key = f.get("name", "").strip()
        if key:
            by_name.setdefault(key, []).append(f)

    unique_videos = []
    duplicate_count = 0
    for key, items in by_name.items():
        items.sort(key=lambda x: x.get("createdTime", ""))
        unique_videos.append(items[0])  # en eski (orijinal) kopya
        if len(items) > 1:
            duplicate_count += len(items) - 1

    unique_videos.sort(key=lambda x: natural_sort_key(x.get("name", "")))
    return unique_videos, duplicate_count


def list_drive_videos(drive, folder_id: str) -> list[dict]:
    unique_videos, _ = list_drive_videos_with_stats(drive, folder_id)
    return unique_videos


def compute_queue_stats(
    drive,
    folder_id: str,
    table: Optional[dict] = None,
    skip_ids: Optional[set] = None,
) -> dict:
    """Strateji Masası 3 sayılı kuyruk raporu: benzersiz video / mükerrer / yayınlanmış."""
    skip_ids = skip_ids or set()
    if table is None:
        table = load_table_from_drive_or_local(drive, folder_id)
    unique_videos, duplicate_count = list_drive_videos_with_stats(drive, folder_id)
    published_count = 0
    ready_count = 0
    for v in unique_videos:
        fn = v.get("name", "")
        vid = v.get("id", "")
        rec = table.get(fn)
        is_pub = (
            is_skipped_by_floor(fn)
            or fn in skip_ids
            or vid in skip_ids
            or bool(rec and (rec.get("has_youtube_link") or not rec.get("is_ready")))
        )
        if is_pub:
            published_count += 1
        elif rec and rec.get("is_ready"):
            ready_count += 1
    return {
        "unique_videos": len(unique_videos),
        "duplicate_videos": duplicate_count,
        "published_videos": published_count,
        "ready_videos": ready_count,
    }


def _recent_uploaded_titles(limit: int = 3) -> list[dict]:
    """uploaded.txt'nin son satırlarından {file_name, title} döndürür (LOCKED/MANUAL satırları atlar)."""
    out: list[dict] = []
    try:
        p = Path("uploaded.txt")
        if not p.exists():
            return out
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if "|" in ln]
        for ln in reversed(lines):
            parts = [x.strip() for x in ln.split("|")]
            if len(parts) < 2:
                continue
            if parts[0].upper().startswith(("LOCKED_", "MANUAL_SKIP")):
                continue
            out.append({"file_name": parts[1], "title": parts[4] if len(parts) >= 5 else ""})
            if len(out) >= limit:
                break
    except Exception:
        pass
    return out


def _kartal_llm_rank(prompt_system: str, prompt_user: str, cfg: dict) -> str:
    """Groq (llama-3.1-8b-instant) -> Gemini (gemini-2.0-flash) sırasıyla dener; ham metin döndürür."""
    import json as _json
    import urllib.request as _u

    groq_key = (cfg.get("groq_api_key") or os.environ.get("GROQ_API_KEY") or "").strip()
    groq_modeller = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    for _model in groq_modeller if groq_key else []:
        try:
            body = _json.dumps({
                "model": _model,
                "messages": [
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": prompt_user},
                ],
                "temperature": 0.4,
                "max_tokens": 220,
                "response_format": {"type": "json_object"},
            }).encode()
            req = _u.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=body, method="POST",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            )
            res = _json.loads(_u.urlopen(req, timeout=25).read().decode())
            txt = res["choices"][0]["message"]["content"]
            if txt.strip():
                return txt
        except Exception as e:
            log.warning(f"KartaL Akıllı Sıra (Groq/{_model}) uyarısı: {e}")
            if "403" in str(e) or "401" in str(e):
                break  # anahtar hatasıysa diğer modeli denemektente fayda yok

    gem_key = (cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY") or "").strip()
    gem_modeller = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-flash-lite-latest", "gemini-2.5-flash"]  # 2026: 2.0 serisi emekli, 3.5 güncel
    for _model in gem_modeller if gem_key else []:
        try:
            body = _json.dumps({
                "contents": [{"parts": [{"text": prompt_system + chr(10) + chr(10) + prompt_user}]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 220},
            }).encode()
            req = _u.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{_model}:generateContent?key={gem_key}",
                data=body, method="POST",
                headers={"Content-Type": "application/json"},
            )
            res = _json.loads(_u.urlopen(req, timeout=25).read().decode())
            txt = res["candidates"][0]["content"]["parts"][0]["text"]
            if txt.strip():
                return txt
        except Exception as e:
            log.warning(f"KartaL Akıllı Sıra (Gemini/{_model}) uyarısı: {e}")
            if "403" in str(e) or "401" in str(e) or "400" in str(e):
                break  # anahtar/istek hatasıysa model geçmek anlamsız
    log.warning("KartaL Akıllı Sıra: tüm LLM sağlayıcıları sustu, doğal sıra kullanılacak.")
    return ""


def kartal_smart_pick(candidates: list[dict], table: dict) -> dict:
    """KartaL Akıllı Sıra: başlık+kategori analiziyle bugünkü slot için en güçlü videoyu seçer.
    Kesin güvence: sadece 'hazır & yüklenmemiş' aday havuzundan seçer -> tekrar İMKANSIZ.
    LLM susarsa doğal sırayla (ilk aday) devam eder; asla turu çökertmez."""
    if not candidates:
        raise RuntimeError("aday havuzu boş")
    if len(candidates) == 1:
        return candidates[0]
    try:
        import json as _json
        from datetime import datetime, timedelta

        cfg: dict = {}
        try:
            cfg = _json.loads(Path("config.json").read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

        tr_now = datetime.utcnow() + timedelta(hours=3)
        gun = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"][tr_now.weekday()]
        slot = "öğle (12-15)" if tr_now.hour < 15 else ("akşamüstü (15-20)" if tr_now.hour < 20 else "prime-time gece (20-24)")

        recents = _recent_uploaded_titles(3)
        recent_lines = []
        for r in recents:
            cat = (table.get(r["file_name"]) or {}).get("category_name", "?")
            recent_lines.append(f"- {r['file_name']}: {(r['title'] or '')[:80]} (kategori: {cat})")
        recent_txt = "\n".join(recent_lines) if recent_lines else "- (yok)"

        cand_lines = []
        for c in candidates[:12]:
            meta = c.get("metadata", {})
            cand_lines.append(f"- {c['name']}: {meta.get('title', '')[:90]} | kategori: {meta.get('category_name', '?')} | tag: {str(meta.get('hashtags', ''))[:60]}")
        cand_txt = "\n".join(cand_lines)

        system_msg = (
            "Sen KartaL — Bilgi Dozu (bilim/merak Shorts) kanalının içerik stratejisisin. "
            "Görevin: verilen aday havuzundan BU slot için yayınlanmaya en uygun videoyu seçmek."
        )
        user_msg = (
            f"Bugün: {gun}, slot: {slot} (TR saati).\n\n"
            f"Son yüklenenler:\n{recent_txt}\n\n"
            f"Aday havuzu (yalnızca bunlardan seç):\n{cand_txt}\n\n"
            "Seçim kuralları:\n"
            "1. Son yüklenenle AYNI kategoriden üst üste basma (çeşitlilik şart).\n"
            "2. Hafta sonu gündüz -> şaşırtıcı/eğlenceli (hayvan, evren, garip olaylar); hafta içi akşam prime-time -> merak uyandıran (beyin, vücut, gizem).\n"
            "3. Güçlü başlık sinyalleri: soru formu, sayı, 'neden/neden' merak boşluğu, duygu.\n"
            "4. Sadece birini seç ve SADECE JSON döndür: {\"file_name\": \"...\", \"neden\": \"tek cümle\"}."
        )

        raw = _kartal_llm_rank(system_msg, user_msg, cfg)
        if raw:
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                data = _json.loads(m.group(0))
                fname = str(data.get("file_name", ""))
                neden = str(data.get("neden", ""))[:200]
                for c in candidates:
                    if c["name"] == fname:
                        log.info(f"KARTAL AKILLI SIRA: {fname} seçildi — {neden}")
                        return c
                log.warning(f"KartaL Akıllı Sıra: LLM havuz dışı isim döndürdü ({fname}), doğal sıraya dön.")
    except Exception as e:
        log.warning(f"KartaL Akıllı Sıra kapalı, doğal sırayla devam: {e}")
    return candidates[0]


def _todays_uploaded_filenames(now_tr: Optional[datetime] = None) -> list[str]:
    """Bugün (TR tarihiyle) yüklenmiş dosya adlarını uploaded.txt'den döndürür."""
    tr_tz = timezone(timedelta(hours=3))
    dt_tr = now_tr.astimezone(tr_tz) if now_tr else datetime.now(tr_tz)
    today_str = dt_tr.strftime("%Y-%m-%d")
    names: list[str] = []
    try:
        p = Path(__file__).parent / "uploaded.txt"
        if not p.exists():
            p = Path("uploaded.txt")
        if not p.exists():
            return names
        for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "|" not in ln or ln.strip().startswith("#"):
                continue
            parts = [x.strip() for x in ln.split("|")]
            if len(parts) < 4 or parts[0].upper().startswith(("LOCKED_", "MANUAL_SKIP")):
                continue
            try:
                utc_dt = datetime.strptime(parts[3], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                if utc_dt.astimezone(tr_tz).strftime("%Y-%m-%d") == today_str:
                    names.append(parts[1])
            except Exception:
                continue
    except Exception:
        pass
    return names


def get_next_scheduled_video(
    drive,
    folder_id: str,
    skip_ids: set = None,
    sheets_id: str = DEFAULT_SHEETS_ID,
    local_xlsx: Optional[Path] = None,
    video_type: str = "auto",
) -> Optional[dict]:
    skip_ids = skip_ids or set()
    table = load_table_from_drive_or_local(drive, folder_id, sheets_id=sheets_id, local_fallback=local_xlsx)
    videos = list_drive_videos(drive, folder_id) if drive else []

    # YAYINLANMIŞ DOSYA ADI FİLTRESİ: DRIVE sekmesinde YouTube Link dolu olan veya hazır olmayan adlar ASLA alınmaz
    published_names = {
        fname for fname, rec in table.items()
        if rec.get("has_youtube_link") or rec.get("youtube_url") or not rec.get("is_ready")
    }

    daily_col = decide_daily_column()  # 'beden_beyin' (5 gün) | 'uzun' (Cuma) | 'doz_disi' (Pazar)
    todays_uploads = _todays_uploaded_filenames()

    # Cuma kuralı: haftada 1 Uzun video. Cuma günü uzun video zaten çıktıysa 2. slotta Shorts karıştırma!
    if video_type == "auto" and daily_col == "uzun":
        if any(is_long_filename(fn) for fn in todays_uploads):
            log.info("CUMA KURALI: Haftalık Uzun Video bugün zaten yayınlandı; aynı gün farklı kategori açılmaz.")
            return None

    def collect_ready(want_long: Optional[bool], want_col: Optional[str] = None, subcat_lock: Optional[str] = None) -> list[dict]:
        ready: list[dict] = []
        for v in videos:
            vid = v["id"]
            vname = v["name"]
            if is_skipped_by_floor(vname):
                continue
            if vid in skip_ids or vname in skip_ids or vname in published_names:
                continue
            if want_long is not None and is_long_filename(vname) != want_long:
                continue
            meta = table.get(vname)
            if not meta or not meta.get("is_ready") or meta.get("has_youtube_link") or meta.get("youtube_url"):
                continue
            col = meta.get("column_group") or classify_strategy_column(vname, meta.get("category_name", ""))
            if want_col and col != want_col:
                continue
            if subcat_lock and classify_doz_disi_subcat(meta.get("category_name", ""), meta.get("title", "")) != subcat_lock:
                continue
            ready.append({
                "id": vid,
                "name": vname,
                "size": int(v.get("size", 0)),
                "video": v,
                "metadata": meta,
                "title": meta["title"],
                "description": meta["description"],
                "tags": meta["tags"],
                "categoryId": meta["categoryId"],
                "category_name": meta.get("category_name", ""),
                "column_group": col,
                "pinned_comment": meta["pinned_comment"],
                "row": meta["row"],
                "video_type": "long" if is_long_filename(vname) else "short",
            })
        # Strateji Masası tablo sırasını birebir uygula (row sırası)
        ready.sort(key=lambda item: (item["row"], natural_sort_key(item["name"])))
        return ready

    # Aynı gün 2 slot varsa İKİSİ DE AYNI SÜTUNDAN olacak (19:00 ne açtıysa 20:15 aynı sütundan devam eder)
    locked_col = daily_col
    locked_subcat = None
    if todays_uploads and video_type == "auto":
        first_today = todays_uploads[0]
        first_meta = table.get(first_today) or {}
        locked_col = first_meta.get("column_group") or classify_strategy_column(first_today, first_meta.get("category_name", ""))
        if locked_col == "doz_disi":
            locked_subcat = classify_doz_disi_subcat(first_meta.get("category_name", ""), first_meta.get("title", ""))

    if video_type == "long" or (video_type == "auto" and locked_col == "uzun"):
        cands = collect_ready(want_long=True, want_col="uzun")
        return cands[0] if cands else None

    if video_type == "short" and locked_col == "uzun":
        locked_col = "beden_beyin"

    # Önce günün kilitli sütunundan (ve varsa aynı alt kategoriden) seç
    cands = collect_ready(want_long=False, want_col=locked_col, subcat_lock=locked_subcat)
    if not cands and locked_subcat:
        cands = collect_ready(want_long=False, want_col=locked_col, subcat_lock=None)
    if not cands and not todays_uploads:
        # Yalnızca günün ilk slotunda o sütun tamamen bittiyse sıradaki Beden&Beyin -> Doz Dışı yedeklemesi
        for fallback_col in ("beden_beyin", "doz_disi"):
            cands = collect_ready(want_long=False, want_col=fallback_col)
            if cands:
                break
    # EMİR 024: shorts — tablo sırası DEĞİL, hazır havuzdan RASTGELE (uzun video path'i sıralı kalır)
    return random.choice(cands) if cands else None


# ---------------------------------------------------------------------------
# EMİR 024 — UYARILAR / İŞÇİLER otomatik kayıt (KURAL 8)
# ---------------------------------------------------------------------------

def _find_primary_table(drive, folder_id: str) -> Optional[str]:
    """Kuyruk klasöründeki ana tablonun Drive ID'si (bilgidozu tablosu; yoksa baslik.xlsx)."""
    if not drive or not folder_id:
        return None
    try:
        res = drive.files().list(
            q=f"'{folder_id}' in parents and (name = 'bilgidozu_yukleme_tablosu.xlsx' or name = 'baslik.xlsx') and trashed = false",
            pageSize=10,
            fields="files(id, name)",
        ).execute()
        files = res.get("files", [])
        for fobj in files:
            if fobj.get("name") == "bilgidozu_yukleme_tablosu.xlsx":
                return fobj["id"]
        return files[0]["id"] if files else None
    except Exception as e:
        log.warning(f"Ana tablo aranırken hata (zararsız): {e}")
        return None


def _drive_table_write(drive, table_file_id: str, writer) -> bool:
    """Drive tablosunu indir, writer(wb) uygula, geri yaz. Hata akışı bozmaz."""
    if not drive or MediaIoBaseDownload is None:
        return False
    try:
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=table_file_id))
        done = False
        while not done:
            _, done = dl.next_chunk()
        buf.seek(0)
        wb = openpyxl.load_workbook(buf)
        writer(wb)
        out_buf = io.BytesIO()
        wb.save(out_buf)
        wb.close()
        out_buf.seek(0)
        media = MediaIoBaseUpload(
            out_buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        drive.files().update(fileId=table_file_id, media_body=media).execute()
        return True
    except Exception as e:
        log.warning(f"Drive tablo yazımı atlandı (akış bozulmaz): {e}")
        return False


def log_uyari_drive(drive, folder_id: str, kategori: str, mesaj: str) -> bool:
    """EMİR 024 KURAL 8: her RED/hata → ana tablonun UYARILAR sekmesine otomatik satır."""
    fid = _find_primary_table(drive, folder_id)
    if not fid:
        return False
    now_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M")

    def writer(wb):
        ws = wb["UYARILAR"] if "UYARILAR" in wb.sheetnames else wb.create_sheet("UYARILAR")
        if not ws.cell(1, 1).value:
            ws.append(["Kontrol Noktası", "Durum", "Seviye", "Son Kontrol", "Detay ve Çözüm"])
        ws.append([kategori, "HATA", "Kırmızı", now_str, str(mesaj)[:500]])

    return _drive_table_write(drive, fid, writer)


def iscilers_heartbeat(drive, folder_id: str) -> bool:
    """EMİR 024: her cron çalışmasında İŞÇİLER sekmesindeki tüm işçilerin 'Son Güncelleme Zamanı' canlanır."""
    fid = _find_primary_table(drive, folder_id)
    if not fid:
        return False
    now_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M")

    def writer(wb):
        ws = None
        for name in ("İŞÇİLER", "ISCILER"):
            if name in wb.sheetnames:
                ws = wb[name]
                break
        if ws is None:
            ws = wb.create_sheet("İŞÇİLER")
        if not ws.cell(1, 1).value:
            ws.append(["İşçi Adı", "Durum", "Son Güncelleme Zamanı", "Son Hata Mesajı", "Kaç İş Yaptı", "Son İşlem Özeti"])
        rows = [r for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value]
        if not rows:
            ws.append(["Yükleyici (Drive -> YouTube)", "Çalışıyor", now_str, "", "", "EMİR 024: otomatik tick aktif"])
            rows = [ws.max_row]
        for r in rows:
            if not ws.cell(r, 2).value:
                ws.cell(r, 2).value = "Çalışıyor"
            ws.cell(r, 3).value = now_str

    return _drive_table_write(drive, fid, writer)


def update_excel_status_in_drive(
    drive,
    folder_id: str,
    file_name: str,
    new_status: str = "YÜKLENDİ",
    youtube_url: str = "",
) -> bool:
    if not drive or not folder_id or MediaIoBaseDownload is None:
        return False
    try:
        res = drive.files().list(
            q=f"'{folder_id}' in parents and (name = 'bilgidozu_yukleme_tablosu.xlsx' or name = 'baslik.xlsx') and trashed = false",
            pageSize=10,
            fields="files(id, name)",
        ).execute()
        files = res.get("files", [])
        if not files:
            return False
        # EMİR 024: yalnız ana tabloya yaz (baslik.xlsx = arşiv, dokunma)
        primary = [x for x in files if x.get("name") == "bilgidozu_yukleme_tablosu.xlsx"]
        if primary:
            files = primary
        now_tr_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M")
        any_ok = False
        for fobj in files:
            fid = fobj["id"]
            buf = io.BytesIO()
            dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=fid))
            done = False
            while not done:
                _, done = dl.next_chunk()
            buf.seek(0)
            wb = openpyxl.load_workbook(buf)
            ws = next((s for s in wb.worksheets if s.title.strip().casefold() == "drive"), wb.active)
            green_fill = PatternFill(start_color="B6D7A8", end_color="B6D7A8", fill_type="solid")
            updated = False
            for r in range(2, ws.max_row + 1):
                if str(ws.cell(r, 2).value or "").strip().casefold() == file_name.casefold():
                    ws.cell(r, 1).value = new_status
                    if youtube_url:
                        ws.cell(r, 2).hyperlink = youtube_url
                        ws.cell(r, 10).value = youtube_url
                    ws.cell(r, 11).value = now_tr_str
                    for c in range(1, 14):
                        ws.cell(r, c).fill = green_fill
                    updated = True
                    break
            if updated:
                out_buf = io.BytesIO()
                wb.save(out_buf)
                out_buf.seek(0)
                media = MediaIoBaseUpload(
                    out_buf,
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    resumable=False,
                )
                drive.files().update(fileId=fid, media_body=media).execute()
                any_ok = True
            wb.close()
        return any_ok
    except Exception as e:
        log.warning(f"Drive XLSX güncellemesi atlandı (salt-okunur token olabilir, sorun değil): {e}")
        return False
