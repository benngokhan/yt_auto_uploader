"""Four explicitly approved image calls. No retries, TTS, render or publication."""
import os,json,hashlib,sys,time,base64,urllib.request,urllib.error,uuid,re
from pathlib import Path
REPO=os.environ['GITHUB_REPOSITORY'];SHA=os.environ['GITHUB_SHA']
LOCK='refs/tags/arena-deniz-images-v2-consumed-20261122'
OUT=Path('image_results');OUT.mkdir(exist_ok=False)
plan_bytes=Path('arena_deniz/plan.json').read_bytes();plan=json.loads(plan_bytes)
assert len(plan['scenes'])==4 and plan['assistant_chosen_request_ceiling']==4
assert plan['automatic_retry'] is False and plan['automatic_fallback'] is False
assert re.fullmatch(r'[a-fA-F0-9]{32}',os.environ.get('CF_ACCOUNT',''))
assert os.environ.get('CF_TOKEN','').strip()
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**kw):return None
opener=urllib.request.build_opener(NoRedirect)
def req(url,data,headers):
 r=urllib.request.Request(url,data=data,headers=headers,method='POST')
 return opener.open(r,timeout=150)
# Durable consumed-ref reservation before any inference. Failure is fail-closed.
with req('https://api.github.com/repos/'+REPO+'/git/refs',json.dumps({'ref':LOCK,'sha':SHA}).encode(),{'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','User-Agent':'deniz-four-bounded-images','Content-Type':'application/json'}) as r:
 assert r.status==201
record={'kind':'four_image_attempts','plan_sha256':hashlib.sha256(plan_bytes).hexdigest(),'model':plan['model'],'attempts':[],'retry_count':0,'publication':False,'billing':'User-declared free account, not independently measured','run_id':os.environ.get('GITHUB_RUN_ID')}
def save():
 (OUT/'manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
save()
for scene in plan['scenes']:
 row={'scene':scene['scene'],'seed':scene['seed'],'prompt':scene['prompt'],'state':'reserved_before_post','request_width':plan['width'],'request_height':plan['height']}
 record['attempts'].append(row);save()
 boundary='arena_'+uuid.uuid4().hex
 fields={'prompt':scene['prompt'],'width':str(plan['width']),'height':str(plan['height']),'seed':str(scene['seed'])}
 parts=[]
 for k,v in fields.items():parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+k+'"\r\n\r\n'+v+'\r\n').encode())
 body=b''.join(parts)+('--'+boundary+'--\r\n').encode()
 url='https://api.cloudflare.com/client/v4/accounts/'+os.environ['CF_ACCOUNT']+'/ai/run/'+plan['model']
 try:
  row['state']='post_attempted';save()
  with req(url,body,{'Authorization':'Bearer '+os.environ['CF_TOKEN'],'Content-Type':'multipart/form-data; boundary='+boundary}) as response:
   raw=response.read(20*1024*1024);ct=response.headers.get('Content-Type','')
  if 'json' in ct:
   obj=json.loads(raw)
   if obj.get('success') is False:raise ValueError('provider_success_false')
   result=obj.get('result') or obj
   encoded=result.get('image') or result.get('output')
   if not isinstance(encoded,str):raise ValueError('missing_base64_image')
   if encoded.startswith('data:'):encoded=encoded.split(',',1)[1]
   raw=base64.b64decode(encoded,validate=True)
  if raw.startswith(b'\xff\xd8\xff'):ext='jpg'
  elif raw.startswith(b'\x89PNG\r\n\x1a\n'):ext='png'
  else:raise ValueError('unknown_image_bytes')
  name='scene_'+str(scene['scene'])+'.'+ext;p=OUT/name;p.write_bytes(raw)
  from PIL import Image
  with Image.open(p) as im:
   im.load();row.update(width=im.width,height=im.height,format=im.format)
  row.update(state='received_needs_review',file=name,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw));save()
  print('scene',scene['scene'],'received',row['width'],row['height'],'needs review',flush=True)
 except urllib.error.HTTPError as e:
  row.update(state='failed',http_status=e.code);save();print('scene failed HTTP',e.code,'stopping without retry',flush=True);sys.exit(1)
 except Exception as e:
  row.update(state='failed',error_type=type(e).__name__);save();print('scene failed; stopping without retry',type(e).__name__,flush=True);sys.exit(1)
record['complete']=True;save()
