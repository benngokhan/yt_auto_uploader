"""One Groq vision calibration, no video or publishing; user confirmed Free tier."""
import json,os,urllib.request,urllib.error
key=(os.getenv('GROQ_API_KEY') or '').strip()
if not key:
 print('GROQ_ANAHTAR_YOK',flush=True);raise SystemExit(1)
urls=['https://images.pexels.com/photos/7500161/pexels-photo-7500161.jpeg?w=600']
prompt=('Video ana konusu: Mum üflendiğinde neden söner? Sahne: Üflemek mum alevinin çevresindeki sıcak gazları hızla soğutur. '
 'Fotoğrafları sırayla incele. Mumu üflemeyi açıkça gösteren 1.0, sahneyi doğrudan temsil eden sönmüş dumanlı mum 0.8, '
 'yalnız genel mum görüntüsü veya belirsiz 0.5, ters eylem veya ilgisiz 0.0. Çakmakla mum yakmak, mum üfleyerek söndürmek değildir. '
 'Sadece JSON: {"items":[{"index":1,"observed":"kısaca görülen eylem","score":0.0}, ...]}. Tam bir eleman.')
parts=[{'type':'text','text':prompt}]
for index,url in enumerate(urls,1):parts.extend([{'type':'text','text':f'Görsel {index}'},{'type':'image_url','image_url':{'url':url}}])
body={'model':'qwen/qwen3.8-27b','messages':[{'role':'user','content':parts}], 'response_format':{'type':'json_object'},
      'reasoning_effort':'none','temperature':0,'max_completion_tokens':400}
req=urllib.request.Request('https://api.groq.com/openai/v1/chat/completions',data=json.dumps(body).encode(),
                           headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'application/json','User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})
try:
 with urllib.request.urlopen(req,timeout=80) as response:
  data=json.load(response)
  for h in ('x-ratelimit-limit-requests','x-ratelimit-remaining-requests','x-ratelimit-limit-tokens','x-ratelimit-remaining-tokens','x-ratelimit-reset-requests'):
   if response.headers.get(h):print('GROQ_LIMIT',h,response.headers.get(h),flush=True)
 choice=data['choices'][0]; content=(choice.get('message',{}).get('content') or '').strip(); parsed=json.loads(content)
 rows=parsed.get('items');
 if not isinstance(rows,list) or len(rows)!=1:print('GROQ_YANIT','SAYI_UYUMSUZ',flush=True)
 else:
  for row in rows:
   if isinstance(row,dict):print('GROQ_ADAY',row.get('index'),'PUAN',row.get('score'),'GORUNEN',str(row.get('observed',''))[:220],flush=True)
  print('GROQ_BITIS',choice.get('finish_reason'),flush=True)
except urllib.error.HTTPError as exc:
 print('GROQ_HTTP',exc.code,flush=True)
 try:
  import re
  raw=exc.read(16000)
  print('GROQ_HATA_BOYUT',len(raw),'CONTENT_TYPE',str(exc.headers.get('Content-Type') or '')[:80],flush=True)
  print('GROQ_HATA_SERVER',str(exc.headers.get('Server') or '')[:60],flush=True)
  text=raw.decode('utf8','replace'); lower=text.lower()
  if re.fullmatch(r'error code: [0-9]{4}',lower.strip()):print('GROQ_CLOUDFLARE',lower.strip(),flush=True)
  words=['permission','model','organization','project','terms','billing','country','region','decommission','disabled','tier','preview','policy','cloudflare','access denied','forbidden','request blocked','rate limit','api key','unsupported']
  print('GROQ_HATA_IPUCLARI',','.join(x for x in words if x in lower) or 'yok',flush=True)
  try:
   obj=json.loads(text).get('error') or {}
   for field in ('type','code'):
    val=obj.get(field)
    if isinstance(val,str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}',val):print('GROQ_HATA_ALANI',field,val,flush=True)
  except (ValueError,AttributeError,TypeError):print('GROQ_HATA_BICIMI','json_degil',flush=True)
 except Exception as problem:print('GROQ_HATA_DETAYI',type(problem).__name__,flush=True)
 for h in ('retry-after','x-ratelimit-remaining-requests','x-ratelimit-reset-requests','x-ratelimit-remaining-tokens'):
  if exc.headers and exc.headers.get(h):print('GROQ_LIMIT',h,exc.headers.get(h),flush=True)
except Exception as exc: print('GROQ_HATA',type(exc).__name__,flush=True)
