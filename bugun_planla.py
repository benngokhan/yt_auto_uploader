"""One-slot YouTube scheduling. Claim first; never release after uncertainty."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json, os, sys, tempfile
from slot_guard import slot_claimed, slot_completed
from uploader import (get_google_clients, load_config, load_uploaded_ids,
                      download_drive_file, upload_to_youtube, mark_as_uploaded,
                      upload_thumbnail_if_exists, sanitize_public_description, _extract_yt_vid_id)
from sheets_metadata import get_next_scheduled_video
from youtube_guvenlik import yayin_guvenlik_kontrolu

STATE = Path(os.getenv('SCHEDULE_STATE_DIR', 'state'))
UTC = timezone.utc
TR = timezone(timedelta(hours=3))


def utcnow():
    return datetime.now(UTC)


def slot_for_today(now=None):
    """Next daily 19:30 TR slot, today or tomorrow; never backfill a past day."""
    now = now or utcnow()
    if now.tzinfo is None:
        raise ValueError('Zaman dilimi zorunlu')
    now = now.astimezone(UTC)
    slot = now.astimezone(TR).replace(hour=19, minute=30, second=0, microsecond=0).astimezone(UTC)
    if slot <= now:
        slot += timedelta(days=1)
    if slot - now < timedelta(minutes=20):
        raise RuntimeError('Yayın saatine 20 dakikadan az kaldı; güvenli ön planlama bekletildi')
    return slot


def ensure_future_target(slot, minimum_minutes=5):
    lead = slot - utcnow()
    if not timedelta(minutes=minimum_minutes) <= lead <= timedelta(hours=24):
        raise RuntimeError('Hedef saat güvenli gelecek aralığında değil; yükleme yapılmadı')


def key_for(slot):
    return slot.strftime('%Y-%m-%dT%H:%MZ')


def previous_publication_verified(youtube, current_slot):
    from slot_guard import parse_slot
    ledger=STATE/'uploaded.txt'
    if not ledger.exists():
        raise RuntimeError('Önceki yayın kayıtları bulunamadı')
    rows=[line for line in ledger.read_text(encoding='utf8').splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if not rows: raise RuntimeError('Önceki yayın kaydı boş')
    parts=[part.strip() for part in rows[-1].split('|')]
    if len(parts)<6: raise RuntimeError('Önceki yayın ve slotu doğrulanamadı')
    tags=[part[5:] for part in parts[5:] if part.startswith('SLOT=')]
    if len(tags)!=1: raise RuntimeError('Önceki yayın slotu belirsiz')
    previous,_=parse_slot(tags[0])
    if previous >= current_slot: raise RuntimeError('Önceki kayıt hedef slotta veya daha sonrada')
    vid=_extract_yt_vid_id(parts[2])
    if not vid: raise RuntimeError('Önceki YouTube bağlantısı okunamadı')
    found=youtube.videos().list(part='status',id=vid).execute().get('items',[])
    if len(found)!=1 or found[0].get('status',{}).get('privacyStatus')!='public':
        raise RuntimeError('Önceki video yayında doğrulanamadı; sıra korunuyor')


def inspect():
    try:
        slot = slot_for_today()
    except RuntimeError as exc:
        return {'should_plan':'false', 'reason':str(exc)}
    key = key_for(slot)
    if slot_completed(STATE / 'uploaded.txt', key):
        return {'should_plan':'false', 'slot':key, 'reason':'Bu saatin yükleme kaydı var; tekrar yüklenmez'}
    if slot_claimed(STATE / 'slot_claims.txt', key):
        raise RuntimeError('Saat ayrılmış ancak yükleme sonucu belirsiz; otomatik tekrar yasak')
    youtube, drive = get_google_clients(); config=load_config()
    previous_publication_verified(youtube, slot)
    candidate=get_next_scheduled_video(drive, config['drive_queue_folder_id'],
        skip_ids=load_uploaded_ids(STATE/'uploaded.txt'), video_type='short')
    if not candidate: raise RuntimeError('Sıradaki video hazır değil')
    yayin_guvenlik_kontrolu(youtube, candidate['title'], slot_key=key)
    return {'should_plan':'true','slot':key,'name':candidate['name'],'id':candidate['id']}


def reserve(key):
    from slot_guard import reserve_slot
    if key != key_for(slot_for_today()): raise RuntimeError('Hedef saat doğrulanamadı')
    if not reserve_slot(STATE/'slot_claims.txt',STATE/'uploaded.txt',key):
        raise RuntimeError('Bu saat zaten ayrılmış')


def upload(key, expected_name, expected_id):
    slot = slot_for_today()
    if key != key_for(slot): raise RuntimeError('Hedef saat doğrulanamadı')
    ensure_future_target(slot, minimum_minutes=20)
    if not slot_claimed(STATE/'slot_claims.txt',key) or slot_completed(STATE/'uploaded.txt',key):
        raise RuntimeError('Saat ayrılmamış veya zaten kaydedilmiş')
    youtube, drive=get_google_clients(); config=load_config()
    previous_publication_verified(youtube, slot)
    candidate=get_next_scheduled_video(drive,config['drive_queue_folder_id'],
        skip_ids=load_uploaded_ids(STATE/'uploaded.txt'),video_type='short')
    if not candidate or candidate['name']!=expected_name or candidate['id']!=expected_id:
        raise RuntimeError('Video sırası değişti; işlem durduruldu')
    yayin_guvenlik_kontrolu(youtube,candidate['title'],slot_key=key)
    meta={'title':candidate['title'],'description':sanitize_public_description(candidate['description']),
          'tags':candidate['tags'],'categoryId':candidate['categoryId'],
          'privacyStatus':'private','publishAt':slot.isoformat(timespec='seconds')}
    with tempfile.TemporaryDirectory(prefix='plan-video-') as temp:
        path=Path(temp)/candidate['name'];download_drive_file(drive,candidate['id'],path)
        ensure_future_target(slot)
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
        if status.get('privacyStatus')!='private' or actual!=slot:
            raise RuntimeError('Video yüklemesi kaydedildi, fakat YouTube planı doğrulanamadı')
        result['status']='PLANLANDI'
        Path('plan_result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
        try:
            from plan_tablo import mark_scheduled
            mark_scheduled(drive, candidate['name'], url, slot)
            result['sheet_ok']=True
        except Exception as exc:
            print('Tablo güncellenemedi:', type(exc).__name__)
            result['sheet_ok']=False
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
