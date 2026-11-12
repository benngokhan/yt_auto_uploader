#!/usr/bin/env python3
import os,re,json,base64,urllib.request,urllib.parse
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload,MediaFileUpload
from openpyxl import load_workbook

BOT=os.environ['TELEGRAM_BOT_TOKEN']; CHAT=str(os.environ['TELEGRAM_CHAT_ID'])
GH=os.environ['GITHUB_TOKEN']; REPO=os.getenv('GITHUB_REPOSITORY','benngokhan/yt_auto_uploader')
APPROVAL=os.getenv('APPROVAL_FOLDER','1N6mMUu3rEvCIie4o4XUWegPzFngMgHHM')
QUEUE=os.getenv('QUEUE_FOLDER','1Mht2RXUJG9qAhinl8PGjMgOXg58AOUIR')
BOOK=os.getenv('WORKBOOK_ID','1ulh13cnzYTaIlp1vehJ7lDrSsgjKyM_X')
OFFSET_PATH='telegram_callback_offset.txt'

def tg(method,payload):
    req=urllib.request.Request(f'https://api.telegram.org/bot{BOT}/{method}',data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=70) as r:return json.load(r)

def gh(method,path,body=None):
    h={'Authorization':f'Bearer {GH}','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'}
    req=urllib.request.Request(f'https://api.github.com/repos/{REPO}/{path}',data=(json.dumps(body).encode() if body else None),headers=h,method=method)
    with urllib.request.urlopen(req,timeout=60) as r:return json.load(r) if r.status!=204 else {}

def offset_load():
    try:
        j=gh('GET',f'contents/{OFFSET_PATH}?ref=main');return int(base64.b64decode(j['content']).decode().strip() or 0),j['sha']
    except Exception:return 0,None

def offset_save(n,sha):
    b={'message':'Telegram onay offsetini guncelle [skip ci]','content':base64.b64encode(str(n).encode()).decode(),'branch':'main'}
    if sha:b['sha']=sha
    gh('PUT',f'contents/{OFFSET_PATH}',b)

def drive_service():
    Path('token.json').write_text(os.environ['GOOGLE_TOKEN_JSON'])
    c=Credentials.from_authorized_user_file('token.json')
    if not c.valid:c.refresh(Request())
    return build('drive','v3',credentials=c,cache_discovery=False)

def find_files(drive,run_no):
    for klasor_id in dict.fromkeys([APPROVAL, QUEUE]):
        if not klasor_id:
            continue
        q=f"'{klasor_id}' in parents and trashed=false"
        files=drive.files().list(q=q,fields='files(id,name,mimeType,parents)',pageSize=1000).execute().get('files',[])
        video=next((x for x in files if x['name'].startswith(f'ONAY_{run_no}_') and x['name'].endswith('.mp4')),None)
        cover=next((x for x in files if x['name']==f'kapak_{run_no}.jpg'),None)
        meta=next((x for x in files if x['name']==f'YAYIN_BILGISI_{run_no}.json'),None)
        if video:
            return video,cover,meta
    return None,None,None

def next_no(drive):
    fs=drive.files().list(q=f"'{QUEUE}' in parents and trashed=false",fields='files(name)',pageSize=1000).execute().get('files',[])
    nums=[int(m.group(1)) for x in fs if (m:=re.fullmatch(r'video_(\d+)\.mp4',x['name']))]
    return max(nums+[175])+1

def metadata_read(drive, meta, topic):
    if not meta: raise RuntimeError("Yayın bilgisi dosyası bulunamadı; kuyruğa alma durduruldu")
    raw=drive.files().get_media(fileId=meta['id']).execute()
    d=json.loads(raw.decode('utf-8'))
    for k in ('baslik','aciklama','hashtag','etiketler','sabit_yorum','kategori'):
        if not str(d.get(k,'')).strip(): raise RuntimeError("Eksik yayın bilgisi: "+k)
    return d

def workbook_add(drive,no,topic,meta):
    req=drive.files().get_media(fileId=BOOK); p=Path('workbook.xlsx')
    with p.open('wb') as f:
        dl=MediaIoBaseDownload(f,req);done=False
        while not done:_,done=dl.next_chunk()
    wb=load_workbook(p);ws=wb['DRIVE']; row=ws.max_row+1
    while row>2 and not ws.cell(row-1,2).value: row-=1
    ws.cell(row,1,'BEKLEMEDE');ws.cell(row,2,f'video_{no}.mp4');ws.cell(row,3,meta['baslik']);ws.cell(row,4,meta['aciklama']);ws.cell(row,5,meta['hashtag']);ws.cell(row,6,meta['etiketler'])
    ws.cell(row,7,meta['sabit_yorum']);ws.cell(row,8,meta['kategori'])
    wb.save(p)
    drive.files().update(fileId=BOOK,media_body=MediaFileUpload(str(p),mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')).execute()

def topic_from(cb):
    msg=cb.get('message') or {}; content=msg.get('text') or msg.get('caption') or ''
    m=re.search(r'Konu:\s*(.+)',content)
    return m.group(1).strip() if m else 'Yeni Bilgi Dozu videosu'

def _baslik_from(cb):
    """Uzun açıklama silineceği için mesajda kalacak kısa video başlığı."""
    msg=cb.get('message') or {}
    content=msg.get('text') or msg.get('caption') or ''
    m=re.search(r'Başlık:\s*(.+)',content)
    return m.group(1).strip() if m else topic_from(cb)


def finish(cb,text,keep_buttons=False):
    """Uzun yayın açıklamasını SİLER, yerine yalnız kısa durum bildirimi yazar.

    Sahip kararı: "Reddet dediğimde uzun açıklama silinip yerine Reddedildi
    notu gelsin." Bu yüzden eski metin korunmaz, tamamen değiştirilir.
    """
    tg('answerCallbackQuery',{'callback_query_id':cb['id'],'text':text[:180],'show_alert':False})
    msg=cb.get('message') or {}
    baslik=_baslik_from(cb)
    govde=f"<b>{baslik}</b>\n\n{text}"
    payload={'chat_id':msg['chat']['id'],'message_id':msg['message_id'],
             'parse_mode':'HTML',
             'reply_markup':{'inline_keyboard':[]} if not keep_buttons else msg.get('reply_markup',{})}
    if msg.get('text') is not None:
        payload['text']=govde; method='editMessageText'
    else:
        payload['caption']=govde; method='editMessageCaption'
    tg(method,payload)

def process(cb,drive):
    if str((cb.get('message',{}).get('chat') or {}).get('id'))!=CHAT:return
    data=cb.get('data','');m=re.fullmatch(r'bd_(queue|retry|reject|keep):(\d+):(\d+)',data)
    if not m:return
    action,run_no,run_id=m.group(1),m.group(2),m.group(3);topic=topic_from(cb)
    video,cover,meta_file=find_files(drive,run_no)
    if action=='keep':
        # Onay klasörünün adını Drive'dan oku, bildirimde o ad geçsin.
        try:
            klasor=drive.files().get(fileId=APPROVAL,fields='name').execute().get('name') or 'Onay Bekleyen Videolar'
        except Exception:
            klasor='Onay Bekleyen Videolar'
        finish(cb,f"📁 Drive'da <b>{klasor}</b> klasörüne alındı.");return
    if action=='reject':
        for f in (video,cover,meta_file):
            if f:drive.files().update(fileId=f['id'],body={'trashed':True}).execute()
        finish(cb,"❌ Reddedildi.");return
    if action=='retry':
        gh('POST','actions/workflows/motor-uret.yml/dispatches',{'ref':'main','inputs':{'konu':topic,'kuru':'false','sahne':'7','sure_min':'38','sure_max':'45','sadece_ses':'false'}})
        finish(cb,"🔄 Üretiliyor.");return
    if action=='queue':
        if not video: finish(cb,'⚠️ Onay videosu Drive’da bulunamadı.');return
        no=next_no(drive)
        meta=metadata_read(drive,meta_file,topic)
        moved=[]
        v_parents=video.get('parents') or [APPROVAL]
        in_queue=(QUEUE in v_parents)
        try:
            if in_queue:
                drive.files().update(fileId=video['id'],body={'name':f'video_{no}.mp4'},fields='id').execute()
            else:
                drive.files().update(fileId=video['id'],addParents=QUEUE,removeParents=','.join(v_parents),body={'name':f'video_{no}.mp4'},fields='id').execute()
            moved.append((video,f'ONAY_{run_no}_geri_alindi.mp4',in_queue,v_parents))
            if cover:
                c_parents=cover.get('parents') or [APPROVAL]
                c_in_q=(QUEUE in c_parents)
                if c_in_q:
                    drive.files().update(fileId=cover['id'],body={'name':f'kapak_{no}.jpg'},fields='id').execute()
                else:
                    drive.files().update(fileId=cover['id'],addParents=QUEUE,removeParents=','.join(c_parents),body={'name':f'kapak_{no}.jpg'},fields='id').execute()
                moved.append((cover,f'kapak_{run_no}.jpg',c_in_q,c_parents))
            workbook_add(drive,no,topic,meta)
        except Exception:
            for f,old_name,was_in_q,orig_p in moved:
                if was_in_q:
                    drive.files().update(fileId=f['id'],body={'name':old_name},fields='id').execute()
                else:
                    drive.files().update(fileId=f['id'],addParents=','.join(orig_p),removeParents=QUEUE,body={'name':old_name},fields='id').execute()
            raise
        if meta_file: drive.files().update(fileId=meta_file['id'],body={'trashed':True}).execute()
        finish(cb,f"✅ video_{no}.mp4 olarak kuyruğa alındı.")

def main():
    off,sha=offset_load(); data=tg('getUpdates',{'offset':off,'timeout':0,'allowed_updates':['callback_query']})
    drive=drive_service(); newest=off
    for upd in data.get('result',[]):
        newest=max(newest,upd['update_id']+1)
        if upd.get('callback_query'):
            try:process(upd['callback_query'],drive)
            except Exception as e:
                try:tg('answerCallbackQuery',{'callback_query_id':upd['callback_query']['id'],'text':'İşlem hatası: '+str(e)[:120],'show_alert':True})
                except Exception:pass
    if newest!=off:offset_save(newest,sha)
if __name__=='__main__':main()
