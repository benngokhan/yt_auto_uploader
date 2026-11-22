"""No-network, no-publication checks for the optional delivery diagnostics."""
import contextlib
import io
import json
import os
import tempfile
import textwrap
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import uploader
import crosspost_worker


class UploadReportingIntegration(unittest.TestCase):
    def simulate_upload(self, related_side_effect=None):
        with tempfile.TemporaryDirectory() as td, contextlib.ExitStack() as stack:
            root = Path(td)
            scheduled = {
                'id': 'fake-drive-id', 'name': 'video_999.mp4', 'title': 'Test Başlık',
                'description': 'Test', 'tags': [], 'categoryId': '27',
                'pinned_comment': 'Test yorum', 'row': 2, 'video_type': 'short'
            }
            replacements = {
                'BASE_DIR': root,
                'REPORT_FILE': root / 'report.txt',
                'get_google_clients': lambda **kw: (object(), object()),
                'drain_lobi_to_queue': lambda *a, **kw: None,
                'iscilers_heartbeat': lambda *a, **kw: None,
                'load_uploaded_ids': lambda *a, **kw: set(),
                'get_next_scheduled_video': lambda *a, **kw: scheduled,
                'route_short_topic': lambda *a, **kw: None,
                'download_drive_file': lambda *a, **kw: None,
                'upload_to_youtube': lambda *a, **kw: {'id': 'aBcdEfGhI12'},
                'mark_as_uploaded': lambda *a, **kw: None,
                'update_excel_status_in_drive': lambda *a, **kw: None,
                'upload_thumbnail_if_exists': lambda *a, **kw: uploader.ThumbnailResult(),
                'post_pinned_comment': lambda *a, **kw: (False, ''),
                'backlink_previous_episode': lambda *a, **kw: None,
                'sync_kartal_status_report': lambda *a, **kw: None,
                'load_table_from_drive_or_local': lambda *a, **kw: {},
            }
            stack.enter_context(patch('youtube_guvenlik.yayin_guvenlik_kontrolu', return_value=None))
            for name, value in replacements.items():
                stack.enter_context(patch.object(uploader, name, value))
            stack.enter_context(patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch'}, clear=True))
            stack.enter_context(patch.object(crosspost_worker, 'run_crosspost', return_value={'instagram': None, 'tiktok': None}))
            if related_side_effect is None:
                stack.enter_context(patch.object(uploader, 'sync_related_links', return_value={
                    'status': 'studio_pending', 'target_name': 'uzun_video_24.mp4',
                    'studio_url': 'https://studio.youtube.com/video/aBcdEfGhI12/edit',
                    'message': 'İlgili video otomatik bağlanmadı; Studio işlemi gerekli.'
                }))
            else:
                stack.enter_context(patch.object(uploader, 'sync_related_links', side_effect=related_side_effect))
            result = uploader.upload_job(
                {'drive_queue_folder_id': 'fake', 'uploaded_list': str(root / 'uploaded.txt')},
                video_type='short')
            payload = json.loads((root / 'last_upload_payload.json').read_text(encoding='utf-8'))
            self.assertTrue((root / 'report.txt').exists())
            return result, payload

    def test_pending_link_and_skipped_social_are_in_same_card(self):
        result, payload = self.simulate_upload()
        self.assertEqual(result['video_id'], 'aBcdEfGhI12')
        self.assertIn('otomatik bağlanmadı', payload['text'])
        self.assertIn('Instagram: Atlandı veya sonuç yok; doğrulanmadı.', payload['text'])
        self.assertIn('TikTok: Atlandı veya sonuç yok; doğrulanmadı.', payload['text'])
        self.assertIn('inline_keyboard', payload['reply_markup'])

    def test_related_planner_failure_does_not_break_recorded_upload(self):
        result, payload = self.simulate_upload(RuntimeError('test failure'))
        self.assertEqual(result['video_id'], 'aBcdEfGhI12')
        self.assertIn('İlgili video doğrulanamadı', payload['text'])
        self.assertIn('ÇAPRAZ PAYLAŞIM DURUMU', payload['text'])


class TelegramWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/youtube-drive-uploader.yml').read_text(encoding='utf-8')
        telegram = workflow.split('      - name: Telegram VIP Bildirimi', 1)[1]
        script = telegram.split("          python - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
        cls.code = compile(textwrap.dedent(script), '<workflow-telegram>', 'exec')

    def run_script(self, response=None, error=None, with_payload=True, with_secrets=True):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(response).encode('utf-8')
        def fake_urlopen(req, timeout):
            if error: raise error
            return Reply()
        environment = {'JOB_STATUS': 'success', 'RUN_URL': 'https://github.example/run'}
        if with_secrets:
            environment.update({'TELEGRAM_BOT_TOKEN': 'FAKE_NOT_REAL_SECRET', 'TELEGRAM_CHAT_ID': '12345'})
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, environment, clear=True), \
             patch('urllib.request.urlopen', side_effect=fake_urlopen), contextlib.redirect_stdout(out):
            if with_payload:
                Path(td, 'last_upload_payload.json').write_text('{"text":"test"}', encoding='utf-8')
            old = os.getcwd()
            os.chdir(td)
            try:
                try:
                    exec(self.code, {})
                    exit_code = 0
                except SystemExit as exc:
                    exit_code = int(exc.code or 0)
            finally:
                os.chdir(old)
        self.assertNotIn('FAKE_NOT_REAL_SECRET', out.getvalue())
        return exit_code, out.getvalue()

    def test_acceptance_is_reported_only_after_message_id(self):
        exit_code, output = self.run_script({'ok': True, 'result': {'message_id': 42}})
        self.assertEqual(exit_code, 0)
        self.assertIn('mesajı kabul etti', output)
        self.assertIn('okunduğu anlamına gelmez', output)
        exit_code, output = self.run_script({'ok': True, 'result': {}})
        self.assertEqual(exit_code, 1)
        self.assertIn('gönderimi doğrulanamadı', output)

    def test_missing_settings_and_payload_are_not_falsely_sent(self):
        exit_code, output = self.run_script(with_secrets=False)
        self.assertEqual(exit_code, 0)
        self.assertIn('bot veya sohbet ayarı eksik', output)
        exit_code, output = self.run_script(with_payload=False)
        self.assertEqual(exit_code, 0)
        self.assertIn('Yayın kartı yok', output)

    def test_telegram_http_failure_is_reported_without_url_or_secret(self):
        error = urllib.error.HTTPError('https://api.telegram.org/botFAKE_NOT_REAL_SECRET/sendMessage', 403, 'Forbidden', {}, None)
        exit_code, output = self.run_script(error=error)
        self.assertEqual(exit_code, 1)
        self.assertIn('HTTPError', output)
        self.assertNotIn('api.telegram.org', output)


if __name__ == '__main__':
    unittest.main()
