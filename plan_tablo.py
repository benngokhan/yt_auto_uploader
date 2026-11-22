"""Write only the specific planned-video row, preserving workbook contents."""
import io
from datetime import timezone, timedelta
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from sheets_metadata import DEFAULT_SHEETS_ID


def mark_scheduled(drive, name, url, slot):
    fid = DEFAULT_SHEETS_ID
    before = drive.files().get(fileId=fid, fields='id,modifiedTime').execute()
    buf = io.BytesIO()
    download = MediaIoBaseDownload(buf, drive.files().get_media(fileId=fid))
    done = False
    while not done:
        _, done = download.next_chunk()
    buf.seek(0)
    wb = load_workbook(buf)
    matches = [s for s in wb.worksheets if s.title.strip().casefold() == 'drive']
    if len(matches) != 1:
        wb.close(); raise RuntimeError('Ana tablo sayfası bulunamadı veya belirsiz')
    ws=matches[0]
    rows=[r for r in range(2,ws.max_row+1) if str(ws.cell(r,2).value or '').strip().casefold()==name.casefold()]
    if len(rows)!=1:
        wb.close(); raise RuntimeError('Planlanacak video satırı tekil değil')
    row=rows[0]
    prior_url=str(ws.cell(row,10).value or '').strip()
    if prior_url and prior_url != url:
        wb.close();raise RuntimeError('Tabloda başka bir YouTube bağlantısı var')
    local=slot.astimezone(timezone(timedelta(hours=3)))
    ws.cell(row,1).value='PLANLANDI'
    ws.cell(row,2).hyperlink=url
    ws.cell(row,10).value=url
    ws.cell(row,11).value=local.strftime('%Y-%m-%d %H:%M')+' (Planlandı)'
    blue=PatternFill(start_color='CFE2F3',end_color='CFE2F3',fill_type='solid')
    for col in range(1,14):ws.cell(row,col).fill=blue
    out=io.BytesIO();wb.save(out);wb.close();out.seek(0)
    after=drive.files().get(fileId=fid,fields='id,modifiedTime').execute()
    if before.get('modifiedTime') != after.get('modifiedTime') or not before.get('modifiedTime'):
        raise RuntimeError('Tablo eşzamanlı değişti; üzerine yazılmadı')
    media=MediaIoBaseUpload(out,mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',resumable=False)
    drive.files().update(fileId=fid,media_body=media).execute()
    print('Drive tablosunda video planlandı olarak işaretlendi.')
