import tempfile,unittest
from unittest.mock import patch,MagicMock
from datetime import datetime,timezone
from pathlib import Path
import bugun_planla as b

SLOT='2026-11-22T16:30Z'
CANDIDATE={'name':'video_183.mp4','id':'drive-183','title':'Yeni Başlık','description':'Açıklama','tags':[], 'categoryId':'27'}

class PreScheduleTests(unittest.TestCase):
    def test_only_today_with_safe_lead_time(self):
        self.assertEqual(b.key_for(b.slot_for_today(datetime(2026,11,22,14,0,tzinfo=timezone.utc))),SLOT)
        for hour,minute in [(16,11),(17,0),(7,0)]:
            with self.assertRaises(RuntimeError): b.slot_for_today(datetime(2026,11,22,hour,minute,tzinfo=timezone.utc))

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

if __name__=='__main__':unittest.main()
