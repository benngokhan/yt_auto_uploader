import base64,hashlib,json,os,re,urllib.request,urllib.error
from pathlib import Path

EXPECTED_REF='9c2e458570272cadc250817ac88f4ad1f0b24ac07814f38e711b1377c0b41850'
EXPECTED_PLAN='baced3010132aaecb14949ffad310ae5c0ac467365c63a283b059d19f488b28b'
token=os.environ.get('CF_TOKEN','').strip();account=os.environ.get('CF_ACCOUNT','').strip()
if not token or not re.fullmatch('[a-fA-F0-9]{32}',account):
 print('STOP=missing_or_invalid_secret_format',flush=True);raise SystemExit(1)
ref=Path('arena_reference/scene1_reference_270x480.png').read_bytes()
planbytes=Path('arena_reference/007_run117_visual_plan.json').read_bytes()
if hashlib.sha256(ref).hexdigest()!=EXPECTED_REF or hashlib.sha256(planbytes).hexdigest()!=EXPECTED_PLAN:
 print('STOP=reference_or_plan_hash_mismatch',flush=True);raise SystemExit(1)
plan=json.loads(planbytes);tasks=plan['tasks']
if len(tasks)!=4 or [t['image_index'] for t in tasks]!=[0,1,2,3]:raise SystemExit('bad plan')
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
op=urllib.request.build_opener(NoRedirect())
reserve=urllib.request.Request('https://api.github.com/repos/'+os.environ['REPO']+'/git/refs',data=json.dumps({'ref':'refs/heads/arena/cf-three-scenes-run117-consumed-20261122','sha':os.environ['SHA']}).encode(),headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json','User-Agent':'three-scenes-guard'},method='POST')
try:
 with op.open(reserve,timeout=20) as r:
  if r.status!=201:raise ValueError('bad reservation response')
except Exception as e:
 print('STOP=reservation_failed_or_exists; TYPE='+type(e).__name__,flush=True);raise SystemExit(1)
print('RESERVATION=created',flush=True)
Path('scene_results').mkdir(exist_ok=True)
manifest={'kind':'three_single_requests_approval_consumed','reference_sha256':EXPECTED_REF,'original_scene1_sha256':'8b6279ff90371e2d6f7d2b07e36f45e7ebd5aca1f1f918b1366cddbdbd073849','plan_sha256':EXPECTED_PLAN,'provider':'cloudflare_workers_ai','model':'@cf/black-forest-labs/flux-2-klein-4b','requests_started':0,'results':[]}
error=False
for i in (1,2,3):
 prompt=tasks[i]['prompt']+' Use the attached reference only for candle material and natural warm lighting; the current shot description takes precedence. This is a close-up of the candle, no face or person visible.'
 if i==3:prompt+=' The candle is completely extinguished; do not retain the burning flame from the reference.'
 boundary='arena_remaining_scenes_117_4b'
 parts=[]
 for k,v in [('prompt',prompt),('width','720'),('height','1280'),('seed','42817')]:
  parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+k+'"\r\n\r\n'+v+'\r\n').encode())
 parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="input_image_0"; filename="reference.png"\r\nContent-Type: image/png\r\n\r\n').encode()+ref+b'\r\n')
 parts.append(('--'+boundary+'--\r\n').encode())
 request=urllib.request.Request('https://api.cloudflare.com/client/v4/accounts/'+account+'/ai/run/@cf/black-forest-labs/flux-2-klein-4b',data=b''.join(parts),headers={'Authorization':'Bearer '+token,'Accept':'application/json','Content-Type':'multipart/form-data; boundary='+boundary,'User-Agent':'bounded-three-scenes'},method='POST')
 manifest['requests_started']+=1
 print('SCENE='+str(i+1)+'; INFERENCE_REQUEST=starting',flush=True)
 try:
  with op.open(request,timeout=120) as response:
   data=response.read(16000001)
   if len(data)>16000000:raise ValueError('response too large')
   result=json.loads(data)
   if result.get('success') is False:raise ValueError('provider rejected')
   raw=base64.b64decode(result.get('result',result)['image'],validate=True)
   if not raw.startswith(b'\x89PNG\r\n\x1a\n') and not raw.startswith(b'\xff\xd8\xff'):raise ValueError('invalid image')
   suffix='.png' if raw.startswith(b'\x89PNG') else '.jpg'
   name='scene_'+str(i+1)+suffix;Path('scene_results/'+name).write_bytes(raw)
   digest=hashlib.sha256(raw).hexdigest()
   manifest['results'].append({'scene':i+1,'status':'image','file':name,'sha256':digest,'requested_width':720,'requested_height':1280,'seed':42817,'prompt':prompt})
   print('SCENE='+str(i+1)+'; RESULT=IMAGE; SHA256='+digest,flush=True)
 except urllib.error.HTTPError as e:
  manifest['results'].append({'scene':i+1,'status':'http_error','http_status':e.code})
  print('SCENE='+str(i+1)+'; RESULT=HTTP_ERROR; STATUS='+str(e.code)+'; NO_RETRY; STOP',flush=True);error=True
 except Exception as e:
  manifest['results'].append({'scene':i+1,'status':'error','error_type':type(e).__name__})
  print('SCENE='+str(i+1)+'; RESULT=ERROR; TYPE='+type(e).__name__+'; NO_RETRY; STOP',flush=True);error=True
 Path('scene_results/result_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 if error:break
print('REQUESTS_STARTED='+str(manifest['requests_started'])+'; NO_RETRY; NO_RENDER; NO_PUBLISH',flush=True)
if error:raise SystemExit(1)
