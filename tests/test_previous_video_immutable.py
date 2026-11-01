import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import uploader


class PriorVideoProtectionTests(unittest.TestCase):
    def test_backlink_never_queries_or_changes_old_videos(self):
        youtube = Mock(name="youtube")
        drive = Mock(name="drive")
        with patch.object(uploader, "load_table_from_drive_or_local", side_effect=AssertionError("must not read")) as load:
            info = uploader.backlink_previous_episode(
                youtube, drive, "queue", Path("not-read.txt"),
                "video_153.mp4", "abcdefghijk", "New episode",
            )
        load.assert_not_called()
        youtube.assert_not_called()
        self.assertEqual(youtube.mock_calls, [])
        self.assertEqual(drive.mock_calls, [])
        self.assertEqual(info["status"], "disabled_by_policy")
        self.assertFalse(info["desc_updated"])
        self.assertFalse(info["comment_updated"])
        self.assertEqual(info["prev_vid_id"], "")

    def test_no_chain_success_or_studio_link_is_fabricated(self):
        # The test report must never leak into a scheduled or dry-run job's
        # actual Telegram payload path, where it could be sent as a real card.
        with TemporaryDirectory() as temp, \
             patch.object(uploader, "BASE_DIR", Path(temp)), \
             patch.dict("os.environ", {"GITHUB_EVENT_NAME": "workflow_dispatch"}), \
             patch.object(uploader, "load_table_from_drive_or_local", side_effect=RuntimeError("not available")):
            text = uploader.build_telegram_report(
                "video_153.mp4", "abcdefghijk", "https://youtu.be/abcdefghijk",
                {"title": "Example", "pinned_comment": ""}, False,
                backlink_info={"status": "disabled_by_policy", "prev_vid_id": "", "desc_updated": False, "comment_updated": False},
                related_info={"status": "waiting_target", "message": "İlgili video bekliyor."},
            )
            self.assertTrue((Path(temp) / "last_upload_payload.json").is_file())
        self.assertNotIn("Zincir Geri-Bağlantı", text)
        self.assertIn("İlgili Video", text)


if __name__ == "__main__":
    unittest.main()
