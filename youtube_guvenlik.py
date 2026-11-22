"""Yayınlamadan önce kanaldaki planları ve mükerrer başlıkları salt okunur denetle."""
from datetime import datetime, timedelta, timezone

from sheets_metadata import sanitize_title
from slot_guard import parse_slot


def _title_key(title):
    return sanitize_title(title).strip().replace('I', 'ı').replace('İ', 'i').casefold()


def yayin_guvenlik_kontrolu(youtube, title, slot_key='', max_pages=10):
    """Belirsizlikte dur: eksik tarama, aynı başlık veya aynı gün plan varsa yükleme yok."""
    expected = _title_key(title)
    if not expected:
        raise RuntimeError('Başlık boş; YouTube çakışma kontrolü yapılamadı')
    local = timezone(timedelta(hours=3))
    target_day = parse_slot(slot_key)[0].astimezone(local).date() if slot_key else None
    channel_items = youtube.channels().list(part='id', mine=True).execute().get('items', [])
    if len(channel_items) != 1 or not channel_items[0].get('id'):
        raise RuntimeError('YouTube kanalı tekil olarak doğrulanamadı')
    channel_id = channel_items[0]['id']
    ids, page = [], None
    for _ in range(max_pages):
        result = youtube.search().list(part='id', forMine=True, type='video', maxResults=50, order='date', pageToken=page).execute()
        for item in result.get('items', []):
            video_id = item.get('id', {}).get('videoId')
            if not video_id:
                raise RuntimeError('YouTube araması eksik sonuç döndürdü')
            ids.append(video_id)
        page = result.get('nextPageToken')
        if not page:
            break
    if page:
        raise RuntimeError('YouTube kanal taraması tamamlanamadı; yayın güvenle durduruldu')
    ids = list(dict.fromkeys(ids))
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        items = youtube.videos().list(part='snippet,status', id=','.join(batch)).execute().get('items', [])
        if {x.get('id') for x in items} != set(batch):
            raise RuntimeError('YouTube video durumu eksik; yayın güvenle durduruldu')
        for item in items:
            snippet, status = item.get('snippet', {}), item.get('status', {})
            if snippet.get('channelId') != channel_id:
                raise RuntimeError('YouTube kanal kontrolünde uyuşmazlık')
            if _title_key(snippet.get('title', '')) == expected:
                raise RuntimeError('Bu başlık kanalda zaten var; tekrar yükleme durduruldu')
            when = status.get('publishAt')
            if when and target_day:
                try:
                    date = datetime.fromisoformat(when.replace('Z', '+00:00'))
                    if date.tzinfo is None:
                        raise ValueError('timezone missing')
                except (ValueError, TypeError):
                    raise RuntimeError('Planlı video saati okunamadı; yayın durduruldu') from None
                if date.astimezone(local).date() == target_day:
                    raise RuntimeError('Bu gün için YouTube’da planlı video var; çakışma önlendi')
    print('YouTube kanal ve planlı video çakışma kontrolü başarılı.')
