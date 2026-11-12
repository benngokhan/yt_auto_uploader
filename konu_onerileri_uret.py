#!/usr/bin/env python3
import os,json,re,base64,urllib.request,tempfile
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from openpyxl import load_workbook

try:  # Gemini/Groq çağrılarını say (kota API'de yok)
    import kota_sayac  # noqa: F401
except Exception:
    pass
BOOK=os.getenv('WORKBOOK_ID','1aBt7me8IOzsJeSMQDVtkTktOgF9EZpJo')       # active.sav81@gmail.com / baslik.xlsx
APPROVAL=os.getenv('APPROVAL_FOLDER','1xyO_jNjbpghfR7CJ1P9DUvkzdb6eC0qf')  # active.sav81@gmail.com / Onay_Bekleyen

def norm(s):
 s=str(s or '').lower();s=re.sub(r'#\S+',' ',s);s=re.sub(r'[^a-zçğıöşü0-9 ]',' ',s);return ' '.join(s.split())
def sim(a,b):
 A=set(norm(a).split());B=set(norm(b).split());return len(A&B)/max(1,len(A|B))
def drive():
 Path('token.json').write_text(os.environ['GOOGLE_TOKEN_JSON']);c=Credentials.from_authorized_user_file('token.json')
 if not c.valid:c.refresh(Request())
 return build('drive','v3',credentials=c,cache_discovery=False)
def download(d,id,path):
 req=d.files().get_media(fileId=id)
 with open(path,'wb') as f:
  dl=MediaIoBaseDownload(f,req);done=False
  while not done:_,done=dl.next_chunk()
def main():
 d=drive();tmp='konular.xlsx';download(d,BOOK,tmp);ws=load_workbook(tmp,data_only=True)['DRIVE']
 used=[]
 for r in range(2,ws.max_row+1):
  title=ws.cell(r,3).value
  if title:used.append(str(title))
 files=d.files().list(q=f"'{APPROVAL}' in parents and trashed=false",fields='files(id,name,mimeType)',pageSize=1000).execute().get('files',[])
 for f in files:
  if f['name'].startswith('YAYIN_BILGISI_'):
   try:
    raw=d.files().get_media(fileId=f['id']).execute();j=json.loads(raw.decode());used += [j.get('baslik',''),j.get('konu_ozeti','')]
   except Exception:pass
 used=[x for x in used if norm(x)]
 prompt=("Bilgi Dozu Türkçe YouTube Shorts kanalı için 12 yeni konu öner. Geçmiş başlıklarla aynı bilgi, olay, deney, hayvan özelliği veya yalnızca farklı kelimelerle tekrar kesinlikle yasak. "
         "Somut, doğrulanabilir, güçlü görseli olan ve ilk saniyede merak uyandıran soru biçimi kullan. Sağlık tavsiyesi ve yanıltıcı iddia kullanma. "
         "Yalnız JSON döndür: {\"suggestions\":[{\"title\":\"...\",\"score\":0-100,\"reason\":\"...\",\"duplicate_check\":\"hangi geçmiş alanlardan farklı\"}]}.\nGEÇMİŞ:\n"+'\n'.join(used[-500:]))
 body={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'responseMimeType':'application/json','temperature':0.85}}
 text=None; errors=[]
 groq=os.getenv('GROQ_API_KEY','').strip()
 if groq:
  try:
   gb={'model':'llama-3.3-70b-versatile','temperature':0.8,'response_format':{'type':'json_object'},'messages':[{'role':'user','content':prompt}]}
   req=urllib.request.Request('https://api.groq.com/openai/v1/chat/completions',data=json.dumps(gb).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+groq,'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36'})
   with urllib.request.urlopen(req,timeout=180) as r:text=json.load(r)['choices'][0]['message']['content']
   print('provider groq')
  except Exception as e: errors.append('groq:'+repr(e))
 if text is None:
  try:
   key=os.environ['GEMINI_API_KEY']
   with urllib.request.urlopen('https://generativelanguage.googleapis.com/v1beta/models?key='+key,timeout=60) as r: models=json.load(r).get('models',[])
   suitable=[m['name'].split('/',1)[-1] for m in models if 'generateContent' in m.get('supportedGenerationMethods',[]) and 'flash' in m.get('name','').lower() and all(x not in m.get('name','').lower() for x in ('tts','image','live','omni'))]
   if not suitable: raise RuntimeError('uygun Gemini modeli yok')
   model=sorted(suitable,key=lambda x:(('preview' not in x),x),reverse=True)[0];print('provider gemini',model)
   url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}'
   req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
   with urllib.request.urlopen(req,timeout=180) as r:data=json.load(r)
   text=data['candidates'][0]['content']['parts'][0]['text']
  except Exception as e: errors.append('gemini:'+repr(e))
 if text is None: raise RuntimeError('Tüm konu sağlayıcıları başarısız: '+' | '.join(errors))
 out=json.loads(text);accepted=[]
 for x in sorted(out.get('suggestions',[]),key=lambda z:z.get('score',0),reverse=True):
  t=str(x.get('title','')).strip()
  if len(t)<15 or any(sim(t,u)>=0.42 for u in used+ [a['title'] for a in accepted]):continue
  accepted.append(x)
  if len(accepted)==5:break
 if len(accepted)<5:raise RuntimeError('Tekrarsız 5 öneri üretilemedi; dosya güncellenmedi')
 Path('konu_onerileri.json').write_text(json.dumps({'generated_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'used_count':len(used),'method':'Drive yükleme tablosu + onay bekleyen metadata + Gemini anlamsal tekrar kontrolü + yerel benzerlik kapısı','suggestions':accepted},ensure_ascii=False,indent=2))
 print('used',len(used),'accepted',len(accepted))
if __name__=='__main__':main()
