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

    def test_gemini_charon_format_conversion_never_adds_atempo(self):
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

    def test_gemini_charon_rejects_speed_change_before_ffmpeg(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            source, target = root / "voice.wav", root / "bad.wav"
            _write_voice_wav(source)
            with mock.patch.object(shorts_pipeline.subprocess, "run") as run:
                with self.assertRaisesRegex(shorts_pipeline.ShortsAcceptanceError, "Gemini/Charon sesi 1.00x"):
                    shorts_pipeline.prepare_voice_wav(str(source), str(target), 1.07)
            run.assert_not_called()

    def test_arena_provider_is_rejected_by_v2_voice_preparation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            source, target = root / "voice.wav", root / "other_provider.wav"
            _write_voice_wav(source)
            with mock.patch.object(shorts_pipeline.subprocess, "run") as run:
                with self.assertRaisesRegex(shorts_pipeline.ShortsAcceptanceError, "yalnız Gemini Natural TTS/Charon"):
                    shorts_pipeline.prepare_voice_wav(
                        str(source), str(target), 1.0, provider="arena.generate_speech"
                    )
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

    def test_hook_trim_removes_only_leading_silence_without_resampling_or_stretching(self):
        import numpy as np

        sample_rate = 1000
        signal = np.concatenate((np.zeros(350), np.full(650, 0.1)))
        trimmed, offset = shorts_pipeline.trim_leading_silence(signal, sample_rate)
        self.assertAlmostEqual(offset, 0.32, places=2)
        self.assertEqual(len(trimmed), len(signal) - 320)
        self.assertEqual(trimmed[-1], signal[-1])
        self.assertAlmostEqual(trimmed[0], 0.0)

    def test_hook_trim_leaves_audio_with_no_leading_silence_unchanged_and_rejects_long_gap(self):
        import numpy as np

        signal = np.full(1000, 0.1)
        trimmed, offset = shorts_pipeline.trim_leading_silence(signal, 1000)
        self.assertEqual(offset, 0.0)
        self.assertTrue(np.array_equal(trimmed, signal))
        long_gap = np.concatenate((np.zeros(1000), signal))
        with self.assertRaisesRegex(shorts_pipeline.ShortsAcceptanceError, "başlangıç sessizliği"):
            shorts_pipeline.trim_leading_silence(long_gap, 1000)


if __name__ == "__main__":
    unittest.main()

class LocalRenderIntegrationTests(unittest.TestCase):
    def test_five_beat_loop_renders_locally_without_external_calls(self):
        """Synthetic audio/images; proves timing, compositing and ffmpeg, not live APIs."""
        import json
        import math
        import shutil
        import subprocess
        import numpy as np
        from PIL import Image
        from test_shorts_acceptance import ShortsV2GateTests, SCRIPT_LINES
        from shorts_acceptance import sha256_file

        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg and ffprobe required for local render integration")
        with tempfile.TemporaryDirectory(dir=ROOT / ".agent_tmp") as temp:
            root = Path(temp)
            cfg, _ = ShortsV2GateTests()._valid_context(root)
            colors = [(230, 90, 80), (70, 200, 100), (90, 110, 230), (220, 200, 80)]
            report_path = root / "visual_validation.json"
            report = json.loads(report_path.read_text())
            for i, color in enumerate(colors):
                name = cfg['scenes'][i]
                Image.new('RGB', (90, 160), color).save(root / name)
                report['render_inputs'][i]['sha256'] = sha256_file(root / name)
            report_path.write_text(json.dumps(report))
            # A tone is NOT real speech: timestamps below are deterministic synthetic alignment.
            sr = shorts_pipeline.SR
            audio = (np.sin(2 * math.pi * 220 * np.arange(20 * sr) / sr) * 0.1)
            shorts_pipeline.write_wav_mono(str(root / 'vo_raw.wav'), audio, sr)
            voice_path = root / 'voice_provenance_v2.json'
            voice = json.loads(voice_path.read_text())
            voice['audio_sha256'] = sha256_file(root / 'vo_raw.wav')
            voice_path.write_text(json.dumps(voice))
            boundaries = [0, 4, 7, 12, 16, 19.98]
            fake_words = []
            for i, line in enumerate(SCRIPT_LINES):
                words = line.split()
                start = boundaries[i] + (0.01 if i == 0 else 0.1)
                end = boundaries[i+1] - 0.1
                step = (end - start) / len(words)
                fake_words.extend({'w': w, 's': start+j*step, 'e': start+(j+1)*step-0.01}
                                  for j, w in enumerate(words))

            def local_mix(work_dir, tl, cfg=None):
                result = Path(work_dir) / 'mix.wav'
                shutil.copyfile(Path(work_dir) / 'vo_spaced.wav', result)
                return str(result)

            with (mock.patch.object(shorts_pipeline, '_resolve_context', return_value=(str(root), cfg, None)),
                  mock.patch.object(shorts_pipeline, '_try_whisper_words', return_value=fake_words),
                  mock.patch.object(shorts_pipeline, 'W', 180),
                  mock.patch.object(shorts_pipeline, 'H', 320),
                  mock.patch.object(shorts_pipeline, 'S_SCALE', 180/1080),
                  mock.patch.object(shorts_pipeline, 'FPS', 5),
                  mock.patch.object(shorts_pipeline, 'build_mix', side_effect=local_mix)):
                shorts_pipeline.stage_timing(str(root))
                tl = json.loads((root / 'timing.json').read_text())
                self.assertEqual([s['file'] for s in tl['scenes']], ['s1.jpg','s2.jpg','s3.jpg','s4.jpg','s1.jpg'])
                self.assertEqual([s['cta_overlay'] for s in tl['scenes']], [None, 'Takip et', None, None, None])
                self.assertGreater(tl['scenes'][1]['start'], 3.5)
                self.assertLess(tl['scenes'][1]['end'], 7.5)
                shorts_pipeline.stage_plates(str(root))
                shorts_pipeline.render_video(str(root))
            manifest = json.loads((root / 'render_manifest_v2.json').read_text())
            self.assertEqual(manifest['visual_sequence'], [0,1,2,3,0])
            self.assertEqual(manifest['cta_overlay_text'], 'Takip et')
            self.assertEqual(len(manifest['images']), 4)
            self.assertGreater((root / 'video.mp4').stat().st_size, 0)
            # Decode representative frames and check the dominant background returns to image 1.
            decoded = {}
            for second, dominant in [(1,'r'), (5,'g'), (9,'b'), (18,'r')]:
                result = subprocess.run([shutil.which('ffmpeg'), '-v','error', '-ss',str(second),
                    '-i',str(root / 'video.mp4'), '-frames:v','1', '-f','image2pipe', '-vcodec','png','-'],
                    capture_output=True, check=True)
                from io import BytesIO
                image = Image.open(BytesIO(result.stdout)).convert('RGB')
                decoded[second] = image
                red, green, blue = image.getpixel((8, 80))
                self.assertEqual(('r','g','b')[[red,green,blue].index(max(red,green,blue))], dominant)
            # At the CTA panel edge there is a dark overlay only during beat 2.
            self.assertLess(sum(decoded[5].getpixel((90, 239))), 100)
            self.assertGreater(sum(decoded[9].getpixel((90, 239))), 200)
