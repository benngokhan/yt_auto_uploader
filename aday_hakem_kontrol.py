"""One bounded dry vision calibration on previously observed candidates; no video."""
import sys, urllib.request
from pathlib import Path
sys.path.insert(0, 'motor')
from openrouter_preview_vision import score_images

rows=[
 {'preview_url':'https://images.pexels.com/photos/39572227/pexels-photo-39572227.jpeg?w=600'},
 {'preview_url':'https://images.pexels.com/photos/10495878/pexels-photo-10495878.jpeg?w=600'},
 {'preview_url':'https://images.pexels.com/photos/19815864/pexels-photo-19815864.jpeg?w=600'},
]
def download(url, path):
 request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
 with urllib.request.urlopen(request,timeout=25) as response:
  Path(path).write_bytes(response.read())
context='Ana konu: Mum üflendiğinde neden söner?\nSahne: Mum alevi üflendiğinde neden birden sönüyor, hiç düşündün mü?'
scores=score_images(context,rows,download)
for tag,score,row in zip(['CAKMAKLA_YAKILAN_MUM','SONMUS_DUMANLI_1','SONMUS_DUMANLI_2'],scores,rows):
 print('KALIBRASYON',tag,'PUAN',score,'HATA',row.get('_vision_error','yok'),flush=True)
print('NOT: Bu küçük karşılaştırma üretim güvencesi değildir.',flush=True)
