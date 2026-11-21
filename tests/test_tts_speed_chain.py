import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
(ROOT / ".agent_tmp").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "motor"))

import tts  # noqa: E402


def _write_wav(path: Path, seconds: float = 1.0, sample_rate: int = 48000):
    frames = int(seconds * sample_rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0\0" * frames)


class TtsSpeedChainTests(unittest.TestCase):
    def test_normal_and_energetic_speed_factors_are_explicit_only(self):
        self.assertEqual(tts._voice_speed_factor({"ses": {"voice_speed_factor": 1.0}}), 1.0)
        self.assertEqual(tts._voice_speed_factor({"ses": {"voice_speed_factor": 1.07}}), 1.07)
        for value in (0.95, 1.05, 1.06, 1.08, float("nan")):
            with self.subTest(value=value), self.assertRaises(tts.SesHatasi):
                tts._voice_speed_factor({"ses": {"voice_speed_factor": value}})

    def test_global_final_stage_uses_zero_or_exactly_one_atempo(self):
        for factor, expected_filter in ((1.0, None), (1.07, "atempo=1.070")):
            with self.subTest(factor=factor), tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
                root = Path(temp)
                source = root / "voice.wav"
                source.write_bytes(b"fixture-voice")

                def fake_ffmpeg(command, **_kwargs):
                    Path(command[-1]).write_bytes(b"normalized-wave")

                with mock.patch.object(tts, "_ffmpeg_executable", return_value="ffmpeg-fixture"), \
                     mock.patch.object(tts.subprocess, "run", side_effect=fake_ffmpeg) as run:
                    tts._normalize_generated_audio(source, factor)

                command = run.call_args.args[0]
                filter_args = [command[i + 1] for i, item in enumerate(command[:-1]) if item == "-af"]
                if expected_filter is None:
                    self.assertEqual(filter_args, [])
                else:
                    self.assertEqual(filter_args, [expected_filter])
                self.assertEqual(sum("atempo=" in item for item in command), 1 if expected_filter else 0)
                self.assertEqual(source.read_bytes(), b"normalized-wave")

    def test_speechify_word_times_scale_with_speed_and_audio_metadata_is_refreshed(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            audio_path = Path(temp) / "speechify.wav"
            _write_wav(audio_path, seconds=1.0)
            alignment = {
                "audio_sha256": "old-hash",
                "audio_duration_seconds": 1.07,
                "words": [
                    {"word": "ilk", "start": 0.107, "end": 0.321, "probability": 1.0},
                    {"word": "ikinci", "start": 0.535, "end": 0.963, "probability": 1.0},
                ],
            }
            updated = tts._update_speechify_alignment(alignment, audio_path, 1.07)
            self.assertAlmostEqual(updated["words"][0]["start"], 0.1, places=3)
            self.assertAlmostEqual(updated["words"][0]["end"], 0.3, places=3)
            self.assertAlmostEqual(updated["words"][1]["start"], 0.5, places=3)
            self.assertAlmostEqual(updated["words"][1]["end"], 0.9, places=3)
            self.assertEqual(updated["audio_duration_seconds"], 1.0)
            self.assertEqual(updated["audio_sha256"], tts._sha256(audio_path))
            self.assertEqual(updated["speed_factor"], 1.07)


if __name__ == "__main__":
    unittest.main()
