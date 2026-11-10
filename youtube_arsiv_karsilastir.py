#!/usr/bin/env python3
import os,json,subprocess,tempfile,statistics,re
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import cv2
CANDIDATE_FOLDER=os.getenv('CANDIDATE_FOLDER','1jtwZ1mOpiNgBIo1yD3ScYVhRJfPlrx0Q')

def clients():
 Path('token.json').write_text(os.environ['GOOGLE_TOKEN_JSON']);c=Credentials.from_authorized_user_file('token.json')
 if not c.valid:c.refresh(Request())
 return build('drive','v3',credentials=c,cache_discovery=False),build('youtube','v3',credentials=c,cache_discovery=False)
def duration(p):
 x=subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(p)],text=True);return float(x)
def hashes(p,n=12):
 cap=cv2.VideoCapture(str(p));frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));out=[]
 for i in range(n):
  cap.set(cv2.CAP_PROP_POS_FRAMES,int((i+.5)*frames/n));ok,im=cap.read()
  if not ok:continue
  g=cv2.cvtColor(cv2.resize(im,(9,8)),cv2.COLOR_BGR2GRAY);bits=(g[:,1:]>g[:,:-1]).flatten();out.append(sum(int(v)<<k for k,v in enumerate(bits)))
 cap.release();return out
def score(a,b):
 return statistics.mean((x^y).bit_count() for x,y in zip(a,b)) if len(a)==len(b) and a else 99
def yt_archive(y):
 ch=y.channels().list(part='contentDetails',mine=True).execute()['items'][0];pl=ch['contentDetails']['relatedPlaylists']['uploads'];ids=[];tok=None
 while True:
  r=y.playlistItems().list(part='snippet,contentDetails',playlistId=pl,maxResults=50,pageToken=tok).execute()
  ids += [(x['contentDetails']['videoId'],x['snippet']['title']) for x in r['items']];tok=r.get('nextPageToken')
  if not tok:break
 out=[]
 for i in range(0,len(ids),50):
  r=y.videos().list(part='contentDetails',id=','.join(x[0] for x in ids[i:i+50])).execute();ds={x['id']:x['contentDetails']['duration'] for x in r['items']}
  for vid,title in ids[i:i+50]:
   m=re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?',ds.get(vid,''));sec=(int(m.group(1)or 0)*3600+int(m.group(2)or 0)*60+int(m.group(3)or 0)) if m else 0;out.append({'id':vid,'title':title,'duration':sec})
 return out
def main():
 d,y=clients();shorts=d.files().list(q=f"'{CANDIDATE_FOLDER}' in parents and trashed=false",fields='files(id,name,shortcutDetails)',pageSize=1000).execute()['files'];archive=yt_archive(y);results=[]
 with tempfile.TemporaryDirectory() as td:
  td=Path(td);ytcache={}
  for idx,s in enumerate(shorts,1):
   tid=s.get('shortcutDetails',{}).get('targetId');row={'name':s['name'],'target_id':tid,'status':'incelenemedi','matches':[]}
   if not tid:results.append(row);continue
   p=td/f'c{idx}.mp4';req=d.files().get_media(fileId=tid)
   with p.open('wb') as f:
    dl=MediaIoBaseDownload(f,req);done=False
    while not done:_,done=dl.next_chunk()
   dur=duration(p);h=hashes(p);row['duration']=round(dur,2)
   for v in archive:
    if abs(v['duration']-dur)>3:continue
    if v['id'] not in ytcache:
     q=td/f"y_{v['id']}.mp4";subprocess.run(['yt-dlp','-q','--no-playlist','-f','worst[ext=mp4]/worst','-o',str(q),f"https://youtu.be/{v['id']}"],check=False);ytcache[v['id']]=hashes(q) if q.exists() else []
    sc=score(h,ytcache[v['id']])
    if sc<=14:row['matches'].append({'video_id':v['id'],'title':v['title'],'score':round(sc,2)})
   row['status']='yayinda_ayni_icerik' if row['matches'] else 'arsivde_eslesme_yok';results.append(row);p.unlink(missing_ok=True);print(idx,s['name'],row['status'],flush=True)
 Path('youtube_arsiv_karsilastirma.json').write_text(json.dumps({'youtube_count':len(archive),'candidate_count':len(shorts),'method':'Süre ±3 sn + 12 kare algısal dHash; düşük çözünürlüklü YouTube kopyasıyla karşılaştırma','results':results},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
