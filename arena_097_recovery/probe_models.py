import json, os, time, urllib.error, urllib.request

KEY = os.environ['GEMINI_API_KEY']


def post(model, timeout=30):
    body = json.dumps({'contents': [{'parts': [{'text': 'ok'}]}],
                       'generationConfig': {'maxOutputTokens': 1}}).encode()
    req = urllib.request.Request(
        'https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent',
        data=body, method='POST',
        headers={'Content-Type': 'application/json', 'x-goog-api-key': KEY})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(200), time.time() - started
    except urllib.error.HTTPError as e:
        return e.code, e.read(200), time.time() - started
    except Exception as e:
        return type(e).__name__, b'', time.time() - started


for model in ['gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash',
              'gemini-3.5-flash', 'gemini-flash-latest', 'gemini-3.1-flash-lite']:
    status, body, elapsed = post(model)
    print('PROBE', model, status, round(elapsed, 1), body[:180].decode('utf-8', 'replace').replace('\n', ' '))
    time.sleep(2)
