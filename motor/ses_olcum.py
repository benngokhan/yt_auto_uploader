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
