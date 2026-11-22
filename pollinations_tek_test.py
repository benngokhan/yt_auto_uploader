"""One Quest-only Pollinations image; no retries, video, queue or publishing."""
import base64
import io
import json
import math
import os
import re
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path
from PIL import Image

BASE='https://gen.pollinations.ai'
MODEL='black-forest-labs/flux.1-schnell'
KEY=(os.getenv('POLLINATIONS_API_KEY') or '').strip()
if not KEY:
    print('POLLINATIONS_DURUM SECRET_YOK',flush=True);raise SystemExit(2)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
opener=urllib.request.build_opener(NoRedirect())

def request_json(path, payload=None):
    headers={'Authorization':'Bearer '+KEY,'Accept':'application/json','User-Agent':'Mozilla/5.0'}
    body=None
    if payload is not None:
        body=json.dumps(payload).encode('utf8');headers['Content-Type']='application/json'
    req=urllib.request.Request(BASE+path,data=body,headers=headers,method='POST' if payload is not None else 'GET')
    with opener.open(req,timeout=100) as response:
        if response.status!=200:raise ValueError('unexpected_http')
        return json.load(response)

def num(value):
    if isinstance(value,bool):return None
    try: n=float(value)
    except (ValueError,TypeError,OverflowError):return None
    return n if math.isfinite(n) else None

try:
    info=request_json('/account/key')
    valid=info.get('valid') is True and info.get('type')=='secret'
    quest_only=info.get('questPollenOnly') is True
    budget=num(info.get('pollenBudget'))
    print('POLLINATIONS_ANAHTAR', 'GECERLI' if valid else 'GECERSIZ', 'YALNIZ_GOREV',quest_only,flush=True)
    if not valid or not quest_only:
        print('POLLINATIONS_DURUM GUVENLIK_KILIDI',flush=True);raise SystemExit(2)
    balance=request_json('/account/balance')
    wallet=balance.get('accountBalance') or {}
    available=num(wallet.get('tier'))
    remaining=num(balance.get('balance'))
    print('POLLINATIONS_GOREV_BAKIYESI', available if available is not None else 'BILINMIYOR',flush=True)
    print('POLLINATIONS_ANAHTAR_BUTCESI', remaining if remaining is not None else 'BILINMIYOR',flush=True)
    if available is None or remaining is None or wallet.get('questPollenRestricted') is True:
        print('POLLINATIONS_DURUM BAKIYE_DOGRULANAMADI',flush=True);raise SystemExit(2)
    models=request_json('/image/models')
    if not isinstance(models,list): raise ValueError('invalid_catalog')
    entries=[x for x in models if isinstance(x,dict) and x.get('name')==MODEL]
    if len(entries)!=1:raise ValueError('missing_model')
    model=entries[0]; price=num((model.get('pricing') or {}).get('completionImageTokens'))
    print('POLLINATIONS_MODEL',MODEL,'BIRIM_KREDI',price if price is not None else 'BILINMIYOR',flush=True)
    if model.get('paid_only') is not False or model.get('flat_rate') is not True or price is None or price<=0 or price>0.002:
        print('POLLINATIONS_DURUM MODEL_FIYATI_DOGRULANAMADI',flush=True);raise SystemExit(2)
    if available<price or remaining<price or (budget is not None and budget<price):
        print('POLLINATIONS_DURUM YETERSIZ_GOREV_BAKIYESI_VEYA_BUTCE',flush=True);raise SystemExit(2)
    prompt='Solda bir kişi, sağda masanın üzerinde tek mum; kişi dudaklarını büzerek muma üflüyor, alev nefes yönünde sağa eğiliyor ve fitilden ince duman çıkıyor. Dikey, gerçekçi, yazısız ve logosuz bir görüntü istedim; ayrıca çakmak ve kibrit olmamasını belirttim.'
    print('POLLINATIONS_GORSEL_ISTEGI 1_BASLADI',flush=True)
    result=request_json('/v1/images/generations',{'model':MODEL,'prompt':prompt,'n':1,'size':'576x1024',
                        'response_format':'b64_json','seed':secrets.randbelow(2_000_000_000)})
    rows=result.get('data')
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):raise ValueError('invalid_image_count')
    raw=base64.b64decode(rows[0].get('b64_json',''),validate=True)
    if not 1000 <= len(raw) <= 10_000_000:raise ValueError('invalid_image_size')
    with Image.open(io.BytesIO(raw)) as im:
        im.load();print('POLLINATIONS_GORSEL_FORMAT',im.format,'BOYUT',im.width,im.height,flush=True)
        if im.width>=im.height or im.width<256:raise ValueError('not_portrait')
        out=Path('pollinations_ornek.png'); im.convert('RGB').save(out,'PNG')
    print('POLLINATIONS_DURUM GORSEL_ALINDI_LOGETIKET_MANUEL_KONTROL_GEREKLI',flush=True)
except urllib.error.HTTPError as exc:
    print('POLLINATIONS_HTTP',exc.code,flush=True)
    try:
        obj=json.loads(exc.read(20000)); code=(obj.get('error') or {}).get('code','')
        if isinstance(code,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}',code):print('POLLINATIONS_HATA_KODU',code,flush=True)
    except (ValueError,TypeError,AttributeError):pass
    raise SystemExit(2)
except Exception as exc:
    print('POLLINATIONS_HATA',type(exc).__name__,flush=True)
    raise SystemExit(2)
