"""Check existing keys against a harmless public candidate. Print no secrets or response bodies."""
import base64,json,os,urllib.request,urllib.error

def request(url,key=None,data=None):
 headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/json'}
 if key:headers['Authorization']='Bearer '+key
 r=urllib.request.Request(url,data=json.dumps(data).encode() if data else None,headers=headers)
 with urllib.request.urlopen(r,timeout=35) as f:return json.load(f)

def check(name, env, base, choices):
 key=os.getenv(env,'').strip()
 if not key:print(name,'ERISIM_YOK',flush=True);return
 try:
  data=request(base+'/models',key)
  models=data.get('data',[])
  print(name,'LISTE_OK',len(models),flush=True)
  if name=='GROQ':
   for m in models:print('GROQ_MEVCUT_MODEL',str(m.get('id',''))[:100],flush=True)
 except urllib.error.HTTPError as e:print(name,'LISTE_HTTP',e.code,flush=True);return
 except Exception as e:print(name,'LISTE_HATA',type(e).__name__,flush=True);return
 active={str(m.get('id')) for m in models if m.get('active',True)}
 selected=[x for x in choices if x in active]
 for m in models:
  arch=m.get('architecture') or {}; pricing=m.get('pricing') or {}
  if name=='OPENROUTER' and 'image' in (arch.get('input_modalities') or []) and str(pricing.get('prompt')) in ('0','0.0') and str(pricing.get('completion')) in ('0','0.0'):
   id=str(m.get('id',''))
   if id.endswith(':free') and id not in selected:selected.append(id)
 selected=selected[:3]
 if not selected:print(name,'GORSEL_MODELI_LISTEDE_YOK',flush=True);return
 try:
  req=urllib.request.Request('https://images.pexels.com/photos/39851086/pexels-photo-39851086.jpeg?auto=compress&cs=tinysrgb&w=300',headers={'User-Agent':'Mozilla/5.0'})
  img=base64.b64encode(urllib.request.urlopen(req,timeout=25).read()).decode()
 except Exception as e:print(name,'GORSEL_INDIRME_HATASI',type(e).__name__,flush=True);return
 for model in selected:
  body={'model':model,'messages':[{'role':'user','content':[{'type':'text','text':'Does this image show a candle? Answer yes or no.'},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+img}}]}], 'max_tokens':20,'temperature':0}
  try:
   answer=request(base+'/chat/completions',key,body)
   msg=answer.get('choices',[{}])[0].get('message',{}).get('content','')
   print(name,'MODEL',model,'YANIT_OK' if isinstance(msg,str) and msg.strip() else 'YANIT_BOS',flush=True)
   if isinstance(msg,str) and msg.strip(): break
  except urllib.error.HTTPError as e: print(name,'MODEL',model,'HTTP',e.code,flush=True)
  except Exception as e: print(name,'MODEL',model,'HATA',type(e).__name__,flush=True)
check('GROQ','GROQ_API_KEY','https://api.groq.com/openai/v1',['meta-llama/llama-4-scout-17b-16e-instruct','meta-llama/llama-4-maverick-17b-128e-instruct'])
check('OPENROUTER','OPENROUTER_API_KEY','https://openrouter.ai/api/v1',['google/gemma-3-27b-it:free','qwen/qwen2.5-vl-72b-instruct:free'])
