import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import crosspost_worker as c
import delivery_diagnostics as d


class StatusClassificationTests(unittest.TestCase):
    def test_unverified_never_becomes_public_success(self):
        for platform, value in [
            ("instagram", None),
            ("instagram", "HATA: an exception with sensitive stuff"),
            ("instagram", "https://www.instagram.com/reel/abc123/"),
            ("tiktok", "https://www.tiktok.com/@bilgidozuofficial"),
        ]:
            self.assertIn("doğrulanmadı", d.classify(platform, value))

    def test_raw_error_and_foreign_html_never_leave_in_status(self):
        fake_secret = "sensitive-example"
        self.assertNotIn(fake_secret, d.classify("tiktok", "HATA: " + fake_secret))
        self.assertNotIn("<script>", d.classify("instagram", "<script>"))

    def test_append_preserves_buttons_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "last_upload_payload.json"
            path.write_text(json.dumps({"text": "kart", "reply_markup": {"inline_keyboard": [[1]]}}))
            self.assertTrue(d.append_to_payload(path, "video_200.mp4", {
                "tiktok": "https://www.tiktok.com/@bilgidozuofficial", "instagram": None
            }))
            obj = json.loads(path.read_text())
            self.assertIn(d.MARKER, obj["text"])
            self.assertEqual(obj["reply_markup"]["inline_keyboard"], [[1]])
            self.assertFalse(d.append_to_payload(path, "video_200.mp4", {}))
            self.assertEqual(obj, json.loads(path.read_text()))

    def test_long_missing_or_too_large_payload_are_not_changed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "payload.json"
            self.assertFalse(d.append_to_payload(path, "video_200.mp4", {}))
            payload = {"text": "a" * 3899}
            path.write_text(json.dumps(payload))
            self.assertFalse(d.append_to_payload(path, "video_200.mp4", {}))
            self.assertEqual(payload, json.loads(path.read_text()))
            path.write_text(json.dumps({"text": "kart"}))
            self.assertFalse(d.append_to_payload(path, "uzun_video_24.mp4", {}))


class DisabledCrosspostTests(unittest.TestCase):
    def test_explicit_flag_stays_off_even_if_drive_has_old_credentials(self):
        keys = {"CROSSPOST_ENABLED": "true", "TIKTOK_ENABLED": "true", "IG_SESSIONID": "old-ig", "TIKTOK_SESSIONID": "old-tt"}
        with patch.dict(os.environ, {"CROSSPOST_ENABLED": "false"}, clear=True), \
             patch.object(c, "_load_drive_keys", return_value=keys), \
             patch.object(c, "post_instagram") as ig, \
             patch.object(c, "post_tiktok") as tt:
            result = c.run_crosspost(Path("/not/real.mp4"), "video_200.mp4", "", drive=object())
            ig.assert_not_called()
            tt.assert_not_called()
            self.assertEqual(result, {"instagram": None, "tiktok": None, "status": "disabled_by_user"})

    def test_drive_flag_off_does_not_post_even_when_sessions_are_present(self):
        keys = {"CROSSPOST_ENABLED": "false", "TIKTOK_ENABLED": "true", "IG_SESSIONID": "old-ig", "TIKTOK_SESSIONID": "old-tt"}
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(c, "_load_drive_keys", return_value=keys), \
             patch.object(c, "post_instagram") as ig, \
             patch.object(c, "post_tiktok") as tt:
            c.run_crosspost(Path("/not/real.mp4"), "video_200.mp4", "", drive=object())
            ig.assert_not_called()
            tt.assert_not_called()

if __name__ == "__main__":
    unittest.main()
