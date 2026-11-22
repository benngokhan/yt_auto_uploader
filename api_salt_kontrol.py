"""Küçük gerçek istekler; yalnız sonuç, asla anahtar veya yanıt gövdesi gösterilmez."""
import json, os, urllib.request, urllib.error, urllib.parse

def check(name, env, build, validate):
    value=os.getenv(env, '').strip()
    if not value:
        print(name, 'ORTAMDA_YOK', flush=True); return
    try:
        req=build(value)
        with urllib.request.urlopen(req, timeout=45) as response:
            code=response.status
            data=json.load(response)
        print(name, 'OK' if code==200 and validate(data) else 'BEKLENMEYEN_YANIT', flush=True)
    except urllib.error.HTTPError as e:
        body=e.read(65536).decode('utf8','replace').lower()
        reasons=[]
        for label, words in [('ANAHTAR_GECERSIZ',('api key not valid','invalid api key','invalid key','api_key_invalid')), ('ERISIM_REDDEDILDI',('permission denied','permission_denied','access denied','forbidden')), ('KOTA',('quota exceeded','quota_exceeded','resource_exhausted','rate limit')), ('MODEL_YOK',('model is not found','is not found for api version','not found for api version','model not found')), ('BOLGE',('location is not supported','country is not supported','unsupported country')), ('FATURA',('billing','payment required')), ('PARAMETRE',('invalid argument','invalid_argument')), ('AG_ENGELI',('robots_denied','blocked by','proxy'))]:
            if any(word in body for word in words): reasons.append(label)
        print(name, 'HTTP_'+str(e.code), ','.join(reasons) or 'NEDEN_TANIMLANAMADI', flush=True)
    except Exception as e:
        print(name, 'HATA_'+type(e).__name__, flush=True)

check('PEXELS', 'PEXELS_API_KEY', lambda k: urllib.request.Request('https://api.pexels.com/v1/search?query=nature&per_page=1', headers={'Authorization':k}), lambda d:bool(d.get('photos')))
check('PIXABAY', 'PIXABAY_API_KEY', lambda k: urllib.request.Request('https://pixabay.com/api/?'+urllib.parse.urlencode({'key':k,'q':'nature','per_page':3})), lambda d:bool(d.get('hits')))
def gem(k):
    data={'contents':[{'parts':[{'text':'Merhaba de.'}]}], 'generationConfig':{'maxOutputTokens':64}}
    return urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?'+urllib.parse.urlencode({'key':k}),data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
check('GEMINI_METIN','GEMINI_API_KEY',gem,lambda d:bool(d.get('candidates')))
def tts(k):
    data={'contents':[{'parts':[{'text':'Merhaba.'}]}], 'generationConfig':{'responseModalities':['AUDIO'],'speechConfig':{'voiceConfig':{'prebuiltVoiceConfig':{'voiceName':'Charon'}}}}}
    return urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?'+urllib.parse.urlencode({'key':k}),data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
check('GEMINI_CHARON','GEMINI_API_KEY',tts,lambda d:bool(d.get('candidates')))
check('GEMINI_MODELLER','GEMINI_API_KEY',lambda k: urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models?'+urllib.parse.urlencode({'key':k})),lambda d: bool(d.get('models')))
