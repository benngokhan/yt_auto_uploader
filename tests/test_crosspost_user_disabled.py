import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import crosspost_worker as worker
import delivery_diagnostics as diagnostics


class CrosspostUserDisabledTests(unittest.TestCase):
    def test_all_env_and_drive_flags_cannot_reactivate_old_sessions(self):
        flags = {
            "CROSSPOST_ENABLED": "true",
            "IG_SESSIONID": "not-real-instagram-session",
            "TIKTOK_SESSIONID": "not-real-tiktok-session",
        }
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

    def test_direct_platform_entrypoints_do_not_upload(self):
        flags = {"CROSSPOST_ENABLED": "true", "IG_SESSIONID": "fake", "TIKTOK_SESSIONID": "fake"}
        with patch.dict(os.environ, flags, clear=True), \
             patch.object(worker, "_ensure_playwright_browser") as browser:
            self.assertIsNone(worker.post_instagram(Path("/missing.mp4"), "test"))
            self.assertIsNone(worker.post_tiktok(Path("/missing.mp4"), "test"))
            browser.assert_not_called()

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

    def test_workflow_also_disables_crosspost_explicitly(self):
        path = Path(__file__).resolve().parents[1] / ".github/workflows/youtube-drive-uploader.yml"
        self.assertIn("CROSSPOST_ENABLED: 'false'", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
