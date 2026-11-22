"""Tek izole metin kalite testi. Ücretli çağrı, render ve yayın yapmaz."""
import json, os, urllib.request, urllib.error
key=os.getenv('GROQ_API_KEY','').strip()
if not key: raise SystemExit('GROQ_ANAHTARI_YOK')
prompt=('Mum üflendiğinde neden söner? Türkçe beş ayrı cümle hazırla. '
        'Birinci ve beşinci cümle mum kelimesini içeren soru olsun. '
        'Açıklama: hava akımı sıcak gazları soğutup mum buharını dağıtır; üflemek oksijeni kesmez. '
        'Her cümle 7 ile 9 kelime arasında; toplam 35 ile 45 kelime. '
        'Yalnız JSON: {"cumleler":["...","...","...","...","..."]}.')
for model in ['openai/gpt-oss-120b']:
 body={'model':model,'max_tokens':2000,'temperature':0.3,'reasoning_effort':'low',
       'response_format':{'type':'json_object'},'messages':[{'role':'user','content':prompt}]}
 try:
  r=urllib.request.Request('https://api.groq.com/openai/v1/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
  with urllib.request.urlopen(r,timeout=75) as f:data=json.load(f)
  c=data['choices'][0];text=(c['message'].get('content') or '').strip();obj=json.loads(text)
  lines=obj.get('cumleler') or [];print('MODEL',model,'BITIS',c.get('finish_reason'),'CUMLE_SAYISI',len(lines),flush=True)
  if isinstance(lines,list):
   for i,line in enumerate(lines,1): print('CUMLE',i,'KELIME',len(str(line).split()),str(line)[:200],flush=True)
 except urllib.error.HTTPError as e:print('MODEL',model,'HTTP',e.code,flush=True)
 except Exception as e:print('MODEL',model,'HATA',type(e).__name__,flush=True)
