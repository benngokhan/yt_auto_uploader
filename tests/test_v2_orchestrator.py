import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
(ROOT / ".agent_tmp").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "motor"))

import ses_olcum  # noqa: E402
import shorts_acceptance  # noqa: E402
import uret  # noqa: E402


def _tts_module(generator):
    """Gerçek TTS bağımlılığı olmadan uret'in içe aktardığı modülü taklit et."""
    modul = ModuleType("tts")
    modul.uret = generator
    return modul


def _ayar():
    return {"ses": {
        "saglayici": "gemini_tts",
        "voice_id": "Charon",
        "model": "gemini-2.5-flash-preview-tts",
        "dil": "tr",
        "voice_speed_factor": 1.0,
    }}


def _fake_tts(_metin, cikti, _ayar):
    cikti = Path(cikti)
    cikti.parent.mkdir(parents=True, exist_ok=True)
    cikti.write_bytes(b"islenmis-gemini-ses")
    cikti.with_name("vo_raw.gemini_ham24k.wav").write_bytes(b"ham-gemini-pcm")
    return None


def _no_audio(*_args, **_kwargs):
    raise AssertionError("API called")


def _olcum(f0=127.0):
    return {
        "dosya": "vo_raw.gemini_ham24k.wav",
        "ornekleme_hz": 24000,
        "sure_sn": 10.0,
        "f0_medyan_hz": f0,
        "f0_yuzde10_hz": f0 - 5,
        "f0_yuzde90_hz": f0 + 5,
        "f0_pencere_sayisi": 100,
        "parlaklik_hz": 1000.0,
        "rms_db": -20.0,
    }


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
                 mock.patch.object(uret, "_generate_gemini_voice_audio", side_effect=no_audio_or_render), \
                 mock.patch.object(uret.subprocess, "run", side_effect=no_audio_or_render):
                result = uret._sablon_v2_uret(args, _ayar(), 7)
            self.assertEqual(result, 0)
            plan = json.loads((motor_root / "cikti" / "plan_only" / "shorts_v2_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["scene_count"], 7)
            self.assertEqual(len(plan["script_lines"]), 7)
            self.assertTrue(plan["plan_only"])
            self.assertEqual(plan["voice_speed_factor"], 1.0)
            self.assertFalse((motor_root / "cikti" / "son" / "v2" / "vo_raw.wav").exists())

    def test_wrong_provider_or_voice_fails_closed_before_any_audio(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            output = Path(temp) / "v2"
            ayar = _ayar()
            ayar["ses"]["saglayici"] = "tts"
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), \
                 mock.patch.dict(sys.modules, {"tts": _tts_module(_no_audio)}):
                with self.assertRaisesRegex(SystemExit, "ses sağlayıcısı gemini_tts"):
                    uret._generate_gemini_voice_audio(["Sahne."], output, ayar)

            ayar = _ayar()
            ayar["ses"]["voice_id"] = "Arena"
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), \
                 mock.patch.dict(sys.modules, {"tts": _tts_module(_no_audio)}):
                with self.assertRaisesRegex(SystemExit, "Ses kimliği Charon"):
                    uret._generate_gemini_voice_audio(["Sahne."], output, ayar)

    def test_gemini_voice_records_hashes_and_passes_audit(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            output = Path(temp) / "v2"
            lines = [f"Sahne {i}." for i in range(1, 8)]
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), \
                 mock.patch.dict(sys.modules, {"tts": _tts_module(_fake_tts)}), \
                 mock.patch.object(ses_olcum, "olc", return_value=_olcum()):
                raw = uret._generate_gemini_voice_audio(lines, output, _ayar())

            manifest = json.loads((output / "voice_provenance_v2.json").read_text(encoding="utf-8"))
            audit = json.loads((output / shorts_acceptance.VOICE_AUDIT_FILE).read_text(encoding="utf-8"))
            narration = " ".join(lines)
            self.assertTrue(raw.is_file())
            self.assertEqual(manifest["provider"], "gemini_tts")
            self.assertEqual(manifest["generation"], "live_gemini_tts")
            self.assertEqual(manifest["provenance_status"], "live_gemini_generated")
            self.assertEqual(manifest["voice_id"], "Charon")
            self.assertEqual(manifest["narration_sha256"], hashlib.sha256(narration.encode()).hexdigest())
            self.assertEqual(manifest["audio_sha256"], shorts_acceptance.sha256_file(raw))
            self.assertEqual(manifest["voice_audit_sha256"],
                             shorts_acceptance.sha256_file(output / shorts_acceptance.VOICE_AUDIT_FILE))
            self.assertTrue(audit["passed"])
            self.assertFalse(audit["uyari"])
            self.assertEqual(audit["f0_medyan_hz"], 127.0)
            self.assertEqual(audit["raw_sha256"],
                             shorts_acceptance.sha256_file(output / shorts_acceptance.VOICE_RAW_HAM_FILE))

    def test_voice_pitch_warning_does_not_stop_production(self):
        # Sahip kararı: f0 sapması yalnız ölçüm/uyarı; Charon kimliği kanıtlarla korunur.
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            output = Path(temp) / "v2"
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), \
                 mock.patch.dict(sys.modules, {"tts": _tts_module(_fake_tts)}), \
                 mock.patch.object(ses_olcum, "olc", return_value=_olcum(100.0)):
                uret._generate_gemini_voice_audio(["Sahne."], output, _ayar())
            audit = json.loads((output / shorts_acceptance.VOICE_AUDIT_FILE).read_text(encoding="utf-8"))
            self.assertTrue(audit["passed"])
            self.assertTrue(audit["uyari"])
            self.assertEqual(audit["voice_id"], "Charon")


if __name__ == "__main__":
    unittest.main()
