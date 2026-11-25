"""One bounded quality completion: reuse voice+assets, review, at most2replacements.
No TTS, silent reviewer substitution, reroll, publication or queue operation.
"""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,wave
from PIL import Image
import providers as p
from provider_io import Stop,ProviderFailure,Budget
ROOT=Path(__file__).resolve().parents[1];HERE=Path(__file__).resolve().parent
WORK=ROOT/'work_100';OUT=ROOT/'result_100';BRANCH='arena/fatih-quality-100';AUTH='FATIH_QUALITY_FINISH_100_ONCE'
VOICE_SHA='c24a2b380eb5bb16db767a01869664133831200f411574e64c2645fc05842392'
def context():
 if os.environ.get('GITHUB_REPOSITORY')!='benngokhan/yt_auto_uploader' or os.environ.get('GITHUB_REF')!='refs/heads/'+BRANCH or os.environ.get('GITHUB_RUN_ATTEMPT')!='1':raise Stop('Wrong context')
 claim=json.loads((HERE/'claimed.json').read_text())
 if claim.get('authorization')!=AUTH or str(claim.get('run_id'))!=os.environ.get('GITHUB_RUN_ID'):raise Stop('Missing permanent run-bound claim')
def prepare():
 source=ROOT/'imported_097/work_097';voice=source/'assets/narration.wav'
 if p.sha(voice)!=VOICE_SHA:raise Stop('Approved voice hash mismatch')
 alignment=json.loads((HERE/'alignment.json').read_text());proof=json.loads((HERE/'audio_content_review.json').read_text())
 if alignment['audio_sha256']!=VOICE_SHA or proof['audio_sha256']!=VOICE_SHA or proof['state']!='audio_verified' or alignment.get('audio_content_state')!='audio_verified' or alignment['asr_similarity']<.95 or not proof['numeric_entities_match']:raise Stop('Independent audio proof mismatch')
 WORK.mkdir(exist_ok=False);(WORK/'assets').mkdir();shutil.copyfile(voice,WORK/'assets/narration.wav');shutil.copyfile(source/'voice_provenance.json',WORK/'voice_provenance.json');shutil.copyfile(HERE/'alignment.json',WORK/'alignment.json');shutil.copyfile(HERE/'audio_content_review.json',WORK/'audio_content_review.json')
 rows=[]
 for i,expected in enumerate(json.loads((HERE/'source_assets.json').read_text()),1):
  name=f'scene{i:02}.png';f=source/'assets'/name
  if expected['name']!=name or p.sha(f)!=expected['sha256']:raise Stop('Original image hash mismatch')
  with Image.open(f) as im:
   if list(im.size)!=expected['size'] or hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()!=expected['pixel_sha256']:raise Stop('Original image pixel mismatch')
  shutil.copyfile(f,WORK/'assets'/name);rows.append({'scene':i,'file':name,'sha256':expected['sha256'],'pixel_sha256':expected['pixel_sha256'],'provider':'cloudflare','model':p.IMAGE_MODEL,'attempts':1,'source_run':45528376909,'approved_for_illustrative_draft':False,'reviewer':'pending'})
 if len(rows)!=8 or len({r['pixel_sha256'] for r in rows})!=8:raise Stop('Eight distinct source images required')
 plan=json.loads((HERE/'original_plan.json').read_text());plan.update(authorization_id=AUTH,budget={'new_images_max':2,'full_narrations_max':0,'visual_review_max':2,'automatic_generation_retries':False,'publication':False},timeline_edges=[0]+[alignment['groups'][i][0]['start'] for i in plan['scene_group_indices'][1:]]+[53]);p.save(WORK/'plan.json',plan)
 return plan,rows

def quality_review(plan,rows,budget,stage):
 folder=OUT/stage;folder.mkdir(exist_ok=False);p.OUT=folder
 try:p.review_images(plan,rows,budget)
 except Stop as exc:
  evidence=folder/'automated_visual_review.json'
  if not evidence.exists() or str(exc)!='One or more images failed automated review; no regeneration':raise
  review=json.loads(evidence.read_text())
  if review.get('state')!='visual_review_rejected':raise
  return {s['scene'] for s in review['scenes'] if not s['pass']}
 return set()

def run_steps(plan,rows,budget):
 bad=quality_review(plan,rows,budget,'review_existing')
 if bad-set((6,7)):raise Stop('Visual rejection outside permitted replacement scenes6/7; no wider generation')
 if bad:p.require_keys()
 replacement_plan=json.loads((HERE/'new_plan.json').read_text());changed=[]
 for scene in sorted(bad):
  # Archive original; no image overwritten until a single bounded response exists.
  old=rows[scene-1];archive=OUT/'original_replaced';archive.mkdir(exist_ok=True);shutil.copyfile(WORK/'assets'/old['file'],archive/old['file'])
  row=p.generate_image(replacement_plan['scene_prompts'][scene-1],scene,budget,WORK/'assets'/old['file']);row['replacement_for_sha256']=old['sha256'];rows[scene-1]=row;plan['scene_prompts'][scene-1]=replacement_plan['scene_prompts'][scene-1];changed.append(scene);p.save(OUT/'current_assets.json',rows)
 if changed:
  if len({r['pixel_sha256'] for r in rows})!=8:raise Stop('Duplicate replacement; no reroll')
  if quality_review(plan,rows,budget,'review_after_replacements'):raise Stop('Replacement visual review rejected; no reroll')
 if not all(r.get('approved_for_illustrative_draft') for r in rows):raise Stop('Visual approval missing')
 p.save(WORK/'plan.json',plan);p.save(WORK/'asset_review.json',rows)
 subprocess.run([sys.executable,str(ROOT/'motor/uret.py'),'--boston-bundle',str(WORK),'--boston-output',str(OUT/'final'),'--boston-mode','render'],check=True)
 return changed

def main():
 context();OUT.mkdir(exist_ok=False);budget=Budget(OUT/'consumed_calls',limits={'tts':0,'images':2,'review':2});state={'state':'started','authorization':AUTH,'voice_reused_sha256':VOICE_SHA,'limits':budget.limits,'automatic_retry':False,'human_approved':False,'published':False,'queue_written':False}
 try:
  # Only Gemini needed if originals pass; image credentials checked only before replacement POST.
  if not os.environ.get('GEMINI_API_KEY','').strip():raise Stop('Required review secret missing')
  plan,rows=prepare();p.WORK=WORK
  changed=run_steps(plan,rows,budget)
  state.update(state='completed_awaiting_user_review',replaced_scenes=changed,video='final/video.mp4',cover='final/kapak.jpg')
 except Exception as exc:
  state.update(state='provider_unavailable' if isinstance(exc,ProviderFailure) else 'stopped_without_retry',error_type=type(exc).__name__,safe_reason=str(exc) if isinstance(exc,Stop) else 'Local pipeline step failed; inspect safe artifacts')
  state['calls']=budget.count;p.save(OUT/'status.json',state);raise SystemExit('100 stopped without retry: '+state['safe_reason']) from None
 state['calls']=budget.count;p.save(OUT/'status.json',state);print('100 complete; same voice, bounded review/replacements, one render. No publication.',flush=True)
if __name__=='__main__':main()
