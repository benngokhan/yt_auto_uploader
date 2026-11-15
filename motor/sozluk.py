#!/usr/bin/env python3
"""Türkçe sözlük denetimi (yapay zekâsız, her çalıştırmada aynı sonuç).

Yalnız BAŞLIK denetiminde kullanılır (sahip kararı, 16.11.2026). Senaryo gövdesinin yazım denetimine dokunmaz.
Araç: zemberek-python (Türkçe biçimbilim çözümleyicisi; kökleri ve ekleri tanır, internet gerektirmez).

Bir kelime "bilinen" sayılır, eğer:
  - çözümleyici onu geçerli bir Türkçe kelime (kök + ekler) olarak çözebiliyorsa, ya da
  - motor/sozluk_ek_kelimeler.txt dosyasında yazıyorsa (sahibin eklediği özel adlar/yabancı terimler).
Tek harfli bir kısaltmaya ek getirilerek çıkan çözümler SAYILMAZ (ör. "EYİ" = "E" kısaltması + "-yi";
65. üretimdeki "MUM EYİ" hatası böyle yakalanır).
Çözümleyicinin YALNIZ "özel ad" olarak tanıdığı kelimeler ŞÜPHELİ sayılır (ör. "ZERRCİKLER" = "Zerr" özel adı
+ ekler). Gerçek özel adlar sozluk_ek_kelimeler.txt dosyasına yazılarak korunur (sahip kararı, 16.11.2026).
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


def durum(kelime: str) -> str:
    """'' = bilinen kelime; aksi hâlde neden: 'sözlükte yok' ya da 'yalnız özel ad olarak tanınıyor'."""
    k = tr_kucuk(str(kelime).replace("’", "'"))
    if not k:
        return ""
    ek = _ek_kelimeler()
    if k in ek or k.split("'")[0] in ek:
        return ""
    ozel_ad = False
    for c in _cozumleyici().analyze(k).analysis_results:
        kok = str(getattr(c.item, "lemma", "") or "")
        ikincil = str(getattr(c.item, "secondary_pos", ""))
        if "Abbreviation" in ikincil and len(kok) <= 1 and len(k) > 1:
            continue  # tek harfli kısaltma + ek: gerçek kelime sayılmaz ("eyi" = E + yi)
        if "ProperNoun" in ikincil:
            if tr_kucuk(kok) in ek:
                return ""  # sahibin onayladığı özel ad (ekli hâlleriyle birlikte)
            ozel_ad = True
            continue
        return ""
    return "yalnız özel ad olarak tanınıyor" if ozel_ad else "sözlükte yok"


def bilinen_mi(kelime: str) -> bool:
    return not durum(kelime)


def not_dus(kelime: str, baslik: str = "", neden: str = "") -> bool:
    """Üretimi durduran kelimeyi ek kelime dosyasına YORUM olarak not eder (kendiliğinden geçerli sayılmaz).

    Kelime gerçekten doğruysa sahip satırın başındaki "# ŞÜPHELİ ..." kısmını silip yalnız kelimeyi bırakır.
    """
    import os
    from datetime import datetime, timezone
    try:
        k = tr_kucuk(str(kelime))
        mevcut = EK_DOSYA.read_text(encoding="utf-8") if EK_DOSYA.exists() else ""
        if f"ŞÜPHELİ: {k} " in mevcut:
            return False
        satir = (f"# ŞÜPHELİ: {k} | {datetime.now(timezone.utc).strftime('%Y-%m-%d')} | "
                 f"üretim {os.getenv('GITHUB_RUN_NUMBER', '-')} | başlık: {baslik} | {neden} | "
                 "DOĞRUYSA bu satırı silip yerine yalnız kelimeyi yazın")
        with EK_DOSYA.open("a", encoding="utf-8") as f:
            f.write(("" if mevcut.endswith("\n") or not mevcut else "\n") + satir + "\n")
        return True
    except Exception:  # noqa: BLE001
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
