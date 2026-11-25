"""Strict visual-review schema. Provider error != visual rejection != approval.
This is still automated image review, never human/publication approval.
"""
import json
from provider_io import Stop
CHECKS=('period_consistent','character_consistent','anatomy_ok','scene_matches','no_fake_text','not_duplicate')

def review_prompt(prompts):
 return '''Review eight AI illustrations for a1479–1480MehmedII/GentileBellini documentary. They are NOT authentic portraits, archives or exact likenesses. Check EACH frame against the scene and compare all eight for continuity/duplicates. Reject modern-looking spectacles or modern eyeglass arms, fez, coffeehouse/modern cup staging, modern transport, implausible post1480Istanbul mosque skylines (e.g. four/six-minaret imperial complexes), modern paint tubes and inconsistent named character faces/age/clothing. Do not equate picturesque Ottoman-looking scenery with period accuracy. Portrait reinterpretations must not be called originalBelliniart. For uncertainty material to the central scene set the relevant check FALSE and explain uncertainty. Do not approve from prompt alone. Output ONLY JSON with exactly key scenes and8objects in order. Each object has EXACT keys scene(integer1–8), pass(boolean), note(nonemptytext), checks(object of boolean period_consistent,character_consistent,anatomy_ok,scene_matches,no_fake_text,not_duplicate). pass must equal all six checks. This is automated illustrative review ONLY, never human or publication approval. Scene requests:\n'''+json.dumps(prompts,ensure_ascii=False)

def validate_review(obj):
 if not isinstance(obj,dict) or set(obj)!={'scenes'} or type(obj['scenes'])is not list or len(obj['scenes'])!=8:raise Stop('visual_review_schema_invalid')
 for i,item in enumerate(obj['scenes'],1):
  if not isinstance(item,dict) or set(item)!={'scene','pass','note','checks'} or type(item['scene'])is not int or item['scene']!=i or type(item['pass'])is not bool:raise Stop('visual_review_schema_invalid')
  if not isinstance(item['note'],str) or not item['note'].strip() or len(item['note'])>1500:raise Stop('visual_review_schema_invalid')
  checks=item['checks']
  if not isinstance(checks,dict) or set(checks)!=set(CHECKS) or any(type(v)is not bool for v in checks.values()):raise Stop('visual_review_schema_invalid')
  if item['pass']!=all(checks.values()):raise Stop('visual_review_inconsistent_verdict')
 return {'state':'visual_review_passed' if all(s['pass'] for s in obj['scenes']) else 'visual_review_rejected','scenes':obj['scenes'],'human_approved':False,'publication_approved':False,'automatic_regeneration':False}
