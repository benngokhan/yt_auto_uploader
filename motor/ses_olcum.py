#!/usr/bin/env python3
"""Ses ölçümü (yalnız ÖLÇER; hiçbir ayara ya da sese dokunmaz).

Perde (f0): 40 ms pencere, öz-ilinti, 60-300 Hz aralığı, tepe/enerji > 0,5 olan pencerelerin medyanı.
Kaba bir ölçümdür (oktav hatası yapabilir); müzikli mikste kullanılmamalıdır.
Kullanım:  python3 motor/ses_olcum.py dosya.wav [dosya2.wav ...]
"""
from __future__ import annotations

import sys
import wave

import numpy as np


def olc(yol) -> dict:
    with wave.open(str(yol)) as w:
        sr, kanal, genislik = w.getframerate(), w.getnchannels(), w.getsampwidth()
        ham = w.readframes(w.getnframes())
    if genislik != 2:
        raise ValueError("yalnız 16-bit PCM WAV ölçülür")
    a = np.frombuffer(ham, dtype=np.int16).astype(np.float64) / 32768
    if kanal > 1:
        a = a.reshape(-1, kanal).mean(1)
    n = int(sr * 0.04)
    f0, parlaklik = [], []
    for i in range(0, len(a) - n, n // 2):
        x = a[i:i + n]
        if np.sqrt((x ** 2).mean()) < 0.03:
            continue
        x = x - x.mean()
        ac = np.correlate(x, x, "full")[n - 1:]
        lo, hi = int(sr / 300), int(sr / 60)
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[0] > 0 and ac[k] / ac[0] > 0.5:
            f0.append(sr / k)
        sp = np.abs(np.fft.rfft(x * np.hanning(n)))
        fr = np.fft.rfftfreq(n, 1 / sr)
        m = fr < 8000
        if sp[m].sum() > 0:
            parlaklik.append(float((sp[m] * fr[m]).sum() / sp[m].sum()))
    rms = float(np.sqrt((a ** 2).mean())) if len(a) else 0.0
    return {
        "dosya": str(yol).split("/")[-1],
        "ornekleme_hz": sr,
        "sure_sn": round(len(a) / sr, 2),
        "f0_medyan_hz": round(float(np.median(f0)), 1) if f0 else None,
        "f0_yuzde10_hz": round(float(np.percentile(f0, 10)), 1) if f0 else None,
        "f0_yuzde90_hz": round(float(np.percentile(f0, 90)), 1) if f0 else None,
        "f0_pencere_sayisi": len(f0),
        "parlaklik_hz": round(float(np.median(parlaklik)), 0) if parlaklik else None,
        "rms_db": round(20 * float(np.log10(rms)), 1) if rms > 0 else None,
    }


def satir(o: dict) -> str:
    return (f"{o['dosya']}: sr={o['ornekleme_hz']} süre={o['sure_sn']}s  f0 medyan={o['f0_medyan_hz']} Hz "
            f"(%10-%90: {o['f0_yuzde10_hz']}-{o['f0_yuzde90_hz']} Hz, {o['f0_pencere_sayisi']} pencere)  "
            f"parlaklık={o['parlaklik_hz']} Hz  rms={o['rms_db']} dB")


if __name__ == "__main__":
    for y in sys.argv[1:]:
        print(satir(olc(y)))


# ── Perde sapması (sahip kararı, 16.11.2026): YALNIZ ÖLÇÜM + UYARI. Üretimi durdurmaz, hiçbir ses ayarına dokunmaz.
TABAN_F0_HZ = 127.0      # onaylı taban (62. üretim)
SAPMA_ESIGI = 0.10       # ham f0 medyanı tabandan %10'dan fazla saparsa uyarı
PERDE_KAYDI = __import__("pathlib").Path(__file__).resolve().parent / "ses_perde_kaydi.csv"
_KAYIT_BASLIK = "tarih_utc,uretim_no,ham_f0_medyan_hz,taban_hz,sapma_yuzde,uyari,f0_yuzde10_hz,f0_yuzde90_hz,sure_sn"


def perde_sapmasi(f0_medyan_hz: float) -> dict:
    """{'sapma_yuzde': -11.7, 'uyari': True, 'satir': '...'} döndürür."""
    sapma = (float(f0_medyan_hz) - TABAN_F0_HZ) / TABAN_F0_HZ
    uyari = abs(sapma) > SAPMA_ESIGI
    satir = (f"ham f0 medyan={float(f0_medyan_hz):.1f} Hz; onaylı taban={TABAN_F0_HZ:g} Hz; "
             f"sapma={sapma * 100:+.1f}% (eşik ±{SAPMA_ESIGI * 100:g}%)")
    return {"sapma_yuzde": round(sapma * 100, 1), "uyari": uyari, "satir": satir}


def perde_kaydet(o: dict, yol=None) -> bool:
    """Ham ses ölçümünü kayıt dosyasına bir satır olarak ekler (iki haftalık veri için).

    Yalnız gerçek üretimde (GITHUB_RUN_NUMBER varken) ya da yol/MOTOR_PERDE_KAYDI verilmişse yazar.
    """
    import os
    from datetime import datetime, timezone
    from pathlib import Path
    try:
        hedef = yol or os.getenv("MOTOR_PERDE_KAYDI", "").strip()
        no = os.getenv("GITHUB_RUN_NUMBER", "").strip()
        if not hedef and not no:
            return False
        hedef = Path(hedef) if hedef else PERDE_KAYDI
        s = perde_sapmasi(o["f0_medyan_hz"])
        yeni = not hedef.exists() or not hedef.read_text(encoding="utf-8").strip()
        with hedef.open("a", encoding="utf-8") as f:
            if yeni:
                f.write(_KAYIT_BASLIK + "\n")
            f.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},{no or '-'},{o['f0_medyan_hz']},"
                    f"{TABAN_F0_HZ:g},{s['sapma_yuzde']},{'EVET' if s['uyari'] else 'hayir'},"
                    f"{o['f0_yuzde10_hz']},{o['f0_yuzde90_hz']},{o['sure_sn']}\n")
        return True
    except Exception:  # noqa: BLE001
        return False
