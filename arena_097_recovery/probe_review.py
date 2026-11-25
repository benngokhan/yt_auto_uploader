import base64, io, json, os, time, urllib.error, urllib.request
from pathlib import Path
from PIL import Image

KEY = os.environ['GEMINI_API_KEY']
ROOT = Path('.').resolve()
WORK = ROOT / 'imported_097' / 'work_097'
rows = json.loads((ROOT / 'imported_097' / 'result_097' / 'asset_review.json').read_text())
plan = json.loads((ROOT / 'arena_096' / 'plan.json').read_text())

prompt = ('You are a strict historical documentary image reviewer. These eight AI reconstructions '
          'illustrate the Ottoman Sultan Mehmed II inviting Venetian painter Gentile Bellini to '
          'Istanbul around 1479-1480. They are NOT photographs of original artwork or exact '
          'historical likenesses. Evaluate the eight images in supplied order against their '
          'individual requested scenes. Reject conspicuous modern objects, obvious malformed '
          'people/hands, unreadable fabricated labels or UI, severe factual contradictions to the '
          'requested composition, or near-duplicate scenes. Minor uncertainties in illustrative '
          'costume/architecture should be disclosed in note, not described as exact historical '
          'evidence. Output ONLY JSON: {"scenes":[{"scene":1,"pass":true,"note":"..."}, ... eight '
          'objects ...]}. Passing is only automated review, not human approval. Requested scenes:\n'
          + json.dumps(plan['scene_prompts'], ensure_ascii=False))
parts = [{'text': prompt}]
for row in rows:
    with Image.open(WORK / 'assets' / row['file']) as im:
        im = im.convert('RGB')
        im.thumbnail((270, 480))
        buf = io.BytesIO()
        im.save(buf, format='JPEG', quality=75)
    parts.append({'text': 'Scene ' + str(row['scene'])})
    parts.append({'inlineData': {'mimeType': 'image/jpeg',
                                 'data': base64.b64encode(buf.getvalue()).decode()}})
body = json.dumps({'contents': [{'parts': parts}],
                   'generationConfig': {'temperature': 0,
                                        'responseMimeType': 'application/json'}}).encode()
print('PAYLOAD_BYTES', len(body), flush=True)

for model in ['gemini-3.5-flash', 'gemini-3.6-flash', 'gemini-3.1-flash-lite']:
    req = urllib.request.Request(
        'https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent',
        data=body, method='POST',
        headers={'Content-Type': 'application/json', 'x-goog-api-key': KEY})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read(2000)
            status, text = r.status, raw.decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read(400).decode('utf-8', 'replace')
    except Exception as e:
        status, text = type(e).__name__, str(e)[:200]
    print('REVIEW', model, status, round(time.time() - started, 1), text[:300].replace('\n', ' '), flush=True)
    time.sleep(2)
