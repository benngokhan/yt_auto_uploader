"""Experimental free-model script JSON for isolated dry-run only."""
from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.request
from openrouter_preview_limits import classify_retry

MODEL = 'particle-ai/particle-1:free'
_DAILY_EXHAUSTED = False  # scoped to this process, never persistent account state


def get_json(prompt, system):
    global _DAILY_EXHAUSTED
    if _DAILY_EXHAUSTED:
        print('Deneysel metin modeli: günlük limit dolu; yeni istek gönderilmedi',flush=True)
        return {}
    key=(os.environ.get('OPENROUTER_API_KEY') or '').strip()
    if not key:
        print('Deneysel metin modeli: anahtar yok')
        return {}
    body={'model': MODEL, 'temperature': 0.35, 'max_tokens': 2200, 'reasoning': {'enabled': False},
          'messages':[{'role':'system','content':system},{'role':'user','content':prompt}]}
    for attempt in range(3):
        request=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',
                    data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=90) as response: data=json.load(response)
            choice=data['choices'][0]
            if choice.get('finish_reason') not in ('stop',None):
                print('Deneysel metin modeli: eksik yanıt');return {}
            content=(choice['message'].get('content') or '').strip()
            if content.startswith('```json'): content=content[7:]
            elif content.startswith('```'):content=content[3:]
            if content.rstrip().endswith('```'):content=content.rstrip()[:-3]
            parsed=json.loads(content.strip())
            if isinstance(parsed,dict):return parsed
            return {}
        except urllib.error.HTTPError as exc:
            print('Deneysel metin modeli: HTTP',exc.code,flush=True)
            if exc.code not in (429,500,502,503,504):break
            reason, wait = classify_retry(exc, attempt)
            if reason == 'daily_quota_exhausted':
                _DAILY_EXHAUSTED = True
                print('Deneysel metin modeli: ücretsiz günlük istek limiti dolu',flush=True)
            if attempt == 2 or wait is None:break
            time.sleep(wait)
        except Exception as exc:
            print('Deneysel metin modeli:',type(exc).__name__,flush=True)
            break
    return {}
