"""One-slot YouTube scheduling. Claim first; never release after uncertainty."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json, os, sys, tempfile
from slot_guard import slot_claimed, slot_completed
from uploader import (get_google_clients, load_config, load_uploaded_ids,
                      download_drive_file, upload_to_youtube, mark_as_uploaded,
                      upload_thumbnail_if_exists, sanitize_public_description)
from sheets_metadata import get_next_scheduled_video
from youtube_guvenlik import yayin_guvenlik_kontrolu

STATE = Path(os.getenv('SCHEDULE_STATE_DIR', 'state'))
UTC = timezone.utc
TR = timezone(timedelta(hours=3))


def slot_for_today(now=None):
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError('Zaman dilimi zorunlu')
    slot = now.astimezone(TR).replace(hour=19, minute=30, second=0, microsecond=0).astimezone(UTC)
    if not timedelta(minutes=20) <= slot - now.astimezone(UTC) <= timedelta(hours=8):
        raise RuntimeError('Güvenli planlama zaman aralığı dışında')
    return slot


def key_for(slot):
    return slot.strftime('%Y-%m-%dT%H:%MZ')


def inspect():
    slot = slot_for_today(); key = key_for(slot)
    if slot_claimed(STATE / 'slot_claims.txt', key) or slot_completed(STATE / 'uploaded.txt', key):
        raise RuntimeError('Bu yayın saati daha önce ayrılmış veya kaydedilmiş')
    youtube, drive = get_google_clients(); config=load_config()
    candidate=get_next_scheduled_video(drive, config['drive_queue_folder_id'],
        skip_ids=load_uploaded_ids(STATE/'uploaded.txt'), video_type='short')
    if not candidate: raise RuntimeError('Sıradaki video hazır değil')
    yayin_guvenlik_kontrolu(youtube, candidate['title'], slot_key=key)
    return {'slot':key,'name':candidate['name'],'id':candidate['id']}


def reserve(key):
    from slot_guard import reserve_slot
    if key != key_for(slot_for_today()): raise RuntimeError('Hedef saat doğrulanamadı')
    if not reserve_slot(STATE/'slot_claims.txt',STATE/'uploaded.txt',key):
        raise RuntimeError('Bu saat zaten ayrılmış')


def upload(key, expected_name, expected_id):
    if key != key_for(slot_for_today()): raise RuntimeError('Hedef saat doğrulanamadı')
    if not slot_claimed(STATE/'slot_claims.txt',key) or slot_completed(STATE/'uploaded.txt',key):
        raise RuntimeError('Saat ayrılmamış veya zaten kaydedilmiş')
    youtube, drive=get_google_clients(); config=load_config()
    candidate=get_next_scheduled_video(drive,config['drive_queue_folder_id'],
        skip_ids=load_uploaded_ids(STATE/'uploaded.txt'),video_type='short')
    if not candidate or candidate['name']!=expected_name or candidate['id']!=expected_id:
        raise RuntimeError('Video sırası değişti; işlem durduruldu')
    yayin_guvenlik_kontrolu(youtube,candidate['title'],slot_key=key)
    meta={'title':candidate['title'],'description':sanitize_public_description(candidate['description']),
          'tags':candidate['tags'],'categoryId':candidate['categoryId'],
          'privacyStatus':'private','publishAt':slot_for_today().isoformat(timespec='seconds')}
    with tempfile.TemporaryDirectory(prefix='plan-video-') as temp:
        path=Path(temp)/candidate['name'];download_drive_file(drive,candidate['id'],path)
        response=upload_to_youtube(youtube,path,meta)
        video_id=response['id'];url='https://youtu.be/'+video_id
        # Save the irreversible upload before querying or attempting optional work.
        mark_as_uploaded(STATE/'uploaded.txt',candidate['id'],candidate['name'],url,
                         title=candidate['title'],slot_key=key)
        result={'slot':key,'filename':candidate['name'],'video_id':video_id,'url':url,
                'status':'DOGRULANMADI','cover_ok':False}
        Path('plan_result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
        videos=youtube.videos().list(part='status',id=video_id).execute().get('items',[])
        status=videos[0].get('status',{}) if len(videos)==1 else {}
        published=status.get('publishAt','')
        try: actual=datetime.fromisoformat(published.replace('Z','+00:00')).astimezone(UTC)
        except (ValueError,TypeError): actual=None
        if status.get('privacyStatus')!='private' or actual!=slot_for_today():
            raise RuntimeError('Video yüklemesi kaydedildi, fakat YouTube planı doğrulanamadı')
        result['status']='PLANLANDI'
        Path('plan_result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
        cover=upload_thumbnail_if_exists(youtube,drive,config['drive_queue_folder_id'],candidate['name'],video_id,
                                         video_path=path,video_title=candidate['title'])
        result['cover_ok']=bool(cover.api_accepted)
        Path('plan_result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
        return result


def main():
    if sys.argv[1]=='inspect':
        info=inspect(); print(json.dumps(info,ensure_ascii=False))
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf8') as f:
            for k,v in info.items(): f.write(f'{k}={v}\n')
    elif sys.argv[1]=='reserve': reserve(os.environ['SLOT'])
    elif sys.argv[1]=='upload': print(json.dumps(upload(os.environ['SLOT'],os.environ['FILE'],os.environ['FILE_ID']),ensure_ascii=False))
    else: raise SystemExit('Bilinmeyen işlem')

if __name__=='__main__':main()
