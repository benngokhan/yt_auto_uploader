"""Isolated, non-publishing OpenRouter vision experiment, not production-certified."""
from __future__ import annotations
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from PIL import Image

MODEL = 'particle-ai/particle-1:free'
ORIGIN = 'live_openrouter_experimental'


def score_images(scene_text, candidates, download):
    key = (os.environ.get('OPENROUTER_API_KEY') or '').strip()
    scores = [None] * len(candidates)
    if not key or not candidates:
        return scores
    parts = [{'type':'text', 'text': (
        'Sahne metni: ' + scene_text + '\n'
        'Her numaralı fotoğrafı sahne metninde anlatılan somut nesne, eylem veya mekanizmayı '
        'gösterip göstermediğine göre puanla. Sadece genel bilim havası alaka değildir. '
        '0 = ilgisiz; 0.5 = kısmi/dolaylı; 1 = doğrudan açıkça gösteriyor. '
        'Sadece JSON döndür: {"scores":[0.0,...]}. Sayı ve sıra görsellerle aynı olmalı.') }]
    ids = []
    with TemporaryDirectory(prefix='or-vision-') as tmp:
        for idx, hit in enumerate(candidates):
            url = str(hit.get('preview_url') or hit.get('indir_url') or '')
            if not url: continue
            try:
                p = Path(tmp) / f'{idx}.jpg'
                download(url, p)
                with Image.open(p) as im:
                    im = im.convert('RGB'); im.thumbnail((384,384), Image.Resampling.LANCZOS)
                    buf = io.BytesIO(); im.save(buf, format='JPEG', quality=78, optimize=True)
                parts.append({'type':'text','text':f'Görsel {len(ids)+1}:'})
                parts.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode('ascii')}})
                ids.append(idx)
            except Exception as exc:
                hit['_vision_error'] = 'image_fetch:' + type(exc).__name__
        if not ids: return scores
        body = {'model':MODEL, 'messages':[{'role':'user','content':parts}], 'max_tokens':1200, 'temperature':0}
        for attempt in range(3):
            req=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',
                data=json.dumps(body).encode(), headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=75) as response: data=json.load(response)
                choice=data['choices'][0]
                if choice.get('finish_reason') not in ('stop', None): raise ValueError('incomplete')
                text=(choice['message'].get('content') or '').strip()
                if text.startswith('```json'): text=text[7:]
                elif text.startswith('```'): text=text[3:]
                if text.rstrip().endswith('```'): text=text.rstrip()[:-3]
                raw=json.loads(text.strip())['scores']
                if not isinstance(raw,list) or len(raw)!=len(ids): raise ValueError('bad_score_count')
                for i,value in zip(ids,raw):
                    if isinstance(value,bool) or not isinstance(value,(int,float)): continue
                    val=float(value)
                    if 0 <= val <= 1:
                        scores[i]=val
                        candidates[i]['_vision_origin']=ORIGIN
                return scores
            except urllib.error.HTTPError as exc:
                for i in ids: candidates[i]['_vision_error'] = 'openrouter_http_'+str(exc.code)
                if exc.code not in (429,500,502,503,504) or attempt == 2: break
                time.sleep((6,12)[attempt])
            except Exception as exc:
                for i in ids: candidates[i]['_vision_error'] = 'openrouter_'+type(exc).__name__
                break
    return scores
