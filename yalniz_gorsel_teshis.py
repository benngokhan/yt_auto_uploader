"""Single visual search diagnostic; no script generation, TTS, render, queue, or upload."""
import os, sys
from pathlib import Path
sys.path.insert(0,'motor')
import gorsel_uret
if os.getenv('MOTOR_EXPERIMENTAL_OPENROUTER') != '1' or os.getenv('MOTOR_VISUAL_QA_PASSED') != '1':
    raise SystemExit('Deneysel test bayrakları yok')
scene={'konu':'Mum üflendiğinde neden söner?',
       'ses':'Üflemek mum alevinin çevresindeki sıcak gazları hızla soğutur.',
       'gorsel':'human face blowing candle',
       'gorsel_alternatif':'human blowing out candle daylight'}
paths=gorsel_uret.sahneler_icin_gorseller([scene],Path('teshis_viz'))
print('YALNIZ_EYLEM_SECILEN',sum(x is not None for x in paths),'/',len(paths),flush=True)
print('NOT: Önceden belirlenmiş sorgu; senaryo, ses, video, yayın ve sıra çalıştırılmadı.',flush=True)
