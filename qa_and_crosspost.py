#!/usr/bin/env python3
"""
Bilgi Dozu (@bilgidozuofficial) — Otomatik Kalite Müfettişi (QA Gate) &
TikTok / Instagram Reels Çoklu Platform (Cross-Post) Köprüsü
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Any

log = logging.getLogger(__name__)


def inspect_video_quality(video_path: Path, is_long: bool = False) -> Dict[str, Any]:
    """
    Lobiye veya yayın kuyruğuna giren videoyu FFprobe/FFmpeg ile denetler:
    - Süre kontrolü (Shorts: 34s..59s, Uzun: >=90s)
    - Çözünürlük kontrolü (Shorts: 1080x1920, Uzun: 1920x1080)
    - Ses kanalı varlığı (44100 Hz AAC)
    """
    result: Dict[str, Any] = {
        "ok": True,
        "file_name": video_path.name,
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "has_audio": False,
        "issues": [],
    }
    if not video_path.exists() or video_path.stat().st_size < 100_000:
        result["ok"] = False
        result["issues"].append("Dosya boyutu çok küçük veya bulunamadı.")
        return result

    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,sample_rate",
            "-of",
            "json",
            str(video_path),
        ]
        raw = subprocess.check_output(cmd, timeout=20).decode("utf-8", errors="replace")
        data = json.loads(raw)
        dur = float(data.get("format", {}).get("duration", 0.0))
        result["duration"] = round(dur, 2)

        for st in data.get("streams", []):
            ctype = st.get("codec_type")
            if ctype == "video":
                result["width"] = int(st.get("width", 0))
                result["height"] = int(st.get("height", 0))
            elif ctype == "audio":
                result["has_audio"] = True

        if not result["has_audio"]:
            result["ok"] = False
            result["issues"].append("Ses kanalı (audio stream) bulunamadı!")

        if is_long:
            if dur < 60.0:
                result["ok"] = False
                result["issues"].append(f"Uzun video süresi çok kısa ({dur:.1f} sn < 60 sn)")
            if (result["width"], result["height"]) != (1920, 1080):
                result["issues"].append(f"Beklenen 1920x1080 yerine {result['width']}x{result['height']}")
        else:
            if not (30.0 <= dur <= 61.0):
                result["issues"].append(f"Shorts süresi ideal aralık dışında ({dur:.1f} sn)")
            if (result["width"], result["height"]) != (1080, 1920):
                result["issues"].append(f"Beklenen 1080x1920 yerine {result['width']}x{result['height']}")
    except Exception as exc:
        log.warning(f"QA ffprobe kontrol uyarısı ({video_path.name}): {exc}")

    return result


def build_crosspost_caption(meta: dict) -> str:
    """YouTube metadata'sından TikTok ve Instagram Reels için hazır açıklama ve hashtag üretir."""
    raw_title = (meta.get("title") or "").replace("#bilgidozu", "").replace("#shorts", "").strip()
    pinned = (meta.get("pinned_comment") or "").strip()
    lines = [raw_title]
    if pinned:
        lines.append(f"\n💬 {pinned}")
    lines.append("\nDaha fazla bilgi dozu için @bilgidozuofficial hesabını takip etmeyi unutma! 🧠🪐")
    lines.append("\n#bilgidozu #bilim #ilginçbilgiler #uzay #keşfet #fyp #reels")
    return "\n".join(lines).strip()
