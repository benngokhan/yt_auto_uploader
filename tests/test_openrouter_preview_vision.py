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

class PreviewSearchTests(unittest.TestCase):
    def test_experimental_search_rejects_queries_without_main_subject(self):
        import uret
        result={'ana_nesne':'candle','sahneler_gorsel':[
            {'ana':'human breath fog','alternatif':'candle smoke'},
            {'ana':'candle flame','alternatif':'hot air balloon'}]}
        with mock.patch.dict(os.environ, {'MOTOR_EXPERIMENTAL_OPENROUTER':'1'}), \
             mock.patch.object(uret,'_llm_json',return_value=result):
            queries,_=uret._gorsel_aramalari('mum',['one','two'],{})
        self.assertEqual(queries,[{'ana':'candle smoke','alternatif':''},
                                  {'ana':'candle flame','alternatif':''}])

    def test_figurative_end_of_life_query_is_rejected_not_generalized(self):
        import uret
        response={'ana_nesne':'candle','sahneler_gorsel':[
            {'ana':'candle wick','alternatif':'candle end of life daylight'}]}
        with mock.patch.dict(os.environ, {'MOTOR_EXPERIMENTAL_OPENROUTER':'1'}), \
             mock.patch.object(uret,'_llm_json',return_value=response):
            queries,_=uret._gorsel_aramalari('mum',['one'],{})
        self.assertEqual(queries,[{'ana':'candle wick','alternatif':''}])

    def test_missing_subject_fails_closed(self):
        import uret
        with mock.patch.dict(os.environ, {'MOTOR_EXPERIMENTAL_OPENROUTER':'1'}), \
             mock.patch.object(uret,'_llm_json',return_value={'sahneler_gorsel':[{'ana':'candle flame'}]}):
            queries,_=uret._gorsel_aramalari('mum',['one'],{})
        self.assertEqual(queries,[{'ana':'','alternatif':''}])

    def test_preview_only_uses_pexels_and_limits_candidates(self):
        import tempfile
        settings={'MOTOR_EXPERIMENTAL_OPENROUTER':'1','MOTOR_VISUAL_QA_PASSED':'1',
                  'PEXELS_API_KEY':'pex','PIXABAY_API_KEY':'pix'}
        # Search can return more than requested when its two API queries merge.
        hits=[{'uid':f'pexels:{n}','id':n,'kaynak':'pexels','tags':'candle flame'} for n in range(7)]
        hits[0]['tags']='candle coffee'  # Existing metadata filter rejects this before vision.
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ,settings), \
             mock.patch.object(gorsel_uret,'pexels_ara',return_value=hits) as pex, \
             mock.patch.object(gorsel_uret,'pixabay_ara') as pix, \
             mock.patch.object(gorsel_uret,'_visual_text_scores',return_value=[None]*4) as judge:
            result=gorsel_uret.sahneler_icin_gorseller([{'gorsel':'candle flame','ses':'mum'}],Path(td))
        self.assertEqual(result,[None])
        self.assertEqual(pex.call_args.kwargs['adet'],4)
        self.assertEqual(len(judge.call_args.args[1]), 4)
        self.assertEqual([x['id'] for x in judge.call_args.args[1]], [1,2,3,4])
        pix.assert_not_called()

    def test_preview_reuses_judgment_only_within_same_scene(self):
        import tempfile
        settings={'MOTOR_EXPERIMENTAL_OPENROUTER':'1','MOTOR_VISUAL_QA_PASSED':'1','PEXELS_API_KEY':'pex'}
        def search(query, key, adet):
            ids = [1,2] if query == 'candle flame' else [2,3]
            return [{'uid':f'pexels:{n}','id':n,'kaynak':'pexels','tags':'candle flame'} for n in ids]
        calls=[]
        def judge(text, hits):
            calls.append((text,[hit['id'] for hit in hits]))
            for hit in hits:
                hit['_vision_origin']='live_openrouter_experimental'
            return [0.5]*len(hits)  # remain below the acceptance threshold
        scenes=[{'gorsel':'candle flame','gorsel_alternatif':'candle daylight','ses':'mum one'},
                {'gorsel':'candle flame','gorsel_alternatif':'candle daylight','ses':'mum two'}]
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ,settings,clear=False), \
             mock.patch.object(gorsel_uret,'pexels_ara',side_effect=search), \
             mock.patch.object(gorsel_uret,'_visual_text_scores',side_effect=judge):
            self.assertEqual(gorsel_uret.sahneler_icin_gorseller(scenes,Path(td)),[None,None])
        self.assertEqual([ids for _,ids in calls],[[1,2],[3],[1,2],[3]])
        self.assertIn('one',calls[0][0])
        self.assertIn('two',calls[2][0])

if __name__ == '__main__': unittest.main()
