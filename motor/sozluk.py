#!/usr/bin/env python3
"""Türkçe sözlük denetimi (yapay zekâsız, her çalıştırmada aynı sonuç).

Yalnız BAŞLIK denetiminde kullanılır (sahip kararı, 16.11.2026). Senaryo gövdesinin yazım denetimine dokunmaz.
Araç: zemberek-python (Türkçe biçimbilim çözümleyicisi; kökleri ve ekleri tanır, internet gerektirmez).

Bir kelime "bilinen" sayılır, eğer:
  - çözümleyici onu geçerli bir Türkçe kelime (kök + ekler) olarak çözebiliyorsa, ya da
  - motor/sozluk_ek_kelimeler.txt dosyasında yazıyorsa (sahibin eklediği özel adlar/yabancı terimler).
Tek harfli bir kısaltmaya ek getirilerek çıkan çözümler SAYILMAZ (ör. "EYİ" = "E" kısaltması + "-yi";
65. üretimdeki "MUM EYİ" hatası böyle yakalanır).
İçinde rakam olan parçalar (ör. "3D", "100") kelime sayılmaz, denetlenmez.
"""
from __future__ import annotations

import logging
import re
import warnings
from pathlib import Path

EK_DOSYA = Path(__file__).resolve().parent / "sozluk_ek_kelimeler.txt"
_durum: dict = {"cozumleyici": None, "hata": "", "ek": None}
_KELIME = re.compile(r"[^\W_]+(?:['’][^\W\d_]+)?", re.UNICODE)


class SozlukYok(RuntimeError):
    """Sözlük yüklenemedi: denetim YAPILAMADI (hiçbir zaman 'temiz' sayılmaz)."""


def tr_kucuk(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def _cozumleyici():
    if _durum["cozumleyici"] is None:
        if _durum["hata"]:
            raise SozlukYok(_durum["hata"])
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from zemberek import TurkishMorphology  # noqa: PLC0415
                for ad in ("zemberek", "zemberek.morphology", "zemberek.morphology.turkish_morphology"):
                    logging.getLogger(ad).setLevel(logging.ERROR)
                _durum["cozumleyici"] = TurkishMorphology.create_with_defaults()
        except BaseException as h:  # noqa: BLE001
            _durum["hata"] = f"{type(h).__name__}: {h}"
            raise SozlukYok(_durum["hata"]) from h
    return _durum["cozumleyici"]


def _ek_kelimeler() -> set:
    if _durum["ek"] is None:
        try:
            satirlar = EK_DOSYA.read_text(encoding="utf-8").splitlines()
        except OSError:
            satirlar = []
        _durum["ek"] = {tr_kucuk(s.strip()) for s in satirlar if s.strip() and not s.lstrip().startswith("#")}
    return _durum["ek"]


def kelimeler(metin: str) -> list[str]:
    """Metindeki denetlenecek kelimeler (rakam içerenler ve noktalama hariç), yazıldığı gibi."""
    return [k for k in _KELIME.findall(str(metin or "")) if not any(c.isdigit() for c in k)]


def bilinen_mi(kelime: str) -> bool:
    k = tr_kucuk(str(kelime).replace("’", "'"))
    if not k:
        return True
    if k in _ek_kelimeler() or k.split("'")[0] in _ek_kelimeler():
        return True
    for c in _cozumleyici().analyze(k).analysis_results:
        kok = str(getattr(c.item, "lemma", "") or "")
        kisaltma = "Abbreviation" in str(getattr(c.item, "secondary_pos", ""))
        if kisaltma and len(kok) <= 1 and len(k) > 1:
            continue  # tek harfli kısaltma + ek: gerçek kelime sayılmaz ("eyi" = E + yi)
        return True
    return False


def bilinmeyenler(metin: str) -> list[str]:
    """Metinde sözlükte bulunmayan kelimeler (yazıldığı gibi, sırayla). Sözlük yüklenemezse SozlukYok fırlatır."""
    return [k for k in kelimeler(metin) if not bilinen_mi(k)]


def hazir_mi() -> tuple[bool, str]:
    try:
        _cozumleyici()
        return True, ""
    except SozlukYok as h:
        return False, str(h)


if __name__ == "__main__":
    import sys
    for _m in sys.argv[1:] or ["MUM EYİ", "MUM EVİ"]:
        print(f"{_m!r}: sözlükte olmayan -> {bilinmeyenler(_m)}")
