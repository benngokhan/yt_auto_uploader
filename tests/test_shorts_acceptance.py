import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
(ROOT / ".agent_tmp").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "motor"))

import shorts_acceptance as acceptance  # noqa: E402


SCRIPT_LINES = [
    "Mum alevi kapalı bir yerde neden söner?",
    "Fitil eriyen balmumunu yukarı doğru sürekli taşır.",
    "Isınan balmumu buharı çevredeki oksijenle birlikte yanar.",
    "Oksijen azalınca yanma yavaşlar ve alev söner.",
    "Peki mum alevi oksijen olmadan yanabilir mi?",
]
TOPIC = "mum alevi"
TITLE = "Mum alevi neden söner?"
COVER_LINES = ["MUM ALEVİ NEDEN", "SÖNER?"]
LOOP_ANCHOR = "mum"


def _scenes(lines=None):
    return [{"ses": text} for text in (lines or SCRIPT_LINES)]


class ShortsV2GateTests(unittest.TestCase):
    def _valid_context(self, root: Path):
        script = "\n".join(SCRIPT_LINES) + "\n"
        (root / "script.txt").write_text(script, encoding="utf-8")
        (root / "vo_raw.wav").write_bytes(b"raw-gemini-charon-waveform")
        narration = " ".join(" ".join(line.split()) for line in SCRIPT_LINES)
        voice_manifest = {
            "provider": "gemini_tts",
            "generation": "motor.tts.uret",
            "provenance_status": "local_tts_call_unverified",
            "voice_id": "Charon",
            "model": "gemini-2.5-flash-preview-tts",
            "language": "tr",
            "narration_sha256": hashlib.sha256(narration.encode()).hexdigest(),
            "audio_sha256": acceptance.sha256_file(root / "vo_raw.wav"),
        }
        (root / "voice_provenance_v2.json").write_text(
            json.dumps(voice_manifest), encoding="utf-8"
        )
        names = []
        render_inputs = []
        selected = []
        for i in range(1, 5):
            name = f"s{i}.jpg"
            Image.new("RGB", (64, 96), (180 + i, 190, 200)).save(root / name)
            names.append(name)
            render_inputs.append({"file": name, "sha256": acceptance.sha256_file(root / name)})
            selected.append({
                "provider": "pexels",
                "uid": f"pexels:{1000 + i}",
                "source_page_url": f"https://www.pexels.com/photo/blue-sky-{1000 + i}/",
                "semantic_similarity": 0.78,
                "score_origin": "live_gemini_vision",
            })
        report = {
            "version": 2,
            "mode": "production_v2",
            "generation": "live",
            "fallback_policy": "fail_closed",
            "semantic_threshold": acceptance.SEMANTIC_THRESHOLD,
            "semantic_model": "test-fixture-not-live-evidence",
            "scenes": [{"selected": item} for item in selected],
            "render_inputs": render_inputs,
        }
        (root / "visual_validation.json").write_text(json.dumps(report), encoding="utf-8")
        config = {
            "format_version": acceptance.FORMAT_VERSION,
            "shorts_version": acceptance.SHORTS_VERSION,
            "template_version": acceptance.TEMPLATE_VERSION,
            "production_mode": "production_v2",
            "topic": TOPIC,
            "question_title": TITLE,
            "cover_lines": COVER_LINES,
            "loop_anchor": LOOP_ANCHOR,
            "source_url": "",
            "voice_provider": "gemini_tts",
            "voice_id": "Charon",
            "voice_model": "gemini-2.5-flash-preview-tts",
            "voice_language": "tr",
            "voice_speed_factor": 1.0,
            "intro_lead": 0.0,
            "sentence_pause": 0.12,
            "outro_hold": 0.0,
            "scenes": names,
            "visual_sequence": [0, 1, 2, 3, 0],
            "cta_overlay_text": "Takip et",
            "cta_overlay_beat_index": 1,
        }
        return config, SCRIPT_LINES

    def test_v2_script_is_35_to_45_words_with_question_hook_and_loop(self):
        result = acceptance.validate_script(
            _scenes(), topic=TOPIC, title=TITLE, cover_lines=COVER_LINES,
            loop_anchor=LOOP_ANCHOR,
        )
        self.assertEqual(result["scene_count"], 4)
        self.assertEqual(result["word_count"], 35)
        self.assertEqual(result["loop_anchor"], LOOP_ANCHOR)
        self.assertEqual(result["hook"], SCRIPT_LINES[0])
        self.assertEqual(result["title_cover"]["cover_lines"], COVER_LINES)

    def test_34_words_rejected_even_when_old_preview_flags_are_set(self):
        lines = SCRIPT_LINES.copy()
        lines[1] = "Fitil eriyen balmumunu yukarı sürekli taşır."
        with mock.patch.dict(os.environ, {"MOTOR_EXPERIMENTAL_OPENROUTER": "1", "MOTOR_PREVIEW_WORDS_30": "1"}):
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "35–45 kelime"):
                acceptance.validate_script(_scenes(lines), topic=TOPIC, title=TITLE, cover_lines=COVER_LINES,
                                           loop_anchor=LOOP_ANCHOR)

    def test_script_rejects_wrong_scene_count_empty_scene_filler_and_cta(self):
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "5 anlatım vuruşu"):
            acceptance.validate_script(_scenes(SCRIPT_LINES[:-1]))
        lines = SCRIPT_LINES.copy()
        lines[3] = " "
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "boş"):
            acceptance.validate_script(_scenes(lines))
        lines = SCRIPT_LINES.copy()
        lines[4] = "Bunu biliyor muydun?"
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "dolgu"):
            acceptance.validate_script(_scenes(lines))
        lines = SCRIPT_LINES.copy()
        lines[4] = "Daha fazla Bilgi Dozu için takip et!"
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "CTA"):
            acceptance.validate_script(_scenes(lines))

    def test_script_rejects_out_of_range_word_count_nonquestion_hook_and_no_loop(self):
        lines = SCRIPT_LINES.copy()
        lines[0] = "Fitil kapalı bir yerde neden kısa kalır?"
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "loop"):
            acceptance.validate_script(_scenes(lines), loop_anchor=LOOP_ANCHOR)
        lines = SCRIPT_LINES.copy()
        lines[0] = "Mum alevi bazen hızlıca söner."
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "soru-hook"):
            acceptance.validate_script(_scenes(lines))
        lines = SCRIPT_LINES.copy()
        lines[4] = "Duman parçacıkları havaya karışır ve uzaklaşır mı?"
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "loop"):
            acceptance.validate_script(_scenes(lines), loop_anchor=LOOP_ANCHOR)
        lines = SCRIPT_LINES.copy()
        lines[-1] += " Böylece duman taşınır."
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "tek kısa cümle"):
            acceptance.validate_script(_scenes(lines))

    def test_topic_filter_blocks_unverified_absolutes_and_metrics(self):
        safe = acceptance.topic_score("Mum alevi neden söner?")
        self.assertTrue(safe["accepted"])
        extreme = acceptance.topic_score("Bu yöntem asla başarısız olmaz")
        self.assertFalse(extreme["accepted"])
        quantified = acceptance.topic_score("Saniyede 20 metre ilerler")
        self.assertFalse(quantified["accepted"])
        with self.assertRaises(acceptance.ShortsAcceptanceError):
            acceptance.select_scored_topic("Dünyanın en hızlısı ve asla durmaz")
        sourced = acceptance.topic_score(
            "Bu yöntem asla başarısız olmaz", "https://www.nature.com/articles/example"
        )
        self.assertTrue(sourced["accepted"])
        self.assertIn("manual_relevance_review", sourced["reasons"][-1])

    def test_title_and_cover_are_questions_and_fit_safe_character_limits(self):
        valid = acceptance.validate_title_cover(TITLE, COVER_LINES, topic=TOPIC)
        self.assertEqual(valid["cover_lines"], COVER_LINES)
        for title, lines in (
            ("Mum alevi söner", COVER_LINES),
            (TITLE, ["MUM ALEVİ NEDEN TAŞIYABİLİR", "SÖNER?"]),
            (TITLE, ["mum alevi neden", "söner?"]),
            ("Başka konu nasıl olur?", COVER_LINES),
        ):
            with self.subTest(title=title, lines=lines), self.assertRaises(acceptance.ShortsAcceptanceError):
                acceptance.validate_title_cover(title, lines, topic=TOPIC)

    def test_immediate_hook_timing_is_zero_and_first_word_within_150ms(self):
        acceptance.validate_hook_timing(0.0, 0.15)
        for scene_start, word_start in ((0.01, 0.0), (0.0, 0.151), (0.0, -0.01)):
            with self.subTest(scene_start=scene_start, word_start=word_start), self.assertRaises(
                acceptance.ShortsAcceptanceError
            ):
                acceptance.validate_hook_timing(scene_start, word_start)

    def test_scene_intervals_and_video_duration_are_gated(self):
        points = [0, 4, 7, 12, 16, 20]
        intervals = [{"start": a, "end": b} for a, b in zip(points, points[1:])]
        self.assertEqual(len(acceptance.validate_scene_intervals(intervals)), 5)
        self.assertEqual(acceptance.validate_duration(20), 20)
        self.assertTrue(acceptance.duration_in_target_band(21))
        self.assertFalse(acceptance.duration_in_target_band(17.5))
        self.assertFalse(acceptance.duration_in_target_band(23))
        self.assertEqual(acceptance.validate_duration(25), 25)
        for value in (float("nan"), 14.99, 25.001):
            with self.subTest(value=value), self.assertRaises(acceptance.ShortsAcceptanceError):
                acceptance.validate_duration(value)
        intervals[0] = {"start": 0, "end": 1.99}
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "2.0–8.0"):
            acceptance.validate_scene_intervals(intervals)
        intervals = [{"start": i * 2, "end": (i + 1) * 2} for i in range(5)]
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "minimum 15.0"):
            acceptance.validate_scene_intervals(intervals)
        intervals = [{"start": a, "end": b} for a, b in zip(points, points[1:])]
        intervals[2]["start"] -= 0.1
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "bitişik"):
            acceptance.validate_scene_intervals(intervals)

    def test_loop_image_and_cta_must_be_in_correct_beats(self):
        names = [f"s{i}.jpg" for i in range(1, 5)]
        points = [0, 4, 7, 12, 16, 20]
        rows = [{"start": points[i], "end": points[i+1],
                 "file": names[j], "cta_overlay": "Takip et" if i == 1 else None}
                for i, j in enumerate([0, 1, 2, 3, 0])]
        acceptance.validate_v2_timeline(rows, names)
        rows[-1]["file"] = names[-1]
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "1-2-3-4-1"):
            acceptance.validate_v2_timeline(rows, names)
        rows[-1]["file"] = names[0]
        rows[-1]["cta_overlay"] = "Takip et"
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "yalnız ikinci"):
            acceptance.validate_v2_timeline(rows, names)

    def test_v2_requires_exact_version_and_locked_mix_but_legacy_remains_unlocked(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            config["template_version"] = "wrong-version"
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "sürüm uyuşmazlığı"):
                acceptance.validate_v2_production_context(root, config)
        legacy = {"sentence_pause": 0.2, "intro_lead": 0.8, "outro_hold": 4.0}
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            self.assertIsNone(acceptance.validate_v2_production_context(temp, legacy))

        for key, value in (("intro_lead", 1.45), ("sentence_pause", 0.54), ("outro_hold", 1.45)):
            with self.subTest(key=key), tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
                root = Path(temp)
                config, _ = self._valid_context(root)
                config[key] = value
                with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "kilidi uyuşmuyor"):
                    acceptance.validate_v2_production_context(root, config)

    def test_audio_visual_hashes_and_gemini_charon_voice_metadata_are_bound(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            result = acceptance.validate_v2_production_context(root, config)
            self.assertEqual(result["scene_count"], 4)
            self.assertEqual(result["voice_speed_factor"], 1.0)
            self.assertEqual(result["voice_provider"], "gemini_tts")
            self.assertEqual(result["voice_id"], "Charon")
            self.assertEqual(result["voice_model"], "gemini-2.5-flash-preview-tts")
            self.assertEqual(result["voice_provenance_status"], "local_tts_call_unverified")
            self.assertEqual(result["script_validation"]["word_count"], 35)
            (root / "s4.jpg").write_bytes(b"changed image")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "SHA256"):
                acceptance.validate_v2_production_context(root, config)

    def test_voice_manifest_must_be_gemini_charon_and_cannot_claim_signed_verification(self):
        for key, value in (
            ("provider", "arena.generate_speech"),
            ("voice_id", "voice-00"),
            ("model", "gemini-other-model"),
            ("provenance_status", "provider_signed_verified"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
                root = Path(temp)
                config, _ = self._valid_context(root)
                manifest_path = root / "voice_provenance_v2.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest[key] = value
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "Gemini/Charon ses manifest"):
                    acceptance.validate_v2_production_context(root, config)

        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            manifest_path = root / "voice_provenance_v2.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["generation"] = "live"
            manifest["provenance_status"] = "verified"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "ses manifest"):
                acceptance.validate_v2_production_context(root, config)

    def test_live_visual_report_rejects_dark_image_low_score_wrong_origin_and_bad_threshold(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            Image.new("RGB", (64, 96), (10, 15, 20)).save(root / "s1.jpg")
            report = json.loads((root / "visual_validation.json").read_text(encoding="utf-8"))
            report["render_inputs"][0]["sha256"] = acceptance.sha256_file(root / "s1.jpg")
            (root / "visual_validation.json").write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "karanlık"):
                acceptance.validate_v2_production_context(root, config)

        for change, error in (
            (lambda r: r["scenes"][0]["selected"].update(semantic_similarity=0.61), "eşiğini"),
            (lambda r: r["scenes"][0]["selected"].update(score_origin="pexels_metadata_overlap_proxy"), "skor kökeni"),
            (lambda r: r.update(semantic_threshold=0.5), "eşiği raporda"),
        ):
            with self.subTest(error=error), tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
                root = Path(temp)
                config, _ = self._valid_context(root)
                report = json.loads((root / "visual_validation.json").read_text(encoding="utf-8"))
                change(report)
                (root / "visual_validation.json").write_text(json.dumps(report), encoding="utf-8")
                with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, error):
                    acceptance.validate_v2_production_context(root, config)

    def test_render_manifest_hashes_duration_versions_and_soft_target_are_checked(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            for name, content in (("vo_final.wav", b"final-voice"),
                                  ("mix.wav", b"mixed-audio"),
                                  ("video.mp4", b"rendered-mp4")):
                (root / name).write_bytes(content)
            manifest = {
                "version": 2,
                "format_version": acceptance.FORMAT_VERSION,
                "production_mode": "production_v2",
                "shorts_version": acceptance.SHORTS_VERSION,
                "template_version": acceptance.TEMPLATE_VERSION,
                "voice_provider": "gemini_tts",
                "voice_generation": "motor.tts.uret",
                "voice_provenance_status": "local_tts_call_unverified",
                "voice_id": "Charon",
                "voice_model": "gemini-2.5-flash-preview-tts",
                "voice_language": "tr",
                "voice_speed_factor": 1.0,
                "voice_raw_sha256": acceptance.sha256_file(root / "vo_raw.wav"),
                "voice_render_sha256": acceptance.sha256_file(root / "vo_final.wav"),
                "mix_sha256": acceptance.sha256_file(root / "mix.wav"),
                "mp4_sha256": acceptance.sha256_file(root / "video.mp4"),
                "images": [
                    {"file": name, "sha256": acceptance.sha256_file(root / name)}
                    for name in config["scenes"]
                ],
                "visual_sequence": [0, 1, 2, 3, 0],
                "cta_overlay_text": "Takip et",
                "cta_overlay_beat_index": 1,
                "mp4_duration_seconds": 17.5,
                "target_duration_met": False,
                "hook_first_word_start": 0.05,
                "scene_intervals": [
                    {"start": i * 3.5, "end": (i + 1) * 3.5,
                     "file": config["scenes"][[0, 1, 2, 3, 0][i]],
                     "cta_overlay": "Takip et" if i == 1 else None} for i in range(5)
                ],
            }
            (root / "render_manifest_v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            checked = acceptance.validate_render_manifest_v2(root, config, 17.5)
            self.assertEqual(checked["voice_provider"], "gemini_tts")
            self.assertEqual(checked["voice_id"], "Charon")
            manifest["target_duration_met"] = True
            (root / "render_manifest_v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "hedef süre"):
                acceptance.validate_render_manifest_v2(root, config, 17.5)
            manifest["target_duration_met"] = False
            manifest["hook_first_word_start"] = 0.2
            (root / "render_manifest_v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "Hook 0. saniyede"):
                acceptance.validate_render_manifest_v2(root, config, 17.5)
            manifest["hook_first_word_start"] = 0.05
            manifest["scene_intervals"][4]["start"] += 0.1
            (root / "render_manifest_v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "bitişik"):
                acceptance.validate_render_manifest_v2(root, config, 17.5)
            manifest["scene_intervals"] = [
                {"start": i * 3.5, "end": (i + 1) * 3.5,
                     "file": config["scenes"][[0, 1, 2, 3, 0][i]],
                     "cta_overlay": "Takip et" if i == 1 else None} for i in range(5)
            ]
            (root / "render_manifest_v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "mix.wav").write_bytes(b"changed-mix")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "mix_sha256"):
                acceptance.validate_render_manifest_v2(root, config, 17.5)

    def test_v2_speed_factor_remains_1x_even_if_legacy_tts_supports_other_rates(self):
        for value in (1.05, 1.07, 1.10):
            with self.subTest(value=value), tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
                root = Path(temp)
                config, _ = self._valid_context(root)
                config["voice_speed_factor"] = value
                with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "Gemini/Charon sesinde tempo"):
                    acceptance.validate_v2_production_context(root, config)


if __name__ == "__main__":
    unittest.main()
