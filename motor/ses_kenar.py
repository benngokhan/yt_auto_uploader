#!/usr/bin/env python3
"""Ses kenarı düzeltme — sahne geçişlerinde boşluk/çıtırtı olmasın diye.

Sorun: bir sahnenin sesi bittiğinde uzun bir sessizlik kalıyor, sonraki sahne
geç başlıyor; ayrıca kesme noktalarında duyulabilir "tık" oluşuyor.

Çözüm (her sahne ses dosyasına uygulanır):
    * baştan/sondan sessizliği kırp, başta 80 ms / sonda 180 ms bırak
    * 15 ms fade-in / fade-out → tık yok
    * çok kısa kırpma olursa dokunma
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

BAS_SESSIZLIK = 0.08
SON_SESSIZLIK = 0.18
FADE = 0.015
ESIK_DB = -42.0


def _kirp(x: np.ndarray, sr: int) -> tuple[int, int]:
    w = max(1, int(0.02 * sr))
    esik = 10 ** (ESIK_DB / 20.0)
    sesli = [i for i in range(0, len(x) - w, w) if np.sqrt(np.mean(x[i:i + w] ** 2)) > esik]
    if not sesli:
        return 0, len(x)
    return sesli[0], min(len(x), sesli[-1] + w)


def duzelt(yol: str | Path, *, bas: float = BAS_SESSIZLIK, son: float = SON_SESSIZLIK,
           fade: float = FADE) -> dict:
    """Ses dosyasını yerinde düzeltir; ne kadar kırpıldığını döndürür."""
    yol = Path(yol)
    x, sr = sf.read(str(yol), dtype="float32", always_2d=True)
    tek_kanal = x.shape[1] == 1
    mono = x.mean(axis=1)

    i0, i1 = _kirp(mono, sr)
    kirpilan_bas = i0 / sr
    kirpilan_son = (len(mono) - i1) / sr

    parca = mono[i0:i1]
    if len(parca) < int(0.2 * sr):                     # neredeyse tamamı sessiz
        return {"degisti": False, "neden": "ses çok kısa"}

    n_bas, n_son = int(bas * sr), int(son * sr)
    parca = np.concatenate([np.zeros(n_bas, dtype="float32"), parca,
                            np.zeros(n_son, dtype="float32")])

    nf = int(fade * sr)
    if nf > 1 and len(parca) > 2 * nf:
        parca[:nf] *= np.linspace(0.0, 1.0, nf, dtype="float32")
        parca[-nf:] *= np.linspace(1.0, 0.0, nf, dtype="float32")

    sf.write(str(yol), parca if tek_kanal else np.column_stack([parca, parca]),
             sr, subtype="PCM_16")
    return {
        "degisti": True,
        "kirpilan_bas_sn": round(kirpilan_bas, 3),
        "kirpilan_son_sn": round(kirpilan_son, 3),
        "yeni_sure_sn": round(len(parca) / sr, 3),
    }


if __name__ == "__main__":
    import sys
    print(duzelt(sys.argv[1]))
