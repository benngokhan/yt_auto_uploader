"""096 single authorized autonomous provider -> review -> align -> motor-render test.
No native Arena generation, no retry/fallback, no publication or queue writes.
"""
from pathlib import Path
import base64,hashlib,io,json,os,re,subprocess,sys,uuid,wave,urllib.request,urllib.error
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];HERE=Path(__file__).resolve().parent
OUT=ROOT/'result_099';WORK=ROOT/'work_099';BRANCH='arena/hardening-099-NOT-AUTHORIZED'
AUTH='UNAUTHORIZED_099_OFFLINE_ONLY';TTS_MODEL='gemini-2.5-flash-preview-tts';IMAGE_MODEL='@cf/black-forest-labs/flux-2-klein-4b';REVIEW_MODEL='gemini-2.5-flash'
from provider_io import Stop, ProviderFailure, Budget
from visual_quality import review_prompt, validate_review
from audio_quality import verify_file

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,obj):Path(p).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def require_keys():
 names=['GEMINI_API_KEY','CLOUDFLARE_ACCOUNT_ID','CLOUDFLARE_API_TOKEN']
 if any(not os.environ.get(n,'').strip() for n in names):raise Stop('Required provider secret missing; no alternate provider')
 if not re.fullmatch('[a-fA-F0-9]{32}',os.environ['CLOUDFLARE_ACCOUNT_ID']):raise Stop('Cloudflare account format invalid')

def generate_voice(plan,budget,target):
 narration=' '.join(plan['script_lines']);prompt=plan['voice_direction']+'\n\nMETİN:\n'+narration
 body=json.dumps({'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'responseModalities':['AUDIO'],'speechConfig':{'voiceConfig':{'prebuiltVoiceConfig':{'voiceName':'Charon'}}}}},ensure_ascii=False).encode()
 raw,_=budget.post('tts','https://generativelanguage.googleapis.com/v1beta/models/'+TTS_MODEL+':generateContent',body,{'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']},16*1024*1024)
 try:
  parts=json.loads(raw)['candidates'][0]['content']['parts'];audio=[p['inlineData'] for p in parts if 'inlineData' in p]
  if len(audio)!=1 or not re.fullmatch('audio/L16;codec=pcm;rate=24000',audio[0]['mimeType'],re.I):raise ValueError()
  pcm=base64.b64decode(audio[0]['data'],validate=True)
  if not pcm or len(pcm)%2:raise ValueError()
 except Exception:raise Stop('Unexpected Charon response; no fallback') from None
 with wave.open(str(target),'wb') as w:w.setparams((1,2,24000,0,'NONE','not compressed'));w.writeframes(pcm)
 duration=len(pcm)/48000
 proof={'provider':'gemini','model':TTS_MODEL,'voice':'Charon','narration_sha256':hashlib.sha256(narration.encode()).hexdigest(),'audio_sha256':sha(target),'speed_factor':1,'natural_seconds':duration,'attempts':1,'voice_direction':plan['voice_direction']}
 save(WORK/'voice_provenance.json',proof)
 if not 40<=duration<=53:raise Stop('Natural voice outside40-53s; not stretched, cut, or regenerated')
 return proof

def generate_image(prompt,index,budget,target):
 boundary='arena096_'+uuid.uuid4().hex;fields={'prompt':prompt,'seed':str(9600+index),'width':'720','height':'1280'}
 body=b''.join(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+k+'"\r\n\r\n'+v+'\r\n').encode() for k,v in fields.items())+('--'+boundary+'--\r\n').encode()
 url='https://api.cloudflare.com/client/v4/accounts/'+os.environ['CLOUDFLARE_ACCOUNT_ID']+'/ai/run/'+IMAGE_MODEL
 raw,ct=budget.post('images',url,body,{'Authorization':'Bearer '+os.environ['CLOUDFLARE_API_TOKEN'],'Content-Type':'multipart/form-data; boundary='+boundary},20*1024*1024)
 try:
  if 'json' in ct:
   obj=json.loads(raw)
   if obj.get('success') is False:raise ValueError()
   result=obj.get('result') or obj;encoded=result.get('image') or result.get('output')
   if encoded.startswith('data:'):encoded=encoded.split(',',1)[1]
   raw=base64.b64decode(encoded,validate=True)
  with Image.open(io.BytesIO(raw)) as im:
   im.load()
   if im.size!=(720,1280) or im.format not in {'PNG','JPEG'}:raise ValueError()
   pixels=hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()
 except Exception:raise Stop('Malformed image response; no replacement or retry') from None
 target.write_bytes(raw)
 return {'scene':index,'file':target.name,'sha256':sha(target),'pixel_sha256':pixels,'provider':'cloudflare','model':IMAGE_MODEL,'attempts':1,'approved_for_illustrative_draft':False,'reviewer':'pending'}

def review_images(plan,rows,budget):
 prompt=review_prompt(plan['scene_prompts'])
 parts=[{'text':prompt}]
 for row in rows:
  with Image.open(WORK/'assets'/row['file']) as im:
   im=im.convert('RGB');im.thumbnail((270,480));buf=io.BytesIO();im.save(buf,format='JPEG',quality=80)
  parts.append({'text':'Scene '+str(row['scene'])});parts.append({'inlineData':{'mimeType':'image/jpeg','data':base64.b64encode(buf.getvalue()).decode()}})
 body=json.dumps({'contents':[{'parts':parts}],'generationConfig':{'temperature':0,'responseMimeType':'application/json'}}).encode()
 raw,_=budget.post('review','https://generativelanguage.googleapis.com/v1beta/models/'+REVIEW_MODEL+':generateContent',body,{'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']},1024*1024)
 try:
  obj=json.loads(raw);text=''.join(p.get('text','') for p in obj['candidates'][0]['content']['parts'] if not p.get('thought'));review=validate_review(json.loads(text));checks=review['scenes']
 except Stop:raise
 except Exception:raise Stop('visual_review_schema_invalid; no silent approval') from None
 save(OUT/'automated_visual_review.json',review)
 for row,check in zip(rows,checks):row.update(approved_for_illustrative_draft=check['pass'],reviewer='automated_'+REVIEW_MODEL,review_note=check['note'],checks=check['checks'],human_approved=False,publication_approved=False)
 save(WORK/'asset_review.json',rows);save(OUT/'asset_review.json',rows)
 if not all(x['pass'] for x in checks):raise Stop('One or more images failed automated review; no regeneration')

def main():
 if os.environ.get('GITHUB_REPOSITORY')!='benngokhan/yt_auto_uploader' or os.environ.get('GITHUB_REF')!='refs/heads/'+BRANCH or os.environ.get('GITHUB_RUN_ATTEMPT')!='1':raise Stop('Wrong repository/ref/attempt')
 claim=json.loads((HERE/'claimed.json').read_text())
 if claim.get('authorization')!=AUTH or str(claim.get('run_id'))!=os.environ.get('GITHUB_RUN_ID'):raise Stop('Permanent run-bound authorization missing')
 plan=json.loads((HERE/'plan.json').read_text())
 if plan.get('authorization_id')!=AUTH or plan.get('voice_id')!='Charon' or len(plan.get('scene_prompts',[]))!=8:raise Stop('Wrong plan or voice')
 require_keys();OUT.mkdir(exist_ok=False);WORK.mkdir(exist_ok=False);(WORK/'assets').mkdir();budget=Budget(OUT/'consumed_calls',limits={'tts':0,'images':0,'review':0});state={'state':'started','authorization':AUTH,'max_tts':0,'max_images':0,'max_visual_reviews':0,'automatic_retry':False,'published':False,'queue_written':False}
 try:
  save(WORK/'plan.json',plan);proof=generate_voice(plan,budget,WORK/'assets/narration.wav');save(OUT/'voice_provenance.json',proof)
  # Align immediately, before spending image budget on an unusable narration.
  env=os.environ.copy();env['BOSTON099_BUNDLE']=str(WORK)
  subprocess.run([sys.executable,str(HERE/'align_audio.py')],check=True,env=env)
  alignment=json.loads((WORK/'alignment.json').read_text())
  if alignment.get('audio_content_state')!='audio_verified' or alignment['asr_similarity']<.95:raise Stop('Narration needs review; no regeneration')
  plan['timeline_edges']=[0]+[alignment['groups'][i][0]['start'] for i in plan['scene_group_indices'][1:]]+[53]
  save(WORK/'plan.json',plan)
  rows=[]
  for i,prompt in enumerate(plan['scene_prompts'],1):
   print('Generating distinct image',i,'of8',flush=True);rows.append(generate_image(prompt,i,budget,WORK/'assets'/f'scene{i:02}.png'));save(OUT/'asset_review.json',rows)
  if len({x['sha256'] for x in rows})!=8 or len({x['pixel_sha256'] for x in rows})!=8:raise Stop('Duplicate image pixels/files; no regeneration')
  review_images(plan,rows,budget)
  subprocess.run([sys.executable,str(ROOT/'motor/uret.py'),'--boston-bundle',str(WORK),'--boston-output',str(OUT/'final'),'--boston-mode','render'],check=True)
  state.update(state='completed_awaiting_user_review',calls=budget.count,video='final/video.mp4',cover='final/kapak.jpg',natural_voice_seconds=proof['natural_seconds'],human_approved=False)
 except Exception as exc:
  state.update(state=('provider_unavailable' if isinstance(exc,ProviderFailure) else 'visual_review_rejected' if isinstance(exc,Stop) and str(exc).startswith('One or more images') else 'stopped_without_retry'),error_type=type(exc).__name__,safe_reason=str(exc) if isinstance(exc,Stop) else 'Pipeline step failed; inspect nonsecret local outputs',calls=budget.count);save(OUT/'status.json',state)
  # Keep failed outputs for inspection; never report success or switch models.
  raise SystemExit('096 stopped; no retry or fallback. '+state['safe_reason']) from None
 save(OUT/'status.json',state);print('096 complete: own Charon audio,8ownCloudflareimages,1automatedreview,1render; no queue/publication.',flush=True)
if __name__=='__main__':main()
