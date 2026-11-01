#!/usr/bin/env python3
"""Bilgi Dozu: özel YouTube Analytics retansiyon raporu.

Yayın yapmaz, mevcut stok tablosuna ve git'e yazmaz. Analytics yetkisi salt-okunur,
çıktı yalnız önceden oluşturulmuş ve erişimi her seferinde denetlenen Drive dosyasına
kaydedilir. Manuel test modunda Drive dosyası da değiştirilmez.
"""
from __future__ import annotations
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from openpyxl import Workbook
from openpyxl.chart import ScatterChart, Series, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

CHANNEL_ID = 'UC3bjZMPZ5FW2JQGfU41iaUg'
REPOSITORY = 'benngokhan/yt_auto_uploader'
FOLDER_ID = '1LyZBIc52OzaGZBaq8yXODcseZ0wilsrs'
PARENT_ID = '190zQiUYkp8fsQFleva77TKqc9MeGxZiI'
REPORT_ID = '1-04hX_5htkheIkCe-W-56bu4zBkfXOvT'
EXPECTED_PERMISSIONS = {'06006357664194807857': 'owner', '16570037873922638546': 'writer'}
XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
ANALYTICS_URL = 'https://youtubeanalytics.googleapis.com/v2/reports'
ALLOWED_HOSTS = {'oauth2.googleapis.com', 'www.googleapis.com', 'youtubeanalytics.googleapis.com', 'api.github.com'}
VIDEO_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')
CURVE_LIMIT = 10
REPORT_DAYS = 30


class SafeError(Exception):
    """User-safe fixed message; never include tokens, server body or private data."""


class HttpError(SafeError):
    def __init__(self, status: int, label: str):
        self.status = int(status)
        super().__init__(f'{label} HTTP {status}')


def request_json(url, *, bearer=None, form=None, body=None, method=None, content_type=None, label='API'):
    """Bounded JSON HTTPS request. Exceptions intentionally exclude response bodies."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise SafeError('API adresi guvenli degil')
    headers = {'User-Agent': 'BilgiDozu-PrivateRetention/1.0', 'Accept': 'application/json'}
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    if form is not None:
        body = urllib.parse.urlencode(form).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    elif content_type:
        headers['Content-Type'] = content_type
    for attempt in range(3):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                raw = response.read(12 * 1024 * 1024 + 1)
                if len(raw) > 12 * 1024 * 1024:
                    raise SafeError(label + ' yaniti cok buyuk')
                try:
                    result = json.loads(raw.decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    raise SafeError(label + ' yaniti okunamadi') from None
                if not isinstance(result, dict):
                    raise SafeError(label + ' yanit bicimi beklenmiyor')
                return result
        except urllib.error.HTTPError as exc:
            if exc.code in {408, 429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise HttpError(exc.code, label) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise SafeError(label + ' baglanti hatasi') from None
    raise SafeError(label + ' baglanti hatasi')


def oauth_config(raw, refresh=None):
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        cfg = data.get('web') or data.get('installed') or data
        if not isinstance(cfg, dict):
            raise ValueError
        fields = {'client_id': cfg.get('client_id'), 'client_secret': cfg.get('client_secret'),
                  'refresh_token': refresh if refresh is not None else cfg.get('refresh_token'),
                  'grant_type': 'refresh_token'}
        if not all(isinstance(x, str) and x.strip() for x in fields.values()):
            raise ValueError
        return fields
    except (ValueError, TypeError):
        raise SafeError('Google OAuth ayarlari eksik') from None


def refresh_token(config):
    response = request_json('https://oauth2.googleapis.com/token', form=config, method='POST', label='Google OAuth')
    value = response.get('access_token')
    if not isinstance(value, str) or not value:
        raise SafeError('Google OAuth erisim yaniti eksik')
    return value


def verify_private_repository(token):
    if not token:
        raise SafeError('GitHub calisma yetkisi eksik')
    data = request_json('https://api.github.com/repos/' + REPOSITORY, bearer=token, label='GitHub')
    if data.get('full_name', '').lower() != REPOSITORY.lower() or data.get('private') is not True:
        raise SafeError('Depo gizli degil: rapor durduruldu')


def validate_acl(response):
    if response.get('nextPageToken'):
        raise SafeError('Drive izin listesi tamamlanamadi')
    permissions = response.get('permissions')
    if not isinstance(permissions, list):
        raise SafeError('Drive izin listesi okunamadi')
    present = {}
    for item in permissions:
        if not isinstance(item, dict) or item.get('deleted') or item.get('type') != 'user':
            raise SafeError('Drive hedefinde beklenmeyen izin var')
        pid, role = str(item.get('id') or ''), str(item.get('role') or '')
        if not pid or pid in present:
            raise SafeError('Drive izin listesi belirsiz')
        present[pid] = role
    if present != EXPECTED_PERMISSIONS:
        raise SafeError('Drive hedefinin ozel izinleri degismis')


def verify_private_destination(drive_token):
    base = 'https://www.googleapis.com/drive/v3/files/'
    fields = 'id,mimeType,parents,trashed,capabilities(canAddChildren,canEdit)'
    for file_id, expected_parent, mime, capability in [
        (FOLDER_ID, PARENT_ID, 'application/vnd.google-apps.folder', 'canAddChildren'),
        (REPORT_ID, FOLDER_ID, XLSX_MIME, 'canEdit'),
    ]:
        meta = request_json(base + file_id + '?' + urllib.parse.urlencode({'fields': fields}),
                            bearer=drive_token, label='Drive hedefi')
        kind = 'klasor' if file_id == FOLDER_ID else 'rapor'
        if meta.get('id') != file_id or meta.get('mimeType') != mime or meta.get('trashed') is True:
            raise SafeError('Drive ' + kind + ' kimlik/bicim dogrulanamadi')
        parents = meta.get('parents')
        # The writer has access to this folder, but not to its private parent;
        # Drive can omit the parent's ID. Both effective ACLs are checked below.
        hidden_parent = file_id == FOLDER_ID and not parents
        if not hidden_parent and parents != [expected_parent]:
            raise SafeError('Drive ' + kind + ' ust klasoru dogrulanamadi')
        if (meta.get('capabilities') or {}).get(capability) is not True:
            raise SafeError('Drive ' + kind + ' yazma yetkisi dogrulanamadi')
        params = {'fields': 'nextPageToken,permissions(id,type,role,deleted)', 'pageSize': '100'}
        acl = request_json(base + file_id + '/permissions?' + urllib.parse.urlencode(params),
                           bearer=drive_token, label='Drive izinleri')
        validate_acl(acl)


def assert_channel(analytics_token):
    params = {'part': 'id', 'mine': 'true', 'fields': 'items(id)'}
    data = request_json('https://www.googleapis.com/youtube/v3/channels?' + urllib.parse.urlencode(params),
                        bearer=analytics_token, label='Kanal')
    if CHANNEL_ID not in [item.get('id') for item in data.get('items', []) if isinstance(item, dict)]:
        raise SafeError('Google izni beklenen YouTube kanalina ait degil')


def query_report(analytics_token, start, end, *, video_id=None):
    query = {'ids': 'channel==' + CHANNEL_ID, 'startDate': start.isoformat(), 'endDate': end.isoformat()}
    if video_id is None:
        query.update({'dimensions': 'video', 'metrics': 'views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage',
                      'sort': '-views', 'maxResults': '200'})
    else:
        if not VIDEO_ID_RE.fullmatch(video_id):
            raise SafeError('Video kimligi gecersiz')
        query.update({'dimensions': 'elapsedVideoTimeRatio', 'metrics': 'audienceWatchRatio', 'filters': 'video==' + video_id})
    return request_json(ANALYTICS_URL + '?' + urllib.parse.urlencode(query), bearer=analytics_token, label='Analytics')


def _table(report, required):
    headers = report.get('columnHeaders') or []
    names = [entry.get('name') if isinstance(entry, dict) else None for entry in headers]
    if len(names) != len(set(names)) or not set(required).issubset(names):
        raise SafeError('Analytics yanit sutunlari eksik')
    rows = report.get('rows') or []
    if not isinstance(rows, list):
        raise SafeError('Analytics satirlari okunamadi')
    mapped = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(names):
            raise SafeError('Analytics satir bicimi hatali')
        mapped.append(dict(zip(names, row)))
    return mapped


def finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (ValueError, TypeError):
        return None
    return x if math.isfinite(x) else None


def parse_video_report(report):
    required = ['video', 'views', 'estimatedMinutesWatched', 'averageViewDuration', 'averageViewPercentage']
    rows = _table(report, required)
    output, seen = [], set()
    for row in rows:
        video_id = str(row.get('video') or '')
        if not VIDEO_ID_RE.fullmatch(video_id) or video_id in seen:
            raise SafeError('Analytics video satirlari belirsiz')
        seen.add(video_id)
        numbers = {key: finite_number(row.get(key)) for key in required[1:]}
        if any(v is None or v < 0 for v in numbers.values()):
            raise SafeError('Analytics metrikleri beklenmedik')
        output.append({'video_id': video_id, 'views': int(numbers['views']),
                       'watch_minutes': numbers['estimatedMinutesWatched'],
                       'average_seconds': numbers['averageViewDuration'],
                       'average_percent': numbers['averageViewPercentage']})
    if not output:
        raise SafeError('Analytics raporunda video verisi yok')
    return output


def parse_curve_report(report):
    # A valid empty report is common for recently published/low-data videos.
    rows = report.get('rows') or []
    if not rows:
        return []
    mapped = _table(report, ['elapsedVideoTimeRatio', 'audienceWatchRatio'])
    points = []
    for row in mapped:
        t = finite_number(row.get('elapsedVideoTimeRatio'))
        ratio = finite_number(row.get('audienceWatchRatio'))
        if t is None or ratio is None or not (0 < t <= 1) or ratio < 0:
            raise SafeError('Analytics egri degeri beklenmedik')
        points.append((t, ratio))
    points.sort()
    if len({x[0] for x in points}) != len(points):
        raise SafeError('Analytics egri noktalari tekrarlaniyor')
    return points


def parse_duration(value):
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?', value)
    if not m or not any(m.groups()):
        return None
    days, hours, minutes, seconds = m.groups()
    seconds = int(days or 0) * 86400 + int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)
    return seconds if seconds > 0 else None


def video_details(analytics_token, ids):
    result = {}
    for start in range(0, len(ids), 50):
        subset = ids[start:start + 50]
        params = {'part': 'snippet,contentDetails', 'id': ','.join(subset),
                  'fields': 'items(id,snippet(title,publishedAt,channelId),contentDetails(duration))'}
        data = request_json('https://www.googleapis.com/youtube/v3/videos?' + urllib.parse.urlencode(params),
                            bearer=analytics_token, label='YouTube video')
        for item in data.get('items', []):
            vid = item.get('id')
            snippet = item.get('snippet') or {}
            if vid not in subset or snippet.get('channelId') != CHANNEL_ID or vid in result:
                raise SafeError('YouTube video kaydi kanal ile uyusmuyor')
            title = snippet.get('title')
            published = snippet.get('publishedAt')
            result[vid] = {'title': str(title or 'Başlık alınamadı'),
                           'published': str(published or ''),
                           'duration': parse_duration((item.get('contentDetails') or {}).get('duration'))}
    return result


def acquire_curves(analytics_token, rows, details, start, end):
    available = [x for x in rows if details.get(x['video_id'], {}).get('published') and details[x['video_id']].get('duration')]
    available.sort(key=lambda x: details[x['video_id']]['published'], reverse=True)
    curves = {}
    for row in available[:CURVE_LIMIT]:
        vid = row['video_id']
        try:
            curves[vid] = parse_curve_report(query_report(analytics_token, start, end, video_id=vid))
        except HttpError as exc:
            # A missing individual report does not turn other data into fake zeros.
            if exc.status in {400, 404}:
                curves[vid] = []
            else:
                raise
    return curves


def closest_retention(points, duration, target_seconds=3):
    if not points or not duration or duration < target_seconds:
        return None
    elapsed, ratio = min(points, key=lambda p: abs(p[0] * duration - target_seconds))
    return (round(elapsed * duration, 2), round(ratio * 100, 2))


def text_cell(cell, value):
    cell.value = str(value or '')
    cell.data_type = 's'  # titles such as '=...' remain text, not Excel formulas


def report_xlsx(rows, details, curves, start, end, now):
    wb = Workbook()
    summary = wb.active; summary.title = 'Rapor Bilgisi'
    metrics = wb.create_sheet('Video Metrikleri')
    curve_sheet = wb.create_sheet('Eğri Verileri')
    charts = wb.create_sheet('Grafikler')
    navy = '172A43'; teal = '087D78'; pale = 'E8F5F2'; dark = '24364F'
    summary.column_dimensions['A'].width = 31; summary.column_dimensions['B'].width = 100
    summary.append(['BİLGİ DOZU | ÖZEL RETANSİYON RAPORU'])
    summary['A1'].font = Font(size=17, bold=True, color='FFFFFF')
    summary['A1'].fill = PatternFill('solid', fgColor=navy); summary.merge_cells('A1:B1'); summary.row_dimensions[1].height = 30
    ready = sum(bool(v) for v in curves.values())
    info = [
        ('Dönem', f'{start.isoformat()} — {end.isoformat()}'),
        ('Hazırlanma (Türkiye)', now.astimezone(timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M')),
        ('Video sayısı', len(rows)),
        ('Eğri verisi olan video', ready),
        ('Eğri kapsamı', f'Son yayınlanan en fazla {CURVE_LIMIT} video; veri varsa.'),
        ('Ortalama izlenen %', 'Videonun ortalama izlenme yüzdesidir; 3. saniye tutma oranı değildir.'),
        ('3. saniye oranı', 'En yakın zaman noktasındaki audienceWatchRatio × 100; yaklaşık değerdir.'),
        ('Tekrar izleme', 'Eğri oranı tekrar izlemeler nedeniyle %100 üstüne çıkabilir; kaydırma/terk oranı değildir.'),
        ('Eksik bilgi', 'Boş hücre sıfır demek değildir. YouTube verileri 1–2 gün gecikebilir.'),
        ('Gizlilik', 'Bu rapor yalnız özel Drive dosyasında tutulur; mevcut yayın tablosuna yazılmaz.'),
    ]
    for key, value in info:
        summary.append([key, value]); summary.cell(summary.max_row,1).font = Font(bold=True,color=teal)
        summary.cell(summary.max_row,2).alignment = Alignment(wrap_text=True,vertical='top')
        summary.row_dimensions[summary.max_row].height = 34 if len(str(value)) > 65 else 22
    summary.freeze_panes = 'B2'

    headers = ['Video', 'Yayın tarihi (UTC)', 'Süre (sn)', 'Görüntülenme', 'Ort. izlenme (sn)',
               'Ort. izlenen (%)', 'İzlenme süresi (dk)', '3. sn yaklaşık oran (%)',
               'Eğri durumu', 'YouTube bağlantısı']
    metrics.append(headers)
    for i, width in enumerate([54,23,13,18,21,23,23,29,20,47], 1):
        metrics.column_dimensions[get_column_letter(i)].width = width
    for item in rows:
        vid=item['video_id']; det=details.get(vid,{})
        point=closest_retention(curves.get(vid,[]),det.get('duration'))
        status='Hazır' if curves.get(vid) else ('Veri yok' if vid in curves else 'İncelenmedi')
        metrics.append(['', det.get('published','')[:10], det.get('duration'), item['views'],
                        round(item['average_seconds'],2), round(item['average_percent'],2),
                        round(item['watch_minutes'],2), point[1] if point else None, status,
                        'https://youtu.be/' + vid])
        rowno=metrics.max_row; text_cell(metrics.cell(rowno,1),det.get('title','Başlık alınamadı'))
        metrics.cell(rowno,10).hyperlink='https://youtu.be/'+vid
        metrics.cell(rowno,10).font=Font(color='205AB8',underline='single')
    metrics.auto_filter.ref=metrics.dimensions; metrics.freeze_panes='B2'

    curve_sheet.append(['Video', 'Video ID', 'Geçen süre oranı', 'Saniye (yaklaşık)', 'İzlenme oranı (%)'])
    for i,width in enumerate([50,19,22,24,25],1): curve_sheet.column_dimensions[get_column_letter(i)].width=width
    chart_index=0
    for vid, points in curves.items():
        if not points: continue
        det=details[vid]; duration=det['duration']; first=curve_sheet.max_row+1
        for elapsed, ratio in points:
            curve_sheet.append(['',vid,round(elapsed,4),round(elapsed*duration,2),round(ratio*100,2)])
            text_cell(curve_sheet.cell(curve_sheet.max_row,1),det.get('title',''))
        last=curve_sheet.max_row
        chart=ScatterChart();chart.title=str(det.get('title') or vid)[:65]
        chart.x_axis.title='Video süresi (sn)';chart.y_axis.title='İzlenme oranı (%)'
        chart.style=13;chart.width=17;chart.height=9
        x=Reference(curve_sheet,min_col=4,min_row=first,max_row=last)
        y=Reference(curve_sheet,min_col=5,min_row=first,max_row=last)
        series=Series(y,x,title='İzlenme oranı');series.graphicalProperties.line.solidFill=teal;chart.series.append(series)
        charts.add_chart(chart,('A' if chart_index % 2 == 0 else 'J')+str(1+(chart_index//2)*19))
        chart_index+=1
    curve_sheet.freeze_panes='C2';curve_sheet.auto_filter.ref=curve_sheet.dimensions
    if chart_index==0:
        charts['A1']='İncelenen videolarda henüz eğri verisi yok.'
    for sheet in (metrics,curve_sheet):
        sheet.row_dimensions[1].height=32
        for cell in sheet[1]:
            cell.fill=PatternFill('solid',fgColor=navy);cell.font=Font(bold=True,color='FFFFFF')
            cell.alignment=Alignment(vertical='center',wrap_text=True)
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment=Alignment(vertical='center')
    stream=io.BytesIO();wb.save(stream);wb.close();return stream.getvalue()


def upload_report(drive_token, data):
    # Re-check both ACLs just before writing. Update only the fixed owner-created file.
    verify_private_destination(drive_token)
    url='https://www.googleapis.com/upload/drive/v3/files/'+REPORT_ID+'?'+urllib.parse.urlencode({'uploadType':'media','fields':'id,md5Checksum'})
    response=request_json(url,bearer=drive_token,body=data,method='PATCH',content_type=XLSX_MIME,label='Drive raporu')
    digest=hashlib.md5(data).hexdigest()
    if response.get('id') != REPORT_ID or response.get('md5Checksum') != digest:
        raise SafeError('Drive rapor dogrulamasi basarisiz')
    meta=request_json('https://www.googleapis.com/drive/v3/files/'+REPORT_ID+'?fields=id,md5Checksum',bearer=drive_token,label='Drive rapor dogrulama')
    if meta.get('id') != REPORT_ID or meta.get('md5Checksum') != digest:
        raise SafeError('Drive raporu kayittan sonra dogrulanamadi')
    verify_private_destination(drive_token)


def main():
    mode=os.environ.get('RETENTION_MODE','test').strip().lower()
    if mode not in {'test','save'}:
        raise SafeError('Bilinmeyen calisma modu')
    verify_private_repository(os.environ.get('GH_READ_TOKEN',''))
    bd_cfg=oauth_config(os.environ.get('BD_ANALYTICS_CLIENT_CONFIG',''),os.environ.get('BD_ANALYTICS_REFRESH_TOKEN',''))
    drive_cfg=oauth_config(os.environ.get('GOOGLE_TOKEN_JSON',''))
    bd=refresh_token(bd_cfg);drive=refresh_token(drive_cfg)
    assert_channel(bd);verify_private_destination(drive)
    now=datetime.now(timezone.utc);end=now.date()-timedelta(days=1);start=end-timedelta(days=REPORT_DAYS-1)
    rows=parse_video_report(query_report(bd,start,end));details=video_details(bd,[r['video_id'] for r in rows])
    curves=acquire_curves(bd,rows,details,start,end)
    data=report_xlsx(rows,details,curves,start,end,now)
    if mode=='save':
        upload_report(drive,data)
        print(f'[ret] Ozel Drive raporu dogrulanarak guncellendi. Video={len(rows)} egri={sum(bool(c) for c in curves.values())}')
    else:
        print(f'[ret] Guvenli test tamamlandi; Drive dosyasi degistirilmedi. Video={len(rows)} egri={sum(bool(c) for c in curves.values())}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SafeError as exc:
        print('[ret] HATA:', str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('[ret] HATA: Beklenmeyen hata; gizli veri kayda yazilmadi.', file=sys.stderr)
        sys.exit(1)
