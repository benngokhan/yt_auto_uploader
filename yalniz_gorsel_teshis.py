"""Bounded, non-publishing visual-stage diagnostic; no TTS, renderer or queue.

The scenes and English searches are manually specified to isolate this one
problem. Success is not proof of automated scenario or search generation.
"""
import os, sys
from pathlib import Path
sys.path.insert(0, 'motor')
import gorsel_uret

if os.getenv('MOTOR_EXPERIMENTAL_OPENROUTER') != '1' or os.getenv('MOTOR_VISUAL_QA_PASSED') != '1':
    raise SystemExit('Deneysel test güvenlik bayrakları yok')
topic='Mum üflendiğinde neden söner?'
spec=[
 ('Mum alevi üflendiğinde neden birden sönüyor, hiç düşündün mü?', 'candle flame close up', 'candle smoke daylight'),
 ('Üflemek mum alevinin çevresindeki sıcak gazları hızla soğutur.', 'candle flame heat', 'candle wax melting daylight'),
 ('Aynı hava akımı yanan balmumu buharını da dağıtır.', 'candle smoke wisps', 'candle smoke daylight'),
 ('Yeterli ısı ve yakıt kalmayınca yanma süreci durur.', 'extinguished candle wick', 'candle smoke daylight'),
]
scenes=[{'konu':topic,'ses':text,'gorsel':primary,'gorsel_alternatif':alt} for text,primary,alt in spec]
results=gorsel_uret.sahneler_icin_gorseller(scenes,Path('teshis_viz'))
print('YALNIZ_GORSEL_SECILEN',sum(p is not None for p in results),'/',len(results),flush=True)
print('NOT: Elle seçilmiş aramalar; ses, video, yayın ve sıra çalıştırılmadı.',flush=True)
