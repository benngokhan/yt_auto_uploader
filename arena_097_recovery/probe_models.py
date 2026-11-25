import json, os, urllib.error, urllib.request

KEY = os.environ['GEMINI_API_KEY']


def get(url):
    req = urllib.request.Request(url, headers={'x-goog-api-key': KEY})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post(model):
    body = json.dumps({'contents': [{'parts': [{'text': 'ok'}]}],
                       'generationConfig': {'maxOutputTokens': 1}}).encode()
    req = urllib.request.Request(
        'https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent',
        data=body, method='POST',
        headers={'Content-Type': 'application/json', 'x-goog-api-key': KEY})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read(300)
    except urllib.error.HTTPError as e:
        return e.code, e.read(300)


status, raw = get('https://generativelanguage.googleapis.com/v1beta/models?pageSize=200')
print('LIST', status)
if status == 200:
    for m in json.loads(raw).get('models', []):
        if 'generateContent' in m.get('supportedGenerationMethods', []) and 'gemini' in m['name']:
            print('MODEL', m['name'], '|', m.get('displayName'))

for model in ['gemini-3.8-flash', 'gemini-3.6-flash', 'gemini-flash-latest',
              'gemini-3.5-flash', 'gemini-flash-lite-latest', 'gemini-3.8-flash-lite']:
    s, b = post(model)
    print('PROBE', model, s, b[:220].decode('utf-8', 'replace').replace('\n', ' '))
