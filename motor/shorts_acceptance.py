"""Fail-closed acceptance gates for the isolated Shorts v2 production path.

Legacy Shorts configuration is deliberately not validated against v2's fixed
mix/timing contract. This module does not publish or upload anything.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

try:  # paket içi / doğrudan motor yolu
    from .ses_olcum import SAPMA_ESIGI, TABAN_F0_HZ, perde_sapmasi
except ImportError:  # pragma: no cover - testler motor/ yolundan yükler
    from ses_olcum import SAPMA_ESIGI, TABAN_F0_HZ, perde_sapmasi

SHORTS_VERSION = "shorts-v2.1"
TEMPLATE_VERSION = "2.2-sablon_v2"
EXPECTED_SCENES = 7
SHORTS_CTA = "Daha fazla Bilgi Dozu için takip et!"
MIN_SCENE_SECONDS = 2.0
MAX_SCENE_SECONDS = 3.0
MIN_AVG_BRIGHTNESS = 100.0
# Ses sabiti: "Arena" etiketi yok. Referans, 097 üretimindeki Gemini TTS Charon sesidir.
VOICE_PROVIDER = "gemini_tts"
VOICE_ID = "Charon"
VOICE_PROVENANCE_STATUS = "live_gemini_generated"
VOICE_LANGUAGES = {"tr", "tr-TR"}
VOICE_AUDIT_FILE = "voice_audit_v2.json"
VOICE_RAW_HAM_FILE = "vo_raw.gemini_ham24k.wav"
FINAL_WIDTH = 1080
FINAL_HEIGHT = 1920
# Threshold for live Gemini Vision image/text similarity scores; Pexels does not supply this score.
SEMANTIC_THRESHOLD = 0.62
LOCKED_MIX_TIMING = {
    "intro_lead": 1.45,
    "sentence_pause": 0.54,
    "outro_hold": 1.45,
}


def validate_final_size(width: object, height: object) -> tuple[int, int]:
    """Son Short her zaman 1080x1920 olmalı; başka boyut fail-closed."""
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError) as exc:
        raise ShortsAcceptanceError("Son video boyutu okunamadı") from exc
    if (w, h) != (FINAL_WIDTH, FINAL_HEIGHT):
        raise ShortsAcceptanceError(
            f"Son video {FINAL_WIDTH}x{FINAL_HEIGHT} olmalı; bulundu: {w}x{h}")
    return w, h


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


def validate_script(scenes: list[dict], topic: str = "") -> dict:
    if not isinstance(scenes, list) or len(scenes) != EXPECTED_SCENES:
        raise ShortsAcceptanceError(f"Shorts v2 tam {EXPECTED_SCENES} sahne ister")
    narration = []
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise ShortsAcceptanceError(f"Sahne {index} nesne olmalı")
        line = " ".join(str(scene.get("ses") or "").split())
        if not line:
            raise ShortsAcceptanceError(f"Sahne {index} anlatımı boş")
        narration.append(line)
    if narration[-1] != SHORTS_CTA or any(SHORTS_CTA in line for line in narration[:-1]):
        raise ShortsAcceptanceError("Shorts v2 son sahnede sabit CTA ister; önceki sahnelerde CTA yasak")
    return {
        "topic": str(topic or "").strip(),
        "scene_count": len(scenes),
        "narration": " ".join(narration),
        "word_count": len(" ".join(narration).split()),
    }


def validate_scene_intervals(intervals: list[dict | tuple | list]) -> list[dict]:
    if not isinstance(intervals, list) or len(intervals) != EXPECTED_SCENES:
        raise ShortsAcceptanceError(f"V2 zaman çizelgesi tam {EXPECTED_SCENES} sahne aralığı ister")
    validated: list[dict] = []
    previous_end = None
    for index, interval in enumerate(intervals, start=1):
        if isinstance(interval, dict):
            start, end = interval.get("start"), interval.get("end")
        elif isinstance(interval, (tuple, list)) and len(interval) == 2:
            start, end = interval
        else:
            raise ShortsAcceptanceError(f"Sahne {index} aralığı start/end içermeli")
        start = _finite_float(start, f"Sahne {index} start")
        end = _finite_float(end, f"Sahne {index} end")
        duration = end - start
        if duration < MIN_SCENE_SECONDS or duration > MAX_SCENE_SECONDS:
            raise ShortsAcceptanceError(
                f"Sahne {index} {duration:.3f}s; izin verilen aralık {MIN_SCENE_SECONDS:.1f}–{MAX_SCENE_SECONDS:.1f}s"
            )
        if start < 0 or (index == 1 and abs(start) > 1e-6):
            raise ShortsAcceptanceError(f"Sahne {index} aralığı negatif veya 0 saniyede başlamıyor")
        if previous_end is not None and abs(start - previous_end) > 1e-6:
            raise ShortsAcceptanceError(f"Sahne {index} aralığı önceki sahneyle bitişik değil")
        validated.append({"start": start, "end": end, "duration": duration})
        previous_end = end
    return validated


def validate_duration(duration_seconds: object) -> float:
    duration = _finite_float(duration_seconds, "MP4 süresi")
    minimum = EXPECTED_SCENES * MIN_SCENE_SECONDS
    maximum = EXPECTED_SCENES * MAX_SCENE_SECONDS
    if duration < minimum or duration > maximum:
        raise ShortsAcceptanceError(f"MP4 süresi {duration:.3f}s; v2 hedefi {minimum:.1f}–{maximum:.1f}s")
    return duration


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
    rows = report.get("scenes")
    if not isinstance(rows, list) or len(rows) != EXPECTED_SCENES:
        raise ShortsAcceptanceError("Canlı görsel raporu tam 7 sahne içermeli")
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        selected = row.get("selected") if isinstance(row, dict) else None
        if not isinstance(selected, dict):
            raise ShortsAcceptanceError(f"Görsel sahne {index} seçimi eksik")
        provider = str(selected.get("provider") or "")
        if provider not in {"pexels", "pixabay", "cloudflare_ai", "gemini_ai"}:
            raise ShortsAcceptanceError(f"Görsel sahne {index} desteklenen canlı kaynak değil: {provider!r}")
        uid = str(selected.get("uid") or "")
        if not uid or uid in seen:
            raise ShortsAcceptanceError("V2 sahne görselleri benzersiz UID taşımalı")
        seen.add(uid)
        url = str(selected.get("source_page_url") or "")
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        if provider == "pexels":
            if host not in {"pexels.com", "www.pexels.com"}:
                raise ShortsAcceptanceError(f"Görsel sahne {index} Pexels kaynak URL'si doğrulanamadı")
        elif provider == "pixabay":
            if host not in {"pixabay.com", "www.pixabay.com"}:
                raise ShortsAcceptanceError(f"Görsel sahne {index} Pixabay kaynak URL'si doğrulanamadı")
        elif provider == "cloudflare_ai":
            if host not in {"developers.cloudflare.com", "www.cloudflare.com", "cloudflare.com"}:
                raise ShortsAcceptanceError(f"Görsel sahne {index} Cloudflare AI kaynak URL'si doğrulanamadı")
        elif provider == "gemini_ai":
            if host not in {"ai.google.dev", "generativelanguage.googleapis.com", "google.com", "www.google.com"}:
                raise ShortsAcceptanceError(f"Görsel sahne {index} Gemini AI kaynak URL'si doğrulanamadı")
        score_origin = selected.get("score_origin")
        if score_origin == "live_gemini_vision":
            score = _finite_float(selected.get("semantic_similarity"), f"Sahne {index} semantik skor")
            if score < SEMANTIC_THRESHOLD or score > 1.0:
                raise ShortsAcceptanceError(f"Görsel sahne {index} canlı Gemini Vision eşiğini geçmedi")
        else:
            raise ShortsAcceptanceError(f"Görsel sahne {index} skor kökeni doğrulanamadı")
    return rows


def validate_v2_production_context(work_dir: str | Path, config: dict) -> dict | None:
    """Validate caller-attested provenance and hashes before a v2 render.

    Any partial/mismatched v2 markers fail closed instead of falling through to
    the legacy renderer/TTS. The images and voice are verified against local
    SHA256 manifests immediately before rendering. The voice provider is an
    operator declaration, not cryptographically authenticated by this module.
    """
    marker_keys = {"shorts_version", "template_version", "production_mode"}
    present = {key for key in marker_keys if key in config}
    if not present:
        return None
    if present != marker_keys:
        raise ShortsAcceptanceError("V2 işaretleri eksik; legacy yoluna geçiş yasak")
    if config.get("shorts_version") != SHORTS_VERSION or config.get("template_version") != TEMPLATE_VERSION:
        raise ShortsAcceptanceError("Shorts v2/template sürüm uyuşmazlığı; render durduruldu")
    if config.get("production_mode") != "production_v2":
        raise ShortsAcceptanceError("V2 production_mode uyuşmuyor; legacy yoluna geçiş yasak")

    work = Path(work_dir).resolve()
    validate_locked_mix_timing(config)
    speed = _finite_float(config.get("voice_speed_factor", 1.0), "voice_speed_factor")
    if abs(speed - 1.0) > 1e-9:
        raise ShortsAcceptanceError("Gemini Charon sesinde tempo değişimi yasak; v2 yalnız 1.00x biçim dönüştürmesi kullanır")

    script_path = work / "script.txt"
    raw_wav = work / "vo_raw.wav"
    voice_manifest_path = work / "voice_provenance_v2.json"
    voice_audit_path = work / VOICE_AUDIT_FILE
    voice_ham_path = work / VOICE_RAW_HAM_FILE
    visual_report_path = work / "visual_validation.json"
    for required in (script_path, raw_wav, voice_manifest_path, voice_audit_path, voice_ham_path, visual_report_path):
        if not required.is_file():
            raise ShortsAcceptanceError(f"V2 zorunlu dosya eksik: {required.name}")

    script_text = script_path.read_text(encoding="utf-8").strip()
    script_lines = [" ".join(line.split()) for line in script_text.splitlines()]
    if len(script_lines) != EXPECTED_SCENES:
        raise ShortsAcceptanceError("script.txt tam 7 satır/sahne içermeli")
    if script_lines[-1] != SHORTS_CTA or any(SHORTS_CTA in line for line in script_lines[:-1]):
        raise ShortsAcceptanceError("script.txt son sahnede sabit CTA içermeli; önceki sahnelerde CTA yasak")
    narration = " ".join(script_lines)
    narration_hash = hashlib.sha256(narration.encode("utf-8")).hexdigest()
    voice_hash = sha256_file(raw_wav)
    manifest = json.loads(voice_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ShortsAcceptanceError("Ses manifest'i JSON nesnesi değil")
    if (
        manifest.get("provider") != VOICE_PROVIDER
        or manifest.get("generation") != "live_gemini_tts"
        or manifest.get("provenance_status") != VOICE_PROVENANCE_STATUS
        or manifest.get("voice_id") != VOICE_ID
        or manifest.get("language") not in VOICE_LANGUAGES
        or manifest.get("narration_sha256") != narration_hash
        or manifest.get("audio_sha256") != voice_hash
    ):
        raise ShortsAcceptanceError("Gemini Charon ses manifest'i WAV/script SHA256 veya kaynakla eşleşmiyor")

    try:
        audit = json.loads(voice_audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShortsAcceptanceError("Ses denetim raporu okunamıyor") from exc
    if not isinstance(audit, dict):
        raise ShortsAcceptanceError("Ses denetim raporu JSON nesnesi değil")
    audit_f0 = _finite_float(audit.get("f0_medyan_hz"), "denetim f0 medyanı")
    _finite_float(audit.get("sapma_yuzde"), "denetim sapması")
    if audit_f0 <= 0:
        raise ShortsAcceptanceError("ses perdesi ölçümü geçersiz")
    # f0 sapması yalnız ölçüm/uyarıdır; metne göre değişir. Ses değişmediğini
    # aşağıdaki canlı üretim, Charon kimliği ve SHA256 kanıtları doğrular.
    perde_sapmasi(audit_f0)
    if (
        audit.get("provider") != VOICE_PROVIDER
        or audit.get("voice_id") != VOICE_ID
        or audit.get("generation") != "live_gemini_tts"
        or audit.get("provenance_status") != VOICE_PROVENANCE_STATUS
        or audit.get("passed") is not True
        or audit.get("voice_sha256") != voice_hash
        or audit.get("raw_sha256") != sha256_file(voice_ham_path)
        or manifest.get("voice_audit_sha256") != sha256_file(voice_audit_path)
    ):
        raise ShortsAcceptanceError("Gemini Charon ses denetimi başarısız veya manifest ile uyuşmuyor")

    report = json.loads(visual_report_path.read_text(encoding="utf-8"))
    rows = _validate_visual_report(report)
    names = config.get("scenes")
    if not isinstance(names, list) or len(names) != EXPECTED_SCENES:
        raise ShortsAcceptanceError("Render config tam 7 görsel dosyası içermeli")
    render_inputs = report.get("render_inputs") if isinstance(report, dict) else None
    if not isinstance(render_inputs, list) or len(render_inputs) != EXPECTED_SCENES:
        raise ShortsAcceptanceError("Görsel manifest'i tam 7 render girdisi içermeli")
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
        "voice_id": manifest["voice_id"],
        "voice_provenance_status": manifest["provenance_status"],
        "voice_audit_sha256": sha256_file(voice_audit_path),
        "voice_f0_medyan_hz": audit_f0,
        "visual_report": report,
        "voice_speed_factor": speed,
        "scene_count": EXPECTED_SCENES,
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
        or manifest.get("production_mode") != "production_v2"
        or manifest.get("shorts_version") != SHORTS_VERSION
        or manifest.get("template_version") != TEMPLATE_VERSION
        or manifest.get("voice_provider") != VOICE_PROVIDER
        or manifest.get("voice_provenance_status") != VOICE_PROVENANCE_STATUS
        or manifest.get("voice_audit_sha256") != sha256_file(work / VOICE_AUDIT_FILE)
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
        raise ShortsAcceptanceError("V2 render manifest config'i 7 görsel içermeli")
    if not isinstance(image_rows, list) or len(image_rows) != EXPECTED_SCENES:
        raise ShortsAcceptanceError("V2 render manifest'i tam 7 görsel hash'i içermeli")
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
    if abs(recorded_duration - actual_duration) > 0.05:
        raise ShortsAcceptanceError("V2 render manifest MP4 süresi ffprobe ile uyuşmuyor")
    return manifest
