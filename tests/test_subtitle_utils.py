import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "motor"))

from subtitle_utils import SubtitleFitError, clean_subtitle_block  # noqa: E402
import render_engine  # noqa: E402
import shorts_pipeline  # noqa: E402


class SubtitleCleanupTests(unittest.TestCase):
    def test_scene_and_numeric_labels_are_removed_without_losing_caption_words(self):
        raw = "  Sahne 3:   Beyin, derideki damarları daraltır ve sinirlere hızlıca sinyal gönderir.  "
        cleaned = clean_subtitle_block(raw)
        self.assertEqual(cleaned, "Beyin, derideki damarları daraltır ve\nsinirlere hızlıca sinyal gönderir.")
        self.assertEqual(cleaned.replace("\n", " ").split(),
                         ["Beyin,", "derideki", "damarları", "daraltır", "ve", "sinirlere", "hızlıca", "sinyal", "gönderir."])
        self.assertEqual(clean_subtitle_block("[Scene 4] Cells release energy."),
                         "Cells release energy.")
        self.assertEqual(clean_subtitle_block("2) Güneş ışığı yapraklara ulaşır."),
                         "Güneş ışığı yapraklara ulaşır.")

    def test_long_text_wraps_at_word_boundaries_without_truncation(self):
        words = "Bu açıklama, kısa videodaki bütün önemli ayrıntıları izleyiciye eksiksiz aktarır.".split()
        cleaned = clean_subtitle_block(" ".join(words))
        self.assertLessEqual(len(cleaned.splitlines()), 2)
        self.assertTrue(all(len(line) <= 42 for line in cleaned.splitlines()))
        self.assertEqual(cleaned.replace("\n", " ").split(), words)

    def test_unfit_caption_and_unbreakable_token_fail_instead_of_clipping(self):
        with self.assertRaises(SubtitleFitError):
            clean_subtitle_block(" ".join(["kelime"] * 30))
        with self.assertRaises(SubtitleFitError):
            clean_subtitle_block("A" * 43)

    def test_scene_captions_are_cleaned_before_word_alignment(self):
        scenes = [{"subs": [("Sahne 7: Ses dalgaları havada hızla ve düzenli biçimde yayılır.", ["dalgaları"])]}]
        cleaned = render_engine.clean_scenes_subtitles(scenes)
        self.assertEqual(cleaned[0]["subs"][0][0], "Ses dalgaları havada hızla ve düzenli\nbiçimde yayılır.")
        self.assertEqual(cleaned[0]["subs"][0][1], ["dalgaları"])
        self.assertEqual(scenes[0]["subs"][0][0], "Sahne 7: Ses dalgaları havada hızla ve düzenli biçimde yayılır.")
        rendered = render_engine.make_subtitle_band(1080, "Sahne 2: Ses dalgaları yayılır.")
        self.assertEqual(rendered.shape, (120, 1080, 4))

    def test_active_v2_renderer_strips_scene_prefix_and_keeps_karaoke_word_index(self):
        with_prefix = {
            "tokens": [
                {"text": "Sahne"}, {"text": "2:"}, {"text": "Ses"},
                {"text": "dalgaları"}, {"text": "yayılır."},
            ],
            "l1_count": 3,
        }
        without_prefix = {
            "tokens": [{"text": "Ses"}, {"text": "dalgaları"}, {"text": "yayılır."}],
            "l1_count": 1,
        }
        rendered_with_prefix = shorts_pipeline.render_subtitle_state(with_prefix, 2)
        rendered_without_prefix = shorts_pipeline.render_subtitle_state(without_prefix, 0)
        self.assertEqual(rendered_with_prefix.tobytes(), rendered_without_prefix.tobytes())

    def test_scene_caption_overflow_fails_before_render(self):
        scenes = [{"subs": [(" ".join(["kelime"] * 30), [])]}]
        with self.assertRaises(SubtitleFitError):
            render_engine.clean_scenes_subtitles(scenes)
        oversized = {"tokens": [{"text": "A" * 43}], "l1_count": 1}
        with self.assertRaises(SubtitleFitError):
            shorts_pipeline.render_subtitle_state(oversized, 0)


if __name__ == "__main__":
    unittest.main()
