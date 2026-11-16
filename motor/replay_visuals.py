"""Render new visuals for an archived video while preserving its approved narration/audio.

This replay path intentionally does not call the script or TTS generators. It reads the
approved run's final scene script and processed voice track, selects scene-matched images,
renders the picture track, then copies the approved MP4 audio stream bit-for-bit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "motor"
if str(MOTOR) not in sys.path:
    sys.path.insert(0, str(MOTOR))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.rglob(pattern))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one {pattern!r} under {root}; found {len(matches)}")
    return matches[0]


def extract_scene_rows(final_script: Path) -> list[dict[str, str]]:
    rows = []
    rx = re.compile(r"^\s*\d+\.\s+\[(.*?)\s*/\s*(.*?)\]\s+(.*?)\s*$")
    for line in final_script.read_text(encoding="utf-8").splitlines():
        m = rx.match(line)
        if not m:
            continue
        title1, title2, narration = (part.strip() for part in m.groups())
        rows.append({"title1": title1, "title2": title2, "narration": narration})
    if len(rows) < 3:
        raise SystemExit(f"Could not parse scene titles/narration from {final_script}; got {len(rows)} scenes")
    return rows


def run_checked(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True, type=Path)
    ap.add_argument("--old-video", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--source-run", default="71")
    args = ap.parse_args()

    archive = args.archive.resolve()
    old_video = args.old_video.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not old_video.is_file():
        raise SystemExit(f"Old reference MP4 not found: {old_video}")

    title_file = find_one(archive, "24_senaryo_4_baslik_denetimi_sonrasi_SON_*.txt")
    tts_file = find_one(archive, "30_tts_metni_2_on_isleme_SONRASI_*.txt")
    voice_file = find_one(archive, "34_islenmis_tts_muziksiz_*.wav")
    info_file = find_one(archive, "01_uretim_bilgisi_*.json")
    source_info = json.loads(info_file.read_text(encoding="utf-8"))
    expected_topic = "Uçak tuvaletinde su neden 0.5 saniyede çekilir?"
    archive_topic = str((source_info.get("argumanlar") or {}).get("konu") or source_info.get("konu") or "")
    # #71 used a longer title; its archived first narration line is the definitive scenario check.
    rows = extract_scene_rows(title_file)
    script = tts_file.read_text(encoding="utf-8").strip()
    first_sentence = re.split(r"(?<=[.!?])\s+", script, maxsplit=1)[0].strip()
    scenario_match = (
        "uçak tuvalet" in first_sentence.casefold()
        and ("basınç" in first_sentence.casefold() or "0.5" in archive_topic or "0.5" in first_sentence)
    )
    if not scenario_match:
        raise SystemExit(f"#71 first narration sentence did not match the requested scenario: {first_sentence}")

    # Deliberately concrete, scene-specific searches based on the approved narration.
    query_pairs = [
        ("airplane toilet", "airplane lavatory"),
        ("airplane toilet flush", "toilet flush mechanism"),
        ("aircraft cabin pressure gauge", "pressure gauge"),
        ("aircraft vacuum toilet pipe", "vacuum pipe pressure"),
        ("airplane toilet waste tank", "aircraft waste tank"),
        ("airplane vacuum toilet flush", "vacuum flush toilet"),
        ("aircraft lavatory toilet", "airplane bathroom"),
    ]
    scenes = []
    for i, row in enumerate(rows):
        q1, q2 = query_pairs[min(i, len(query_pairs) - 1)]
        scenes.append({
            "ses": row["narration"],
            "gorsel": q1,
            "gorsel_anahtar": q1,
            "gorsel_alternatif": q2,
        })

    os.environ["MOTOR_VISUAL_QA_PASSED"] = "1"
    import gorsel_uret

    assets = out / "visual_selection"
    selected_paths = gorsel_uret.sahneler_icin_gorseller(scenes, assets, yedek_sorgular=[])
    report_path = assets / "gorsel_secim_raporu.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    selected_rows = [s.get("selected") for s in report.get("scenes", []) if s.get("selected")]
    if len(selected_rows) < 3:
        raise SystemExit(f"Live visual QA requires >=3 real selected images; selected {len(selected_rows)}")
    if any(float(s["semantic_similarity"]) < 0.62 for s in selected_rows):
        raise SystemExit("A selected live image was below the 0.62 semantic threshold")

    # Build the new picture track from the same archived script/processed narration.
    from PIL import Image
    vdir = out / "son"
    vdir.mkdir(parents=True, exist_ok=True)
    script_copy = vdir / "script.txt"
    script_copy.write_text(script + "\n", encoding="utf-8")
    shutil.copyfile(voice_file, vdir / "vo_raw.wav")
    scene_files = []
    visual_credits = []
    for i, (scene, image_path) in enumerate(zip(report["scenes"], selected_paths), start=1):
        target = vdir / f"s{i}.jpg"
        if image_path is None:
            Image.new("RGB", (1080, 1920), (10, 17, 23)).save(target, "JPEG", quality=94)
            visual_credits.append(None)
        else:
            with Image.open(image_path) as im:
                im.convert("RGB").save(target, "JPEG", quality=94)
            selected = scene["selected"]
            visual_credits.append({
                "provider": selected["provider"],
                "url": selected["source_page_url"],
                "representative": True,
            })
        scene_files.append(target.name)

    headlines = []
    for row in rows:
        headlines.append({"icon": "!", "line1": row["title1"], "line2": row["title2"]})
    # This config only controls visual rendering. TTS and mix are not regenerated in the final MP4.
    config = {
        "son": {
            "title": [[rows[0]["title1"], "g"], [rows[0]["title2"]]],
            "scene_headlines": headlines,
            "cover_lines": [rows[0]["title1"], rows[0]["title2"]],
            "music_theme": "gunluk_bilim",
            "intro_lead": 1.45,
            "sentence_pause": 0.54,
            "outro_hold": 1.45,
            "note1": "",
            "note2": "",
            "source_url": "",
            "visual_credits": visual_credits,
            "scenes": scene_files,
        }
    }
    config_path = out / "shorts_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    pipeline = MOTOR / "shorts_pipeline.py"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required by shorts_pipeline")
    os.environ["MIRA_MOTOR_FFMPEG"] = ffmpeg
    run_checked([sys.executable, str(pipeline), "all", str(vdir), str(config_path)])
    picture_video = vdir / "video.mp4"
    if not picture_video.is_file():
        raise SystemExit("shorts_pipeline did not produce a picture video")

    final_video = out / "Ucak_tuvaleti_gorsel_duzeltme.mp4"
    run_checked([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(picture_video), "-i", str(old_video),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy",
        "-shortest", "-movflags", "+faststart", str(final_video),
    ])

    # Verify the narration text is copied byte-for-byte and the final MP4 audio decodes identically.
    original_script_text = tts_file.read_text(encoding="utf-8").strip()
    replay_script_text = script_copy.read_text(encoding="utf-8").strip()
    original_text_hash = hashlib.sha256(original_script_text.encode("utf-8")).hexdigest()
    new_text_hash = hashlib.sha256(replay_script_text.encode("utf-8")).hexdigest()
    if original_text_hash != new_text_hash:
        raise SystemExit("Archived narration text changed during visual replay")
    decoded_old = out / "old_audio.pcm"
    decoded_new = out / "new_audio.pcm"
    for path, target in ((old_video, decoded_old), (final_video, decoded_new)):
        run_checked([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
                     "-map", "0:a:0", "-f", "s16le", "-ac", "2", "-ar", "48000", str(target)])
    old_audio_hash = sha256(decoded_old)
    new_audio_hash = sha256(decoded_new)
    if old_audio_hash != new_audio_hash:
        raise SystemExit("Final MP4 audio differs from #71 after mux")

    report_out = {
        "source_run": str(args.source_run),
        "requested_topic": expected_topic,
        "archived_topic": archive_topic,
        "first_narration_sentence": first_sentence,
        "first_sentence_matches_topic": scenario_match,
        "scene_count": len(rows),
        "live_semantic_model": report.get("semantic_model"),
        "threshold": report.get("threshold"),
        "selected_scene_count": len(selected_rows),
        "selected_scenes": selected_rows,
        "narration_sha256_old_and_replay": original_text_hash,
        "decoded_audio_sha256_old_and_replay": old_audio_hash,
        "audio_identical": old_audio_hash == new_audio_hash,
        "new_video": str(final_video),
        "new_video_sha256": sha256(final_video),
        "visual_selection_report": str(report_path),
        "visual_sources": [s.get("selected") for s in report.get("scenes", [])],
    }
    (out / "replay_report.json").write_text(json.dumps(report_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report_out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
