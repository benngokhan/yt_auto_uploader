from datetime import datetime,timezone
from pathlib import Path
from uploader import get_google_clients
from plan_tablo import mark_scheduled
vid='V-R79ZGpcOk'; name='video_183.mp4'; key='2026-11-22T16:30Z'; url='https://youtu.be/'+vid
rows=(Path('uploaded.txt').read_text(encoding='utf8')).splitlines()
if not any(name in row and url in row and ('SLOT='+key) in row for row in rows):
    raise SystemExit('Yayın kaydı uyuşmadı; tablo değiştirilmedi')
yt,drive=get_google_clients()
videos=yt.videos().list(part='status',id=vid).execute().get('items',[])
status=videos[0].get('status',{}) if len(videos)==1 else {}
try: scheduled=datetime.fromisoformat(status.get('publishAt','').replace('Z','+00:00')).astimezone(timezone.utc)
except ValueError: raise SystemExit('Plan saati okunamadı; tablo değiştirilmedi') from None
if status.get('privacyStatus')!='private' or scheduled!=datetime(2026,11,22,16,30,tzinfo=timezone.utc):
    raise SystemExit('YouTube planı uyuşmadı; tablo değiştirilmedi')
mark_scheduled(drive,name,url,scheduled)
