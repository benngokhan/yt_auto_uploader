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
            "Mum söner, yakıt kalır.",
            "Balmumu havaya karışır.",
            "Soğuyunca damla oluşur.",
            "Duman yakıt zerrecikleridir.",
            "Kıvılcım onları tutuşturur.",
            "Yakıt dumanın içindedir.",
            "Daha fazla Bilgi Dozu için takip et!",
        ]
        return [{"ses": line, "baslik1": f"SAHNE {i}", "baslik2": "BİLİM"}
                for i, line in enumerate(lines, start=1)]

    def test_plan_only_writes_seven_scenes_without_audio_or_render(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            motor_root = Path(temp) / "motor"
            args = SimpleNamespace(konu="mum dumanı", plan_only=True, sadece_ses=False, kuru=True)
            no_audio_or_render = AssertionError("plan-only called an audio/render path")
            with mock.patch.object(uret, "MOTOR", motor_root), \
                 mock.patch.object(uret, "sahne_plani_v2", return_value=self._scenes()), \
                 mock.patch.object(uret, "_arsivle_senaryo"), \
                 mock.patch.object(uret, "_terim_birligi_sagla"), \
                 mock.patch.object(uret, "_sayi_denetimi"), \
                 mock.patch.object(uret, "_yazim_denetimi"), \
                 mock.patch.object(uret, "_baslik_denetimi"), \
                 mock.patch.object(uret, "_senaryo_son_kapi"), \
                 mock.patch.object(uret, "_baslik_anlam_denetimi"), \
                 mock.patch.object(uret, "_copy_arena_voice_audio", side_effect=no_audio_or_render), \
                 mock.patch.object(uret.subprocess, "run", side_effect=no_audio_or_render):
                result = uret._sablon_v2_uret(args, {"sahne_sayisi": 7}, 7)
            self.assertEqual(result, 0)
            plan = json.loads((motor_root / "cikti" / "plan_only" / "shorts_v2_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["scene_count"], 7)
            self.assertEqual(len(plan["script_lines"]), 7)
            self.assertTrue(plan["plan_only"])
            self.assertEqual(plan["voice_speed_factor"], 1.0)
            self.assertFalse((motor_root / "cikti" / "son" / "v2" / "vo_raw.wav").exists())

    def test_arena_import_fails_closed_when_voice_asset_is_missing(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp, \
             mock.patch.dict(os.environ, {"MIRA_ARENA_AUDIO_FILE": "", "MIRA_ARENA_VOICE_ID": ""}):
            with self.assertRaisesRegex(SystemExit, "no legacy-TTS fallback"):
                uret._copy_arena_voice_audio(["voice text"], Path(temp) / "v2")

    def test_arena_import_records_audio_and_script_hashes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            source = root / "arena.wav"
            source.write_bytes(b"arena-live-audio")
            output = root / "v2"
            lines = [f"Sahne {i}." for i in range(1, 8)]
            with mock.patch.dict(os.environ, {
                "MIRA_ARENA_AUDIO_FILE": str(source),
                "MIRA_ARENA_VOICE_ID": "voice-00",
                "MIRA_ARENA_VOICE_LANGUAGE": "tr",
            }):
                raw = uret._copy_arena_voice_audio(lines, output)
            manifest = json.loads((output / "voice_provenance_v2.json").read_text(encoding="utf-8"))
            narration = " ".join(lines)
            self.assertEqual(raw.read_bytes(), source.read_bytes())
            self.assertEqual(manifest["provider"], "arena.generate_speech")
            self.assertEqual(manifest["generation"], "caller_supplied")
            self.assertEqual(manifest["provenance_status"], "caller_attested_unverified")
            self.assertEqual(manifest["audio_sha256"], shorts_acceptance.sha256_file(raw))
            self.assertEqual(manifest["narration_sha256"], hashlib.sha256(narration.encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
