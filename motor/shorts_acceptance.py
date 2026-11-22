"""Fail-closed acceptance gates for the isolated Shorts v2 production path.

Legacy Shorts configuration is deliberately not validated against v2's fixed
mix/timing contract. This module does not publish or upload anything.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

SHORTS_VERSION = "shorts-v2.4"
TEMPLATE_VERSION = "2.4-four-image-loop"
FORMAT_VERSION = "v2"
EXPECTED_SCENES = 4                 # Four unique stills/assets.
EXPECTED_NARRATION_BEATS = 5        # Hook, answer intro, two details, loop question.
EXPECTED_TIMELINE_BEATS = 5         # The final beat reuses image 1.
V2_VISUAL_SEQUENCE = (0, 1, 2, 3, 0)
V2_CTA_OVERLAY_TEXT = "Takip et"
V2_CTA_OVERLAY_BEAT_INDEX = 1       # Answer begins on visual 2.
V2_VOICE_PROVIDER = "gemini_tts"
V2_VOICE_ID = "Charon"
V2_VOICE_GENERATION = "motor.tts.uret"
V2_VOICE_PROVENANCE_STATUS = "local_tts_call_unverified"
SHORTS_CTA = "Daha fazla Bilgi Dozu için takip et!"  # legacy-only spoken CTA
MIN_SCENE_SECONDS = 2.0
MAX_SCENE_SECONDS = 8.0
MIN_VIDEO_SECONDS = 15.0
TARGET_VIDEO_SECONDS = 20.0
TARGET_MIN_VIDEO_SECONDS = 18.0
TARGET_MAX_VIDEO_SECONDS = 22.0
HARD_MAX_VIDEO_SECONDS = 25.0
MIN_NARRATION_WORDS = 35
MAX_NARRATION_WORDS = 45
MIN_AVG_BRIGHTNESS = 100.0
# Live Gemini Vision image/text similarity score, not a Pexels API score.
SEMANTIC_THRESHOLD = 0.62
LOCKED_MIX_TIMING = {
    "intro_lead": 0.0,
    "sentence_pause": 0.12,
    "outro_hold": 0.0,
}


class ShortsAcceptanceError(ValueError):
    """An input or artifact does not satisfy the Shorts v2 production contract."""


def _finite_float(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ShortsAcceptanceError(f"{name} sayı olmalı") from exc
    if not math.isfinite(result):
        raise ShortsAcceptanceError(f"{name} sonlu bir sayı olmalı")
    return result


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


_EXTREME_CLAIM_PATTERNS = {
    "absolute_claim": re.compile(
        r"\b(?:asla|hiçbir zaman|her zaman|kesinlikle|mutlak(?:a)?|tek gerçek|yüzde yüz|%\s*100)\b",
        re.IGNORECASE,
    ),
    "unsupported_superlative": re.compile(
        r"\ben\s+(?:büyük|küçük|hızlı|yavaş|tehlikeli|sıcak|soğuk|derin|yaşlı|güçlü|zayıf|zeki)\b",
        re.IGNORECASE,
    ),
    "sensational_or_medical_claim": re.compile(
        r"\b(?:mucize|ölümcül|öldür(?:ür|üyor|dü)|kanser\s+yap(?:ar|ıyor)|şoke\s+eden|şok\s+edici)\b",
        re.IGNORECASE,
    ),
}
_UNSUPPORTED_NUMERIC_PATTERN = re.compile(
    r"\b\d+(?:[.,]\d+)?\b|\b(?:iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|yirmi|otuz|kırk|"
    r"elli|altmış|yetmiş|seksen|doksan|yüz|bin|milyon|milyar)\b|"
    r"\bbir\s*(?:%|yüzde|derece|saniye|dakika|saat|gün|yıl|metre|kilometre|kat|gram|kilogram|litre)\b",
    re.IGNORECASE,
)
_INTRO_PATTERN = re.compile(
    r"^\s*(?:merhaba|selam|hoş\s+geldin|bu\s+videoda|bugün\s+(?:sizlere|size)|"
    r"kanalımıza|bilgi\s+dozu|şimdi\s+birlikte)\b",
    re.IGNORECASE,
)
_FILLER_PATTERN = re.compile(
    r"\b(?:bunu\s+biliyor\s+muydun|çok\s+ilginç|şaşırtıcı\s+ama\s+gerçek|"
    r"gördüğün\s+gibi|sonuç\s+olarak|işte\s+bu|şimdi\s+birlikte)\b",
    re.IGNORECASE,
)
_AUDIO_CUE_PATTERN = re.compile(r"\[\s*(?:m[uü]zik|ses|music|sound|sfx)\b[^\]]*\]", re.IGNORECASE)
_UNVERIFIED_INSTITUTION_PATTERN = re.compile(
    r"\b(?:NASA|Boeing|Harvard(?:\s+University)?|Stanford(?:\s+University)?|"
    r"Oxford(?:\s+University)?|Cambridge(?:\s+University)?|MIT|TÜBİTAK|CERN|"
    r"WHO|World\s+Health\s+Organization|Mayo\s+Clinic|Nobel)\b",
    re.IGNORECASE,
)
_RESCUE_TEXT_PATTERN = re.compile(r"görsel(?:ler)?\s+temsildir|temsil[iî]\s+görsel", re.IGNORECASE)
_LOOP_STOPWORDS = {
    "acaba", "ama", "artık", "aslında", "bazen", "bazı", "bir", "bu", "da", "de", "diye",
    "en", "gibi", "için", "ile", "işte", "ki", "mu", "mü", "mi", "mı", "nasıl", "neden",
    "o", "ve", "veya", "çok", "daha", "şu", "sonunda", "gerçekten", "çünkü", "yani",
}
_TRUSTED_SOURCE_DOMAINS = (
    "nasa.gov", "boeing.com", "doi.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
    "nature.com", "science.org", "aaas.org", "nejm.org", "thelancet.com", "pnas.org",
    "aps.org", "arxiv.org", "who.int", "cdc.gov", "nih.gov", "esa.int",
)
_QUESTION_WORDS = {"neden", "nasıl", "niçin", "ne", "kaç", "hangi", "mı", "mi", "mu", "mü"}


def _words(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", str(text or "")).lower()
    return re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)


def topic_score(topic: str, verified_source_url: str = "") -> dict:
    """Score topic risk, not truth: unsupported absolutes/metrics are penalized."""
    clean = " ".join(str(topic or "").split())
    flags = [name for name, pattern in _EXTREME_CLAIM_PATTERNS.items() if pattern.search(clean)]
    if _UNSUPPORTED_NUMERIC_PATTERN.search(clean):
        flags.append("quantified_claim")
    source_available = _verified_source_url(verified_source_url)
    score = max(0, 100 - 35 * len(flags))
    accepted = not flags or source_available
    reasons = [*flags]
    if flags and source_available:
        reasons.append("allowlisted_https_source_present_claim_still_needs_manual_relevance_review")
    return {
        "topic": clean,
        "score": score,
        "accepted": accepted,
        "risk_flags": flags,
        "source_url_present": source_available,
        "reasons": reasons,
    }


def select_scored_topic(topic: str, alternatives: list[str] | None = None) -> dict:
    """Keep the supplied subject when safe; otherwise choose a caller-provided safe alternative."""
    candidates = [topic, *(alternatives or [])]
    seen: set[str] = set()
    history = []
    for candidate in candidates:
        clean = " ".join(str(candidate or "").split())
        if not clean or clean.casefold() in seen:
            continue
        seen.add(clean.casefold())
        scored = topic_score(clean)
        history.append(scored)
        if scored["accepted"]:
            return {**scored, "attempts": history}
    raise ShortsAcceptanceError(
        "Konu filtresi doğrulanmamış mutlak/sayısal iddiayı reddetti; kaynak doğrulanmadan üretim yok. "
        + "; ".join(f"{x['topic']!r}={x['risk_flags']}" for x in history)
    )


def _verified_source_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and any(host == domain or host.endswith("." + domain)
                                             for domain in _TRUSTED_SOURCE_DOMAINS)


def validate_title_cover(title: str, cover_lines: list[str], topic: str = "") -> dict:
    clean_title = " ".join(str(title or "").split())
    lines = [" ".join(str(line or "").split()) for line in cover_lines or []]
    title_words = set(_words(clean_title)) - _LOOP_STOPWORDS
    cover_words = set(_words(" ".join(lines))) - _LOOP_STOPWORDS
    cover_text = " ".join(lines)
    if not clean_title or len(clean_title) > 70 or not clean_title.endswith("?"):
        raise ShortsAcceptanceError("Yayın başlığı 70 karakteri aşmayan tek soru olmalı")
    if not _QUESTION_WORDS.intersection(_words(clean_title)):
        raise ShortsAcceptanceError("Yayın başlığı açık bir Türkçe soru sözcüğü içermeli")
    if len(lines) not in (2, 3) or any(not line for line in lines):
        raise ShortsAcceptanceError("Kapak tek soruyu 2–3 dolu satırda taşımalı")
    if any(len(line) > 18 or len(line) < 3 for line in lines):
        raise ShortsAcceptanceError("Kapak satırları 3–18 karakter aralığında olmalı; taşma riski")
    if any(line != line.upper() for line in lines):
        raise ShortsAcceptanceError("Kapak satırları TAM BÜYÜK HARF olmalı")
    if any(any(mark in line for mark in "?!.:") for line in lines[:-1]) or not lines[-1].endswith("?"):
        raise ShortsAcceptanceError("Kapak tek soru olmalı; soru işareti yalnız son satırda yer alır")
    if not (title_words & cover_words):
        raise ShortsAcceptanceError("Kapak metni yayın başlığıyla aynı konuya dönmüyor")
    if topic:
        topic_words = {w for w in _words(topic) if len(w) >= 4 and w not in _LOOP_STOPWORDS}
        if topic_words and not any(
            any(t.startswith(c[:4]) or c.startswith(t[:4]) for t in title_words)
            for c in topic_words for t in title_words if min(len(c), len(t)) >= 4
        ):
            raise ShortsAcceptanceError("Soru başlığı verilen konuya bağlı değil")
    return {"title": clean_title, "cover_lines": lines, "cover_text": cover_text}


def validate_hook_timing(first_scene_start: object, first_word_start: object) -> None:
    scene_start = _finite_float(first_scene_start, "İlk sahne başlangıcı")
    word_start = _finite_float(first_word_start, "Hook ilk kelime başlangıcı")
    if abs(scene_start) > 1e-6 or word_start < 0 or word_start > 0.15:
        raise ShortsAcceptanceError("Hook 0. saniyede başlamalı; ilk kelime gecikmesi en çok 0.15s")


def _anchor_in_words(anchor: str, words: list[str]) -> bool:
    target = _words(anchor)
    if not target:
        return False
    for token in words:
        for part in target:
            if len(part) >= 3 and len(token) >= 3:
                prefix = min(4, len(part), len(token))
                if token.startswith(part[:prefix]) or part.startswith(token[:prefix]):
                    return True
    return False


def validate_script(
    scenes: list[dict],
    topic: str = "",
    *,
    verified_source_url: str = "",
    title: str = "",
    cover_lines: list[str] | None = None,
    loop_anchor: str = "",
) -> dict:
    if not isinstance(scenes, list) or len(scenes) != EXPECTED_NARRATION_BEATS:
        raise ShortsAcceptanceError(
            f"Shorts v2 tam {EXPECTED_NARRATION_BEATS} anlatım vuruşu ister (4 görsel + kapanış dönüşü)"
        )
    narration: list[str] = []
    per_scene_words: list[list[str]] = []
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise ShortsAcceptanceError(f"Anlatım vuruşu {index} nesne olmalı")
        line = " ".join(str(scene.get("ses") or "").split())
        if not line:
            raise ShortsAcceptanceError(f"Anlatım vuruşu {index} boş")
        if _AUDIO_CUE_PATTERN.search(line):
            raise ShortsAcceptanceError(f"Anlatım vuruşu {index} anlatımında [müzik]/[ses] etiketi var")
        if SHORTS_CTA.casefold() in line.casefold() or re.search(r"\b(?:takip\s+et|abone\s+ol)\b", line, re.IGNORECASE):
            raise ShortsAcceptanceError("CTA yalnız ikinci görselde yazı katmanı olmalı; seslendirmeye eklenemez")
        if _FILLER_PATTERN.search(line):
            raise ShortsAcceptanceError(f"Anlatım vuruşu {index} yalnız dolgu/boş sahne ifadesi içeriyor")
        if re.search(r"[.!?]\s+\S", line):
            raise ShortsAcceptanceError(f"Anlatım vuruşu {index} tek kısa cümle olmalı")
        words = _words(line)
        if not 3 <= len(words) <= 10:
            raise ShortsAcceptanceError(f"Anlatım vuruşu {index} 3–10 kelimelik tek kısa cümle olmalı")
        narration.append(line)
        per_scene_words.append(words)
    if _INTRO_PATTERN.search(narration[0]):
        raise ShortsAcceptanceError("Hook ilk saniyede başlamalı; selamlama veya intro kullanılamaz")
    if len(per_scene_words[0]) < 3 or not narration[0].rstrip().endswith("?"):
        raise ShortsAcceptanceError("İlk anlatım vuruşu 0. saniyede başlayan kısa soru-hook olmalı")
    if not narration[-1].rstrip().endswith("?"):
        raise ShortsAcceptanceError("Son anlatım vuruşu açılış sorusuna bağlanan kısa loop sorusu olmalı")

    all_text = " ".join(narration)
    all_words = _words(all_text)
    if not MIN_NARRATION_WORDS <= len(all_words) <= MAX_NARRATION_WORDS:
        raise ShortsAcceptanceError(
            f"Anlatım {MIN_NARRATION_WORDS}–{MAX_NARRATION_WORDS} kelime olmalı; bulundu: {len(all_words)}"
        )
    if _RESCUE_TEXT_PATTERN.search(all_text):
        raise ShortsAcceptanceError("'Görsel temsildir' kurtarma metni anlatımda kullanılamaz")
    if _verified_source_url(verified_source_url) is False and (
        _UNVERIFIED_INSTITUTION_PATTERN.search(all_text) or _UNSUPPORTED_NUMERIC_PATTERN.search(all_text)
    ):
        raise ShortsAcceptanceError("Kaynak URL'si olmadan kurum veya ölçü/sayı iddiası kullanılamaz")
    risk = topic_score(str(topic or ""), verified_source_url) if topic else {"accepted": True, "score": 100, "risk_flags": []}
    narration_risk = topic_score(all_text, verified_source_url)
    if not risk["accepted"]:
        raise ShortsAcceptanceError(f"Konu aşırı/ölçülü iddia filtresinden geçmedi: {risk['risk_flags']}")
    if not narration_risk["accepted"]:
        raise ShortsAcceptanceError(
            f"Anlatım doğrulanmamış aşırı/sayısal iddia filtresinden geçmedi: {narration_risk['risk_flags']}"
        )

    anchor = " ".join(str(loop_anchor or "").split())
    first_words, last_words = per_scene_words[0], per_scene_words[-1]
    if not anchor:
        shared = [w for w in first_words if len(w) >= 4 and w not in _LOOP_STOPWORDS
                  and _anchor_in_words(w, last_words)]
        anchor = shared[0] if shared else ""
    if not anchor or not _anchor_in_words(anchor, first_words) or not _anchor_in_words(anchor, last_words):
        raise ShortsAcceptanceError("Son loop sorusu açılış hook'undaki ana kavramı yeniden anmalı")

    title_info = None
    if title or cover_lines is not None:
        title_info = validate_title_cover(title, cover_lines or [], topic=topic)
        title_risk = topic_score(title, verified_source_url)
        cover_risk = topic_score(" ".join(cover_lines or []), verified_source_url)
        if not title_risk["accepted"] or not cover_risk["accepted"]:
            raise ShortsAcceptanceError("Başlık/kapak doğrulanmamış ekstrem iddia filtresinden geçmedi")
    return {
        "topic": str(topic or "").strip(),
        "scene_count": EXPECTED_SCENES,
        "narration_beat_count": len(scenes),
        "narration": " ".join(narration),
        "word_count": len(all_words),
        "hook": narration[0],
        "loop_question": narration[-1],
        "loop_anchor": anchor,
        "title_cover": title_info,
        "topic_filter": risk,
        "narration_filter": narration_risk,
    }

def validate_visual_sequence(sequence: object) -> list[int]:
    """Only four unique visuals are permitted; the last beat must reuse visual 1."""
    if not isinstance(sequence, list) or len(sequence) != EXPECTED_TIMELINE_BEATS:
        raise ShortsAcceptanceError(
            f"Görsel zaman çizelgesi tam {EXPECTED_TIMELINE_BEATS} vuruş içermeli"
        )
    try:
        values = [int(value) for value in sequence]
    except (TypeError, ValueError) as exc:
        raise ShortsAcceptanceError("Görsel sıra indeksi tam sayı olmalı") from exc
    if tuple(values) != V2_VISUAL_SEQUENCE:
        raise ShortsAcceptanceError("Görsel sırası 1-2-3-4-1 olmalı; kapanış ilk görseli kullanmalı")
    return values


def validate_scene_intervals(intervals: list[dict | tuple | list]) -> list[dict]:
    if not isinstance(intervals, list) or len(intervals) != EXPECTED_TIMELINE_BEATS:
        raise ShortsAcceptanceError(
            f"V2 zaman çizelgesi tam {EXPECTED_TIMELINE_BEATS} görsel vuruşu ister"
        )
    validated: list[dict] = []
    previous_end = None
    for index, interval in enumerate(intervals, start=1):
        if isinstance(interval, dict):
            start, end = interval.get("start"), interval.get("end")
        elif isinstance(interval, (tuple, list)) and len(interval) == 2:
            start, end = interval
        else:
            raise ShortsAcceptanceError(f"Vuruş {index} aralığı start/end içermeli")
        start = _finite_float(start, f"Vuruş {index} start")
        end = _finite_float(end, f"Vuruş {index} end")
        duration = end - start
        if duration < MIN_SCENE_SECONDS or duration > MAX_SCENE_SECONDS:
            raise ShortsAcceptanceError(
                f"Vuruş {index} {duration:.3f}s; izin verilen aralık {MIN_SCENE_SECONDS:.1f}–{MAX_SCENE_SECONDS:.1f}s"
            )
        if start < 0 or (index == 1 and abs(start) > 1e-6):
            raise ShortsAcceptanceError(f"Vuruş {index} aralığı negatif veya 0 saniyede başlamıyor")
        if previous_end is not None and abs(start - previous_end) > 1e-6:
            raise ShortsAcceptanceError(f"Vuruş {index} aralığı önceki vuruşla bitişik değil")
        validated.append({"start": start, "end": end, "duration": duration})
        previous_end = end
    validate_duration(previous_end or 0.0)
    return validated



def validate_v2_timeline(intervals: list[dict], names: list[str]) -> list[dict]:
    validated = validate_scene_intervals(intervals)
    if not isinstance(names, list) or len(names) != EXPECTED_SCENES or len(set(names)) != EXPECTED_SCENES:
        raise ShortsAcceptanceError("Dört benzersiz görsel dosyası gerekli")
    if any(not isinstance(row, dict) for row in intervals):
        raise ShortsAcceptanceError("V2 zaman çizelgesi dosya ve CTA katmanı içermeli")
    expected = [names[i] for i in V2_VISUAL_SEQUENCE]
    if [row.get("file") for row in intervals] != expected:
        raise ShortsAcceptanceError("Zaman çizelgesinde görsel sırası 1-2-3-4-1 olmalı")
    for i, row in enumerate(intervals):
        expected_overlay = V2_CTA_OVERLAY_TEXT if i == V2_CTA_OVERLAY_BEAT_INDEX else None
        if row.get("cta_overlay") != expected_overlay:
            raise ShortsAcceptanceError("Takip et yalnız ikinci görsel vuruşunda görünmeli")
    return validated

def validate_duration(duration_seconds: object) -> float:
    """Enforce the requested 15–25s band; 20s is the nominal target."""
    duration = _finite_float(duration_seconds, "MP4 süresi")
    if duration < MIN_VIDEO_SECONDS:
        raise ShortsAcceptanceError(
            f"MP4 süresi {duration:.3f}s; minimum {MIN_VIDEO_SECONDS:.1f}s (hedef yaklaşık {TARGET_VIDEO_SECONDS:.0f}s)"
        )
    if duration > HARD_MAX_VIDEO_SECONDS:
        raise ShortsAcceptanceError(
            f"MP4 süresi {duration:.3f}s; sert üst sınır {HARD_MAX_VIDEO_SECONDS:.1f}s"
        )
    return duration


def duration_in_target_band(duration_seconds: object) -> bool:
    duration = validate_duration(duration_seconds)
    return TARGET_MIN_VIDEO_SECONDS <= duration <= TARGET_MAX_VIDEO_SECONDS

def validate_locked_mix_timing(config: dict) -> None:
    """Apply the locked timing only to v2; legacy mix settings remain configurable."""
    for key, expected in LOCKED_MIX_TIMING.items():
        actual = _finite_float(config.get(key, expected), key)
        if abs(actual - expected) > 1e-6:
            raise ShortsAcceptanceError(f"V2 {key} kilidi uyuşmuyor: {actual} != {expected}")


def _validate_visual_report(report: dict) -> list[dict]:
    if not isinstance(report, dict) or report.get("mode") != "production_v2" or report.get("generation") != "live":
        raise ShortsAcceptanceError("Görsel raporu canlı production_v2 kökenini doğrulamıyor")
    if report.get("fallback_policy") != "fail_closed":
        raise ShortsAcceptanceError("V2 görsel yedek politikası fail-closed olmalı")
    if _finite_float(report.get("semantic_threshold"), "Görsel semantik eşiği") != SEMANTIC_THRESHOLD:
        raise ShortsAcceptanceError("Canlı Gemini Vision eşiği raporda uyuşmuyor")
    rows = report.get("scenes")
    if not isinstance(rows, list) or len(rows) != EXPECTED_SCENES:
        raise ShortsAcceptanceError(f"Canlı görsel raporu tam {EXPECTED_SCENES} benzersiz görsel içermeli")
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        selected = row.get("selected") if isinstance(row, dict) else None
        if not isinstance(selected, dict):
            raise ShortsAcceptanceError(f"Görsel sahne {index} seçimi eksik")
        if selected.get("provider") != "pexels":
            raise ShortsAcceptanceError(f"Görsel sahne {index} canlı Pexels kaynağı değil")
        uid = str(selected.get("uid") or "")
        if not uid or uid in seen:
            raise ShortsAcceptanceError("V2 sahne görselleri benzersiz Pexels UID taşımalı")
        seen.add(uid)
        url = str(selected.get("source_page_url") or "")
        if urlparse(url).hostname not in {"pexels.com", "www.pexels.com"}:
            raise ShortsAcceptanceError(f"Görsel sahne {index} Pexels kaynak URL'si doğrulanamadı")
        score_origin = selected.get("score_origin")
        if score_origin == "live_gemini_vision":
            score = _finite_float(selected.get("semantic_similarity"), f"Sahne {index} semantik skor")
            if score < SEMANTIC_THRESHOLD or score > 1.0:
                raise ShortsAcceptanceError(f"Görsel sahne {index} canlı Gemini Vision eşiğini geçmedi")
        else:
            raise ShortsAcceptanceError(f"Görsel sahne {index} skor kökeni doğrulanamadı")
    return rows


def validate_v2_production_context(work_dir: str | Path, config: dict) -> dict | None:
    """Validate the local Gemini Natural TTS/Charon path and artifact hashes.

    Any partial/mismatched v2 markers fail closed instead of falling through to
    the legacy renderer/TTS. Audio and images are bound to local SHA256
    manifests; provider/model identity records the configured local TTS call,
    not a cryptographically signed statement from the provider.
    """
    marker_keys = {"format_version", "shorts_version", "template_version", "production_mode"}
    present = {key for key in marker_keys if key in config}
    if not present:
        return None
    if present != marker_keys:
        raise ShortsAcceptanceError("V2 işaretleri eksik; legacy yoluna geçiş yasak")
    if (
        config.get("format_version") != FORMAT_VERSION
        or config.get("shorts_version") != SHORTS_VERSION
        or config.get("template_version") != TEMPLATE_VERSION
    ):
        raise ShortsAcceptanceError("Shorts v2/template sürüm uyuşmazlığı; render durduruldu")
    if config.get("production_mode") != "production_v2":
        raise ShortsAcceptanceError("V2 production_mode uyuşmuyor; legacy yoluna geçiş yasak")

    work = Path(work_dir).resolve()
    voice_provider = str(config.get("voice_provider") or "")
    voice_id = str(config.get("voice_id") or "")
    voice_model = str(config.get("voice_model") or "").strip()
    voice_language = str(config.get("voice_language") or "")
    if (
        voice_provider != V2_VOICE_PROVIDER
        or voice_id != V2_VOICE_ID
        or not voice_model.startswith("gemini-")
        or voice_language not in {"tr", "tr-TR"}
    ):
        raise ShortsAcceptanceError("V2 yalnız Gemini Natural TTS / Charon ile Türkçe üretilebilir")
    validate_locked_mix_timing(config)
    visual_sequence = validate_visual_sequence(config.get("visual_sequence"))
    if config.get("cta_overlay_text") != V2_CTA_OVERLAY_TEXT:
        raise ShortsAcceptanceError("İkinci görselde ekranda 'Takip et' yazı katmanı olmalı")
    try:
        cta_beat_index = int(config.get("cta_overlay_beat_index"))
    except (TypeError, ValueError) as exc:
        raise ShortsAcceptanceError("CTA yazı katmanı vuruş indeksi geçersiz") from exc
    if cta_beat_index != V2_CTA_OVERLAY_BEAT_INDEX:
        raise ShortsAcceptanceError("'Takip et' yazı katmanı ikinci görsel vuruşunda olmalı")
    speed = _finite_float(config.get("voice_speed_factor", 1.0), "voice_speed_factor")
    if abs(speed - 1.0) > 1e-9:
        raise ShortsAcceptanceError("Gemini/Charon sesinde tempo değişimi yasak; v2 yalnız 1.00x biçim dönüştürmesi kullanır")

    script_path = work / "script.txt"
    raw_wav = work / "vo_raw.wav"
    voice_manifest_path = work / "voice_provenance_v2.json"
    visual_report_path = work / "visual_validation.json"
    for required in (script_path, raw_wav, voice_manifest_path, visual_report_path):
        if not required.is_file():
            raise ShortsAcceptanceError(f"V2 zorunlu dosya eksik: {required.name}")

    script_text = script_path.read_text(encoding="utf-8").strip()
    script_lines = [" ".join(line.split()) for line in script_text.splitlines()]
    if len(script_lines) != EXPECTED_NARRATION_BEATS:
        raise ShortsAcceptanceError(f"script.txt tam {EXPECTED_NARRATION_BEATS} anlatım vuruşu içermeli")
    topic = " ".join(str(config.get("topic") or "").split())
    source_url = str(config.get("source_url") or "")
    title = str(config.get("question_title") or "")
    cover_lines = config.get("cover_lines")
    loop_anchor = str(config.get("loop_anchor") or "")
    if not topic or not loop_anchor:
        raise ShortsAcceptanceError("V2 topic/loop_anchor etiketi eksik")
    script_check = validate_script(
        [{"ses": line} for line in script_lines], topic=topic,
        verified_source_url=source_url, title=title, cover_lines=cover_lines,
        loop_anchor=loop_anchor,
    )
    narration = " ".join(script_lines)
    narration_hash = hashlib.sha256(narration.encode("utf-8")).hexdigest()
    voice_hash = sha256_file(raw_wav)
    manifest = json.loads(voice_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ShortsAcceptanceError("Ses manifest'i JSON nesnesi değil")
    if (
        manifest.get("provider") != V2_VOICE_PROVIDER
        or manifest.get("generation") != V2_VOICE_GENERATION
        or manifest.get("provenance_status") != V2_VOICE_PROVENANCE_STATUS
        or manifest.get("voice_id") != V2_VOICE_ID
        or manifest.get("model") != voice_model
        or manifest.get("language") != voice_language
        or manifest.get("narration_sha256") != narration_hash
        or manifest.get("audio_sha256") != voice_hash
    ):
        raise ShortsAcceptanceError("Gemini/Charon ses manifest'i WAV, model veya script ile eşleşmiyor")

    report = json.loads(visual_report_path.read_text(encoding="utf-8"))
    rows = _validate_visual_report(report)
    names = config.get("scenes")
    if not isinstance(names, list) or len(names) != EXPECTED_SCENES:
        raise ShortsAcceptanceError(f"Render config tam {EXPECTED_SCENES} benzersiz görsel dosyası içermeli")
    if len({str(name) for name in names}) != EXPECTED_SCENES:
        raise ShortsAcceptanceError("Render config dört farklı görsel dosyası içermeli; kapanış ilkini yeniden kullanır")
    render_inputs = report.get("render_inputs") if isinstance(report, dict) else None
    if not isinstance(render_inputs, list) or len(render_inputs) != EXPECTED_SCENES:
        raise ShortsAcceptanceError(f"Görsel manifest'i tam {EXPECTED_SCENES} render girdisi içermeli")
    by_name = {str(row.get("file")): row for row in render_inputs if isinstance(row, dict)}
    if len(by_name) != EXPECTED_SCENES:
        raise ShortsAcceptanceError("Görsel manifest dosya adları yineleniyor veya eksik")
    for index, name in enumerate(names, start=1):
        image = (work / str(name)).resolve()
        if image.parent != work or not image.is_file():
            raise ShortsAcceptanceError(f"Sahne {index} görsel yolu geçersiz/eksik")
        record = by_name.get(image.name)
        if not record or record.get("sha256") != sha256_file(image):
            raise ShortsAcceptanceError(f"Görsel sahne {index} SHA256 manifest uyuşmuyor")
        with Image.open(image) as im:
            rgb = im.convert("RGB")
            import numpy as np
            luma = 0.299 * np.asarray(rgb.getchannel("R"), dtype=np.float32)
            luma += 0.587 * np.asarray(rgb.getchannel("G"), dtype=np.float32)
            luma += 0.114 * np.asarray(rgb.getchannel("B"), dtype=np.float32)
            brightness = float(luma.mean())
        if brightness < MIN_AVG_BRIGHTNESS:
            raise ShortsAcceptanceError(f"Sahne {index} görseli karanlık ({brightness:.1f}/255)")

    return {
        "script_sha256": hashlib.sha256(script_text.encode("utf-8")).hexdigest(),
        "narration_sha256": narration_hash,
        "voice_raw_sha256": voice_hash,
        "voice_provider": manifest["provider"],
        "voice_generation": manifest["generation"],
        "voice_provenance_status": manifest["provenance_status"],
        "voice_id": manifest["voice_id"],
        "voice_model": manifest["model"],
        "voice_language": manifest["language"],
        "visual_report": report,
        "voice_speed_factor": speed,
        "scene_count": EXPECTED_SCENES,
        "narration_beat_count": EXPECTED_NARRATION_BEATS,
        "visual_sequence": visual_sequence,
        "cta_overlay_text": V2_CTA_OVERLAY_TEXT,
        "cta_overlay_beat_index": cta_beat_index,
        "script_validation": script_check,
        "topic": topic,
        "question_title": title,
        "loop_anchor": loop_anchor,
    }


def validate_render_manifest_v2(
    work_dir: str | Path,
    config: dict,
    probed_duration: object,
    mp4_path: str | Path | None = None,
) -> dict:
    """Re-open and verify every audio, image, mix, and MP4 hash after rendering."""
    work = Path(work_dir).resolve()
    manifest_path = work / "render_manifest_v2.json"
    if not manifest_path.is_file():
        raise ShortsAcceptanceError("V2 render manifest'i eksik")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShortsAcceptanceError("V2 render manifest'i okunamıyor") from exc
    if not isinstance(manifest, dict):
        raise ShortsAcceptanceError("V2 render manifest'i JSON nesnesi değil")
    if (
        manifest.get("version") != 2
        or manifest.get("format_version") != FORMAT_VERSION
        or manifest.get("production_mode") != "production_v2"
        or manifest.get("shorts_version") != SHORTS_VERSION
        or manifest.get("template_version") != TEMPLATE_VERSION
        or manifest.get("voice_provider") != V2_VOICE_PROVIDER
        or manifest.get("voice_generation") != V2_VOICE_GENERATION
        or manifest.get("voice_provenance_status") != V2_VOICE_PROVENANCE_STATUS
        or manifest.get("voice_id") != V2_VOICE_ID
        or manifest.get("voice_model") != config.get("voice_model")
        or manifest.get("voice_language") != config.get("voice_language")
        or config.get("voice_provider") != V2_VOICE_PROVIDER
        or config.get("voice_id") != V2_VOICE_ID
        or not str(config.get("voice_model") or "").startswith("gemini-")
        or config.get("voice_language") not in {"tr", "tr-TR"}
        or manifest.get("visual_sequence") != list(V2_VISUAL_SEQUENCE)
        or manifest.get("cta_overlay_text") != V2_CTA_OVERLAY_TEXT
        or manifest.get("cta_overlay_beat_index") != V2_CTA_OVERLAY_BEAT_INDEX
        or _finite_float(manifest.get("voice_speed_factor"), "manifest voice_speed_factor") != 1.0
        or _finite_float(config.get("voice_speed_factor", 1.0), "voice_speed_factor") != 1.0
    ):
        raise ShortsAcceptanceError("V2 render manifest sürüm/sağlayıcı/hız uyuşmuyor")

    required_hashes = {
        "voice_raw_sha256": work / "vo_raw.wav",
        "voice_render_sha256": work / "vo_final.wav",
        "mix_sha256": work / "mix.wav",
        "mp4_sha256": Path(mp4_path).resolve() if mp4_path is not None else work / "video.mp4",
    }
    for key, path in required_hashes.items():
        if not path.is_file() or manifest.get(key) != sha256_file(path):
            raise ShortsAcceptanceError(f"V2 render manifest SHA256 uyuşmuyor: {key}")

    scene_names = config.get("scenes")
    image_rows = manifest.get("images")
    if not isinstance(scene_names, list) or len(scene_names) != EXPECTED_SCENES:
        raise ShortsAcceptanceError(f"V2 render manifest config'i {EXPECTED_SCENES} görsel içermeli")
    if not isinstance(image_rows, list) or len(image_rows) != EXPECTED_SCENES:
        raise ShortsAcceptanceError(f"V2 render manifest'i {EXPECTED_SCENES} görsel hash'i içermeli")
    if len({str(name) for name in scene_names}) != EXPECTED_SCENES:
        raise ShortsAcceptanceError("V2 render manifest config'i dört benzersiz görsel içermeli")
    by_name = {str(row.get("file")): row for row in image_rows if isinstance(row, dict)}
    if len(by_name) != EXPECTED_SCENES:
        raise ShortsAcceptanceError("V2 render manifest görsel dosya adları yineleniyor")
    for name in scene_names:
        path = (work / str(name)).resolve()
        row = by_name.get(path.name)
        if path.parent != work or not path.is_file() or not row or row.get("sha256") != sha256_file(path):
            raise ShortsAcceptanceError(f"V2 render manifest görsel SHA256 uyuşmuyor: {name}")

    recorded_duration = validate_duration(manifest.get("mp4_duration_seconds"))
    actual_duration = validate_duration(probed_duration)
    if manifest.get("target_duration_met") is not duration_in_target_band(recorded_duration):
        raise ShortsAcceptanceError("V2 render manifest hedef süre işareti uyuşmuyor")
    validate_hook_timing(0.0, manifest.get("hook_first_word_start"))
    recorded_intervals = validate_v2_timeline(manifest.get("scene_intervals"), scene_names)
    if abs(recorded_intervals[-1]["end"] - recorded_duration) > 0.05:
        raise ShortsAcceptanceError("V2 render manifest sahne zamanları toplam MP4 süresiyle uyuşmuyor")
    if abs(recorded_duration - actual_duration) > 0.05:
        raise ShortsAcceptanceError("V2 render manifest MP4 süresi ffprobe ile uyuşmuyor")
    return manifest
