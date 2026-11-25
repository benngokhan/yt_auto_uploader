import base64, io, json, os, time, urllib.error, urllib.request
from pathlib import Path
from PIL import Image

KEY = os.environ['GEMINI_API_KEY']
ROOT = Path('.').resolve()
WORK = ROOT / 'imported_097' / 'work_097'
rows = json.loads((ROOT / 'imported_097' / 'result_097' / 'asset_review.json').read_text())
plan = json.loads((ROOT / 'arena_096' / 'plan.json').read_text())

prompt = ('You are a strict historical documentary image reviewer. These AI reconstructions '
          'illustrate the Ottoman Sultan Mehmed II inviting Venetian painter Gentile Bellini to '
          'Istanbul around 1479-1480. They are NOT photographs of original artwork or exact '
          'historical likenesses. Evaluate the images in supplied order against their individual '
          'requested scenes. Reject conspicuous modern objects, obvious malformed people/hands, '
          'unreadable fabricated labels or UI, severe factual contradictions, or near-duplicate '
          'scenes. Output ONLY JSON: {"scenes":[{"scene":1,"pass":true,"note":"..."}]}. '
          'Passing is only automated review, not human approval. Requested scenes:\n'
          + json.dumps(plan['scene_prompts'], ensure_ascii=False))


def jpeg(im, quality=75):
    buf = io.BytesIO()
    im.convert('RGB').save(buf, format='JPEG', quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def load(row, size):
    with Image.open(WORK / 'assets' / row['file']) as im:
        im = im.convert('RGB')
        im.thumbnail(size)
        return im.copy()


def post(model, parts):
    body = json.dumps({'contents': [{'parts': parts}],
                       'generationConfig': {'temperature': 0,
                                            'responseMimeType': 'application/json'}}).encode()
    req = urllib.request.Request(
        'https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent',
        data=body, method='POST',
        headers={'Content-Type': 'application/json', 'x-goog-api-key': KEY})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            status, text = r.status, r.read(400).decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read(300).decode('utf-8', 'replace')
    except Exception as e:
        status, text = type(e).__name__, str(e)[:200]
    print('REVIEW', model, 'bytes=' + str(len(body)), status, round(time.time() - started, 1),
          text[:200].replace('\n', ' '), flush=True)


model = 'gemini-3.6-flash'

# A: one image
parts = [{'text': prompt}, {'inlineData': {'mimeType': 'image/jpeg', 'data': jpeg(load(rows[0], (270, 480)))}}]
post(model, parts)

# B: single 4x2 contact sheet
sheet = Image.new('RGB', (1080, 960), (0, 0, 0))
for i, row in enumerate(rows):
    tile = load(row, (270, 480))
    sheet.paste(tile, ((i % 4) * 270, (i // 4) * 480))
parts = [{'text': prompt + '\nThe eight scenes are in one contact sheet, row-major: top-left to '
          'bottom-right = scenes 1-8.'},
         {'inlineData': {'mimeType': 'image/jpeg', 'data': jpeg(sheet, 80)}}]
post(model, parts)

# C: eight tiny images
parts = [{'text': prompt}]
for row in rows:
    parts.append({'text': 'Scene ' + str(row['scene'])})
    parts.append({'inlineData': {'mimeType': 'image/jpeg', 'data': jpeg(load(row, (120, 213)), 70)}})
post(model, parts)
