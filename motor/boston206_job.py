"""Opt-in motor handoff for the approved template, with no provider/queue imports."""
from pathlib import Path
import json,shutil,hashlib
try:
 from . import boston206 as engine
 from .boston206_cover import render_cover
except ImportError:
 import boston206 as engine
 from boston206_cover import render_cover

def run_bundle(bundle,output,mode='check'):
 if mode not in {'check','stills','render'}:raise ValueError('Invalid Boston mode')
 source=Path(bundle).resolve();dest=Path(output).resolve()
 if not source.is_dir() or dest.exists() or source==dest or source in dest.parents:raise ValueError('Use a new output directory outside the immutable input bundle')
 engine.verify_template_lock()
 plan=json.loads((source/'plan.json').read_text(encoding='utf-8'))
 engine.validate_edges(plan.get('timeline_edges'))
 if plan.get('template_version')!=engine.TEMPLATE_VERSION:raise ValueError('Explicit Boston206 template version required')
 if plan.get('voice_speed_factor')!=1 or plan.get('voice_id') not in {'voice-00','Charon'}:raise ValueError('Approved voice identity and 1x speed required; no provider fallback')
 lines=plan.get('script_lines',[])
 if not lines or lines[-1]!='Merakını besle, Bilgi Dozu’nu takip et!' or sum('Merakını besle' in x for x in lines)!=1:raise ValueError('Exact end-only CTA required')
 if not plan.get('source',{}).get('reviewed') or not str(plan['source'].get('url','')).startswith('https://'):raise ValueError('Reviewed source required')
 title=plan.get('design',{}).get('cover_title')
 try:from .boston206_cover import layout_title
 except ImportError:from boston206_cover import layout_title
 layout_title(title)
 reviews=json.loads((source/'asset_review.json').read_text(encoding='utf-8'))
 if len(reviews)!=8:raise ValueError('Eight reviewed images required')
 files=['plan.json','alignment.json','asset_review.json','assets/narration.wav']
 if plan.get('voice_id')=='Charon':files.append('voice_provenance.json')
 for row in reviews:
  p=engine.safe_asset(source/'assets',row['file']);files.append('assets/'+p.name)
 for name in files:
  p=source/name
  if p.is_symlink() or not p.is_file() or p.stat().st_size>100_000_000:raise ValueError('Unsafe/missing/oversize asset')
 dest.mkdir(parents=True,exist_ok=False)
 for name in files:
  out=dest/name;out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,out)
 story=engine.Story(dest)
 cover=render_cover(dest/'assets'/reviews[0]['file'],dest/'kapak.jpg',title,
  category=plan.get('design',{}).get('cover_category',''),subtitle=plan.get('design',{}).get('cover_subtitle',''),
  disclosure=plan.get('cover_disclosure','Yapay zekâ ile temsili canlandırma'))
 if mode=='stills':engine.stills(story)
 if mode=='render':engine.render(story)
 report={'template_version':engine.TEMPLATE_VERSION,'mode':mode,'provider_calls':0,'new_narrations':0,'new_images':0,'publication':False,'queue_written':False,'voice_identity_status':'provider response recorded as Charon' if plan['voice_id']=='Charon' else 'caller-attested audio import; not proof of reusable provider voice','voice_speed_factor':1,'cover':cover.name,'video_encoded':mode=='render','input_bundle_unchanged':True,'duration_seconds':53,'canvas':[1080,1920],'fps':30}
 engine.save(dest/'boston206_report.json',report)
 return report
