import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import related_plan as r
import uploader


class RelatedPlanTests(unittest.TestCase):
    def setUp(self):
        self.headers = ['Dosya Adı', 'YouTube Link', 'İlgili Video']
        self.short = 'aBcdEfGhI12'
        self.target = 'jKlmNoPqR34'
        self.rows = {'uzun_video_18.mp4': ('uzun_video_18.mp4', f'https://youtu.be/{self.target}', 'video_151.mp4')}

    def test_never_calls_youtube_for_related_link(self):
        class ForbiddenAPI:
            def __getattr__(self, name):
                raise AssertionError('API must not be called')
        with patch.object(uploader, '_ilgili_tablo_oku', return_value=(self.headers, self.rows)), \
             patch.object(r, 'uploaded_file_ids', return_value={}):
            result = uploader.sync_related_links(ForbiddenAPI(), object(), 'q', 'video_151.mp4', self.short)
        self.assertEqual(result['status'], 'studio_pending')
        self.assertEqual(result['target_id'], self.target)
        self.assertIn('otomatik bağlanmadı', result['message'])

    def test_missing_target_waits_and_duplicate_is_ambiguous(self):
        no_target = {'uzun_video_18.mp4': ('uzun_video_18.mp4', '', 'video_151.mp4')}
        self.assertEqual(r.plan(self.headers, no_target, 'video_151.mp4', self.short)['status'], 'waiting_target')
        duplicate = dict(self.rows, **{'uzun_video_19.mp4': ('uzun_video_19.mp4', '', 'video_151.mp4')})
        self.assertEqual(r.plan(self.headers, duplicate, 'video_151.mp4', self.short)['status'], 'ambiguous')

    def test_reject_non_youtube_or_invalid_ids_and_never_edit_long(self):
        self.assertEqual(r.extract_id('https://youtube.com.evil.test/watch?v=' + self.target), '')
        self.assertEqual(r.extract_id('https://youtu.be/' + self.target + '?t=2'), self.target)
        self.assertEqual(r.plan(self.headers, self.rows, 'video_151.mp4', 'bad')['status'], 'invalid_short')
        self.assertEqual(r.plan(self.headers, self.rows, 'uzun_video_18.mp4', self.target)['status'], 'long_video')

    def test_publication_log_fallback_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'uploaded.txt'
            p.write_text(f'fakeid | uzun_video_18.mp4 | https://youtu.be/{self.target} | 2026-10-31 12:00\n')
            before = p.read_bytes()
            mapping = r.uploaded_file_ids(p)
            no_target = {'uzun_video_18.mp4': ('uzun_video_18.mp4', '', 'video_151.mp4')}
            result = r.plan(self.headers, no_target, 'video_151.mp4', self.short, mapping)
            self.assertEqual(result['status'], 'studio_pending')
            self.assertEqual(before, p.read_bytes())

    def test_report_calls_out_pending_without_false_success(self):
        p = {'status': 'studio_pending', 'target_name': 'uzun_video_18.mp4',
             'studio_url': f'https://studio.youtube.com/video/{self.short}/edit',
             'message': 'İlgili video otomatik bağlanmadı; Studio işlemi gerekli.'}
        with patch.object(uploader, 'load_table_from_drive_or_local', side_effect=RuntimeError()), \
             patch.object(uploader, 'BASE_DIR', Path('/nonexistent')), \
             patch.dict('os.environ', {'GITHUB_EVENT_NAME': 'push'}):
            text = uploader.build_telegram_report('video_151.mp4', self.short, 'https://youtu.be/' + self.short,
                                                  {'title': 'Başlık'}, False, related_info=p)
        self.assertIn('otomatik bağlanmadı', text)
        self.assertIn('uzun_video_18.mp4', text)


if __name__ == '__main__':
    unittest.main()
