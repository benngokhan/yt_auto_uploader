import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import crosspost_worker as worker
import delivery_diagnostics as diagnostics


FLAGS = {
    "CROSSPOST_ENABLED": "true",
    "TIKTOK_ENABLED": "true",
    "INSTAGRAM_ENABLED": "true",
    "TIKTOK_SESSIONID": "fresh-tiktok-session",
    "IG_SESSIONID": "fresh-instagram-session",
}


class CrosspostOwnerDecisionTests(unittest.TestCase):
    def test_global_kill_switch_still_wins(self):
        flags = dict(FLAGS, CROSSPOST_ENABLED="false")
        drive = Mock(name="drive")
        with patch.dict(os.environ, flags, clear=True), \
             patch.object(worker, "_load_drive_keys") as load, \
             patch.object(worker, "_hydrate_env_from_keys") as hydrate, \
             patch.object(worker, "post_instagram") as instagram, \
             patch.object(worker, "post_tiktok") as tiktok, \
             patch.object(worker, "_send_telegram_note") as telegram:
            self.assertFalse(worker.crosspost_enabled())
            result = worker.run_crosspost(Path("/not/real.mp4"), "video_200.mp4", "", drive=drive)
        self.assertEqual(result, {"instagram": None, "tiktok": None, "status": "disabled_by_user"})
        for fn in (load, hydrate, instagram, tiktok, telegram):
            fn.assert_not_called()
        self.assertEqual(drive.mock_calls, [])

    def test_tiktok_only_instagram_stays_locked(self):
        drive = Mock(name="drive")
        with patch.dict(os.environ, FLAGS, clear=True), \
             patch.object(worker, "_load_drive_keys") as load, \
             patch.object(worker, "post_instagram") as instagram, \
             patch.object(worker, "post_tiktok", return_value="https://www.tiktok.com/@bilgidozuofficial") as tiktok, \
             patch.object(worker, "_send_telegram_note") as telegram:
            self.assertTrue(worker.crosspost_enabled())
            result = worker.run_crosspost(Path("/not/real.mp4"), "video_200.mp4", "", drive=drive)
        load.assert_not_called()
        instagram.assert_not_called()
        tiktok.assert_called_once()
        telegram.assert_called_once()
        self.assertEqual(result["tiktok"], "https://www.tiktok.com/@bilgidozuofficial")
        self.assertIsNone(result["instagram"])
        self.assertEqual(drive.mock_calls, [])

    def test_no_tiktok_session_means_no_upload(self):
        flags = dict(FLAGS)
        flags.pop("TIKTOK_SESSIONID")
        with patch.dict(os.environ, flags, clear=True), \
             patch.object(worker, "_load_drive_keys", return_value={}), \
             patch.object(worker, "post_tiktok") as tiktok, \
             patch.object(worker, "_send_telegram_note"):
            self.assertFalse(worker.crosspost_enabled())
            result = worker.run_crosspost(Path("/not/real.mp4"), "video_200.mp4", "", drive=object())
        tiktok.assert_not_called()
        self.assertEqual(result, {"instagram": None, "tiktok": None})

    def test_instagram_entrypoint_ignores_all_flags(self):
        with patch.dict(os.environ, FLAGS, clear=True):
            self.assertIsNone(worker.post_instagram(Path("/missing.mp4"), "test"))

    def test_long_video_is_not_crossposted(self):
        with patch.dict(os.environ, FLAGS, clear=True), \
             patch.object(worker, "post_tiktok") as tiktok, \
             patch.object(worker, "_send_telegram_note") as telegram:
            result = worker.run_crosspost(Path("/not/real.mp4"), "uzun_video_24.mp4", "")
        tiktok.assert_not_called()
        telegram.assert_not_called()
        self.assertEqual(result, {"instagram": None, "tiktok": None})

    def test_intentionally_disabled_is_not_reported_as_a_failure_or_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.json"
            original = '{"text":"YouTube kartı", "reply_markup": {"inline_keyboard": []}}'
            path.write_text(original, encoding="utf-8")
            changed = diagnostics.append_to_payload(path, "video_200.mp4", {
                "instagram": None, "tiktok": None, "status": "disabled_by_user"
            })
            self.assertFalse(changed)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_workflow_enables_tiktok_only(self):
        path = Path(__file__).resolve().parents[1] / ".github/workflows/youtube-drive-uploader.yml"
        text = path.read_text(encoding="utf-8")
        self.assertIn("CROSSPOST_ENABLED: 'true'", text)
        self.assertIn("TIKTOK_ENABLED: 'true'", text)
        self.assertIn("INSTAGRAM_ENABLED: 'false'", text)


if __name__ == "__main__":
    unittest.main()
