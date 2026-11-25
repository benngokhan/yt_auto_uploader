"""097 recovery: reuse the approved 096 Charon voice and the eight run-150 images.

One authorized visual review, then one local render. No TTS, no image generation,
no automatic retry, no publication or queue writes.
"""
from pathlib import Path
import base64, hashlib, io, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'arena_096'))
import produce as providers

AUTH = 'FATIH_REMAINING_IMAGES_097_RECOVERY3_ONCE'
BRANCH = 'arena/fatih-remaining-097-recovery3'
VOICE_SHA = 'c24a2b380eb5bb16db767a01869664133831200f411574e64c2645fc05842392'
SOURCE_RUN = 45528376909
IMPORT = ROOT / 'imported_097'
SRC_WORK = IMPORT / 'work_097'
SRC_OUT = IMPORT / 'result_097'
WORK = ROOT / 'work_097_recovery'
OUT = ROOT / 'result_097_recovery'
REVIEW_MODEL = 'gemini-3.8-flash'
SCENE_FILES = ['scene%02d.png' % i for i in range(1, 9)]


def fail(message):
    raise providers.Stop(message)


def check_context():
    if os.environ.get('GITHUB_REPOSITORY') != 'benngokhan/yt_auto_uploader':
        fail('Wrong repository')
    if os.environ.get('GITHUB_REF') != 'refs/heads/' + BRANCH:
        fail('Wrong ref')
    if os.environ.get('GITHUB_RUN_ATTEMPT') != '1':
        fail('Wrong run attempt')
    claim = json.loads((HERE / 'claimed.json').read_text())
    if claim.get('authorization') != AUTH or str(claim.get('run_id')) != os.environ.get('GITHUB_RUN_ID'):
        fail('Permanent run-bound 097 recovery claim missing')
    if not os.environ.get('GEMINI_API_KEY', '').strip():
        fail('GEMINI_API_KEY missing; no alternate provider')


def validate_inputs():
    voice = SRC_WORK / 'assets' / 'narration.wav'
    if not voice.is_file() or providers.sha(voice) != VOICE_SHA:
        fail('Approved voice hash mismatch; do not regenerate')

    proof = json.loads((SRC_WORK / 'voice_provenance.json').read_text())
    alignment = json.loads((SRC_WORK / 'alignment.json').read_text())
    asrproof = json.loads((SRC_WORK / 'asr_validation.json').read_text())
    if proof.get('audio_sha256') != VOICE_SHA or proof.get('voice') != 'Charon':
        fail('Voice provenance mismatch')
    if alignment.get('audio_sha256') != VOICE_SHA or alignment.get('asr_similarity', 0) < .95:
        fail('Alignment mismatch')
    if asrproof.get('audio_sha256') != VOICE_SHA or asrproof.get('combined_similarity', 0) < .95:
        fail('ASR validation mismatch')

    rows = json.loads((SRC_OUT / 'asset_review.json').read_text())
    if len(rows) != 8 or [r.get('file') for r in rows] != SCENE_FILES:
        fail('Eight reviewed image records required')
    if len({r['sha256'] for r in rows}) != 8 or len({r['pixel_sha256'] for r in rows}) != 8:
        fail('Duplicate image records')

    for row in rows:
        path = SRC_WORK / 'assets' / row['file']
        if not path.is_file() or path.stat().st_size > 100_000_000:
            fail('Missing or oversize image: ' + row['file'])
        if providers.sha(path) != row['sha256']:
            fail('Image file hash mismatch: ' + row['file'])
        with Image.open(path) as im:
            im.load()
            if im.size != (720, 1280) or im.format not in {'PNG', 'JPEG'}:
                fail('Image format/size mismatch: ' + row['file'])
            if hashlib.sha256(im.convert('RGB').tobytes()).hexdigest() != row['pixel_sha256']:
                fail('Image pixel hash mismatch: ' + row['file'])
    return rows, proof, alignment


def build_work(rows):
    WORK.mkdir(exist_ok=False)
    (WORK / 'assets').mkdir()
    shutil.copyfile(SRC_WORK / 'assets' / 'narration.wav', WORK / 'assets' / 'narration.wav')
    shutil.copyfile(SRC_WORK / 'voice_provenance.json', WORK / 'voice_provenance.json')
    shutil.copyfile(SRC_WORK / 'alignment.json', WORK / 'alignment.json')
    shutil.copyfile(SRC_WORK / 'asr_validation.json', WORK / 'asr_validation.json')
    for name in SCENE_FILES:
        shutil.copyfile(SRC_WORK / 'assets' / name, WORK / 'assets' / name)

    plan = json.loads((ROOT / 'arena_096' / 'plan.json').read_text())
    alignment = json.loads((WORK / 'alignment.json').read_text())
    plan['authorization_id'] = AUTH
    plan['budget'] = {'full_narrations_max': 0, 'new_images_max': 0, 'visual_review_max': 1,
                      'automatic_generation_retries': False, 'publication': False}
    plan['timeline_edges'] = [0] + [alignment['groups'][i][0]['start']
                                    for i in plan['scene_group_indices'][1:]] + [53]
    providers.save(WORK / 'plan.json', plan)
    providers.save(WORK / 'asset_review.json', rows)
    return plan


def review_once(plan, rows, budget):
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
    providers.save(OUT / 'review_request_meta.json', {
        'model': REVIEW_MODEL, 'payload_bytes': len(body), 'images': [r['sha256'] for r in rows],
        'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'automatic_retry': False})

    url = 'https://generativelanguage.googleapis.com/v1beta/models/' + REVIEW_MODEL + ':generateContent'
    headers = {'Content-Type': 'application/json', 'x-goog-api-key': os.environ['GEMINI_API_KEY']}
    budget.reserve('review', body)
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    raw = None
    attempts = []
    for attempt in (1, 2, 3):
        try:
            with providers.OPEN.open(req, timeout=180) as resp:
                raw = resp.read(1024 * 1024 + 1)
            attempts.append({'attempt': attempt, 'http': 200})
            break
        except urllib.error.HTTPError as exc:
            detail = ''
            try:
                detail = exc.read(1200).decode('utf-8', 'replace').replace('\n', ' ')
            except Exception:
                pass
            attempts.append({'attempt': attempt, 'http': exc.code, 'body': detail[:300]})
            providers.save(OUT / 'review_attempts.json', attempts)
            # 503/429 mean the model never processed the request; a short bounded wait is
            # transport-level, not a second visual review. Anything else stops immediately.
            if exc.code in (429, 503) and attempt < 3:
                time.sleep(30 if attempt == 1 else 90)
                continue
            fail('Review provider HTTP %s; reserved budget consumed; %s' % (exc.code, detail[:300]))
        except Exception as exc:
            attempts.append({'attempt': attempt, 'error': type(exc).__name__})
            providers.save(OUT / 'review_attempts.json', attempts)
            fail('Review call failed or uncertain; reserved budget consumed; ' + type(exc).__name__)
    providers.save(OUT / 'review_attempts.json', attempts)
    if raw is None or len(raw) > 1024 * 1024:
        fail('Review response missing or too large')

    try:
        obj = json.loads(raw)
        text = ''.join(p.get('text', '') for p in obj['candidates'][0]['content']['parts']
                       if not p.get('thought'))
        review = json.loads(text)
        checks = review['scenes']
        if len(checks) != 8 or [x['scene'] for x in checks] != list(range(1, 9)):
            raise ValueError('scene list')
        if any(type(x['pass']) is not bool for x in checks):
            raise ValueError('pass type')
    except Exception:
        fail('Visual review response invalid; no silent approval')

    providers.save(OUT / 'automated_visual_review.json', review)
    for row, check in zip(rows, checks):
        row.update(approved_for_illustrative_draft=check['pass'],
                   reviewer='automated_' + REVIEW_MODEL,
                   review_note=check.get('note', ''), human_approved=False)
    providers.save(WORK / 'asset_review.json', rows)
    providers.save(OUT / 'asset_review.json', rows)
    failed = [x['scene'] for x in checks if not x['pass']]
    if failed:
        fail('Automated review rejected scenes %s; no regeneration' % failed)
    return checks


def main():
    state = {'state': 'started', 'authorization': AUTH, 'reused_voice_sha256': VOICE_SHA,
             'source_run': SOURCE_RUN, 'reused_images': 8, 'new_tts_max': 0, 'new_images_max': 0,
             'review_max': 1, 'automatic_retry': False, 'published': False, 'queue_written': False,
             'calls': {'tts': 0, 'images': 0, 'review': 0}}
    try:
        check_context()
    except providers.Stop as exc:
        raise SystemExit('097 recovery not started: ' + str(exc)) from None
    OUT.mkdir(exist_ok=False)
    try:
        rows, proof, _alignment = validate_inputs()
        plan = build_work(rows)
        budget = providers.Budget(OUT / 'consumed_calls')
        budget.limits = {'tts': 0, 'images': 0, 'review': 1}
        state['calls'] = budget.count
        review_once(plan, rows, budget)
        subprocess.run([sys.executable, str(ROOT / 'motor/uret.py'),
                        '--boston-bundle', str(WORK), '--boston-output', str(OUT / 'final'),
                        '--boston-mode', 'render'], check=True)
        state.update(state='completed_awaiting_user_review', calls=budget.count,
                     video='final/video.mp4', cover='final/kapak.jpg',
                     natural_voice_seconds=proof['natural_seconds'], human_approved=False)
    except Exception as exc:
        state.update(state='stopped_without_retry', error_type=type(exc).__name__,
                     safe_reason=str(exc) if isinstance(exc, providers.Stop)
                     else 'Pipeline step failed; inspect nonsecret outputs')
        providers.save(OUT / 'status.json', state)
        raise SystemExit('097 recovery stopped; no retry or regeneration. ' + state['safe_reason']) from None
    providers.save(OUT / 'status.json', state)
    print('097 recovery complete: SAME approved Charon voice, SAME eight reviewed images, '
          'one review, one render. No queue/publication.', flush=True)


if __name__ == '__main__':
    main()
