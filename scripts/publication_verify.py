"""Live read-only health, then public-only, at-most-once Telegram publication cards.
No video insertion/update/delete or inference APIs exist in this module.
"""
import hashlib
import html
import json
import os
import subprocess
from pathlib import Path
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bugun_planla as planner
import uploader
from slot_guard import parse_slot
from sheets_metadata import load_table_from_drive_or_local, list_drive_videos

LEDGER = ROOT / 'publication_notifications.json'
PAYLOAD = ROOT / 'publication_notice.json'
UTC = timezone.utc
TR = timezone(timedelta(hours=3))


def now():
    return datetime.now(UTC)


def clients():
    # Fail instead of attempting an interactive OAuth browser in Actions.
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    token = ROOT / 'token.json'
    if not token.is_file():
        raise RuntimeError('Google authorization file missing')
    creds = Credentials.from_authorized_user_file(str(token))
    if not creds.valid:
        if not creds.refresh_token:
            raise RuntimeError('Google reauthorization required')
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding='utf8')
    return uploader.get_google_clients()


def telegram(method, payload):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('Telegram bot setting missing')
    request = urllib.request.Request('https://api.telegram.org/bot' + token + '/' + method,
        data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
    except Exception as exc:
        raise RuntimeError('Telegram connection failed: ' + type(exc).__name__) from None
    if not result.get('ok'):
        raise RuntimeError('Telegram request not accepted')
    return result.get('result')


def chat_id():
    value = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not value:
        raise RuntimeError('Telegram chat setting missing')
    return value


def channel(youtube):
    items = youtube.channels().list(part='id,snippet', mine=True).execute().get('items', [])
    if len(items) != 1 or items[0].get('snippet', {}).get('customUrl', '').lstrip('@').casefold() != 'bilgidozuofficial':
        raise RuntimeError('Bilgi Dozu channel identity not verified')
    return items[0]['id']


def slot_row(key):
    matches = []
    for line in (ROOT/'uploaded.txt').read_text(encoding='utf8').splitlines():
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 6 and ('SLOT='+key) in parts[5:] and parts[1].startswith('video_'):
            video_id = uploader._extract_yt_vid_id(parts[2])
            if not video_id:
                raise RuntimeError('Recorded YouTube video identifier invalid')
            matches.append({'slot':key,'filename':parts[1],'video_id':video_id,'url':parts[2],'title':parts[4]})
    if len(matches) > 1:
        raise RuntimeError('Multiple video records for one daily slot')
    return matches[0] if matches else None


def get_video(youtube, row, expected_channel):
    items = youtube.videos().list(part='snippet,status', id=row['video_id']).execute().get('items', [])
    if len(items) != 1 or items[0].get('id') != row['video_id'] or items[0].get('snippet', {}).get('channelId') != expected_channel:
        raise RuntimeError('Recorded video identity or ownership not verified')
    return items[0]


def health(test_message=False):
    youtube, drive = clients()
    channel_id = channel(youtube)
    print('LIVE_YOUTUBE_CHANNEL_OK',flush=True)
    bot = telegram('getMe', {})
    if not isinstance(bot, dict) or not bot.get('is_bot'):
        raise RuntimeError('Telegram bot identity not verified')
    telegram('getChat', {'chat_id':chat_id()})
    print('LIVE_TELEGRAM_CONNECTION_OK',flush=True)
    previous_state = planner.STATE
    try:
        planner.STATE = ROOT
        print('LIVE_QUEUE_AND_PLAN_PREFLIGHT',flush=True)
        inspected = planner.inspect()
    finally:
        planner.STATE = previous_state
    result = {'channel_id':channel_id,'telegram_connected':True,'plan':inspected}
    if inspected.get('slot') and inspected.get('should_plan') == 'false':
        row = slot_row(inspected['slot'])
        if not row:
            raise RuntimeError('Scheduled slot has no verifiable video record')
        video = get_video(youtube,row,channel_id)
        target = parse_slot(row['slot'])[0]
        status = video.get('status', {})
        if target > now():
            actual = status.get('publishAt','')
            try: actual = datetime.fromisoformat(actual.replace('Z','+00:00')).astimezone(UTC)
            except (ValueError,TypeError): actual = None
            if status.get('privacyStatus') != 'private' or actual != target:
                raise RuntimeError('Future YouTube publishAt is not verified')
        elif status.get('privacyStatus') != 'public':
            raise RuntimeError('Past publication is not public')
        result['existing_video'] = row
    elif inspected.get('should_plan') != 'true':
        raise RuntimeError('Safe future planning window not available')
    if test_message:
        sent = telegram('sendMessage', {'chat_id':chat_id(),'text':'🛠️ Bilgi Dozu: YouTube, stok ve Telegram bağlantıları doğrulandı. Bu bir bağlantı testidir; yeni video yayın bildirimi değildir.'})
        if not isinstance(sent,dict) or not sent.get('message_id'):
            raise RuntimeError('Telegram test delivery not acknowledged')
        result['test_message_id'] = sent['message_id']
    return result


def latest_due_slot(stamp=None):
    stamp = stamp or now()
    slot = stamp.astimezone(TR).replace(hour=19,minute=30,second=0,microsecond=0).astimezone(UTC)
    if slot > stamp:
        slot -= timedelta(days=1)
    return slot.strftime('%Y-%m-%dT%H:%MZ')


def load_notifications():
    if not LEDGER.exists():
        return {}
    value = json.loads(LEDGER.read_text())
    if not isinstance(value,dict):
        raise RuntimeError('Notification ledger invalid')
    return value


def make_card(row, video, records, inventory, done):
    meta = records.get(row['filename'], {})
    title = video['snippet'].get('title') or row['title']
    title = title.replace('#bilgidozu','').replace('#shorts','').strip()
    pinned = str(meta.get('pinned_comment') or '').strip()
    available = {item['name'] for item in inventory}
    short_count = sum(1 for name,rec in records.items() if name in available and name not in done and rec.get('is_ready') and not rec.get('is_long') and name != row['filename'])
    long_count = sum(1 for name,rec in records.items() if name in available and name not in done and rec.get('is_ready') and rec.get('is_long') and name != row['filename'])
    text = ('🟢 <b>BİLGİ DOZU · YENİ VİDEO YAYINDA!</b>\n━━━━━━━━━━━━━━━━━━━━\n'
        + '🎬 <b>'+html.escape(title)+'</b>\n📂 <code>'+html.escape(row['filename'])+'</code> · Shorts 📱\n'
        + f'📦 <b>Kalan Stok:</b> <code>{short_count} Shorts · {long_count} Uzun (~{short_count} Gün)</code>\n\n'
        + '🖼️ <b>Kapak:</b> YouTube görünümünü Studio’dan kontrol et.\n\n'
        + '📢 <b>YOUTUBE GÖNDERİLER METNİ (1 Kez Dokun Tamamı Kopyalanır):</b>\n'
        + '<pre>'+html.escape('🔥 '+title+'\n💬 '+pinned+'\n'+row['url'])+'</pre>')
    if len(text)>4096:
        raise RuntimeError('Publication card exceeds Telegram size limit')
    return {'chat_id':chat_id(),'text':text,'parse_mode':'HTML','disable_web_page_preview':True,
        'reply_markup':{'inline_keyboard':[[{'text':'▶️ Videoyu İzle','url':row['url']}],
            [{'text':'📢 Gönderiler (Topluluk) Sekmesini Aç','url':'https://www.youtube.com/@bilgidozuofficial/community'}]]}}


def prepare():
    key = latest_due_slot()
    if key in load_notifications():
        return {'ready':False,'reason':'already_sent_or_reserved'}
    row = slot_row(key)
    if not row:
        return {'ready':False,'reason':'no_record_for_due_slot'}
    youtube,drive = clients()
    video = get_video(youtube,row,channel(youtube))
    if video.get('status',{}).get('privacyStatus') != 'public':
        return {'ready':False,'reason':'not_public'}
    cfg = uploader.load_config()
    records = load_table_from_drive_or_local(drive,cfg['drive_queue_folder_id'])
    inventory = list_drive_videos(drive,cfg['drive_queue_folder_id'])
    payload = make_card(row,video,records,inventory,uploader.load_uploaded_ids(ROOT/'uploaded.txt'))
    content = {'row':row,'payload':payload,'prepared_at':now().isoformat()}
    PAYLOAD.write_text(json.dumps(content,ensure_ascii=False),encoding='utf8')
    return {'ready':True,'slot':key,'video_id':row['video_id']}


def reserve():
    content = json.loads(PAYLOAD.read_text());row = content['row'];key = row['slot']
    notices = load_notifications()
    if key != latest_due_slot() or key in notices:
        raise RuntimeError('Publication card already reserved or stale')
    notices[key]={'state':'pending','video_id':row['video_id'], 'run_id':os.environ.get('GITHUB_RUN_ID',''),
        'payload_sha256':hashlib.sha256(PAYLOAD.read_bytes()).hexdigest()}
    LEDGER.write_text(json.dumps(notices,ensure_ascii=False,indent=2),encoding='utf8')
    return {'reserved':True,'slot':key}


def send():
    content=json.loads(PAYLOAD.read_text());row=content['row'];notices=load_notifications();entry=notices.get(row['slot'],{})
    if entry.get('state')!='pending' or entry.get('run_id')!=os.environ.get('GITHUB_RUN_ID','') or entry.get('video_id')!=row['video_id'] or entry.get('payload_sha256')!=hashlib.sha256(PAYLOAD.read_bytes()).hexdigest():
        raise RuntimeError('Publication card reservation mismatch; not sent')
    youtube,_=clients()
    if get_video(youtube,row,channel(youtube)).get('status',{}).get('privacyStatus')!='public':
        raise RuntimeError('Video is not public; green card prohibited')
    # Durable pending reservation was pushed before this request. No retry on uncertainty.
    response=telegram('sendMessage',content['payload'])
    if not isinstance(response,dict) or not response.get('message_id'):
        raise RuntimeError('Telegram publication delivery not acknowledged')
    entry.update(state='sent',message_id=response['message_id'],sent_at=now().isoformat())
    LEDGER.write_text(json.dumps(notices,ensure_ascii=False,indent=2),encoding='utf8')
    return {'sent':True,'slot':row['slot'],'message_id':response['message_id']}


def persist_notifications():
    def git(*args, check=True):
        return subprocess.run(['git',*args],cwd=ROOT,check=check,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    git('config','user.name','github-actions[bot]')
    git('config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
    git('add','--',LEDGER.name)
    difference=git('diff','--cached','--quiet',check=False).returncode
    if difference == 0:
        return
    if difference != 1:
        raise RuntimeError('Notification ledger staging failed')
    git('commit','-m','chore: record verified Telegram publication card [skip ci]')
    git('pull','--rebase','--autostash','origin','main')
    git('push','origin','HEAD:main')


def deliver():
    result=prepare()
    if not result.get('ready'):
        return result
    reserve()
    persist_notifications()  # Must succeed BEFORE a Telegram send is possible.
    result=send()
    persist_notifications()
    return result


def main():
    mode=sys.argv[1]
    if mode=='health':result=health(os.environ.get('TEST_MESSAGE','false').lower()=='true')
    elif mode=='prepare':result=prepare()
    elif mode=='reserve':result=reserve()
    elif mode=='send':result=send()
    elif mode=='deliver':result=deliver()
    else:raise RuntimeError('Unknown verification mode')
    print('VERIFY_RESULT='+json.dumps(result,ensure_ascii=False))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as out:
            out.write('ready='+str(result.get('ready',False)).lower()+'\n')
    if mode=='health':(ROOT/'publication_health_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        # No exception text: transport errors may contain authenticated URLs.
        print('::error::Publication verification failed ('+type(exc).__name__+'). Check live authorization/queue state.')
        raise SystemExit(1) from None
