import tempfile,unittest
from unittest.mock import patch,MagicMock
from datetime import datetime,timezone
from pathlib import Path
import bugun_planla as b

SLOT='2026-11-22T16:30Z'
CANDIDATE={'name':'video_183.mp4','id':'drive-183','title':'Yeni Başlık','description':'Açıklama','tags':[], 'categoryId':'27'}

class PreScheduleTests(unittest.TestCase):
    def setUp(self):
        clock=patch.object(b,'utcnow',return_value=datetime(2026,11,22,14,0,tzinfo=timezone.utc))
        clock.start();self.addCleanup(clock.stop)

    def test_next_slot_today_or_tomorrow_never_backfills(self):
        for hour in [0,7,14]:
            self.assertEqual(b.key_for(b.slot_for_today(datetime(2026,11,22,hour,0,tzinfo=timezone.utc))),SLOT)
        for hour in [17,23]:
            self.assertEqual(b.key_for(b.slot_for_today(datetime(2026,11,22,hour,0,tzinfo=timezone.utc))),'2026-11-23T16:30Z')
        with self.assertRaises(RuntimeError):b.slot_for_today(datetime(2026,11,22,16,11,tzinfo=timezone.utc))

    def test_exact_twenty_minute_lead_is_allowed(self):
        self.assertEqual(b.key_for(b.slot_for_today(datetime(2026,11,22,16,10,tzinfo=timezone.utc))),SLOT)

    def test_slot_at_exact_publication_time_moves_to_next_day(self):
        self.assertEqual(b.key_for(b.slot_for_today(datetime(2026,11,22,16,30,tzinfo=timezone.utc))),'2026-11-23T16:30Z')

    def test_timezone_required(self):
        with self.assertRaises(ValueError):b.slot_for_today(datetime(2026,11,22,14,0))

    def test_future_guard_blocks_past_or_over_24_hours(self):
        for target in [datetime(2026,11,22,13,59,tzinfo=timezone.utc),datetime(2026,11,23,16,30,tzinfo=timezone.utc)]:
            with self.assertRaisesRegex(RuntimeError,'gelecek'):b.ensure_future_target(target)

    def test_near_slot_inspect_skips_without_api_calls(self):
        with patch.object(b,'utcnow',return_value=datetime(2026,11,22,16,17,tzinfo=timezone.utc)),patch.object(b,'get_google_clients') as clients:
            self.assertEqual(b.inspect()['should_plan'],'false');clients.assert_not_called()

    def test_recorded_slot_is_noop_without_another_upload(self):
        with tempfile.TemporaryDirectory() as td,patch.object(b,'STATE',Path(td)),patch.object(b,'get_google_clients') as clients:
            (Path(td)/'uploaded.txt').write_text('id | video_183.mp4 | https://youtu.be/abcdefghijk | 2026-11-22 14:00 | title | SLOT='+SLOT+'\n')
            self.assertEqual(b.inspect()['should_plan'],'false');clients.assert_not_called()

    def test_uncertain_claim_is_not_retried(self):
        with tempfile.TemporaryDirectory() as td,patch.object(b,'STATE',Path(td)),patch.object(b,'get_google_clients') as clients:
            (Path(td)/'slot_claims.txt').write_text(SLOT+'\n')
            with self.assertRaisesRegex(RuntimeError,'belirsiz'):b.inspect()
            clients.assert_not_called()

    def test_year_boundary_rolls_to_next_date(self):
        self.assertEqual(b.key_for(b.slot_for_today(datetime(2026,12,31,23,0,tzinfo=timezone.utc))),'2027-01-01T16:30Z')

    def test_local_timezone_input_selects_same_slot(self):
        from datetime import timedelta
        now=datetime(2026,11,22,20,0,tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(b.key_for(b.slot_for_today(now)),'2026-11-23T16:30Z')

    def test_inspect_emits_ready_and_only_short_candidate(self):
        with tempfile.TemporaryDirectory() as td,patch.object(b,'STATE',Path(td)), \
             patch.object(b,'get_google_clients',return_value=(object(),object())), \
             patch.object(b,'load_config',return_value={'drive_queue_folder_id':'folder'}), \
             patch.object(b,'previous_publication_verified'),patch.object(b,'yayin_guvenlik_kontrolu'), \
             patch.object(b,'get_next_scheduled_video',return_value=CANDIDATE) as next_video:
            result=b.inspect()
            self.assertEqual(result['should_plan'],'true')
            self.assertEqual(result['slot'],SLOT)
            self.assertEqual(next_video.call_args.kwargs['video_type'],'short')

    def test_friday_is_still_short(self):
        slot=b.slot_for_today(datetime(2026,11,27,10,0,tzinfo=timezone.utc))
        from slot_guard import parse_slot
        self.assertEqual(parse_slot(b.key_for(slot))[1],'short')

    def test_claim_survives_even_if_upload_fails(self):
        with tempfile.TemporaryDirectory() as td, patch.object(b,'STATE',Path(td)), patch.object(b,'slot_for_today',return_value=datetime(2026,11,22,16,30,tzinfo=timezone.utc)):
            b.reserve(SLOT)
            with self.assertRaises(RuntimeError):b.reserve(SLOT)
            self.assertTrue((Path(td)/'slot_claims.txt').exists())

    def test_upload_is_scheduled_and_recorded_before_optional_work(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'slot_claims.txt').write_text(SLOT+'\n')
            youtube=MagicMock();youtube.videos().list().execute.return_value={'items':[{'status':{'privacyStatus':'private','publishAt':'2026-11-22T16:30:00Z'}}]}
            with patch.object(b,'STATE',root), patch.object(b,'slot_for_today',return_value=datetime(2026,11,22,16,30,tzinfo=timezone.utc)), \
                 patch.object(b,'previous_publication_verified'),patch.object(b,'get_google_clients',return_value=(youtube,object())),patch.object(b,'load_config',return_value={'drive_queue_folder_id':'folder'}), \
                 patch.object(b,'get_next_scheduled_video',return_value=CANDIDATE),patch.object(b,'yayin_guvenlik_kontrolu'), \
                 patch.object(b,'download_drive_file'),patch.object(b,'upload_to_youtube',return_value={'id':'fake-id'}) as send, \
                 patch.object(b,'upload_thumbnail_if_exists',return_value=type('Cover',(),{'api_accepted':True})()), \
                 patch.object(b.Path,'write_text',autospec=True) as writes:
                result=b.upload(SLOT,CANDIDATE['name'],CANDIDATE['id'])
                self.assertEqual(result['status'],'PLANLANDI')
                self.assertEqual(send.call_args.args[2]['publishAt'],'2026-11-22T16:30:00+00:00')
                self.assertIn('video_183.mp4',(root/'uploaded.txt').read_text())

    def test_unverified_schedule_still_records_upload_and_blocks_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'slot_claims.txt').write_text(SLOT+'\n')
            youtube=MagicMock();youtube.videos().list().execute.return_value={'items': []}
            with patch.object(b,'STATE',root),patch.object(b,'slot_for_today',return_value=datetime(2026,11,22,16,30,tzinfo=timezone.utc)), \
                 patch.object(b,'previous_publication_verified'),patch.object(b,'get_google_clients',return_value=(youtube,object())),patch.object(b,'load_config',return_value={'drive_queue_folder_id':'folder'}), \
                 patch.object(b,'get_next_scheduled_video',return_value=CANDIDATE),patch.object(b,'yayin_guvenlik_kontrolu'), \
                 patch.object(b,'download_drive_file'),patch.object(b,'upload_to_youtube',return_value={'id':'fake-id'}), \
                 patch.object(b.Path,'write_text',autospec=True):
                with self.assertRaisesRegex(RuntimeError,'doğrulanamadı'): b.upload(SLOT,CANDIDATE['name'],CANDIDATE['id'])
                self.assertIn('video_183.mp4',(root/'uploaded.txt').read_text())

    def test_previous_planned_video_must_be_public(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'uploaded.txt').write_text('id | video_182.mp4 | https://youtu.be/_J95OOCW488 | 2026-11-18 17:09 | title | SLOT=2026-11-18T16:30Z\n')
            yt=MagicMock()
            with patch.object(b,'STATE',root):
                yt.videos().list().execute.return_value={'items':[{'status':{'privacyStatus':'private'}}]}
                with self.assertRaisesRegex(RuntimeError,'yayında doğrulanamadı'):b.previous_publication_verified(yt,datetime(2026,11,22,16,30,tzinfo=timezone.utc))
                yt.videos().list().execute.return_value={'items':[{'status':{'privacyStatus':'public'}}]}
                b.previous_publication_verified(yt,datetime(2026,11,22,16,30,tzinfo=timezone.utc))

    def test_changed_queue_blocks_before_upload(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'slot_claims.txt').write_text(SLOT+'\n')
            with patch.object(b,'STATE',root),patch.object(b,'slot_for_today',return_value=datetime(2026,11,22,16,30,tzinfo=timezone.utc)), \
                 patch.object(b,'previous_publication_verified'),patch.object(b,'get_google_clients',return_value=(object(),object())), patch.object(b,'load_config',return_value={'drive_queue_folder_id':'f'}), \
                 patch.object(b,'get_next_scheduled_video',return_value=CANDIDATE),patch.object(b,'upload_to_youtube') as send:
                with self.assertRaisesRegex(RuntimeError,'sırası'):b.upload(SLOT,'video_184.mp4','different')
                send.assert_not_called()

class PreScheduleBoundaryTests(unittest.TestCase):
    def test_download_that_runs_past_safe_lead_never_uploads(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'slot_claims.txt').write_text(SLOT+'\n')
            with patch.object(b,'STATE',root),patch.object(b,'slot_for_today',return_value=datetime(2026,11,22,16,30,tzinfo=timezone.utc)), \
                 patch.object(b,'utcnow',side_effect=[datetime(2026,11,22,14,0,tzinfo=timezone.utc),datetime(2026,11,22,16,28,tzinfo=timezone.utc)]), \
                 patch.object(b,'previous_publication_verified'),patch.object(b,'get_google_clients',return_value=(object(),object())), \
                 patch.object(b,'load_config',return_value={'drive_queue_folder_id':'folder'}),patch.object(b,'get_next_scheduled_video',return_value=CANDIDATE), \
                 patch.object(b,'yayin_guvenlik_kontrolu'),patch.object(b,'download_drive_file'),patch.object(b,'upload_to_youtube') as send:
                with self.assertRaisesRegex(RuntimeError,'gelecek'):b.upload(SLOT,CANDIDATE['name'],CANDIDATE['id'])
                send.assert_not_called()
                self.assertTrue((root/'slot_claims.txt').exists())

if __name__=='__main__':unittest.main()
