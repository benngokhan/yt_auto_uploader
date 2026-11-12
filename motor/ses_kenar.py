#!/usr/bin/env python3
"""Ses kenarı düzeltme — sahne geçişlerinde boşluk/çıtırtı olmasın diye.

Sorun: bir sahnenin sesi bittiğinde uzun bir sessizlik kalıyor, sonraki sahne
geç başlıyor; ayrıca kesme noktalarında duyulabilir "tık" oluşuyor.

Çözüm (her sahne ses dosyasına uygulanır):
    * baştan/sondan sessizliği kırp, başta 80 ms / sonda 180 ms bırak
    * 15 ms fade-in / fade-out → tık yok
    * çok kısa kırpma olursa dokunma

Ayrıca TEK İSTEK SES kuralı için `cumlelere_bol()`: tek Gemini çıktısını
cümle sınırlarından (gerçek sessizlikler) parçalara ayırır.
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


# ── TEK İSTEK SES: cümlelere bölme (sahip kuralı — tek anlatıcı, tek ton) ────
class Parca:
    """Tek ses dosyasından kesilmiş bir cümle parçası."""

    __slots__ = ("veri", "sr")

    def __init__(self, veri: np.ndarray, sr: int):
        self.veri = veri
        self.sr = sr

    def to_wav(self, yol) -> Path:
        yol = Path(yol)
        yol.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(yol), self.veri.astype("float32"), self.sr, subtype="PCM_16")
        return yol


def _sessiz_araliklar(mono: np.ndarray, sr: int, esik_db: float = ESIK_DB,
                      min_sn: float = 0.08):
    """(bas, son) sessizlik aralıkları, saniye cinsinden."""
    w = max(1, int(0.02 * sr))
    esik = 10 ** (esik_db / 20.0)
    adet = len(mono) // w
    sesli = np.zeros(adet, dtype=bool)
    for i in range(adet):
        dilim = mono[i * w:(i + 1) * w]
        sesli[i] = len(dilim) > 0 and float(np.sqrt(np.mean(dilim ** 2))) > esik
    araliklar, bas = [], None
    for i, s in enumerate(sesli):
        if not s and bas is None:
            bas = i * w
        elif s and bas is not None:
            if (i * w - bas) / sr >= min_sn:
                araliklar.append((bas / sr, i * w / sr))
            bas = None
    if bas is not None and (len(mono) - bas) / sr >= min_sn:
        araliklar.append((bas / sr, len(mono) / sr))
    return araliklar


def cumlelere_bol(yol, cumleler, esik_db: float = ESIK_DB):
    """Tek ses dosyasını cümle sayısına böler.

    Sınırlar gerçek sessizliklerin orta noktasından seçilir. Yeterli sessizlik
    yoksa konuşma süresi cümle uzunluğuna göre orantılı paylaştırılır.
    Kesim yalnızca sessizlik içinde yapılır; konuşulan hece kesilmez.
    """
    x, sr = sf.read(str(yol), dtype="float32", always_2d=True)
    mono = x.mean(axis=1) if x.shape[1] > 1 else x[:, 0]
    n = len(cumleler)
    if n <= 1:
        return [Parca(mono, sr)]

    toplam = len(mono) / float(sr)
    sessiz = _sessiz_araliklar(mono, sr, esik_db)
    adaylar = sorted(0.5 * (a + b) for a, b in sessiz
                     if a > 0.05 and b < toplam - 0.05)

    uzun = np.array([max(1, len(c)) for c in cumleler], dtype=float)
    oran = np.cumsum(uzun)[:-1] / uzun.sum()
    hedefler = [float(oran[i]) * toplam for i in range(n - 1)]

    kesimler = []
    for h in hedefler:
        if adaylar:
            yakin = min(adaylar, key=lambda t: abs(t - h))
            kesimler.append(yakin)
            adaylar = [t for t in adaylar if t > yakin + 0.02]
        else:
            kesimler.append(h)

    sinirlar = [0.0] + kesimler + [toplam]
    parcalar = []
    nf = int(0.012 * sr)
    for i in range(n):
        i0 = int(round(sinirlar[i] * sr))
        i1 = int(round(sinirlar[i + 1] * sr))
        seg = mono[max(0, i0):min(len(mono), i1)].copy()
        if len(seg) > 2 * nf + 10:
            seg[:nf] *= np.linspace(0.0, 1.0, nf, dtype="float32")
            seg[-nf:] *= np.linspace(1.0, 0.0, nf, dtype="float32")
        parcalar.append(Parca(seg, sr))
    return parcalar


if __name__ == "__main__":
    import sys
    print(duzelt(sys.argv[1]))
