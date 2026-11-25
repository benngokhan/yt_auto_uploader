"""Resume only unused visual work with approved096audio; zero TTS calls permitted."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'arena_096'))
import produce as providers
AUTH='FATIH_REMAINING_IMAGES_097_ONCE';BRANCH='arena/fatih-remaining-097'
VOICE_SHA='c24a2b380eb5bb16db767a01869664133831200f411574e64c2645fc05842392'
WORK=ROOT/'work_097';OUT=ROOT/'result_097'
def main():
 if os.environ.get('GITHUB_REPOSITORY')!='benngokhan/yt_auto_uploader' or os.environ.get('GITHUB_REF')!='refs/heads/'+BRANCH or os.environ.get('GITHUB_RUN_ATTEMPT')!='1':raise providers.Stop('Wrong context')
 claim=json.loads((HERE/'claimed.json').read_text())
 if claim.get('authorization')!=AUTH or str(claim.get('run_id'))!=os.environ.get('GITHUB_RUN_ID'):raise providers.Stop('Permanent run-bound097claim missing')
 voice=ROOT/'imported_096/work_096/assets/narration.wav';voice_proof=ROOT/'imported_096/work_096/voice_provenance.json'
 if providers.sha(voice)!=VOICE_SHA:raise providers.Stop('Approved voice hash mismatch; do not regenerate')
 proof=json.loads(voice_proof.read_text());alignment=json.loads((HERE/'alignment.json').read_text());asrproof=json.loads((HERE/'asr_validation.json').read_text())
 if proof.get('audio_sha256')!=VOICE_SHA or proof.get('voice')!='Charon' or alignment['audio_sha256']!=VOICE_SHA or asrproof['audio_sha256']!=VOICE_SHA or asrproof['combined_similarity']<.95:raise providers.Stop('Existing voice validation mismatch')
 providers.require_keys();OUT.mkdir(exist_ok=False);WORK.mkdir(exist_ok=False);(WORK/'assets').mkdir();shutil.copyfile(voice,WORK/'assets/narration.wav');shutil.copyfile(voice_proof,WORK/'voice_provenance.json');shutil.copyfile(HERE/'alignment.json',WORK/'alignment.json');shutil.copyfile(HERE/'asr_validation.json',WORK/'asr_validation.json')
 providers.WORK=WORK;providers.OUT=OUT
 budget=providers.Budget(OUT/'consumed_calls');budget.limits={'tts':0,'images':8,'review':1}
 state={'state':'started','authorization':AUTH,'reused_voice_sha256':VOICE_SHA,'source_run':45526381049,'new_tts_max':0,'images_max':8,'review_max':1,'automatic_retry':False,'published':False,'queue_written':False}
 try:
  plan=json.loads((ROOT/'arena_096/plan.json').read_text());plan['authorization_id']=AUTH;plan['budget']={'full_narrations_max':0,'new_images_max':8,'visual_review_max':1,'automatic_generation_retries':False,'publication':False};plan['timeline_edges']=[0]+[alignment['groups'][i][0]['start'] for i in plan['scene_group_indices'][1:]]+[53];providers.save(WORK/'plan.json',plan)
  rows=[]
  for i,prompt in enumerate(plan['scene_prompts'],1):
   print('Generating remaining image',i,'of8; no TTS call',flush=True);rows.append(providers.generate_image(prompt,i,budget,WORK/'assets'/f'scene{i:02}.png'));providers.save(OUT/'asset_review.json',rows)
  if len({x['sha256'] for x in rows})!=8 or len({x['pixel_sha256'] for x in rows})!=8:raise providers.Stop('Duplicate images; no regeneration')
  providers.review_images(plan,rows,budget)
  subprocess.run([sys.executable,str(ROOT/'motor/uret.py'),'--boston-bundle',str(WORK),'--boston-output',str(OUT/'final'),'--boston-mode','render'],check=True)
  state.update(state='completed_awaiting_user_review',calls=budget.count,video='final/video.mp4',cover='final/kapak.jpg',natural_voice_seconds=proof['natural_seconds'],human_approved=False)
 except Exception as exc:
  state.update(state='stopped_without_retry',error_type=type(exc).__name__,safe_reason=str(exc) if isinstance(exc,providers.Stop) else 'Pipeline step failed; inspect nonsecret outputs',calls=budget.count);providers.save(OUT/'status.json',state)
  raise SystemExit('097 stopped; no retry or voice regeneration. '+state['safe_reason']) from None
 providers.save(OUT/'status.json',state);print('097 complete: SAME approved Charon voice,8newimages,onevisualreview,onefinalencode. No queue/publication.',flush=True)
if __name__=='__main__':main()
