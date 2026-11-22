import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock
from PIL import Image

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'motor'))
import groq_preview_vision as groq
import gorsel_uret
import shorts_acceptance as acceptance


def download(_,path):
    Image.new('RGB',(32,32),'red').save(path,'JPEG')


def response(score):
    content=json.dumps({'score':score,'observed':'fixture'})
    body={'choices':[{'finish_reason':'stop','message':{'content':content}}]}
    r=io.BytesIO(json.dumps(body).encode());r.headers={}
    return r


class GroqPreviewTests(unittest.TestCase):
    def test_valid_scores_have_actual_origin_and_one_image_per_request(self):
        rows=[{'preview_url':'https://example.test/a'},{'preview_url':'https://example.test/b'}]
        with mock.patch.dict(os.environ,{'GROQ_API_KEY':'test-secret'}), \
             mock.patch.object(groq,'_not_before',0), \
             mock.patch('urllib.request.urlopen',side_effect=[response(0.0),response(0.8)]) as req:
            self.assertEqual(groq.score_images('mum',rows,download),[0.0,0.8])
        self.assertTrue(all(r['_vision_origin']==groq.ORIGIN for r in rows))
        self.assertEqual(req.call_count,2)
        for call in req.call_args_list:
            request=call.args[0]; body=json.loads(request.data)
            self.assertEqual(body['model'],groq.MODEL)
            self.assertEqual(sum(part['type']=='image_url' for part in body['messages'][0]['content']),1)
            self.assertIn('Mozilla',request.get_header('User-agent'))

    def test_http_403_stops_batch_and_never_invents_a_score(self):
        rows=[{'preview_url':'https://example.test/a'},{'preview_url':'https://example.test/b'}]
        err=urllib.error.HTTPError('https://api.groq.com',403,'Forbidden',{},None)
        with mock.patch.dict(os.environ,{'GROQ_API_KEY':'test-secret'}), \
             mock.patch.object(groq,'_not_before',0), \
             mock.patch('urllib.request.urlopen',side_effect=err) as req:
            self.assertEqual(groq.score_images('mum',rows,download),[None,None])
        req.assert_called_once()
        self.assertEqual([r['_vision_error'] for r in rows],['groq_http_403','groq_http_403'])
        self.assertTrue(all('_vision_origin' not in r for r in rows))

    def test_invalid_score_fails_closed(self):
        for score in (True,1.5,-0.1,'0.8'):
            rows=[{'preview_url':'https://example.test/a'}]
            with self.subTest(score=score), mock.patch.dict(os.environ,{'GROQ_API_KEY':'test-secret'}), \
                 mock.patch.object(groq,'_not_before',0), \
                 mock.patch('urllib.request.urlopen',return_value=response(score)):
                self.assertEqual(groq.score_images('mum',rows,download),[None])
                self.assertNotIn('_vision_origin',rows[0])

    def test_429_honors_retry_after_once_and_fails_closed(self):
        rows=[{'preview_url':'https://example.test/a'}]
        err=urllib.error.HTTPError('https://api.groq.com',429,'rate',{'retry-after':'4'},None)
        with mock.patch.dict(os.environ,{'GROQ_API_KEY':'test-secret'}), \
             mock.patch.object(groq,'_not_before',0), \
             mock.patch.object(groq.time,'sleep') as sleep, \
             mock.patch('urllib.request.urlopen',side_effect=[err,response(0.8)]) as req:
            self.assertEqual(groq.score_images('mum',rows,download),[0.8])
        self.assertEqual(req.call_count,2)
        self.assertEqual(sleep.call_count,1)
        self.assertNotIn('_vision_error',rows[0])

    def test_groq_origin_only_with_explicit_isolated_opt_in(self):
        selected={'score_origin':groq.ORIGIN,'semantic_similarity':0.8}
        for env,expected in [({'MOTOR_EXPERIMENTAL_OPENROUTER':'0','MOTOR_PREVIEW_VISION_PROVIDER':'groq'},False),
                             ({'MOTOR_EXPERIMENTAL_OPENROUTER':'1','MOTOR_PREVIEW_VISION_PROVIDER':'openrouter'},False),
                             ({'MOTOR_EXPERIMENTAL_OPENROUTER':'1','MOTOR_PREVIEW_VISION_PROVIDER':'groq'},True)]:
            with self.subTest(env=env),mock.patch.dict(os.environ,env):
                self.assertEqual(gorsel_uret._record_score_passes(selected),expected)
                self.assertFalse(gorsel_uret._record_score_passes(dict(selected,semantic_similarity=0.5)))

    def test_provenance_report_does_not_mislabel_groq_as_gemini(self):
        report={'mode':'production_v2','generation':'live','fallback_policy':'fail_closed',
                'semantic_threshold':0.62,'semantic_model':groq.MODEL,
                'scenes':[{'selected':{'provider':'pexels','uid':f'pexels:{i}',
                'source_page_url':f'https://www.pexels.com/photo/x-{i}/',
                'score_origin':groq.ORIGIN,'semantic_similarity':0.8}} for i in range(1,5)]}
        with mock.patch.dict(os.environ,{'MOTOR_EXPERIMENTAL_OPENROUTER':'0','MOTOR_PREVIEW_VISION_PROVIDER':'groq'}):
            with self.assertRaises(acceptance.ShortsAcceptanceError): acceptance._validate_visual_report(report)
        with mock.patch.dict(os.environ,{'MOTOR_EXPERIMENTAL_OPENROUTER':'1','MOTOR_PREVIEW_VISION_PROVIDER':'groq'}):
            self.assertEqual(len(acceptance._validate_visual_report(report)),4)
            report['scenes'][0]['selected']['semantic_similarity']=0.5
            with self.assertRaises(acceptance.ShortsAcceptanceError): acceptance._validate_visual_report(report)


if __name__=='__main__': unittest.main()
