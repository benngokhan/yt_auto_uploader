#!/usr/bin/env python3
"""Başlık -> 4 sahneli senaryo + sabit TTS + zamanlar + görsel promptları -> Drive paketi."""
from __future__ import annotations
import argparse, json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOTOR = ROOT / "motor"
sys.path.insert(0, str(MOTOR)); sys.path.insert(0, str(ROOT))
import uret, tts  # noqa: E402

PARENT = os.getenv("MOTOR_PAKET_DRIVE_ID", "1lKrhKOx9ywnhhA9xRkBGlhjxY8Ee9fg1")


def slug(s: str) -> str:
    table = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    return re.sub(r"[^a-z0-9]+", "-", s.translate(table).lower()).strip("-")[:55]


def drive_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    token = Path(os.getenv("GOOGLE_TOKEN_FILE", "token.json"))
    if not token.exists(): raise SystemExit("token.json yok")
    return build("drive", "v3", credentials=Credentials.from_authorized_user_file(str(token)), cache_discovery=False)


def upload_file(svc, path: Path, parent: str):
    from googleapiclient.http import MediaFileUpload
    mime = "audio/wav" if path.suffix == ".wav" else "application/json" if path.suffix == ".json" else "text/plain"
    return svc.files().create(body={"name": path.name, "parents": [parent]}, media_body=MediaFileUpload(str(path), mimetype=mime, resumable=False), fields="id,name,webViewLink").execute()


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--baslik", required=True); a=ap.parse_args()
    cfg=uret.ayar_yukle(); cfg["sahne_sayisi"]=4
    cfg["ses"]["voice_id"] = os.getenv("MOTOR_VOICE_ID", cfg["ses"].get("voice_id", "klon_095_xtts"))
    scenes=uret.sahne_plani(a.baslik, 4, cfg)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out=ROOT/"motor"/"cikti"/"paketler"/f"{stamp}_{slug(a.baslik)}"; out.mkdir(parents=True, exist_ok=True)
    manifest={"surum":1,"baslik":a.baslik,"durum":"BANT_RENDER_BEKLIYOR","hedef":{"sure":"38-42","fps":60,"boyut":"1080x1920","sahne":4},"ses":{"saglayici":cfg["ses"]["saglayici"],"voice_id":cfg["ses"]["voice_id"],"model":cfg["ses"]["model"],"dil":"tr"},"sahneler":[]}
    for i,s in enumerate(scenes,1):
        wav=out/f"sahne_{i:02d}.wav"; timing=tts.uret(s["ses"],wav,cfg)
        if timing is None: timing=uret.hizala(wav,s["ses"],cfg)
        (out/f"sahne_{i:02d}_zaman.json").write_text(json.dumps(timing,ensure_ascii=False,indent=2),encoding="utf-8")
        manifest["sahneler"].append({"no":i,"metin":s["ses"],"baslik1":s["baslik1"],"baslik2":s["baslik2"],"emoji":s.get("emoji",""),"gorsel_prompt":s["gorsel"],"wav":wav.name,"zaman":f"sahne_{i:02d}_zaman.json"})
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"BANT_TALIMATI.txt").write_text("Bu paket değiştirilemez: 4 promptla 4 farklı görsel üret; onaylı sablonu kullan; zoom 1.00-1.04; 60 fps; 38-42 sn; MP4'u Onay Bekleyen'e koy. Senaryo ve sesi yeniden üretme.\n",encoding="utf-8")
    svc=drive_service(); folder=svc.files().create(body={"name":out.name,"mimeType":"application/vnd.google-apps.folder","parents":[PARENT]},fields="id,name,webViewLink").execute()
    uploaded=[upload_file(svc,p,folder["id"]) for p in sorted(out.iterdir()) if p.is_file()]
    print(json.dumps({"ok":True,"folder":folder,"files":uploaded},ensure_ascii=False))
if __name__=="__main__": main()
