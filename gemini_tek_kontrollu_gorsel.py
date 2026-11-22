"""One Gemini request with three known test photos; no generation, retry or publishing."""
import base64
import io
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from PIL import Image

MODEL='gemini-3.8-flash'
key=(os.environ.get('GEMINI_API_KEY') or '').strip()
if not key:
    print('GEMINI_SONUC ANAHTAR_YOK',flush=True)
    raise SystemExit(2)
urls=[
    'https://images.pexels.com/photos/7500161/pexels-photo-7500161.jpeg?w=600',
    'https://images.pexels.com/photos/39572227/pexels-photo-39572227.jpeg?w=600',
    'https://images.pexels.com/photos/10495878/pexels-photo-10495878.jpeg?w=600',
]
prompt=('Video konusu: Mum üflendiğinde neden söner? Sahne: Üflemek mum alevinin çevresindeki sıcak gazları hızla soğutur. '
 'Fotoğrafları sırayla incele. Mumu üflemeyi açıkça gösteren 1.0, sahneyi doğrudan temsil eden sönmüş dumanlı mum 0.8, '
 'yalnız genel mum görüntüsü veya belirsiz 0.5, ters eylem veya ilgisiz 0.0. Çakmakla mum yakmak, mum üfleyerek söndürmek değildir. '
 'Sadece JSON: {"items":[{"index":1,"observed":"kısaca görülen eylem","score":0.0}, ...]}. Tam üç eleman sırayla.')
parts=[{'text':prompt}]
for index,url in enumerate(urls,1):
    try:
        request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(request,timeout=25) as r:
            data=r.read(8_000_001)
        if len(data)>8_000_000: raise ValueError('image_too_large')
        with Image.open(io.BytesIO(data)) as im:
            im=im.convert('RGB'); im.thumbnail((384,384),Image.Resampling.LANCZOS)
            buf=io.BytesIO(); im.save(buf,format='JPEG',quality=78,optimize=True)
        parts.extend([{'text':f'Görsel {index}'},{'inline_data':{'mime_type':'image/jpeg','data':base64.b64encode(buf.getvalue()).decode('ascii')}}])
    except Exception as exc:
        print('GEMINI_GORSEL_HATA',index,type(exc).__name__,flush=True)
        raise SystemExit(2)
body={'contents':[{'parts':parts}],'generationConfig':{'responseMimeType':'application/json','temperature':0}}
req=urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent',
    data=json.dumps(body).encode('utf8'),headers={'Content-Type':'application/json','x-goog-api-key':key})
try:
    with urllib.request.urlopen(req,timeout=90) as response:
        data=json.load(response)
    candidate=data['candidates'][0]
    answer=''.join(part.get('text','') for part in candidate['content']['parts'] if isinstance(part,dict))
    parsed=json.loads(answer); rows=parsed.get('items')
    if not isinstance(rows,list) or len(rows)!=3: raise ValueError('wrong_item_count')
    for index,row in enumerate(rows,1):
        if not isinstance(row,dict) or row.get('index')!=index:raise ValueError('wrong_order')
        value=row.get('score')
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0<=value<=1:
            raise ValueError('invalid_score')
    print('GEMINI_HTTP 200 MODEL',MODEL,flush=True)
    for row in rows:
        observed=str(row.get('observed') or '').replace(key,'[redacted]')[:200]
        print('GEMINI_ADAY',row['index'],'PUAN',row['score'],'GORUNEN',observed,flush=True)
    print('GEMINI_BITIS',str(candidate.get('finishReason','unknown'))[:40],flush=True)
except urllib.error.HTTPError as exc:
    print('GEMINI_HTTP',exc.code,flush=True)
    if exc.headers and exc.headers.get('Retry-After'):
        hint=exc.headers.get('Retry-After')
        if re.fullmatch(r'[0-9.]{1,20}',hint):print('GEMINI_RETRY_AFTER_SECONDS',hint,flush=True)
    try:
        error=json.loads(exc.read(65536)).get('error') or {}
        status=error.get('status')
        if isinstance(status,str) and re.fullmatch(r'[A-Z_]{1,60}',status):print('GEMINI_DURUM',status,flush=True)
        for detail in error.get('details') or []:
            if 'QuotaFailure' in str(detail.get('@type','')):
                for violation in detail.get('violations') or []:
                    for field in ('quotaId','quotaMetric','quotaValue'):
                        val=str(violation.get(field) or '')
                        if re.fullmatch(r'[A-Za-z0-9_./-]{1,180}',val):print('GEMINI_KOTA',field,val,flush=True)
            if 'RetryInfo' in str(detail.get('@type','')):
                delay=str(detail.get('retryDelay') or '')
                if re.fullmatch(r'[0-9.]{1,20}s',delay):print('GEMINI_TEKRAR_BEKLE',delay,flush=True)
    except (ValueError,TypeError,AttributeError):
        pass
    raise SystemExit(2)
except Exception as exc:
    print('GEMINI_HATA',type(exc).__name__,flush=True)
    raise SystemExit(2)
