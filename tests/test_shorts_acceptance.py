import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
(ROOT / ".agent_tmp").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "motor"))

import shorts_acceptance as acceptance  # noqa: E402


class ShortsV2GateTests(unittest.TestCase):
    def _valid_context(self, root: Path):
        lines = [f"Sahne {i} için kısa ve aydınlık anlatım." for i in range(1, 7)] + [acceptance.SHORTS_CTA]
        script = "\n".join(lines) + "\n"
        (root / "script.txt").write_text(script, encoding="utf-8")
        (root / "vo_raw.wav").write_bytes(b"raw-gemini-waveform")
        ham = root / acceptance.VOICE_RAW_HAM_FILE
        ham.write_bytes(b"ham-gemini-pcm")
        narration = " ".join(" ".join(line.split()) for line in lines)
        audit = {
            "provider": acceptance.VOICE_PROVIDER,
            "generation": "live_gemini_tts",
            "provenance_status": acceptance.VOICE_PROVENANCE_STATUS,
            "voice_id": acceptance.VOICE_ID,
            "language": "tr",
            "raw_sha256": acceptance.sha256_file(ham),
            "voice_sha256": acceptance.sha256_file(root / "vo_raw.wav"),
            "f0_medyan_hz": acceptance.TABAN_F0_HZ,
            "sapma_yuzde": 0.0,
            "uyari": False,
            "passed": True,
        }
        audit_path = root / acceptance.VOICE_AUDIT_FILE
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        manifest = {
            "provider": acceptance.VOICE_PROVIDER,
            "generation": "live_gemini_tts",
            "provenance_status": acceptance.VOICE_PROVENANCE_STATUS,
            "voice_id": acceptance.VOICE_ID,
            "language": "tr",
            "narration_sha256": hashlib.sha256(narration.encode()).hexdigest(),
            "audio_sha256": acceptance.sha256_file(root / "vo_raw.wav"),
            "voice_audit_sha256": acceptance.sha256_file(audit_path),
        }
        (root / "voice_provenance_v2.json").write_text(json.dumps(manifest), encoding="utf-8")
        names = []
        render_inputs = []
        selected = []
        for i in range(1, 8):
            name = f"s{i}.jpg"
            Image.new("RGB", (32, 48), (180, 190, 200)).save(root / name)
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
            "scenes": [{"selected": item} for item in selected],
            "render_inputs": render_inputs,
        }
        (root / "visual_validation.json").write_text(json.dumps(report), encoding="utf-8")
        config = {
            "shorts_version": acceptance.SHORTS_VERSION,
            "template_version": acceptance.TEMPLATE_VERSION,
            "production_mode": "production_v2",
            "voice_speed_factor": 1.0,
            "intro_lead": 1.45,
            "sentence_pause": 0.54,
            "outro_hold": 1.45,
            "scenes": names,
        }
        return config, lines

    def test_v2_requires_exactly_seven_nonempty_scenes(self):
        good = [{"ses": f"Satır {i}"} for i in range(6)] + [{"ses": acceptance.SHORTS_CTA}]
        self.assertEqual(acceptance.validate_script(good)["scene_count"], 7)
        with self.assertRaises(acceptance.ShortsAcceptanceError):
            acceptance.validate_script(good[:-1])
        good[3]["ses"] = " "
        with self.assertRaises(acceptance.ShortsAcceptanceError):
            acceptance.validate_script(good)

    def test_scene_intervals_fit_38_to_45_second_target_and_are_ordered(self):
        intervals = [{"start": i * 5.8, "end": (i + 1) * 5.8} for i in range(7)]
        self.assertEqual(len(acceptance.validate_scene_intervals(intervals)), 7)
        intervals[2] = {"start": 11.6, "end": 19.0}
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "5.0–7.0"):
            acceptance.validate_scene_intervals(intervals)
        intervals[2] = {"start": 12.0, "end": 17.5}
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "bitişik"):
            acceptance.validate_scene_intervals(intervals)

    def test_final_size_is_always_1080x1920(self):
        self.assertEqual(acceptance.validate_final_size(1080, 1920), (1080, 1920))
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "1080x1920"):
            acceptance.validate_final_size(1920, 1080)
        with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "1080x1920"):
            acceptance.validate_final_size(1080, 1921)

    def test_version_mismatch_fails_closed_but_legacy_mix_is_not_overlocked(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            config["template_version"] = "wrong-version"
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "sürüm uyuşmazlığı"):
                acceptance.validate_v2_production_context(root, config)
        legacy = {"sentence_pause": 0.2, "intro_lead": 0.8, "outro_hold": 4.0}
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            self.assertIsNone(acceptance.validate_v2_production_context(temp, legacy))

    def test_audio_and_image_hashes_bind_the_v2_render_context(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            result = acceptance.validate_v2_production_context(root, config)
            self.assertEqual(result["scene_count"], 7)
            self.assertEqual(result["voice_speed_factor"], 1.0)
            self.assertEqual(result["voice_provenance_status"], acceptance.VOICE_PROVENANCE_STATUS)
            (root / "s4.jpg").write_bytes(b"changed image")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "SHA256"):
                acceptance.validate_v2_production_context(root, config)

    def test_voice_manifest_requires_live_gemini_charon_origin(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            manifest_path = root / "voice_provenance_v2.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["generation"], "live_gemini_tts")
            self.assertEqual(manifest["provenance_status"], acceptance.VOICE_PROVENANCE_STATUS)
            self.assertEqual(manifest["voice_id"], acceptance.VOICE_ID)
            manifest["voice_id"] = "Arena"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "ses manifest"):
                acceptance.validate_v2_production_context(root, config)

    def test_voice_audit_fails_closed_on_invalid_measurement_or_hash(self):
        # Perde sapması uyarıdır; ölçüm yoksa/sonsuzsa fail-closed.
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            audit_path = root / acceptance.VOICE_AUDIT_FILE
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["f0_medyan_hz"] = 0.0
            audit["sapma_yuzde"] = -100.0
            audit["uyari"] = True
            audit["passed"] = True
            audit_path.write_text(json.dumps(audit), encoding="utf-8")
            manifest_path = root / "voice_provenance_v2.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["voice_audit_sha256"] = acceptance.sha256_file(audit_path)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "ses perdesi"):
                acceptance.validate_v2_production_context(root, config)

        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            (root / acceptance.VOICE_RAW_HAM_FILE).write_bytes(b"changed-ham")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "ses denetimi"):
                acceptance.validate_v2_production_context(root, config)

    def test_dark_visual_and_nonfinite_semantic_score_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            Image.new("RGB", (32, 48), (10, 15, 20)).save(root / "s1.jpg")
            report = json.loads((root / "visual_validation.json").read_text(encoding="utf-8"))
            report["render_inputs"][0]["sha256"] = acceptance.sha256_file(root / "s1.jpg")
            (root / "visual_validation.json").write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "karanlık"):
                acceptance.validate_v2_production_context(root, config)

        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            report = json.loads((root / "visual_validation.json").read_text(encoding="utf-8"))
            report["scenes"][0]["selected"]["semantic_similarity"] = float("nan")
            (root / "visual_validation.json").write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "sonlu"):
                acceptance.validate_v2_production_context(root, config)

        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            report = json.loads((root / "visual_validation.json").read_text(encoding="utf-8"))
            report["scenes"][0]["selected"]["score_origin"] = "pexels_metadata_overlap_proxy"
            (root / "visual_validation.json").write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "skor kökeni"):
                acceptance.validate_v2_production_context(root, config)

    def test_plain_background_cards_allowed_when_three_live_visuals_pass(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            report_path = root / "visual_validation.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            for index in range(3, 7):
                report["scenes"][index] = {
                    "fallback": "plain_background",
                    "fallback_reason": "no_candidate_passed_semantic_threshold_or_pixel_checks",
                }
            report_path.write_text(json.dumps(report), encoding="utf-8")
            result = acceptance.validate_v2_production_context(root, config)
            self.assertEqual(result["scene_count"], 7)

    def test_plain_background_cards_still_require_minimum_live_visuals(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            report_path = root / "visual_validation.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            for index in range(2, 7):
                report["scenes"][index] = {
                    "fallback": "plain_background",
                    "fallback_reason": "no_candidate_passed_semantic_threshold_or_pixel_checks",
                }
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "En az 3"):
                acceptance.validate_v2_production_context(root, config)

    def test_render_manifest_hashes_are_reopened_and_checked(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            config, _ = self._valid_context(root)
            for name, content in (("vo_final.wav", b"final-voice"),
                                  ("mix.wav", b"mixed-audio"),
                                  ("video.mp4", b"rendered-mp4")):
                (root / name).write_bytes(content)
            manifest = {
                "version": 2,
                "production_mode": "production_v2",
                "shorts_version": acceptance.SHORTS_VERSION,
                "template_version": acceptance.TEMPLATE_VERSION,
                "voice_provider": acceptance.VOICE_PROVIDER,
                "voice_provenance_status": acceptance.VOICE_PROVENANCE_STATUS,
                "voice_audit_sha256": acceptance.sha256_file(root / acceptance.VOICE_AUDIT_FILE),
                "voice_speed_factor": 1.0,
                "voice_raw_sha256": acceptance.sha256_file(root / "vo_raw.wav"),
                "voice_render_sha256": acceptance.sha256_file(root / "vo_final.wav"),
                "mix_sha256": acceptance.sha256_file(root / "mix.wav"),
                "mp4_sha256": acceptance.sha256_file(root / "video.mp4"),
                "images": [
                    {"file": name, "sha256": acceptance.sha256_file(root / name)}
                    for name in config["scenes"]
                ],
                "mp4_duration_seconds": 41.0,
            }
            (root / "render_manifest_v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            checked = acceptance.validate_render_manifest_v2(root, config, 41.0)
            self.assertEqual(checked["voice_provider"], acceptance.VOICE_PROVIDER)
            (root / "mix.wav").write_bytes(b"changed-mix")
            with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "mix_sha256"):
                acceptance.validate_render_manifest_v2(root, config, 41.0)

    def test_speed_factor_and_mp4_duration_gates(self):
        for value in (1.0, 1.05, 1.07, 1.10):
            config = {
                "shorts_version": acceptance.SHORTS_VERSION,
                "template_version": acceptance.TEMPLATE_VERSION,
                "production_mode": "production_v2",
                "voice_speed_factor": value,
                "intro_lead": 1.45,
                "sentence_pause": 0.54,
                "outro_hold": 1.45,
            }
            acceptance.validate_locked_mix_timing(config)
        for value in (0.99, 1.04, 1.07, 1.11):
            with self.subTest(value=value), tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
                root = Path(temp)
                config, _ = self._valid_context(root)
                config["voice_speed_factor"] = value
                with self.assertRaisesRegex(acceptance.ShortsAcceptanceError, "Gemini Charon sesinde tempo"):
                    acceptance.validate_v2_production_context(root, config)
        self.assertEqual(acceptance.validate_duration(41.0), 41.0)
        with self.assertRaises(acceptance.ShortsAcceptanceError):
            acceptance.validate_duration(float("nan"))
        with self.assertRaises(acceptance.ShortsAcceptanceError):
            acceptance.validate_duration(30.0)
        with self.assertRaises(acceptance.ShortsAcceptanceError):
            acceptance.validate_duration(50.0)


if __name__ == "__main__":
    unittest.main()
