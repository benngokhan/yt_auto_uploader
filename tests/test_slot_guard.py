import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import slot_guard as g
import uploader

UTC = timezone.utc


class SlotGuardTests(unittest.TestCase):
    def test_daily_slots_and_extra_friday_long(self):
        now=datetime(2026,10,30,13,45,tzinfo=UTC)
        self.assertEqual(g.scheduled_slot('30 9 * * *',now),('2026-10-30T09:30Z','short'))
        self.assertEqual(g.scheduled_slot('0 13 * * 5',now),('2026-10-30T13:00Z','long'))
        self.assertEqual(g.watchdog_slot('45 13 * * 5',now),('2026-10-30T13:00Z','long','tescil'))

    def test_late_run_after_midnight_retains_previous_day_slot(self):
        now=datetime(2026,10,31,0,15,tzinfo=UTC)
        self.assertEqual(g.scheduled_slot('30 16 * * *',now),('2026-10-30T16:30Z','short'))

    def test_slot_age_and_weekday_are_validated(self):
        now=datetime(2026,10,30,13,45,tzinfo=UTC)
        g.parse_slot('2026-10-30T13:00Z',now,recovery=True)
        with self.assertRaises(ValueError): g.parse_slot('2026-10-29T13:00Z',now,recovery=True)
        with self.assertRaises(ValueError): g.parse_slot('2026-10-30T16:30Z',now,recovery=True)
        with self.assertRaises(ValueError): g.parse_slot('2026-10-23T13:00Z',now,recovery=True)

    def test_slot_marker_is_matched_by_slot_and_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'uploaded.txt'
            p.write_text('f | video_150.mp4 | https://youtu.be/abc | 2026-10-30 09:35 | title | SLOT=2026-10-30T09:30Z\n')
            now=datetime(2026,10,30,10,15,tzinfo=UTC)
            self.assertTrue(g.slot_completed(p,'2026-10-30T09:30Z',now))
            self.assertFalse(g.slot_completed(p,'2026-10-30T13:00Z',now))
            self.assertFalse(g.slot_completed(p,'2026-10-30T16:30Z',now))

    def test_legacy_record_matches_only_appropriate_type_and_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'uploaded.txt'
            p.write_text('f | uzun_video_18.mp4 | https://youtu.be/abc | 2026-10-30 13:10 | title\n')
            now=datetime(2026,10,30,13,45,tzinfo=UTC)
            self.assertTrue(g.slot_completed(p,'2026-10-30T13:00Z',now))
            self.assertFalse(g.slot_completed(p,'2026-10-30T09:30Z',now))

    def test_tagged_other_slot_is_not_counted_as_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'uploaded.txt'
            p.write_text('f | video_150.mp4 | https://youtu.be/abc | 2026-10-30 16:20 | title | SLOT=2026-10-30T09:30Z\n')
            self.assertFalse(g.slot_completed(p,'2026-10-30T16:30Z',datetime(2026,10,30,17,0,tzinfo=UTC)))

    def test_record_includes_slot_and_is_compatible_with_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'uploaded.txt'
            uploader.mark_as_uploaded(p,'drive-id','video_150.mp4','https://youtu.be/abc','title',
                                      slot_key='2026-10-30T09:30Z')
            self.assertTrue(g.slot_completed(p,'2026-10-30T09:30Z'))
            self.assertTrue({'drive-id','video_150.mp4'}.issubset(uploader.load_uploaded_ids(p)))

    def test_duplicate_slot_exits_before_google_clients(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'uploaded.txt'
            p.write_text('f | video_150.mp4 | https://youtu.be/abc | 2026-10-30 09:31 | title | SLOT=2026-10-30T09:30Z\n')
            cfg={'drive_queue_folder_id':'queue','uploaded_list':str(p)}
            with patch.dict(os.environ,{'BILGI_SLOT_KEY':'2026-10-30T09:30Z'},clear=False), \
                 patch.object(uploader,'get_google_clients') as clients:
                self.assertIsNone(uploader.upload_job(channel_config=cfg,video_type='short'))
                clients.assert_not_called()

    def test_wrong_video_type_rejected_before_google_clients(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg={'drive_queue_folder_id':'queue','uploaded_list':str(Path(tmp)/'uploaded.txt')}
            with patch.dict(os.environ,{'BILGI_SLOT_KEY':'2026-10-30T13:00Z'},clear=False), \
                 patch.object(uploader,'get_google_clients') as clients:
                with self.assertRaisesRegex(RuntimeError,'uyuşmuyor'):
                    uploader.upload_job(channel_config=cfg,video_type='short')
                clients.assert_not_called()

    def test_reservation_blocks_a_second_attempt_even_without_publish_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            claims=Path(tmp)/'slot_claims.txt';log=Path(tmp)/'uploaded.txt'
            key='2026-10-30T09:30Z'
            self.assertTrue(g.reserve_slot(claims,log,key))
            self.assertTrue(g.slot_claimed(claims,key))
            self.assertFalse(g.reserve_slot(claims,log,key))
            self.assertEqual(claims.read_text().splitlines(),[key])

    def test_reservation_also_refuses_already_published_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            claims=Path(tmp)/'slot_claims.txt';log=Path(tmp)/'uploaded.txt'
            key='2026-10-30T09:30Z'
            log.write_text(f'f | video_150.mp4 | https://youtu.be/abc | 2026-10-30 09:31 | title | SLOT={key}\n')
            self.assertFalse(g.reserve_slot(claims,log,key))
            self.assertFalse(claims.exists())

    def test_log_persisted_even_if_later_upload_step_fails(self):
        workflow=(Path(__file__).resolve().parent.parent/'.github/workflows/youtube-drive-uploader.yml').read_text()
        self.assertLess(workflow.index('Reserve the publication slot'),workflow.index('Upload one queued video'))
        self.assertIn("if: ${{ steps.reserve.outputs.allow == 'true' }}",workflow)
        self.assertIn('git push origin HEAD:main',workflow)
        self.assertIn("always() && steps.publish.outcome != 'skipped'",workflow)
        source=(Path(__file__).resolve().parent.parent/'uploader.py').read_text()
        start=source.index('yt_url = f"https://youtu.be/{vid_id}"')
        self.assertLess(source.index('mark_as_uploaded(',start),source.index('upload_thumbnail_if_exists(',start))


if __name__=='__main__':
    unittest.main()
