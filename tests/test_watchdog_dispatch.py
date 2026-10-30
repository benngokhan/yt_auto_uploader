import io
import json
import os
import tempfile
import textwrap
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import slot_guard

ROOT = Path(__file__).resolve().parent.parent

def watchdog_script():
    text=(ROOT/'.github/workflows/slot-watchdog.yml').read_text(encoding='utf-8')
    step=text.split('      - name: Video yayina cikti mi?',1)[1].split('      - name: Telegram alarmi',1)[0]
    source=step.split("python - <<'PY'\n",1)[1].split('\n          PY',1)[0]
    return textwrap.dedent(source)

class Reply:
    def __init__(self, body=None, status=200):
        self.body=json.dumps(body or {}).encode();self.status=status
    def read(self,*args): return self.body

class WatchdogDispatchTests(unittest.TestCase):
    def run_script(self, *, info, existing_log='', claims='', runs=(), fail_get=False):
        calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); (p/'uploaded.txt').write_text(existing_log,encoding='utf-8')
            (p/'slot_claims.txt').write_text(claims,encoding='utf-8')
            out=p/'github_output';out.write_text('')
            def fake_urlopen(req,timeout=0):
                if req.get_method()=='POST':
                    calls.append(json.loads(req.data.decode()))
                    return Reply(status=204)
                if fail_get: raise OSError('simulated GitHub outage')
                return Reply({'workflow_runs':list(runs)})
            env={'GITHUB_EVENT_SCHEDULE':'45 13 * * 5','GH_TOKEN':'not-a-real-token',
                 'REPO':'example/repo','GITHUB_OUTPUT':str(out)}
            old=os.getcwd()
            try:
                os.chdir(tmp)
                with patch.dict(os.environ,env,clear=False), \
                     patch.object(slot_guard,'watchdog_slot',return_value=info), \
                     patch.object(urllib.request,'urlopen',side_effect=fake_urlopen), \
                     patch('sys.stdout',new_callable=io.StringIO):
                    try: exec(compile(watchdog_script(),'<watchdog>','exec'),{})
                    except SystemExit as exc:
                        self.assertEqual(exc.code,0)
                output=out.read_text()
            finally: os.chdir(old)
        return calls,output

    def test_long_rescue_has_exact_slot_and_type(self):
        key='2026-10-30T13:00Z'
        calls,output=self.run_script(info=(key,'long','tescil'))
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['inputs']['video_type'],'long')
        self.assertEqual(calls[0]['inputs']['recovery_slot'],key)
        self.assertIn('alert=true',output)

    def test_completed_slot_prevents_dispatch(self):
        key='2026-10-30T13:00Z'
        row=f'f | uzun_video_18.mp4 | https://youtu.be/abc | 2026-10-30 13:05 | title | SLOT={key}\n'
        calls,output=self.run_script(info=(key,'long','tescil'),existing_log=row)
        self.assertEqual(calls,[])
        self.assertEqual(output,'')

    def test_claim_without_completion_alerts_without_another_upload(self):
        key='2026-10-30T13:00Z'
        calls,output=self.run_script(info=(key,'long','tescil'),claims=key+'\n')
        self.assertEqual(calls,[])
        self.assertIn('alert=true',output)
        self.assertIn('otomatik tekrar durduruldu',output)

    def test_push_validation_run_does_not_mask_missing_schedule(self):
        key='2026-10-30T13:00Z'
        run={'name':'YouTube Drive Uploader','event':'push','status':'completed','created_at':'2026-10-30T13:02:00Z'}
        calls,_=self.run_script(info=(key,'long','tescil'),runs=[run])
        self.assertEqual(len(calls),1)

    def test_unavailable_github_api_alerts_but_never_blindly_dispatches(self):
        key='2026-10-30T13:00Z'
        calls,output=self.run_script(info=(key,'long','tescil'),fail_get=True)
        self.assertEqual(calls,[])
        self.assertIn('alert=true',output)
        self.assertIn('doğrulanamadı',output)

    def test_started_scheduled_run_blocks_rescue(self):
        key='2026-10-30T13:00Z'
        run={'name':'YouTube Drive Uploader','event':'schedule','status':'in_progress','created_at':'2026-10-30T13:01:00Z'}
        calls,output=self.run_script(info=(key,'long','tescil'),runs=[run])
        self.assertEqual(calls,[])
        self.assertIn('alert=true',output)

if __name__=='__main__':
    unittest.main()
