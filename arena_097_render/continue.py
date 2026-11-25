"""097 render: reuse the approved 096 Charon voice and the eight run-150 images.

The Gemini visual review endpoint was unavailable (2.5-flash retired with HTTP 404,
flash vision models HTTP 503, pro models HTTP 429), so this run uses an explicit
agent vision review recorded in agent_visual_review.json. No TTS, no image
generation, no provider call, no publication or queue writes.
"""
from pathlib import Path
import hashlib, json, os, shutil, subprocess, sys
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'arena_096'))
import produce as providers

AUTH = 'FATIH_REMAINING_IMAGES_097_AGENT_REVIEW_ONCE'
BRANCH = 'arena/fatih-remaining-097-render'
VOICE_SHA = 'c24a2b380eb5bb16db767a01869664133831200f411574e64c2645fc05842392'
SOURCE_RUN = 45528376909
IMPORT = ROOT / 'imported_097'
SRC_WORK = IMPORT / 'work_097'
SRC_OUT = IMPORT / 'result_097'
WORK = ROOT / 'work_097_render'
OUT = ROOT / 'result_097_render'
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
        fail('Permanent run-bound 097 render claim missing')


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


def apply_agent_review(rows):
    review = json.loads((HERE / 'agent_visual_review.json').read_text())
    checks = review.get('scenes') or []
    if len(checks) != 8 or [x.get('scene') for x in checks] != list(range(1, 9)):
        fail('Agent review scene list invalid')
    if any(type(x.get('pass')) is not bool for x in checks):
        fail('Agent review pass values invalid')
    for row, check in zip(rows, checks):
        row.update(approved_for_illustrative_draft=check['pass'],
                   reviewer='agent_vision_review',
                   review_note=check.get('note', ''), human_approved=False)
    failed = [x['scene'] for x in checks if not x['pass']]
    if failed:
        fail('Agent review rejected scenes %s; no regeneration' % failed)
    providers.save(OUT / 'agent_visual_review.json', review)
    providers.save(OUT / 'asset_review.json', rows)
    return rows


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
    plan['budget'] = {'full_narrations_max': 0, 'new_images_max': 0, 'visual_review_max': 0,
                      'automatic_generation_retries': False, 'publication': False}
    plan['timeline_edges'] = [0] + [alignment['groups'][i][0]['start']
                                    for i in plan['scene_group_indices'][1:]] + [53]
    providers.save(WORK / 'plan.json', plan)
    providers.save(WORK / 'asset_review.json', rows)
    return plan


def main():
    state = {'state': 'started', 'authorization': AUTH, 'reused_voice_sha256': VOICE_SHA,
             'source_run': SOURCE_RUN, 'reused_images': 8, 'new_tts': 0, 'new_images': 0,
             'provider_calls': 0, 'review_method': 'agent_vision_review',
             'gemini_review_status': 'unavailable: 2.5-flash HTTP 404, flash vision HTTP 503, pro HTTP 429',
             'automatic_retry': False, 'published': False, 'queue_written': False}
    try:
        check_context()
    except providers.Stop as exc:
        raise SystemExit('097 render not started: ' + str(exc)) from None
    OUT.mkdir(exist_ok=False)
    try:
        rows, proof, _alignment = validate_inputs()
        rows = apply_agent_review(rows)
        build_work(rows)
        subprocess.run([sys.executable, str(ROOT / 'motor/uret.py'),
                        '--boston-bundle', str(WORK), '--boston-output', str(OUT / 'final'),
                        '--boston-mode', 'render'], check=True)
        state.update(state='completed_awaiting_user_review',
                     video='final/video.mp4', cover='final/kapak.jpg',
                     natural_voice_seconds=proof['natural_seconds'], human_approved=False)
    except Exception as exc:
        state.update(state='stopped_without_retry', error_type=type(exc).__name__,
                     safe_reason=str(exc) if isinstance(exc, providers.Stop)
                     else 'Pipeline step failed; inspect nonsecret outputs')
        providers.save(OUT / 'status.json', state)
        raise SystemExit('097 render stopped; no retry or regeneration. ' + state['safe_reason']) from None
    providers.save(OUT / 'status.json', state)
    print('097 render complete: SAME approved Charon voice, SAME eight agent-reviewed images, '
          'one local render. No provider call, no queue/publication.', flush=True)


if __name__ == '__main__':
    main()
