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
        print(name, 'HTTP_'+str(e.code), flush=True)
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
