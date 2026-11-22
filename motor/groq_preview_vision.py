"""Free-plan Groq visual judge for isolated, non-publishing previews only.

The caller must enforce the experimental dry-run guard. Score provenance stays
separate from Gemini, and provider failures always produce None, never a guess.
"""
from __future__ import annotations
import base64
import io
import json
import math
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from PIL import Image

MODEL = 'qwen/qwen3.8-27b'
ORIGIN = 'live_groq_experimental'
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
_not_before = 0.0


def _duration(value):
    if not value:
        return None
    s = str(value).strip().lower()
    try:
        return max(0.0, float(s))
    except ValueError:
        pass
    if not re.fullmatch(r'(?:\d+(?:\.\d+)?h)?(?:\d+(?:\.\d+)?m)?(?:\d+(?:\.\d+)?s)?',s):
        return None
    found = re.findall(r'(\d+(?:\.\d+)?)([hms])',s)
    return sum(float(n)*{'h':3600,'m':60,'s':1}[unit] for n,unit in found) if found else None


def score_images(scene_text, candidates, download):
    global _not_before
    scores = [None] * len(candidates)
    key = (os.getenv('GROQ_API_KEY') or '').strip()
    if not key:
        for hit in candidates: hit['_vision_error'] = 'groq_missing_key'
        return scores
    with tempfile.TemporaryDirectory(prefix='groq-vision-') as tmp:
        for index, hit in enumerate(candidates):
            url = str(hit.get('preview_url') or hit.get('indir_url') or '')
            try:
                if not url: raise ValueError('missing image')
                path = Path(tmp) / f'{index}.jpg'
                download(url, path)
                with Image.open(path) as im:
                    im = im.convert('RGB'); im.thumbnail((384,384), Image.Resampling.LANCZOS)
                    buf=io.BytesIO(); im.save(buf,format='JPEG',quality=78,optimize=True)
                encoded=base64.b64encode(buf.getvalue()).decode('ascii')
            except (Exception, SystemExit) as exc:
                hit['_vision_error'] = 'image_fetch:' + type(exc).__name__
                continue
            prompt=('Video ve sahne: '+scene_text+'\n'
                    'Fotoğrafı dikkatle incele ve bu sahneye uygunluğunu değerlendir. '
                    'Sahnedeki nesne ve eylem açıkça görülüyorsa 1.0, '
                    'konu nesnesini gösteren ve yanıltmayan doğrudan temsili fotoğraf 0.8, '
                    'yalnız genel bağlantı veya belirsizlik 0.5, ilgisiz veya ters eylem 0.0. '
                    'Örnek: çakmakla mum yakmak üfleyerek söndürmek değildir. '
                    'Görünmeyen eylemi var sayma. Yalnız JSON döndür: '
                    '{"observed":"görülen nesne ve eylem","score":0.0}.')
            body={'model':MODEL,'messages':[{'role':'user','content':[
                    {'type':'text','text':prompt},
                    {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+encoded}}]}],
                  'response_format':{'type':'json_object'},'reasoning_effort':'none',
                  'temperature':0,'max_completion_tokens':300}
            success=False
            for attempt in range(2):
                delay=max(0.0,_not_before-time.monotonic())
                if delay>75:
                    hit['_vision_error']='groq_rate_limit_wait_too_long'; break
                if delay: time.sleep(delay)
                req=urllib.request.Request('https://api.groq.com/openai/v1/chat/completions',
                    data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,
                        'Content-Type':'application/json','Accept':'application/json','User-Agent':USER_AGENT})
                try:
                    with urllib.request.urlopen(req,timeout=90) as response:
                        data=json.load(response); headers=response.headers
                    remaining=headers.get('x-ratelimit-remaining-tokens')
                    reset=_duration(headers.get('x-ratelimit-reset-tokens'))
                    try:
                        if remaining is not None and int(remaining)<2500 and reset is not None:
                            _not_before=max(_not_before,time.monotonic()+reset+1.0)
                    except (TypeError,ValueError):
                        pass
                    choice=data['choices'][0]
                    if choice.get('finish_reason') not in ('stop',None): raise ValueError('truncated')
                    parsed=json.loads((choice.get('message',{}).get('content') or '').strip())
                    score=parsed.get('score')
                    if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0 <= score <= 1:
                        raise ValueError('invalid_score')
                    scores[index]=float(score);hit['_vision_origin']=ORIGIN;hit.pop('_vision_error',None);success=True;break
                except urllib.error.HTTPError as exc:
                    hit['_vision_error']='groq_http_'+str(exc.code)
                    retry=_duration(exc.headers.get('retry-after') if exc.headers else None)
                    if exc.code==429 and attempt==0 and retry is not None and retry<=75:
                        _not_before=max(_not_before,time.monotonic()+retry+1.0)
                        continue
                    break
                except Exception as exc:
                    hit['_vision_error']='groq_'+type(exc).__name__;break
            if not success and hit.get('_vision_error','').startswith(('groq_http_429','groq_http_401','groq_http_403','groq_rate_limit')):
                # Do not spend quota or bypass the error on the remaining batch.
                for rest in candidates[index+1:]:rest['_vision_error']=hit['_vision_error']
                break
    return scores
