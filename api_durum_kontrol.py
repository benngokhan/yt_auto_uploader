#!/usr/bin/env python3
import os,json,urllib.request,urllib.error,datetime

def call(name,req):
 out={'durum':'hata','http':0,'limit':{},'mesaj':''}
 try:
  with urllib.request.urlopen(req,timeout=60) as r:
   r.read();out['durum']='aktif';out['http']=r.status;h={k.lower():v for k,v in r.headers.items()}
 except urllib.error.HTTPError as e:
  out['http']=e.code;h={k.lower():v for k,v in e.headers.items()};raw=e.read().decode(errors='replace')
  try:
   j=json.loads(raw);out['mesaj']=j.get('error',{}).get('message',raw)[:240]
  except:out['mesaj']=raw[:240]
  out['durum']='kota' if e.code==429 else 'hata'
 except Exception as e:
  h={};out['mesaj']=str(e)[:240]
 for k,v in h.items():
  if k.startswith('x-ratelimit-'):out['limit'][k.replace('x-ratelimit-','')]=v
 return out

def main():
 gk=os.getenv('GEMINI_API_KEY','');qk=os.getenv('GROQ_API_KEY','')
 gem=call('Gemini',urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models?key='+gk)) if gk else {'durum':'anahtar_yok','http':0,'limit':{},'mesaj':''}
 body={'model':'llama-3.3-70b-versatile','messages':[{'role':'user','content':'Sadece OK yaz.'}],'max_tokens':1}
 groq=call('Groq',urllib.request.Request('https://api.groq.com/openai/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+qk})) if qk else {'durum':'anahtar_yok','http':0,'limit':{},'mesaj':''}
 open('api_durum.json','w').write(json.dumps({'guncellendi':datetime.datetime.now(datetime.timezone.utc).isoformat(),'not':'Sağlayıcı yalnız sunduğu limit başlıklarını gösterir; Gemini kalan günlük kotayı API anahtarıyla açıklamaz.','gemini':gem,'groq':groq},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
