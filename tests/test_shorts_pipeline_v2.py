import sys
import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
(ROOT / ".agent_tmp").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "motor"))

import shorts_pipeline  # noqa: E402


def _write_voice_wav(path: Path, sample_rate: int = 44100):
    samples = array("h", [600] * (sample_rate // 10))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples.tobytes())


class VoiceSpeedProcessingTests(unittest.TestCase):
    def test_normal_control_copies_original_wav_without_filtering(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            source, target = root / "voice.wav", root / "normal.wav"
            _write_voice_wav(source)
            with mock.patch.object(shorts_pipeline.subprocess, "run") as run:
                shorts_pipeline.prepare_voice_wav(str(source), str(target), 1.0)
            run.assert_not_called()
            self.assertEqual(source.read_bytes(), target.read_bytes())

    def test_arena_format_conversion_never_adds_atempo(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            source, target = root / "voice.wav", root / "normalized.wav"
            _write_voice_wav(source, sample_rate=22050)
            source_bytes = source.read_bytes()

            def fake_ffmpeg(command, **_kwargs):
                self.assertNotIn("-af", command)
                self.assertNotIn("atempo", " ".join(command))
                _write_voice_wav(target, sample_rate=44100)

            with mock.patch.object(shorts_pipeline.subprocess, "run", side_effect=fake_ffmpeg) as run:
                shorts_pipeline.prepare_voice_wav(str(source), str(target), 1.0)
            command = run.call_args.args[0]
            self.assertIn("44100", command)
            self.assertEqual(source.read_bytes(), source_bytes)

    def test_arena_rejects_speed_change_before_ffmpeg(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            source, target = root / "voice.wav", root / "bad.wav"
            _write_voice_wav(source)
            with mock.patch.object(shorts_pipeline.subprocess, "run") as run:
                with self.assertRaisesRegex(shorts_pipeline.ShortsAcceptanceError, "Arena sesi 1.00x"):
                    shorts_pipeline.prepare_voice_wav(str(source), str(target), 1.07)
            run.assert_not_called()

    def test_non_arena_provider_is_rejected_by_v2_voice_preparation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            source, target = root / "voice.wav", root / "non_arena.wav"
            _write_voice_wav(source)
            with mock.patch.object(shorts_pipeline.subprocess, "run") as run:
                with self.assertRaisesRegex(shorts_pipeline.ShortsAcceptanceError, "yalnız Arena"):
                    shorts_pipeline.prepare_voice_wav(str(source), str(target), 1.07, provider="tts")
            run.assert_not_called()

    def test_invalid_speed_rejected_before_ffmpeg(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            source, target = root / "voice.wav", root / "bad.wav"
            _write_voice_wav(source)
            with mock.patch.object(shorts_pipeline.subprocess, "run") as run:
                with self.assertRaises(shorts_pipeline.ShortsAcceptanceError):
                    shorts_pipeline.prepare_voice_wav(str(source), str(target), 1.04)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
