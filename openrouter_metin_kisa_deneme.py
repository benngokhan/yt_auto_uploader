"""Tek izole, ücretsiz model metin testi; yayın ve render yapmaz."""
import json,os,time,urllib.request,urllib.error
key=os.getenv('OPENROUTER_API_KEY','').strip()
prompt=('Mum üflendiğinde neden söner? Türkçe beş cümle yaz. '
        'İlk ve son cümle mum kelimesini içeren soru olsun. '
        'Hava akımı sıcak gazları soğutur ve balmumu buharını dağıtır. Oksijen kesilmez. '
        'Her cümle 7 ila 9 kelime; toplam 35 ila 45 kelime. '
        'Sadece JSON: {"cumleler":["...","...","...","...","..."]}.')
body={'model':'particle-ai/particle-1:free','max_tokens':1100,'temperature':0.2,'reasoning':{'enabled':False},
      'messages':[{'role':'user','content':prompt}]}
for attempt in range(3):
 try:
  r=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
  with urllib.request.urlopen(r,timeout=90) as f:data=json.load(f)
  choice=data['choices'][0];text=(choice['message'].get('content') or '').strip().removeprefix('```json').removesuffix('```').strip();lines=json.loads(text).get('cumleler') or []
  print('BITIS',choice.get('finish_reason'),'CUMLE_SAYISI',len(lines),flush=True)
  for i,line in enumerate(lines,1):print('CUMLE',i,'KELIME',len(str(line).split()),str(line)[:200],flush=True)
  break
 except urllib.error.HTTPError as e:
  print('HTTP',e.code,flush=True)
  if e.code!=429 or attempt==2:break
  time.sleep((6,12)[attempt])
 except Exception as e:print('HATA',type(e).__name__,flush=True);break
