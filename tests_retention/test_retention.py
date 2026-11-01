import importlib.util
import io
import json
import os
from datetime import datetime, date, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from openpyxl import load_workbook

SCRIPT=Path(__file__).resolve().parent.parent / 'retansiyon_raporu.py'
spec=importlib.util.spec_from_file_location('retention_tested',SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def analytics(rows=None, headers=None):
    headers=headers or ['video','views','estimatedMinutesWatched','averageViewDuration','averageViewPercentage']
    return {'columnHeaders':[{'name':h} for h in headers], 'rows':rows or []}

def curve(rows=None):
    return {'columnHeaders':[{'name':'elapsedVideoTimeRatio'},{'name':'audienceWatchRatio'}], 'rows':rows or []}

def valid_acl():
    return {'permissions':[{'id':k,'type':'user','role':v} for k,v in m.EXPECTED_PERMISSIONS.items()]}

class CredentialsTests(unittest.TestCase):
    def test_web_client_and_separate_refresh(self):
        c=m.oauth_config(json.dumps({'web':{'client_id':'id','client_secret':'secret'}}),'refresh')
        self.assertEqual(c['refresh_token'],'refresh');self.assertEqual(c['grant_type'],'refresh_token')
    def test_flat_drive_credentials(self):
        c=m.oauth_config(json.dumps({'client_id':'id','client_secret':'secret','refresh_token':'ref'}));self.assertEqual(c['refresh_token'],'ref')
    def test_no_secret_in_error(self):
        with self.assertRaises(m.SafeError) as e:m.oauth_config('topsecret-not-json')
        self.assertNotIn('topsecret',str(e.exception))
    def test_refuses_unknown_hostname(self):
        with self.assertRaises(m.SafeError):m.request_json('https://example.com/x',bearer='token')

class PrivateAclTests(unittest.TestCase):
    def test_exact_acl_passes(self):m.validate_acl(valid_acl())
    def test_public_permission_rejected(self):
        x=valid_acl();x['permissions'].append({'id':'anyone','type':'anyone','role':'reader'})
        with self.assertRaises(m.SafeError):m.validate_acl(x)
    def test_domain_and_group_rejected(self):
        for typ in ('group','domain'):
            x=valid_acl();x['permissions'].append({'id':'other','type':typ,'role':'reader'})
            with self.subTest(typ=typ),self.assertRaises(m.SafeError):m.validate_acl(x)
    def test_new_user_rejected(self):
        x=valid_acl();x['permissions'].append({'id':'unexpected','type':'user','role':'reader'})
        with self.assertRaises(m.SafeError):m.validate_acl(x)
    def test_wrong_role_missing_and_pagination_rejected(self):
        for x in [dict(valid_acl(),nextPageToken='more'),{'permissions':valid_acl()['permissions'][:1]},
                  {'permissions':[{'id':k,'type':'user','role':'reader'} for k in m.EXPECTED_PERMISSIONS]}]:
            with self.subTest(x=x),self.assertRaises(m.SafeError):m.validate_acl(x)
    def test_duplicate_and_deleted_rejected(self):
        for extra in [valid_acl()['permissions'][0],{'id':'x','type':'user','role':'reader','deleted':True}]:
            x=valid_acl();x['permissions'].append(extra)
            with self.subTest(extra=extra),self.assertRaises(m.SafeError):m.validate_acl(x)
    def test_public_repo_rejected(self):
        with patch.object(m,'request_json',return_value={'full_name':m.REPOSITORY,'private':False}):
            with self.assertRaises(m.SafeError):m.verify_private_repository('gh')
    def test_private_correct_repo_ok(self):
        with patch.object(m,'request_json',return_value={'full_name':m.REPOSITORY,'private':True}):m.verify_private_repository('gh')
    def test_private_folder_can_hide_parent_but_report_parent_is_checked(self):
        folder={'id':m.FOLDER_ID,'mimeType':'application/vnd.google-apps.folder','capabilities':{'canAddChildren':True}}
        file={'id':m.REPORT_ID,'mimeType':m.XLSX_MIME,'parents':[m.FOLDER_ID],'capabilities':{'canEdit':True}}
        with patch.object(m,'request_json',side_effect=[folder,valid_acl(),file,valid_acl()]):m.verify_private_destination('drive')
        file['parents']=['wrong']
        with patch.object(m,'request_json',side_effect=[folder,valid_acl(),file,valid_acl()]):
            with self.assertRaises(m.SafeError):m.verify_private_destination('drive')
    def test_even_with_hidden_parent_public_acl_is_blocked(self):
        folder={'id':m.FOLDER_ID,'mimeType':'application/vnd.google-apps.folder','capabilities':{'canAddChildren':True}}
        bad=valid_acl();bad['permissions'].append({'id':'anyone','type':'anyone','role':'reader'})
        with patch.object(m,'request_json',side_effect=[folder,bad]):
            with self.assertRaises(m.SafeError):m.verify_private_destination('drive')

class AnalyticsTests(unittest.TestCase):
    def test_valid_rows_percentage_is_already_percent(self):
        got=m.parse_video_report(analytics([['abcdefghijk',12,5.5,22.0,54.53]]))
        self.assertEqual(got[0]['average_percent'],54.53);self.assertEqual(got[0]['views'],12)
    def test_headers_order_not_assumed(self):
        got=m.parse_video_report(analytics([[54.53,'abcdefghijk',12,5.5,22.0]],['averageViewPercentage','video','views','estimatedMinutesWatched','averageViewDuration']))
        self.assertEqual(got[0]['average_seconds'],22.0)
    def test_empty_video_report_fails_closed(self):
        with self.assertRaises(m.SafeError):m.parse_video_report(analytics())
    def test_missing_column_fails_closed(self):
        with self.assertRaises(m.SafeError):m.parse_video_report(analytics([[1]],['video']))
    def test_duplicate_video_fails_closed(self):
        row=['abcdefghijk',12,5.5,22,54]
        with self.assertRaises(m.SafeError):m.parse_video_report(analytics([row,row]))
    def test_nonfinite_value_fails_closed(self):
        with self.assertRaises(m.SafeError):m.parse_video_report(analytics([['abcdefghijk',12,5.5,22,float('nan')]]))
    def test_curve_empty_is_missing_not_zero(self):self.assertEqual(m.parse_curve_report({}),[])
    def test_curve_ratio_can_exceed_100(self):
        pts=m.parse_curve_report(curve([[0.05,1.23],[0.1,0.9]]))
        self.assertEqual(m.closest_retention(pts,60),(3.0,123.0))
    def test_duplicate_curve_point_fails(self):
        with self.assertRaises(m.SafeError):m.parse_curve_report(curve([[0.1,1],[0.1,2]]))
    def test_duration_variants(self):
        for source,sec in [('PT57S',57),('PT1H2M3S',3723),('P1DT2H',93600)]:
            self.assertEqual(m.parse_duration(source),sec)
        self.assertIsNone(m.parse_duration('PT0S'));self.assertIsNone(m.parse_duration('bad'))
    def test_query_uses_correct_channel_metrics_and_dates(self):
        with patch.object(m,'request_json',return_value={}) as req:
            m.query_report('secret',date(2026,10,1),date(2026,10,30));url=req.call_args.args[0]
            self.assertIn('youtubeanalytics.googleapis.com/v2/reports',url)
            self.assertIn('averageViewPercentage',url);self.assertNotIn('percentViewed',url)
            self.assertIn('2026-10-01',url)
    def test_each_curve_only_one_video(self):
        with patch.object(m,'request_json',return_value={}) as req:
            m.query_report('x',date(2026,10,1),date(2026,10,30),video_id='abcdefghijk')
            self.assertIn('elapsedVideoTimeRatio',req.call_args.args[0]);self.assertIn('audienceWatchRatio',req.call_args.args[0])
        with self.assertRaises(m.SafeError):m.query_report('x',date(2026,10,1),date(2026,10,30),video_id='../../evil')

class ReportTests(unittest.TestCase):
    def setUp(self):
        self.row={'video_id':'abcdefghijk','views':100,'watch_minutes':34.4,'average_seconds':21.2,'average_percent':54.53}
        self.details={'abcdefghijk':{'title':'=HYPERLINK("https://bad")','published':'2026-10-27T01:00:00Z','duration':60}}
        self.curves={'abcdefghijk':[(0.05,1.23),(0.1,0.9)]}
    def test_xlsx_is_separate_and_formula_safe(self):
        buf=m.report_xlsx([self.row],self.details,self.curves,date(2026,10,1),date(2026,10,30),datetime(2026,11,1,tzinfo=timezone.utc))
        book=load_workbook(io.BytesIO(buf),data_only=False)
        self.assertEqual(book.sheetnames,['Rapor Bilgisi','Video Metrikleri','Eğri Verileri','Grafikler'])
        self.assertEqual(book['Video Metrikleri']['A2'].data_type,'s')
        self.assertEqual(book['Video Metrikleri']['F2'].value,54.53)
        self.assertEqual(book['Video Metrikleri']['H2'].value,123.0)
        self.assertEqual(book['Eğri Verileri'].max_row,3);book.close()
    def test_empty_curve_not_presented_as_zero(self):
        buf=m.report_xlsx([self.row],self.details,{'abcdefghijk':[]},date(2026,10,1),date(2026,10,30),datetime(2026,11,1,tzinfo=timezone.utc))
        book=load_workbook(io.BytesIO(buf));self.assertIsNone(book['Video Metrikleri']['H2'].value)
        self.assertEqual(book['Video Metrikleri']['I2'].value,'Veri yok');book.close()
    def test_save_only_updates_fixed_file_and_verifies(self):
        import hashlib
        data=b'fake workbook bytes';h=hashlib.md5(data).hexdigest()
        with patch.object(m,'verify_private_destination') as verify,patch.object(m,'request_json',return_value={'id':m.REPORT_ID,'md5Checksum':h}) as req:
            m.upload_report('secret',data);self.assertEqual(verify.call_count,2)
            self.assertEqual(req.call_args_list[0].kwargs['method'],'PATCH')
            self.assertIn(m.REPORT_ID,req.call_args_list[0].args[0])
    def test_main_test_never_uploads(self):
        env={'RETENTION_MODE':'test','GH_READ_TOKEN':'x','BD_ANALYTICS_CLIENT_CONFIG':json.dumps({'client_id':'a','client_secret':'b'}),
             'BD_ANALYTICS_REFRESH_TOKEN':'c','GOOGLE_TOKEN_JSON':json.dumps({'client_id':'a','client_secret':'b','refresh_token':'c'})}
        with patch.dict(os.environ,env,clear=True),patch.object(m,'verify_private_repository'),patch.object(m,'refresh_token',return_value='t'),\
             patch.object(m,'assert_channel'),patch.object(m,'verify_private_destination'),patch.object(m,'query_report',return_value=analytics([['abcdefghijk',100,34.4,21.2,54.53]])),\
             patch.object(m,'video_details',return_value=self.details),patch.object(m,'acquire_curves',return_value=self.curves),patch.object(m,'upload_report') as up:
            self.assertEqual(m.main(),0);up.assert_not_called()
    def test_invalid_mode_never_uploads(self):
        with patch.dict(os.environ,{'RETENTION_MODE':'bad'},clear=True),patch.object(m,'upload_report') as up:
            with self.assertRaises(m.SafeError):m.main()
            up.assert_not_called()

if __name__=='__main__':unittest.main()
