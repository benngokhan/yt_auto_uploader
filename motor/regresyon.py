#!/usr/bin/env python3
"""Regresyon testleri — bilinen hatalar. Motor HER AÇILIŞTA çalıştırır; biri başarısızsa video üretilmez.

Test seti (sahip, 15.11.2026):
  R1  "tütcen"  (64. üretim)            -> yazım denetimi düzeltmeli
  R2  "MUM EYİ" (65. üretim, başlık)    -> yazım denetimi yakalamalı
  R3  "beş yüz derece" (65. üretim)     -> doğrulanamayan kesin sayı olarak işaretlenmeli
  R4  "zerrecik" + "damlacık" (65)      -> terim tutarsızlığı uyarısı
  R5  64'ün neredeyse aynı ilk iki cümlesi -> tekrar olarak yakalanmalı

R1 ve R2 motorun GERÇEK yazım denetimini (yapay zekâ çağrısı) çalıştırır: sahte cevapla "yeşil" gösterilmez.
Yapay zekâya ulaşılamazsa ya da düzeltmezse test KIRMIZIdır. R3-R5 yapay zekâsız, her zaman aynı sonucu verir.
Kullanım:  python3 motor/regresyon.py     (çıkış kodu 0 = hepsi yeşil)
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

MOTOR = Path(__file__).resolve().parent
if str(MOTOR) not in sys.path:
    sys.path.insert(0, str(MOTOR))

CTA = "Daha fazla Bilgi Dozu için takip et!"

# 64. üretimin metni (videodaki altyazıdan okunmuştur)
URETIM_64 = [
    "Söndürülen mumun tütcen duman kül değil, kolayca tutuşabilen yakıt zerrecikleridir.",
    "Bu tütcen duman kül değil, kolayca tutuşabilen parafin zerrecikleridir.",
    "Mum alevi, parafin zerreciklerini havada asılı tutarak dumanın yeniden tutuşmasını sağlar.",
    "Mum söndüğünde parafin zerrecikleri soğuk havada duman şeklinde yayılır.",
    "Bu zerrecikler hâlâ çok küçük ve kolayca tutuşabilir.",
    "Ateş bu zerreciklere değince zincirleme tepkime başlar.",
    "Yanma için sadece ısı değil, yakıt da şarttır, değil mi? " + CTA,
]
# 65. üretimin metni ve başlıkları (logdan birebir)
URETIM_65 = [
    "Mum söndürülünce çıkan duman neden tekrar alev alır?",
    "Bu duman kül değil, havada asılı kalan parafin zerrecikleridir.",
    "Mum yandıkça eriyen parafin buharlaşır ve havada küçük damlacıklar oluşturur.",
    "Söndürme anında bu zerrecikler hızla soğuyup beyaz duman hâline dönüşür.",
    "Bu duman, alevle temas ettiğinde ortalama beş yüz derece ısıya ulaşır.",
    "Isınan zerrecikler tekrar buharlaşır ve oksijenle tepkimeye girerek yanar.",
    "Yani duman yakıtın kendisidir, kül değil; kendi mumunu dener misin? " + CTA,
]
BASLIKLAR_65 = [("DUMAN NEDEN", "TEKRAR YANAR?"), ("KÜL DEĞİL", "YAKIT DAMLASI"), ("MUM EYİ", "BUHARLAŞIR"),
                ("SOĞUYUP", "BEYAZ DUMAN"), ("ALEVLE", "TEMAS ANI"), ("TEKRAR", "YANAR"), ("YAKIT HÂLÂ", "ORADA")]


def _yazim_canli(uret_mod, ayar: dict) -> dict:
    """Motorun gerçek yazım denetimini bilinen iki hatayla bir kez çalıştırır (R1 + R2 aynı çağrıyı paylaşır)."""
    sahneler = [{"ses": c, "baslik1": b[0], "baslik2": b[1], "ikon": "!"} for c, b in zip(URETIM_64, BASLIKLAR_65)]
    kayit = io.StringIO()
    hata = ""
    try:
        with contextlib.redirect_stdout(kayit):
            uret_mod._yazim_denetimi(sahneler, ayar)
    except BaseException as h:  # noqa: BLE001
        hata = f"{type(h).__name__}: {h}"
    return {"sahneler": sahneler, "kayit": kayit.getvalue(), "hata": hata}


def calistir(ayar: dict | None = None, uret_mod=None) -> list[dict]:
    """Testleri çalıştırır; [{'kod','ad','gecti','ayrinti'}] döndürür. Asla istisna fırlatmaz."""
    sonuc: list[dict] = []

    def ekle(kod, ad, gecti, ayrinti):
        sonuc.append({"kod": kod, "ad": ad, "gecti": bool(gecti), "ayrinti": str(ayrinti)})

    try:
        if uret_mod is None:
            import uret as uret_mod  # noqa: PLC0415
        if ayar is None:
            ayar = json.loads((MOTOR / "ayarlar.json").read_text(encoding="utf-8"))
    except BaseException as h:  # noqa: BLE001
        ekle("R0", "motor yüklenebiliyor", False, f"{type(h).__name__}: {h}")
        return sonuc

    # R1 + R2: gerçek yazım denetimi
    try:
        y = _yazim_canli(uret_mod, ayar)
        metin = " ".join(x["ses"] for x in y["sahneler"])
        son_satirlar = " | ".join(x.strip() for x in y["kayit"].strip().splitlines()[-3:]) or "kayıt yok"
        ipucu = f"DÜZELTİLMEDİ. {y['hata'] or 'Gerçek yazım denetiminin kaydı'}: {son_satirlar}"
        ekle("R1", "'tütcen' düzeltilir", "tütcen" not in metin.lower(),
             "düzeltildi: " + y["sahneler"][0]["ses"] if "tütcen" not in metin.lower() else ipucu)
        b = y["sahneler"][2]["baslik1"]
        ekle("R2", "'MUM EYİ' başlığı yakalanır", b != "MUM EYİ",
             f"düzeltildi: 'MUM EYİ' -> '{b}'" if b != "MUM EYİ" else ipucu)
    except BaseException as h:  # noqa: BLE001
        ekle("R1", "'tütcen' düzeltilir", False, f"{type(h).__name__}: {h}")
        ekle("R2", "'MUM EYİ' başlığı yakalanır", False, f"{type(h).__name__}: {h}")

    # R3 + R4: yapay zekâsız uyarı denetimleri
    try:
        import senaryo_denetim as sd  # noqa: PLC0415
        sayilar = sd.kesin_sayi_bul(URETIM_65)
        ekle("R3", "'beş yüz derece' kesin sayı olarak işaretlenir",
             any(s["cumle"] == 5 and "beş yüz derece" in s["ifade"] for s in sayilar), f"işaretlenenler: {sayilar}")
        terimler = sd.terim_tutarsizligi_bul(URETIM_65)
        ekle("R4", "'zerrecik' + 'damlacık' tutarsızlık uyarısı verir",
             any({"zerrecik", "damlacık"} <= set(t["terimler"]) for t in terimler), f"uyarılar: {terimler}")
    except BaseException as h:  # noqa: BLE001
        ekle("R3", "'beş yüz derece' kesin sayı olarak işaretlenir", False, f"{type(h).__name__}: {h}")
        ekle("R4", "'zerrecik' + 'damlacık' tutarsızlık uyarısı verir", False, f"{type(h).__name__}: {h}")

    # R5: tekrar eden başlangıç
    try:
        tekrar = uret_mod._tekrar_eden_cumleler(URETIM_64)
        ekle("R5", "64'ün neredeyse aynı ilk iki cümlesi yakalanır",
             any((i, j) == (1, 2) for i, j, _ in tekrar), f"yakalanan çiftler (cümle, cümle, benzerlik): {tekrar}")
    except BaseException as h:  # noqa: BLE001
        ekle("R5", "64'ün neredeyse aynı ilk iki cümlesi yakalanır", False, f"{type(h).__name__}: {h}")
    return sonuc


def rapor(sonuc: list[dict]) -> str:
    satirlar = ["REGRESYON TESTLERİ (bilinen hatalar)"]
    for s in sonuc:
        satirlar.append(f"  [{'YEŞİL  ' if s['gecti'] else 'KIRMIZI'}] {s['kod']} {s['ad']} — {s['ayrinti']}")
    yesil = sum(1 for s in sonuc if s["gecti"])
    satirlar.append(f"  Sonuç: {yesil}/{len(sonuc)} yeşil" + ("" if yesil == len(sonuc) else " — MOTOR VİDEO ÜRETMEYECEK"))
    return "\n".join(satirlar)


def hepsi_yesil(sonuc: list[dict]) -> bool:
    return bool(sonuc) and all(s["gecti"] for s in sonuc)


if __name__ == "__main__":
    _s = calistir()
    print(rapor(_s))
    raise SystemExit(0 if hepsi_yesil(_s) else 1)
