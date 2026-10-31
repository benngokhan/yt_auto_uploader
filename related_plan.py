"""Shorts ilgili-video iş emri planlayıcısı — YAYIN VEYA DÜZENLEME YAPMAZ.

YouTube Data API ilgili-video alanını sunmaz. Plan, yerel tablodan olası
Short->uzun eşleşmesini bulur; Studio'da işlem yapılmadan önce hedefin gerçekten
herkese açık/liste dışı olması ve doğru kanal ayrıca doğrulanmalıdır.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_id(url: object) -> str:
    try:
        s = str(url or "").strip()
        u = urlsplit(s)
        host = (u.hostname or "").lower()
        if host in {"youtu.be", "www.youtu.be"}:
            candidate = u.path.strip("/").split("/")[0]
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            path = u.path.strip("/").split("/")
            candidate = path[1] if len(path) > 1 and path[0] in {"shorts", "embed", "live"} else parse_qs(u.query).get("v", [""])[0]
        else:
            return ""
        return candidate if VIDEO_ID.fullmatch(candidate) else ""
    except (TypeError, ValueError):
        return ""


def uploaded_file_ids(path: Path) -> dict[str, str]:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = [x.strip() for x in line.split("|")]
            if len(fields) < 3:
                continue
            vid = extract_id(fields[2])
            if vid:
                out[fields[1].casefold()] = vid
    except OSError:
        return {}
    return out


def plan(headers: list[str], rows: dict[str, tuple], current_name: str,
         current_id: str, uploaded: dict[str, str] | None = None) -> dict:
    """Tek mevcut Short için eşsiz eşleşme üret; hiçbir ağa/hesaba erişmez."""
    current = current_name.casefold().strip()
    if current.startswith("uzun_"):
        return {"status": "long_video", "message": "Uzun video: Shorts bağlantıları elle/işçi tarafından ayrıca değerlendirilecek."}
    if not VIDEO_ID.fullmatch(current_id or ""):
        return {"status": "invalid_short", "message": "Short ID doğrulanamadı; bağlantı yapılmadı."}
    # Türkçe büyük İ casefold ile i + birleştirici nokta olur; eşleşmeyi normalize et.
    folded = [str(h or "").strip().casefold().replace("\u0307", "") for h in headers]
    if "dosya adı" not in folded or "youtube link" not in folded or "ilgili video" not in folded:
        return {"status": "no_mapping", "message": "Eşleştirme sütunları bulunamadı; bağlantı yapılmadı."}
    idx_link = folded.index("youtube link")
    idx_related = folded.index("ilgili video")
    matches = []
    for name, row in rows.items():
        if not str(name).casefold().startswith("uzun_") or len(row) <= idx_related:
            continue
        refs = [x.strip().casefold() for x in str(row[idx_related] or "").replace("\n", ",").split(",") if x.strip()]
        if current in refs:
            matches.append((str(name), row))
    if len(matches) > 1:
        return {"status": "ambiguous", "message": "Birden fazla eşleşme var; yanlış bağlantı kurulmaması için bekliyor."}
    if not matches:
        return {"status": "no_mapping", "message": "Bu Short için ilgili uzun video eşleşmesi yok."}
    name, row = matches[0]
    target = extract_id(row[idx_link] if len(row) > idx_link else "")
    target = target or (uploaded or {}).get(name.casefold(), "")
    if not VIDEO_ID.fullmatch(target or ""):
        return {"status": "waiting_target", "target_name": name,
                "message": "İlgili uzun video henüz yayın kaydında yok; bağlantı beklemede."}
    if target == current_id:
        return {"status": "invalid_target", "message": "Short ve hedef aynı; bağlantı yapılmadı."}
    return {"status": "studio_pending", "short_id": current_id, "target_id": target,
            "target_name": name, "studio_url": f"https://studio.youtube.com/video/{current_id}/edit",
            "message": "İlgili video otomatik bağlanmadı; Studio işlemi ve hedef erişimi doğrulanmalı."}
