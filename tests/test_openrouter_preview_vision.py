import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'motor'))
import openrouter_preview_vision as vision
import gorsel_uret
import shorts_acceptance


def download(_, path):
    Image.new('RGB', (32,32), 'red').save(path, 'JPEG')


def answer(text, reason='stop'):
    return io.BytesIO(json.dumps({'choices':[{'finish_reason':reason,'message':{'content':text}}]}).encode())


class PreviewVisionTests(unittest.TestCase):
    def test_valid_scores_keep_actual_origin_and_retry_429(self):
        rows=[{'preview_url':'https://example.test/a'}, {'preview_url':'https://example.test/b'}]
        error=urllib.error.HTTPError('https://openrouter.ai',429,'rate',{},None)
        with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-secret'}), \
             mock.patch('urllib.request.urlopen', side_effect=[error,answer('{"scores":[0.9,0.1]}')]), \
             mock.patch.object(vision.time,'sleep') as sleep:
            self.assertEqual(vision.score_images('test',rows,download),[0.9,0.1])
            self.assertEqual(rows[0]['_vision_origin'],vision.ORIGIN)
            sleep.assert_called_once_with(6)

    def test_bad_or_truncated_answer_fails_closed(self):
        for body, reason in [('{"scores":[0.9]}','length'),('{"scores":[true]}','stop'),('not json','stop')]:
            rows=[{'preview_url':'https://example.test/a'}]
            with self.subTest(body=body), mock.patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-secret'}), \
                 mock.patch('urllib.request.urlopen', return_value=answer(body,reason)):
                self.assertEqual(vision.score_images('test',rows,download),[None])
                self.assertNotIn('_vision_origin',rows[0])

    def test_experimental_origin_cannot_pass_without_opt_in_and_threshold(self):
        row={'score_origin':vision.ORIGIN,'semantic_similarity':0.9}
        with mock.patch.dict(os.environ, {'MOTOR_EXPERIMENTAL_OPENROUTER':'0'}):
            self.assertFalse(gorsel_uret._record_score_passes(row))
        with mock.patch.dict(os.environ, {'MOTOR_EXPERIMENTAL_OPENROUTER':'1'}):
            self.assertTrue(gorsel_uret._record_score_passes(row))
            self.assertFalse(gorsel_uret._record_score_passes(dict(row,semantic_similarity=0.5)))

if __name__ == '__main__': unittest.main()
