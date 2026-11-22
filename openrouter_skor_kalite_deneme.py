"""Izole OpenRouter görsel kalite testi; yayın veya Drive işlemi yapmaz."""
import base64, json, os, time, urllib.request, urllib.error
from io import BytesIO
from PIL import Image

key = os.getenv('OPENROUTER_API_KEY', '').strip()
if not key: raise SystemExit('OPENROUTER_ANAHTARI_YOK')
images = [
 ('mum', 'https://images.pexels.com/photos/39851086/pexels-photo-39851086.jpeg'),
 ('balon', 'https://images.pexels.com/photos/12267732/pexels-photo-12267732.jpeg'),
 ('termometre', 'https://images.pexels.com/photos/5998444/pexels-photo-5998444.jpeg'),
 ('kibrit', 'https://images.pexels.com/photos/39244/match-fire-close-burn-39244.jpeg')]
parts=[{'type':'text','text':('Sahne metni: Mum üflendiğinde alev neden bir anda kararır?\nHer numaralı fotoğrafı, sahne metninde anlatılan somut nesne/eylem/mekanizmayı gerçekten gösterip göstermediğine göre puanla. Renk, sinematik görünüm veya yalnızca genel bilim havası alaka değildir. 0 = ilgisiz/yanıltıcı, 0.5 = kısmi veya yalnızca dolaylı, 1 = sahneyi doğrudan ve açıkça gösteriyor. Sadece geçerli JSON döndür: {"scores":[0.0, ...]}; sıra görsellerin numarasıyla aynı ve her puan 0 ile 1 arasında olsun.')}]
for i,(_,url) in enumerate(images,1):
 try:
  req=urllib.request.Request(url+'?auto=compress&cs=tinysrgb&w=500',headers={'User-Agent':'Mozilla/5.0'})
  with urllib.request.urlopen(req,timeout=25) as r: data=r.read(3000000)
  with Image.open(BytesIO(data)) as im:
   im=im.convert('RGB');im.thumbnail((384,384));out=BytesIO();im.save(out,format='JPEG',quality=78)
  parts.append({'type':'text','text':f'Image {i}:'})
  parts.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode('ascii')}})
 except Exception as e:
  print('GORSEL_INDIRME_HATASI',i,type(e).__name__,flush=True);raise SystemExit(1)
models=['particle-ai/particle-1:free','nvidia/nemotron-3.5-super-vl:free','inclusionai/ling-3.2-flash:free']
for model in models:
 body={'model':model,'messages':[{'role':'user','content':parts}],'max_tokens':500,'temperature':0}
 for attempt in range(2):
  req=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
  try:
   with urllib.request.urlopen(req,timeout=90) as r:result=json.load(r)
   text=(result['choices'][0]['message'].get('content') or '').strip().removeprefix('```json').removesuffix('```').strip()
   try:
    rows=json.loads(text)['scores']
    if not isinstance(rows,list) or len(rows)!=4: raise ValueError('bad rows')
    for i,row in enumerate(rows,1):
     val=float(row)
     if not 0 <= val <= 1: raise ValueError('invalid score')
     print('PUAN',model,i,val,flush=True)
    raise SystemExit(0)
   except (ValueError,TypeError,KeyError): print('YANIT_JSON_GECERSIZ',model,'BITIS',result['choices'][0].get('finish_reason'),'METIN',repr(text[:800]),flush=True);break
  except urllib.error.HTTPError as e:
   print('OPENROUTER_HTTP',model,e.code,'RETRY_AFTER',e.headers.get('Retry-After','yok'),flush=True)
   try:
    er=json.load(e).get('error') or {};m=er.get('metadata') or {};msg=str(er.get('message','')).lower()
    categories=[x for x in ['rate limit','capacity','upstream','free','quota','daily','minute','no endpoints'] if x in msg]
    print('HATA_KODU',str(m.get('provider_code',''))[:50],'TIP',str(m.get('error_type',''))[:50],'KATEGORI',','.join(categories),flush=True)
   except Exception: pass
   if e.code != 429: break
   time.sleep(6*(attempt+1))
  except Exception as e: print('OPENROUTER_HATA',model,type(e).__name__,flush=True);break
print('KALITE_TESTI_TAMAMLANAMADI',flush=True)
