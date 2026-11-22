"""Izole OpenRouter görsel doğrulayıcı testi; hiçbir yayın veya Drive işlemi yapmaz."""
import base64, json, os, time, urllib.request, urllib.error
from io import BytesIO
from PIL import Image

key = os.getenv('OPENROUTER_API_KEY', '').strip()
if not key:
    raise SystemExit('OPENROUTER_ANAHTARI_YOK')
images = [
    ('mum', 'https://images.pexels.com/photos/39851086/pexels-photo-39851086.jpeg'),
    ('balon', 'https://images.pexels.com/photos/12267732/pexels-photo-12267732.jpeg'),
    ('termometre', 'https://images.pexels.com/photos/5998444/pexels-photo-5998444.jpeg'),
    ('kibrit', 'https://images.pexels.com/photos/39244/match-fire-close-burn-39244.jpeg'),
]
model = 'particle-ai/particle-1:free'
question = ('Inspect the picture. Is a candle with a visible flame clearly shown? '
            'A hot air balloon, thermometer, or match alone is not a candle. '
            'Return only JSON with keys candle_visible (boolean) and main_object (short string).')
for label, url in images:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = r.read(3000000)
        with Image.open(BytesIO(data)) as im:
            im = im.convert('RGB'); im.thumbnail((384,384)); out = BytesIO(); im.save(out, format='JPEG', quality=78)
        data_url = 'data:image/jpeg;base64,' + base64.b64encode(out.getvalue()).decode('ascii')
        body = {'model': model, 'messages': [{'role':'user', 'content': [
            {'type':'text','text':question}, {'type':'image_url','image_url':{'url':data_url}}]}],
            'max_tokens':250, 'temperature':0}
        req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',
            data=json.dumps(body).encode(), headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=70) as r:
            result=json.load(r)
        text=result['choices'][0]['message'].get('content') or ''
        text=text.strip().removeprefix('```json').removesuffix('```').strip()
        try:
            parsed=json.loads(text)
            obj=str(parsed.get('main_object',''))[:90].replace('\n',' ')
            print('GORSEL', label, 'MUM_MU', parsed.get('candle_visible'), 'NESNE',obj,flush=True)
        except (ValueError, TypeError):
            print('GORSEL',label,'JSON_GECERSIZ',flush=True)
    except urllib.error.HTTPError as e:
        print('GORSEL',label,'HTTP',e.code,flush=True)
    except Exception as e:
        print('GORSEL',label,'HATA',type(e).__name__,flush=True)
    time.sleep(1)
