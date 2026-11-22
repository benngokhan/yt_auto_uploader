"""Read only the key's documented free-model request counter; no inference."""
import json, os, urllib.error, urllib.request
key=(os.getenv('OPENROUTER_API_KEY') or '').strip()
if not key:
 print('KOTA_ANAHTAR_YOK'); raise SystemExit(1)
req=urllib.request.Request('https://openrouter.ai/api/v1/key',headers={'Authorization':'Bearer '+key,'Accept':'application/json'})
try:
 with urllib.request.urlopen(req,timeout=35) as response: data=json.load(response).get('data') or {}
 counter=data.get('free_model_daily_requests')
 print('KOTA_ERISIM', 'OK',flush=True)
 print('UCRETSIZ_HESAP',data.get('is_free_tier'),flush=True)
 if isinstance(counter,dict):
  for name in ('used','limit','remaining','resets_at','reset_at','reset'):
   value=counter.get(name)
   if value is None or isinstance(value,(int,float,str,bool)):
    print('UCRETSIZ_ISTEK',name, value,flush=True)
 else:
  print('UCRETSIZ_ISTEK_SAYACI','SUNULMADI',flush=True)
except urllib.error.HTTPError as exc:
 print('KOTA_HTTP',exc.code,flush=True)
except Exception as exc:
 print('KOTA_HATA',type(exc).__name__,flush=True)
