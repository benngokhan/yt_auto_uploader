"""Two bounded stock-search probes, no generation, no publishing, no semantic claims."""
import json, os, sys, urllib.request
from io import BytesIO
from pathlib import Path
from PIL import Image
sys.path.insert(0, 'motor')
import gorsel_uret as g

key = (os.getenv('PEXELS_API_KEY') or '').strip()
if not key:
    raise SystemExit('Pexels anahtarı sağlanmadı')
queries = ['candle flame daylight', 'candle smoke daylight']
output=[]
for query in queries:
    try:
        hits=g.pexels_ara(query,key,adet=8)[:8]
    except BaseException as exc:
        print('ARAMA_HATA',query,type(exc).__name__,flush=True)
        continue
    print('ARAMA',query,'ADAY',len(hits),flush=True)
    for hit in hits:
        row={'query':query,'uid':hit.get('uid'), 'source_page_url':hit.get('source_page_url'), 'image_url':hit.get('indir_url'), 'tags':hit.get('tags')}
        if not g._yeterince_uygun(hit, query, 'mum alevi', gevsek=True):
            row['result']='metadata_rejected'
        else:
            try:
                url=str(hit.get('indir_url') or '')
                url += ('&' if '?' in url else '?') + 'w=1200'
                req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=25) as response: blob=response.read()
                with Image.open(BytesIO(blob)) as image: raw=image.convert('RGB')
                reject,why=g._ham_kusurlu_mu(raw)
                row['raw_check']=why
                if reject:
                    row['result']='raw_rejected'
                else:
                    plate=g.sinematik_isle(g.dikey_kirp(raw),tohum=20261101)
                    value=g.average_image_brightness(plate)
                    row['processed_brightness']=round(value,1)
                    row['result']='pixel_candidate' if value>=g.MIN_AVG_BRIGHTNESS else 'processed_dark'
            except Exception as exc:
                row['result']='download_or_pixel_error:' + type(exc).__name__
        output.append(row)
        print('ADAY',row['uid'],row['result'],row.get('raw_check',''),row.get('processed_brightness',''),flush=True)
Path('aday_isik_sonuclari.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
print('NOT: piksel koşulları semantik doğrulama değildir; hiçbir görsel seçilmedi.',flush=True)
