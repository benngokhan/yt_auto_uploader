import base64, io, json, os, time, urllib.error, urllib.request
from pathlib import Path
from PIL import Image

KEY = os.environ['GEMINI_API_KEY']
ROOT = Path('.').resolve()
WORK = ROOT / 'imported_097' / 'work_097'
rows = json.loads((ROOT / 'imported_097' / 'result_097' / 'asset_review.json').read_text())
plan = json.loads((ROOT / 'arena_096' / 'plan.json').read_text())

prompt = ('Strict documentary image review. These are AI reconstructions of Mehmed II and Gentile '
          'Bellini in Istanbul ~1479-1480, not photographs. Reject modern objects, malformed '
          'people/hands, unreadable fabricated text, or near-duplicates. Output ONLY JSON '
          '{"scenes":[{"scene":1,"pass":true,"note":"..."}]}. Requested scenes:\n'
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
        with urllib.request.urlopen(req, timeout=120) as r:
            status, text = r.status, r.read(300).decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read(200).decode('utf-8', 'replace')
    except Exception as e:
        status, text = type(e).__name__, str(e)[:150]
    print('REVIEW', model, 'bytes=' + str(len(body)), status, round(time.time() - started, 1),
          text[:160].replace('\n', ' '), flush=True)
    return status


models = ['gemini-2.5-pro', 'gemini-3.1-pro-preview', 'gemini-pro-latest',
          'gemini-3-flash-preview', 'gemini-omni-1.2-flash', 'gemini-3.1-flash-lite']
single = [{'text': prompt},
          {'inlineData': {'mimeType': 'image/jpeg', 'data': jpeg(load(rows[0], (270, 480)))}}]

sheet = Image.new('RGB', (1080, 960), (0, 0, 0))
for i, row in enumerate(rows):
    sheet.paste(load(row, (270, 480)), ((i % 4) * 270, (i // 4) * 480))
sheet_parts = [{'text': prompt + '\nOne contact sheet, row-major: top-left to bottom-right = scenes 1-8.'},
               {'inlineData': {'mimeType': 'image/jpeg', 'data': jpeg(sheet, 80)}}]

ok = []
for model in models:
    if post(model, single) == 200:
        ok.append(model)
for model in ok:
    post(model, sheet_parts)
print('WORKING_MODELS', ok, flush=True)
