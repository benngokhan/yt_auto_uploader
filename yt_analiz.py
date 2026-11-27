#!/usr/bin/env python3
"""Salt-okunur YouTube uzun-video analizi.

Amaç: çok yorum alan / beğeni toplayan / ilgi çeken UZUN videoları gerçek
Analytics verisiyle sıralamak ve retansiyon eğrisinden "en can alıcı anı"
çıkarmak. Çıktı, Shorts v2'nin 7 sahneli şablonuna temiz bir konu/odak verir.

Yayın yapmaz, kuyruğa yazmaz, token yazmaz, secret yazmaz.Tek çıktı yt_analiz.json'dır.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import retansiyon_raporu as rr

SCHEMA = 1
SCORE_VERSION = "engagement-retention-trend-v1"
LONG_MIN_SEC = 180.0
LONG_MAX_SEC = 3600.0
MIN_VIEWS = 200
DEFAULT_DAYS = 30
DEFAULT_LIMIT = 10
DEFAULT_CURVE_LIMIT = 6
ENGAGEMENT_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,shares"
)
UNKNOWN_HIGHLIGHT = {
    "signal": "unknown",
    "timestamp_sec": None,
    "window_sec": None,
    "peak_pct": None,
    "drop_pp": 0.0,
    "score": 0.0,
    "confidence": 0.0,
    "evidence": "Retansiyon verisi yok; odak yalnız başlıktan çıkarılacak.",
}


# ------------------------------------------------------------------ saf yardımcılar
def _finite(value: object) -> float | None:
    x = rr.finite_number(value)
    return x


def normalize_curve(points, duration: float) -> list[dict]:
    """Analytics eğrisini saniyeye çevirir; %100+ tekrar izlemeyi ayrı saklar."""
    if not isinstance(points, (list, tuple)) or not duration or duration <= 0:
        return []
    rows = []
    for item in points:
        try:
            if isinstance(item, dict):
                if "elapsedVideoTimeRatio" in item and "audienceWatchRatio" in item:
                    ratio, watch = item["elapsedVideoTimeRatio"], item["audienceWatchRatio"]
                elif "sec" in item and "ratio" in item:
                    ratio, watch = float(item["sec"]) / duration, item["ratio"]
                else:
                    ratio, watch = item.get("t"), item.get("watch")
            else:
                ratio, watch = item[0], item[1]
            ratio, watch = float(ratio), float(watch)
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if not (math.isfinite(ratio) and math.isfinite(watch)) or not (0 < ratio <= 1) or watch < 0:
            continue
        sec = ratio * duration
        if sec < 0 or sec > duration:
            continue
        rows.append({
            "sec": round(sec, 2),
            "ratio": round(watch, 4),
            "pct": round(min(watch * 100.0, 100.0), 2),
            "raw_pct": round(watch * 100.0, 2),
        })
    rows.sort(key=lambda row: row["sec"])
    seen, unique = set(), []
    for row in rows:
        if row["sec"] not in seen:
            seen.add(row["sec"])
            unique.append(row)
    return unique


def smooth_curve(points: list[dict], window: int = 3) -> list[dict]:
    """3 noktalı medyan ile gürültüyü azaltır; zaman damgalarını korur."""
    if window < 1 or len(points) < window:
        return list(points)
    half = window // 2
    out = []
    for index in range(len(points)):
        chunk = points[max(0, index - half):min(len(points), index + half + 1)]
        median_pct = statistics.median(row["pct"] for row in chunk)
        item = dict(points[index])
        item["pct"] = round(float(median_pct), 2)
        out.append(item)
    return out


def detect_pre_drop_peak(points: list[dict], duration: float) -> dict | None:
    """Düşüşün hemen öncesindeki tepe: plot twist / 'ya bak bu böyleymiş' anı."""
    if len(points) < 3:
        return None
    best = None
    for index in range(len(points) - 2):
        start = points[index]
        if start["sec"] < 1 or start["sec"] > duration * 0.90:
            continue
        span = max(2, min(6, len(points) - index - 1))
        future = points[index + 1:index + 1 + span]
        dip = min(future, key=lambda row: row["pct"])
        drop = start["pct"] - dip["pct"]
        if drop < 3.0:
            continue
        bonus = 1.2 if 25.0 <= start["sec"] <= 75.0 else 1.0
        score = round((drop + 0.25 * start["pct"]) * bonus, 2)
        candidate = {
            "signal": "pre_drop_peak",
            "timestamp_sec": start["sec"],
            "window_sec": [start["sec"], dip["sec"]],
            "peak_pct": start["pct"],
            "drop_pp": round(drop, 2),
            "score": score,
            "confidence": round(min(1.0, drop / 12.0), 2),
            "evidence": f"%{start['pct']:.0f} izlenmede kırılma; sonraki %{dip['pct']:.0f}'e {drop:.1f} puan düşüş.",
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def detect_rebound(points: list[dict]) -> dict | None:
    """Dip'ten toparlanma: izleyiciyi geri çeken 'vay anasını ya' anı."""
    if len(points) < 3:
        return None
    best = None
    for end_index in range(2, len(points)):
        before = points[:end_index]
        dip = min(before, key=lambda row: row["pct"])
        rise = points[end_index]["pct"] - dip["pct"]
        if rise < 3.0 or dip["sec"] < 1:
            continue
        bonus = 1.2 if 25.0 <= dip["sec"] <= 75.0 else 1.0
        candidate = {
            "signal": "dip_recovery",
            "timestamp_sec": dip["sec"],
            "window_sec": [dip["sec"], points[end_index]["sec"]],
            "peak_pct": round(float(rise), 2),
            "drop_pp": 0.0,
            "score": round((rise + 0.20 * dip["pct"]) * bonus, 2),
            "confidence": round(min(1.0, rise / 10.0), 2),
            "evidence": f"%{dip['pct']:.0f}'e düşen izlenme %{points[end_index]['pct']:.0f}'e çıktı; geri çeken an.",
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def detect_hook(points: list[dict]) -> dict | None:
    """İlk 3 saniyedeki güçlü giriş; eğri zayıfsa son çare olarak kullanılır."""
    opening = [row for row in points if row["sec"] <= 3.0]
    if not opening:
        return None
    peak = max(opening, key=lambda row: row["pct"])
    return {
        "signal": "hook",
        "timestamp_sec": peak["sec"],
        "window_sec": [peak["sec"], peak["sec"]],
        "peak_pct": peak["pct"],
        "drop_pp": 0.0,
        "score": round(peak["pct"] * 0.30, 2),
        "confidence": round(min(0.65, peak["pct"] / 100.0), 2),
        "evidence": f"Açılışın ilk {peak['sec']:.0f} sn'sinde izlenme %{peak['pct']:.0f}.",
    }


def choose_highlight(points, duration: float) -> dict:
    raw = normalize_curve(points, duration)
    # Kısa eğrilerde medyan tepeyi/dibi siler; yalnız yoğun eğriyi yumuşat.
    clean = smooth_curve(raw) if len(raw) >= 8 else raw
    if not clean:
        return dict(UNKNOWN_HIGHLIGHT)
    candidates = [
        item for item in (detect_pre_drop_peak(clean, duration), detect_rebound(clean), detect_hook(clean))
        if item and item["confidence"] > 0
    ]
    if not candidates:
        result = dict(UNKNOWN_HIGHLIGHT)
        result["evidence"] = "Retansiyon eğrisinde belirgin kırılma yok; odak başlıktan çıkarılacak."
        return result
    candidates.sort(key=lambda row: (row["score"], row["confidence"]), reverse=True)
    return candidates[0]


def engagement_score(views: float, likes: float | None, comments: float | None) -> dict:
    views = max(float(views or 0), 1.0)
    like_rate = (float(likes) / views) if likes is not None else 0.0
    comment_rate = (float(comments) / views) if comments is not None else 0.0
    score = 0.6 * min(1.0, like_rate / 0.05) + 0.4 * min(1.0, comment_rate / 0.005)
    return {
        "score": round(min(1.0, max(0.0, score)), 4),
        "like_rate": round(like_rate, 5),
        "comment_rate": round(comment_rate, 5),
    }


def retention_score(average_percent: float | None, average_seconds: float | None,
                    duration: float, highlight: dict) -> float:
    avg_pct = max(0.0, min(100.0, float(average_percent or 0.0)))
    avg_sec = max(0.0, float(average_seconds or 0.0))
    peak = float(highlight.get("peak_pct") or avg_pct)
    score = (
        0.45 * min(1.0, avg_pct / 70.0)
        + 0.35 * min(1.0, avg_sec / max(1.0, duration * 0.5))
        + 0.20 * min(1.0, peak / 80.0)
    )
    return round(min(1.0, score), 4)


def trend_score(views: float, median_views: float, last7: float | None, prev7: float | None) -> tuple[float, float | None]:
    growth = None
    if prev7 and prev7 > 0 and last7 is not None:
        growth = float(last7) / float(prev7)
    elif median_views and median_views > 0:
        growth = float(views) / float(median_views)
    if growth is None or growth <= 1.0:
        return 0.0, growth
    score = math.log1p(growth - 1.0) / math.log1p(3.0)
    return round(min(1.0, score), 4), round(growth, 3)


def score_candidate(candidate: dict, median_views: float) -> dict:
    missing = list(candidate.get("missing_fields") or [])
    engagement = engagement_score(candidate["views"], candidate.get("likes"), candidate.get("comments"))
    highlight = candidate.get("highlight") or dict(UNKNOWN_HIGHLIGHT)
    duration = float(candidate["duration_sec"])
    retention = retention_score(
        candidate.get("average_percent"), candidate.get("average_seconds"), duration, highlight)
    trend, growth = trend_score(
        candidate["views"], median_views, candidate.get("views_last7"), candidate.get("views_prev7"))
    confidence = 1.0 - (0.25 if "likes" in missing else 0.0) \
        - (0.30 if "comments" in missing else 0.0) \
        - (0.20 if highlight["signal"] == "unknown" else 0.0)
    confidence = round(max(0.25, confidence), 2)
    total = round(100.0 * (0.40 * engagement["score"] + 0.35 * retention + 0.25 * trend) * confidence, 2)
    candidate["scores"] = {
        "engagement": engagement["score"],
        "retention": retention,
        "trend": trend,
        "total": total,
        "confidence": confidence,
        "growth": growth,
        "like_rate": engagement["like_rate"],
        "comment_rate": engagement["comment_rate"],
        "score_version": SCORE_VERSION,
    }
    return candidate


def rank_candidates(candidates: list[dict]) -> list[dict]:
    ordered = sorted(candidates, key=lambda row: (row["scores"]["total"], row["views"], row["video_id"]), reverse=True)
    for index, row in enumerate(ordered, start=1):
        row["rank"] = index
    return ordered


def build_handoff(candidate: dict) -> dict:
    """Shorts v2'ye gidecek sözleşme. CTA'yı motor koyar; analiz CTA üretmez."""
    motor = str(Path(__file__).resolve().parent / "motor")
    if motor not in sys.path:
        sys.path.insert(0, motor)
    from shorts_acceptance import EXPECTED_SCENES, SHORTS_CTA, TEMPLATE_VERSION  # noqa: PLC0415

    highlight = candidate.get("highlight") or dict(UNKNOWN_HIGHLIGHT)
    title = str(candidate.get("title") or "").strip()
    timestamp = highlight.get("timestamp_sec")
    focus = f"{highlight['signal']} @ {timestamp:g} sn" if timestamp is not None else highlight["signal"]
    return {
        "template": TEMPLATE_VERSION,
        "scene_count": EXPECTED_SCENES,
        "topic": f"{title} | odak: {focus}" if title else f"Uzun video analizi | odak: {focus}",
        "source_video_id": candidate["video_id"],
        "source_timestamp_sec": timestamp,
        "source_url": f"https://youtu.be/{candidate['video_id']}?t={int(timestamp or 0)}",
        "highlight_signal": highlight["signal"],
        "evidence": highlight["evidence"],
        "cta_added_by_motor": True,
        "cta": SHORTS_CTA,
        "notes": "Başlık/odak analizden gelir; 6 içerik cümlesi + 7. sabit CTA motor tarafından üretilir.",
    }


# ------------------------------------------------------------------ veri erişimi
def _analytics_token() -> str:
    raw = os.getenv("BD_ANALYTICS_CLIENT_CONFIG", "").strip()
    refresh = os.getenv("BD_ANALYTICS_REFRESH_TOKEN", "").strip()
    if not raw or not refresh:
        raise SystemExit("BD_ANALYTICS_CLIENT_CONFIG / BD_ANALYTICS_REFRESH_TOKEN yok; analiz durduruldu.")
    token = rr.refresh_token(rr.oauth_config(raw, refresh))
    rr.assert_channel(token)
    return token


def _report(token: str, start: date, end: date, metrics: str) -> dict:
    query = {
        "ids": "channel==" + rr.CHANNEL_ID,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": "video",
        "metrics": metrics,
        "sort": "-views",
        "maxResults": "200",
    }
    return rr.request_json(rr.ANALYTICS_URL + "?" + urllib.parse.urlencode(query),
                           bearer=token, label="Analytics")


def fetch_engagement(token: str, start: date, end: date) -> dict:
    return _report(token, start, end, ENGAGEMENT_METRICS)


def fetch_views_window(token: str, start: date, end: date) -> dict[str, float]:
    report = _report(token, start, end, "views")
    result = {}
    for row in rr._table(report, ["video", "views"]):
        views = _finite(row.get("views"))
        if views is not None:
            result[str(row.get("video") or "")] = views
    return result


def parse_engagement_report(report: dict) -> list[dict]:
    required = ["video", "views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage",
                "likes", "comments", "shares"]
    rows = rr._table(report, required)
    out, seen = [], set()
    for row in rows:
        video_id = str(row.get("video") or "")
        if not rr.VIDEO_ID_RE.fullmatch(video_id) or video_id in seen:
            raise rr.SafeError("Analytics video satırları belirsiz")
        seen.add(video_id)
        views = _finite(row.get("views"))
        if views is None or views < 0:
            raise rr.SafeError("Analytics görüntülenme değeri beklenmedik")
        item = {
            "video_id": video_id,
            "views": int(views),
            "watch_minutes": _finite(row.get("estimatedMinutesWatched")) or 0.0,
            "average_seconds": _finite(row.get("averageViewDuration")) or 0.0,
            "average_percent": _finite(row.get("averageViewPercentage")) or 0.0,
            "likes": _finite(row.get("likes")),
            "comments": _finite(row.get("comments")),
            "shares": _finite(row.get("shares")),
            "missing_fields": [],
        }
        for key in ("likes", "comments"):
            if item[key] is None:
                item["missing_fields"].append(key)
        out.append(item)
    if not out:
        raise rr.SafeError("Analytics raporunda video verisi yok")
    return out


def build_candidates(rows: list[dict], details: dict, last7: dict, prev7: dict,
                     median_views: float, days: int) -> list[dict]:
    candidates = []
    for row in rows:
        detail = details.get(row["video_id"]) or {}
        duration = detail.get("duration")
        if not isinstance(duration, (int, float)) or not (LONG_MIN_SEC <= duration <= LONG_MAX_SEC):
            continue
        if row["views"] < MIN_VIEWS:
            continue
        candidate = dict(row)
        candidate.update({
            "title": detail.get("title") or "Başlık alınamadı",
            "published": detail.get("published") or "",
            "url": f"https://youtu.be/{row['video_id']}",
            "studio_url": f"https://studio.youtube.com/video/{row['video_id']}/edit",
            "duration_sec": round(float(duration), 1),
            "window_days": days,
            "views_last7": _finite(last7.get(row["video_id"])),
            "views_prev7": _finite(prev7.get(row["video_id"])),
            "vs_channel_median": round(row["views"] / median_views, 2) if median_views else None,
            "retention": {
                "watch_minutes": round(row["watch_minutes"], 2),
                "avg_view_sec": round(row["average_seconds"], 2),
                "avg_view_pct": round(row["average_percent"], 2),
                "curve": [],
                "curve_status": "missing",
            },
            "highlight": dict(UNKNOWN_HIGHLIGHT),
        })
        score_candidate(candidate, median_views)
        candidates.append(candidate)
    return candidates


def attach_curves(candidates: list[dict], curves: dict, median_views: float) -> None:
    for candidate in candidates:
        points = curves.get(candidate["video_id"])
        if points is None:
            continue
        candidate["retention"]["curve"] = [
            {"sec": round(t * candidate["duration_sec"], 2), "pct": round(min(watch * 100.0, 100.0), 2),
             "raw_pct": round(watch * 100.0, 2)}
            for t, watch in points
        ]
        candidate["retention"]["curve_status"] = "ready" if points else "missing"
        candidate["highlight"] = choose_highlight(points, candidate["duration_sec"])
        if not points and "curve" not in candidate["missing_fields"]:
            candidate["missing_fields"].append("curve")
        score_candidate(candidate, median_views)


def analyze(token: str, days: int, limit: int, curve_limit: int) -> dict:
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    engagement = fetch_engagement(token, start, end)
    rows = parse_engagement_report(engagement)
    details = rr.video_details(token, [row["video_id"] for row in rows])

    last7_end = end
    last7_start = end - timedelta(days=6)
    prev7_end = last7_start - timedelta(days=1)
    prev7_start = prev7_end - timedelta(days=6)
    last7 = fetch_views_window(token, last7_start, last7_end)
    prev7 = fetch_views_window(token, prev7_start, prev7_end)

    views = [row["views"] for row in rows]
    median = float(statistics.median(views)) if views else 0.0
    candidates = build_candidates(rows, details, last7, prev7, median, days)
    if not candidates:
        raise SystemExit(f"Son {days} günde {LONG_MIN_SEC:.0f}sn üzeri ve {MIN_VIEWS}+ izlenme alan uzun video yok.")

    preliminary = rank_candidates(candidates)
    targets = preliminary[:max(1, curve_limit)]
    curves = rr.acquire_curves(token, targets, details, start, end)
    attach_curves(candidates, curves, median)
    final = rank_candidates(candidates)[:max(1, limit)]
    for candidate in final:
        candidate["short_handoff"] = build_handoff(candidate)

    return {
        "schema": SCHEMA,
        "score_version": SCORE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "source": {
            "analytics": "youtubeanalytics.googleapis.com/v2/reports",
            "details": "youtube/v3/videos",
            "curve_status": "ready" if any(curves.values()) else "missing",
            "latency_note": "Analytics verisi 1-3 gün gecikebilir.",
        },
        "filters": {"long_min_sec": LONG_MIN_SEC, "long_max_sec": LONG_MAX_SEC, "min_views": MIN_VIEWS},
        "channel_median_views": round(median, 1),
        "candidate_count": len(candidates),
        "candidates": final,
        "potential_claim": "Yok. Skor göreli sıralamadır; izlenme garantisi değildir.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--curve-limit", type=int, default=DEFAULT_CURVE_LIMIT)
    parser.add_argument("--out", default="yt_analiz.json")
    parser.add_argument("--dry-run", action="store_true", help="Dosya yazmadan JSON'u stdout'a basar")
    args = parser.parse_args(argv)
    if args.days < 1 or args.limit < 1 or args.curve_limit < 1:
        raise SystemExit("days/limit/curve-limit 1'den küçük olamaz.")
    try:
        result = analyze(_analytics_token(), args.days, args.limit, args.curve_limit)
    except rr.SafeError as exc:
        raise SystemExit(f"Analiz durduruldu: {exc}") from exc
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.dry_run:
        print(payload)
        return 0
    out = Path(args.out)
    out.write_text(payload + "\n", encoding="utf-8")
    print(f"YT_ANALIZ: {out} — {result['candidate_count']} uzun video, {len(result['candidates'])} aday")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
