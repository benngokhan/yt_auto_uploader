import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
(ROOT / ".agent_tmp").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "motor"))

import uret  # noqa: E402
import shorts_acceptance  # noqa: E402


class V2OrchestratorTests(unittest.TestCase):
    def _scenes(self):
        lines = [
            "Mum alevi kapalı bir yerde neden söner?",
            "Fitil eriyen balmumunu yukarı doğru sürekli taşır.",
            "Isınan balmumu buharı çevredeki oksijenle birlikte yanar.",
            "Oksijen azalınca yanma yavaşlar ve alev söner.",
            "Peki mum alevi oksijen olmadan yanabilir mi?",
]
        scenes = [{"ses": line, "baslik1": f"SAHNE {i}", "baslik2": "BİLİM"}
                  for i, line in enumerate(lines, start=1)]
        scenes[0]["_v2_metadata"] = {
            "title_question": "Mum alevi neden söner?",
            "cover_lines": ["MUM ALEVİ NEDEN", "SÖNER?"],
            "loop_anchor": "mum",
            "source_url": "",
            "topic_filter": {"score": 100, "accepted": True},
        }
        return scenes

    def test_v2_planner_accepts_hook_loop_title_and_cover_from_formatted_prompt(self):
        lines = [scene["ses"] for scene in self._scenes()]
        response = {
            "title_question": "Mum alevi neden söner?",
            "kapak_baslik": ["MUM ALEVİ NEDEN", "SÖNER?"],
            "loop_anchor": "mum",
            "kaynak_url": "",
            "cumleler": lines,
            "sahne_basliklari": [
                {"ikon": "?", "satir1": f"BİLGİ {i}", "satir2": "MUM ALEVİ"}
                for i in range(1, 5)
            ],
        }
        with (
            mock.patch.object(uret, "_llm_json", return_value=response),
            mock.patch.object(uret, "_arsivle"),
            mock.patch("builtins.print"),
        ):
            scenes = uret.sahne_plani_v2("mum alevi", 4, {})
        self.assertEqual(len(scenes), 5)
        self.assertEqual([scene["ses"] for scene in scenes], lines)
        self.assertEqual(scenes[0]["_v2_metadata"]["loop_anchor"], "mum")
        self.assertNotIn("takip et", scenes[-1]["ses"].lower())

    def test_plan_only_writes_five_beats_without_audio_or_render(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            motor_root = Path(temp) / "motor"
            args = SimpleNamespace(konu="mum alevi", plan_only=True, sadece_ses=False, kuru=True)
            no_audio_or_render = AssertionError("plan-only called an audio/render path")
            settings = {
                "sahne_sayisi": 4,
                "ses": {
                    "saglayici": "gemini_tts",
                    "voice_id": "Charon",
                    "model": "gemini-2.5-flash-preview-tts",
                    "dil": "tr",
                    "voice_speed_factor": 1.0,
                },
            }
            with mock.patch.object(uret, "MOTOR", motor_root), \
                 mock.patch.object(uret, "sahne_plani_v2", return_value=self._scenes()), \
                 mock.patch.object(uret, "_arsivle_senaryo"), \
                 mock.patch.object(uret, "_terim_birligi_sagla"), \
                 mock.patch.object(uret, "_sayi_denetimi"), \
                 mock.patch.object(uret, "_yazim_denetimi"), \
                 mock.patch.object(uret, "_baslik_denetimi"), \
                 mock.patch.object(uret, "_senaryo_son_kapi"), \
                 mock.patch.object(uret, "_baslik_anlam_denetimi"), \
                 mock.patch.object(uret, "_generate_gemini_v2_voice_audio", side_effect=no_audio_or_render), \
                 mock.patch.object(uret.subprocess, "run", side_effect=no_audio_or_render):
                result = uret._sablon_v2_uret(args, settings, 4)
            self.assertEqual(result, 0)
            plan = json.loads((motor_root / "cikti" / "plan_only" / "shorts_v2_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["scene_count"], 4)
            self.assertEqual(len(plan["script_lines"]), 5)
            self.assertTrue(plan["plan_only"])
            self.assertEqual(plan["voice_speed_factor"], 1.0)
            self.assertEqual(plan["voice_provider"], "gemini_tts")
            self.assertEqual(plan["voice_id"], "Charon")
            self.assertEqual(plan["voice_generation"], "not_run_plan_only")
            self.assertFalse((motor_root / "cikti" / "son" / "v2" / "vo_raw.wav").exists())

    @staticmethod
    def _tts_settings():
        return {
            "ses": {
                "saglayici": "gemini_tts",
                "voice_id": "Charon",
                "model": "gemini-2.5-flash-preview-tts",
                "dil": "tr",
                "voice_speed_factor": 1.0,
            }
        }

    def test_gemini_charon_tts_generation_records_audio_and_script_hashes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            output = root / "v2"
            lines = [f"Sahne {i}." for i in range(1, 6)]
            generated_text = "\n".join(lines)
            tts_mock = mock.Mock()

            def generate(text, path, settings):
                self.assertEqual(text, generated_text)
                self.assertEqual(settings["ses"]["voice_id"], "Charon")
                Path(path).write_bytes(b"gemini-charon-audio")

            tts_mock.uret.side_effect = generate
            with mock.patch.dict(sys.modules, {"tts": tts_mock}):
                raw = uret._generate_gemini_v2_voice_audio(lines, output, self._tts_settings())
            manifest = json.loads((output / "voice_provenance_v2.json").read_text(encoding="utf-8"))
            narration = " ".join(lines)
            self.assertEqual(raw.read_bytes(), b"gemini-charon-audio")
            self.assertEqual(manifest["provider"], "gemini_tts")
            self.assertEqual(manifest["generation"], "motor.tts.uret")
            self.assertEqual(manifest["provenance_status"], "local_tts_call_unverified")
            self.assertEqual(manifest["voice_id"], "Charon")
            self.assertEqual(manifest["model"], "gemini-2.5-flash-preview-tts")
            self.assertEqual(manifest["audio_sha256"], shorts_acceptance.sha256_file(raw))
            self.assertEqual(manifest["narration_sha256"], hashlib.sha256(narration.encode()).hexdigest())

    def test_v2_rejects_non_gemini_or_non_charon_voice_before_tts_call(self):
        for key, value in (("saglayici", "speechify"), ("voice_id", "voice-00"), ("voice_speed_factor", 1.07)):
            with self.subTest(key=key, value=value):
                settings = self._tts_settings()
                settings["ses"][key] = value
                tts_mock = mock.Mock()
                with mock.patch.dict(sys.modules, {"tts": tts_mock}):
                    with self.assertRaises(shorts_acceptance.ShortsAcceptanceError):
                        uret._generate_gemini_v2_voice_audio(
                            [f"Sahne {i}." for i in range(1, 6)], Path("unused-test-output"), settings
                        )
                tts_mock.uret.assert_not_called()


if __name__ == "__main__":
    unittest.main()
