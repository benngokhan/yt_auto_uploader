#!/usr/bin/env python3
"""Sabit ses seçilmeden önce noktalama ve doğal vurgu pilotu üretip Drive'a yükler."""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT/'motor'))
import tts, uret
from paket_uret import drive_service, upload_file, PARENT

METIN=("Bazen beynin, sen fark etmeden küçük bir mola ister. "
       "Peki bunu nasıl yapar? Kısa bir nefes alır; ardından, omuzlarını yavaşça gevşetirsin. "
       "İşte o an, bedenin sana şunu söyler: Bir saniye dur ve yeniden başla.")

def main():
 cfg=uret.ayar_yukle(); cfg['ses']['voice_id']=os.getenv('MOTOR_VOICE_ID',cfg['ses'].get('voice_id','ahmet'))
 out=ROOT/'motor'/'cikti'/'ses_pilot'; out.mkdir(parents=True,exist_ok=True)
 wav=out/f"ses_pilot_{cfg['ses']['voice_id']}.wav"; timing=tts.uret(METIN,wav,cfg)
 (out/'ses_pilot_zaman.json').write_text(json.dumps(timing,ensure_ascii=False,indent=2),encoding='utf-8')
 svc=drive_service(); stamp=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
 folder=svc.files().create(body={'name':f'SES_PILOT_{cfg["ses"]["voice_id"]}_{stamp}','mimeType':'application/vnd.google-apps.folder','parents':[PARENT]},fields='id,name,webViewLink').execute()
 files=[upload_file(svc,p,folder['id']) for p in sorted(out.iterdir()) if p.is_file()]
 print(json.dumps({'ok':True,'folder':folder,'files':files},ensure_ascii=False))
if __name__=='__main__': main()
