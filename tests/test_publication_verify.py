import ast
import contextlib
from datetime import datetime,timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
from scripts import publication_verify as v

KEY='2026-11-24T16:30Z'
ROW={'slot':KEY,'filename':'video_184.mp4','video_id':'abcdefghijk','url':'https://youtu.be/abcdefghijk','title':'Uçak & bilim'}
VIDEO={'id':'abcdefghijk','status':{'privacyStatus':'public'},'snippet':{'channelId':'ours','title':'Uçak & bilim #shorts'}}

class VerificationTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup);self.root=Path(td.name)
        (self.root/'uploaded.txt').write_text('id | video_184.mp4 | https://youtu.be/abcdefghijk | 2026-11-24 12:00 | Uçak | SLOT='+KEY+'\n')
        for name,value in [('ROOT',self.root),('LEDGER',self.root/'publication_notifications.json'),('PAYLOAD',self.root/'publication_notice.json')]:
            p=patch.object(v,name,value);p.start();self.addCleanup(p.stop)
        p=patch.dict(os.environ,{'GITHUB_RUN_ID':'run-1','TELEGRAM_CHAT_ID':'chat-test'});p.start();self.addCleanup(p.stop)
    def test_latest_due_slot_today_and_yesterday(self):
        self.assertEqual(v.latest_due_slot(datetime(2026,11,24,16,35,tzinfo=timezone.utc)),KEY)
        self.assertEqual(v.latest_due_slot(datetime(2026,11,24,14,0,tzinfo=timezone.utc)),'2026-11-23T16:30Z')
    def test_exact_slot_row_not_historical_or_other_slot(self):
        self.assertEqual(v.slot_row(KEY)['filename'],'video_184.mp4')
        self.assertIsNone(v.slot_row('2026-11-23T16:30Z'))
    def test_duplicate_slot_records_fail_closed(self):
        p=self.root/'uploaded.txt';p.write_text(p.read_text()*2)
        with self.assertRaises(RuntimeError):v.slot_row(KEY)
    def test_wrong_channel_is_rejected(self):
        yt=Mock();yt.channels().list().execute.return_value={'items':[{'id':'other','snippet':{'customUrl':'@other'}}]}
        with self.assertRaises(RuntimeError):v.channel(yt)
    def test_video_owner_mismatch_is_rejected(self):
        yt=Mock();yt.videos().list().execute.return_value={'items':[VIDEO]}
        with self.assertRaises(RuntimeError):v.get_video(yt,ROW,'other')
    def test_no_record_skips_without_any_network(self):
        with patch.object(v,'latest_due_slot',return_value='2026-11-23T16:30Z'),patch.object(v,'clients') as clients:
            self.assertFalse(v.prepare()['ready']);clients.assert_not_called()
    def test_existing_sent_or_uncertain_reservation_never_resends(self):
        for state in ['pending','sent']:
            v.LEDGER.write_text(json.dumps({KEY:{'state':state}}))
            with patch.object(v,'latest_due_slot',return_value=KEY),patch.object(v,'clients') as clients:
                self.assertFalse(v.prepare()['ready']);clients.assert_not_called()
    def prepare_fixture(self, public=True):
        video=dict(VIDEO);video['status']={'privacyStatus':'public' if public else 'private'}
        with contextlib.ExitStack() as stack:
            for name,value in [('latest_due_slot',lambda:KEY),('clients',lambda:(object(),object())),('channel',lambda yt:'ours'),
                ('get_video',lambda *args:video),('load_table_from_drive_or_local',lambda *a:{}),('list_drive_videos',lambda *a:[])]:stack.enter_context(patch.object(v,name,value))
            return v.prepare()
    def test_private_video_never_generates_green_card(self):
        self.assertFalse(self.prepare_fixture(False)['ready']);self.assertFalse(v.PAYLOAD.exists())
    def test_public_video_generates_requested_card(self):
        self.assertTrue(self.prepare_fixture()['ready'])
        text=json.loads(v.PAYLOAD.read_text())['payload']['text']
        self.assertIn('🟢 <b>BİLGİ DOZU · YENİ VİDEO YAYINDA!',text)
        self.assertIn('YOUTUBE GÖNDERİLER METNİ',text);self.assertIn('Uçak &amp; bilim',text)
        self.assertIn(ROW['url'],text)
    def test_reservation_is_bound_to_run_video_and_payload(self):
        self.prepare_fixture()
        with patch.object(v,'latest_due_slot',return_value=KEY):
            self.assertTrue(v.reserve()['reserved'])
            with self.assertRaises(RuntimeError):v.reserve()
        row=json.loads(v.LEDGER.read_text())[KEY]
        self.assertEqual(row['state'],'pending');self.assertEqual(row['run_id'],'run-1')
        self.assertTrue(row['payload_sha256'])
    def test_send_without_reservation_never_calls_telegram(self):
        self.prepare_fixture()
        with patch.object(v,'telegram') as send:
            with self.assertRaises(RuntimeError):v.send()
            send.assert_not_called()
    def reserve_fixture(self):
        self.prepare_fixture()
        with patch.object(v,'latest_due_slot',return_value=KEY):v.reserve()
    def test_recheck_private_blocks_send_even_after_reservation(self):
        self.reserve_fixture()
        with patch.object(v,'clients',return_value=(object(),object())),patch.object(v,'channel',return_value='ours'),patch.object(v,'get_video',return_value={'status':{'privacyStatus':'private'}}),patch.object(v,'telegram') as send:
            with self.assertRaises(RuntimeError):v.send()
            send.assert_not_called()
    def test_success_records_telegram_message_id_and_deduplicates(self):
        self.reserve_fixture()
        with patch.object(v,'clients',return_value=(object(),object())),patch.object(v,'channel',return_value='ours'),patch.object(v,'get_video',return_value=VIDEO),patch.object(v,'telegram',return_value={'message_id':123}) as send:
            self.assertEqual(v.send()['message_id'],123)
            with self.assertRaises(RuntimeError):v.send()
            self.assertEqual(send.call_count,1)
        self.assertEqual(json.loads(v.LEDGER.read_text())[KEY]['state'],'sent')
    def test_unknown_send_response_stays_pending_no_blind_retry(self):
        self.reserve_fixture()
        with patch.object(v,'clients',return_value=(object(),object())),patch.object(v,'channel',return_value='ours'),patch.object(v,'get_video',return_value=VIDEO),patch.object(v,'telegram',side_effect=RuntimeError('Unknown response')):
            with self.assertRaises(RuntimeError):v.send()
        self.assertEqual(json.loads(v.LEDGER.read_text())[KEY]['state'],'pending')
    def test_payload_tamper_prevents_send(self):
        self.reserve_fixture();v.PAYLOAD.write_text(v.PAYLOAD.read_text()+' ')
        with patch.object(v,'telegram') as send:
            with self.assertRaises(RuntimeError):v.send()
            send.assert_not_called()
    def test_failed_durable_push_prevents_telegram(self):
        with patch.object(v,'prepare',return_value={'ready':True}),patch.object(v,'reserve'),patch.object(v,'persist_notifications',side_effect=RuntimeError()),patch.object(v,'send') as send:
            with self.assertRaises(RuntimeError):v.deliver()
            send.assert_not_called()
    def test_deliver_order_persist_before_send_then_persist_receipt(self):
        order=[]
        with patch.object(v,'prepare',return_value={'ready':True}),patch.object(v,'reserve',side_effect=lambda:order.append('reserve')),patch.object(v,'persist_notifications',side_effect=lambda:order.append('persist')),patch.object(v,'send',side_effect=lambda:order.append('send')):
            v.deliver()
        self.assertEqual(order,['reserve','persist','send','persist'])
    def test_card_counts_one_short_per_day_not_two(self):
        records={'video_185.mp4':{'is_ready':True,'pinned_comment':'<yorum>'}}
        payload=v.make_card(ROW,VIDEO,records,[{'name':'video_185.mp4'}],set())
        self.assertIn('1 Shorts · 0 Uzun (~1 Gün)',payload['text'])
    def test_health_uses_read_only_preflight_then_one_labelled_test(self):
        with patch.object(v,'clients',return_value=(object(),object())),patch.object(v,'channel',return_value='ours'),patch.object(v.planner,'inspect',return_value={'should_plan':'true','slot':KEY,'name':'video_184.mp4'}),patch.object(v,'telegram',side_effect=[{'is_bot':True},{'id':1},{'message_id':321}]) as tg:
            result=v.health(True)
            self.assertEqual(result['test_message_id'],321)
            self.assertEqual([c.args[0] for c in tg.call_args_list],['getMe','getChat','sendMessage'])
            self.assertIn('testidir',tg.call_args_list[-1].args[1]['text'])
    def test_helper_has_no_video_insertion_update_delete_or_inference(self):
        tree=ast.parse(Path(v.__file__).read_text())
        forbidden={'delete','generate_content','generate_images','generate_speech'}
        self.assertNotIn('.videos().insert(',Path(v.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):self.assertNotIn(node.func.attr,forbidden)

if __name__=='__main__':unittest.main()
