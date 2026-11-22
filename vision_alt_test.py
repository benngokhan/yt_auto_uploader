import os, sys
from pathlib import Path
sys.path.insert(0,str(Path('motor').resolve()))
import gorsel_uret as g
k=os.getenv('PEXELS_API_KEY','').strip()
if not k: raise SystemExit('Pexels erişimi yok')
try: hits=g.pexels_ara('candle flame close up',k,adet=3)[:2]
except BaseException as e: raise SystemExit('Pexels araması başarısız: '+type(e).__name__) from None
print('PEXELS_ADAY',len(hits),flush=True)
if not hits:raise SystemExit('Pexels aday bulunamadı')
for model in ('gemini-flash-latest','gemini-2.5-flash'):
    g.SEMANTIC_MODEL=model
    for hit in hits:hit.pop('_vision_error',None)
    original=g.urllib.request.urlopen
    def bounded(req,timeout=None): return original(req,timeout=min(timeout or 25,25))
    g.urllib.request.urlopen=bounded
    try:
        values=g._visual_text_scores('Bir mumun alevini yakından görüyorsun.',hits)
        print('VISION',model,'PUAN_VAR' if any(v is not None for v in values) else 'PUAN_YOK',flush=True)
    except Exception as e:print('VISION',model,'HATA',type(e).__name__,flush=True)
    finally:g.urllib.request.urlopen=original
