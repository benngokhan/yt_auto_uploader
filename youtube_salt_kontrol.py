"""Salt okunur YouTube ve sıra kontrolü. Video yüklemez, değiştirmez."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uploader import get_google_clients, load_config, load_uploaded_ids
from sheets_metadata import get_next_scheduled_video, sanitize_title
import json

now = datetime.now(timezone.utc)
youtube, drive = get_google_clients()
channels = youtube.channels().list(part='id,snippet', mine=True).execute().get('items', [])
if len(channels) != 1:
    raise SystemExit('Kanal tekil olarak doğrulanamadı')
channel_id = channels[0]['id']
config = load_config()
candidate = get_next_scheduled_video(drive, config['drive_queue_folder_id'], skip_ids=load_uploaded_ids(Path('uploaded.txt')), video_type='short')
print('SIRADAKI_VIDEO:', candidate['name'] if candidate else 'YOK')
expected_title = sanitize_title(candidate['title']).strip().casefold() if candidate else ''
ids = []
page = None
for number in range(10):
    result = youtube.search().list(part='id', forMine=True, type='video', maxResults=50, pageToken=page, order='date').execute()
    ids.extend(x['id']['videoId'] for x in result.get('items', []) if x.get('id', {}).get('videoId'))
    page = result.get('nextPageToken')
    if not page:
        break
ids = list(dict.fromkeys(ids))
print('KANAL_VIDEO_TARAMASI:', len(ids), 'TAM' if not page else 'EKSIK')
all_items = []
for i in range(0, len(ids), 50):
    data = youtube.videos().list(part='snippet,status', id=','.join(ids[i:i+50])).execute()
    all_items.extend(data.get('items', []))
if len(all_items) != len(ids):
    raise SystemExit('Kanal videolarının tamamı okunamadı')
matching, upcoming = [], []
for item in all_items:
    if item.get('snippet', {}).get('channelId') != channel_id:
        raise SystemExit('Beklenmeyen kanal sonucu')
    if expected_title and sanitize_title(item.get('snippet', {}).get('title', '')).strip().casefold() == expected_title:
        matching.append(item)
    status = item.get('status', {})
    value = status.get('publishAt')
    if value:
        when = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
        if when > now:
            upcoming.append(when)
print('SIRADAKI_BASLIK_KANALDA:', len(matching))
print('GELECEK_PLANLI_VIDEO:', len(upcoming))
local = timezone(timedelta(hours=3))
for when in sorted(upcoming):
    print('PLANLI_SAAT_TR:', when.astimezone(local).strftime('%Y-%m-%d %H:%M'))
old = json.loads(Path('scheduled_5day_plan.json').read_text())
old_ids = [x.get('youtube_video_id') for x in old.get('items', []) if x.get('youtube_video_id')]
if old_ids:
    found = youtube.videos().list(part='status', id=','.join(old_ids)).execute().get('items', [])
    print('BES_VIDEO_KAYDI:', len(old_ids), 'YOUTUBEDA_GORULEN:', len(found), 'PUBLIC:', sum(x.get('status',{}).get('privacyStatus')=='public' for x in found))
if page:
    raise SystemExit('Kanal taraması eksik; güvenli çakışma denetimi tamamlanmadı')
