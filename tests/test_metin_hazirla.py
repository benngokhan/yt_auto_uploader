"""Seslendirme öncesi metin hazırlığı + ses ayarlarının ayarlar.json'a taşınması.

unittest ile yazıldı: yükleme işindeki `python -m unittest discover -s tests` kapısında da çalışır.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "motor"))
sys.path.insert(0, str(KOK))
import metin_hazirla as m  # noqa: E402

AYAR = json.loads((KOK / "motor" / "ayarlar.json").read_text(encoding="utf-8"))


def _yukle(ad):
    """Ağır bağımlılığı olan motor modülünü yükler; ortamda yoksa testi atlar."""
    try:
        return __import__(ad)
    except Exception as e:  # noqa: BLE001
        raise unittest.SkipTest(f"{ad} bu ortamda yüklenemedi: {type(e).__name__}")


class MetinHazirlikTestleri(unittest.TestCase):
    def _esit(self, ciftler, ayar=AYAR):
        for girdi, beklenen in ciftler:
            with self.subTest(girdi=girdi):
                # Küçük harfli bir kelimeden sonra geldiğinde çeviri aynen beklenir
                self.assertEqual(m.hazirla("ve " + girdi, ayar), "ve " + beklenen)

    def test_sayilar(self):
        self._esit([
            ("13", "on üç"), ("2,5", "iki virgül beş"), ("%50", "yüzde elli"), ("14:30", "on dört otuz"),
            ("29.10.1923", "yirmi dokuz Ekim bin dokuz yüz yirmi üç"),
            ("0", "sıfır"), ("1000", "bin"), ("1.500", "bin beş yüz"), ("2026", "iki bin yirmi altı"),
            ("1.250.000", "bir milyon iki yüz elli bin"), ("0,05", "sıfır virgül sıfır beş"),
            ("50%", "yüzde elli"), ("%2,5", "yüzde iki virgül beş"), ("%50'si", "yüzde ellisi"),
            ("%30-45", "yüzde otuz ile kırk beş"), ("09:05", "dokuz sıfır beş"), ("14:00'te", "on dörtte"),
            ("13'ü", "on üçü"), ("1923'te", "bin dokuz yüz yirmi üçte"), ("-5 derece", "eksi beş derece"),
            ("3. sırada", "üçüncü sırada"), ("19. yy. başında", "on dokuzuncu yüzyıl başında"),
            ("1/3", "üçte bir"), ("3/4", "dörtte üç"), ("007", "sıfır sıfır yedi"),
            ("15/04/2021", "on beş Nisan iki bin yirmi bir"),
        ])

    def test_kisaltmalar_ve_birimler(self):
        self._esit([
            ("3 dk", "üç dakika"), ("45 sn", "kırk beş saniye"), ("5 km", "beş kilometre"),
            ("5km", "beş kilometre"), ("10 km'lik yol", "on kilometrelik yol"),
            ("90 km/sa hızla", "saatte doksan kilometre hızla"), ("25°C", "yirmi beş derece"),
            ("100 m", "yüz metre"), ("$5", "beş dolar"),
            ("elma vb. meyveler", "elma vesaire meyveler"),
            ("elma, armut vb. Sonra gitti.", "elma, armut vesaire. Sonra gitti."),
            ("Dr. Ali", "Doktor Ali"), ("20 dk. sürdü", "yirmi dakika sürdü"),
            ("24/7 açık", "yedi gün yirmi dört saat açık"),
        ])

    def test_harfe_bitisik_rakamlar_dokunulmaz(self):
        for x in ("B12 vitamini", "H2O", "5G", "4K video", "COVID-19", "A4 kâğıt"):
            with self.subTest(girdi=x):
                self.assertEqual(m.hazirla(x, AYAR), x)

    def test_cumle_sonu_noktasi_korunur(self):
        self.assertEqual(m.hazirla("Yaşı 13. Sonra büyüdü.", AYAR), "Yaşı on üç. Sonra büyüdü.")

    def test_istisna_listesi(self):
        ayar = {"metin_hazirlik": {"istisnalar": ["iPhone 15", "Windows 11"]}}
        self.assertEqual(m.hazirla("iPhone 15 ile 5 km koştu, Windows 11 kurdu.", ayar),
                         "iPhone 15 ile beş kilometre koştu, Windows 11 kurdu.")
        self.assertEqual(m.hazirla("iPhone 15", {}), "iPhone on beş")

    def test_cumle_basindaki_sayi_buyuk_harfle_baslar(self):
        self.assertEqual(m.hazirla("13 kişi geldi. 2 kişi gitti.", AYAR), "On üç kişi geldi. İki kişi gitti.")
        self.assertEqual(m.hazirla("%50 arttı. 14:30'da bitti. iPhone aldı.", AYAR),
                         "Yüzde elli arttı. On dört otuzda bitti. iPhone aldı.")

    def test_listeler_ayardan_genisletilir(self):
        ayar = {"metin_hazirlik": {"kisaltmalar": {"TBMM": "Türkiye Büyük Millet Meclisi"},
                                   "birimler": {"au": "astronomik birim"}}}
        self.assertEqual(m.hazirla("TBMM 3 au uzakta", ayar),
                         "Türkiye Büyük Millet Meclisi üç astronomik birim uzakta")

    def test_kapatilabilir_ve_hata_uretimi_durdurmaz(self):
        self.assertEqual(m.hazirla("13 km", {"metin_hazirlik": {"etkin": False}}), "13 km")
        self.assertEqual(m.hazirla("", {}), "")
        with mock.patch.object(m, "_tarihler", side_effect=RuntimeError("x")), mock.patch("builtins.print"):
            self.assertEqual(m.hazirla("13 km", {}), "13 km")

    def test_ayar_dosyasindaki_listeler_kod_varsayilaniyla_ayni(self):
        b = AYAR["metin_hazirlik"]
        self.assertEqual(b["kisaltmalar"], m.VARSAYILAN_KISALTMALAR)
        self.assertEqual(b["birimler"], m.VARSAYILAN_BIRIMLER)


class TasinanSesAyarlariTestleri(unittest.TestCase):
    """Değerler eski gömülü değerlerle birebir aynı olmalı; yalnız yerleri değişti."""

    def test_ayar_dosyasindaki_degerler(self):
        sk = AYAR["ses"]["sessizlik_kisaltma"]
        self.assertEqual((sk["esik_db"], sk["cerceve_ms"], sk["en_uzun_sessizlik_cerceve"],
                          sk["korunan_bas_cerceve"], sk["korunan_son_cerceve"]), (-44.0, 20, 26, 13, 13))
        self.assertEqual(int(round(24000 * sk["cerceve_ms"] / 1000.0)), 480)
        self.assertEqual(AYAR["miks"]["cumle_arasi_es_sn"], 0.54)
        self.assertEqual(AYAR["miks"]["muzik_kisma_tabani"], 0.135)
        self.assertEqual(AYAR["miks"]["hedef_ses_yuksekligi_lufs"], -14.2)

    def test_ton_zinciri_birebir_ayni(self):
        tts = _yukle("tts")
        eski = ["highpass=f=75", "equalizer=f=280:t=q:width=1.2:g=-1.2", "equalizer=f=3300:t=q:width=1.1:g=1.8"]
        self.assertEqual(tts._ton_zinciri(AYAR["ses"]), eski)   # ayar dosyasından
        self.assertEqual(tts._ton_zinciri({}), eski)            # bölüm yoksa varsayılan

    def test_montaj_sabitleri_birebir_ayni(self):
        sp = _yukle("shorts_pipeline")
        self.assertEqual((sp.DEFAULT_SENT_PAUSE, sp.DUCK_FLOOR, sp.TARGET_LUFS), (0.54, 0.135, -14.2))

    def test_hazirlik_tek_yerden_her_motor_icin_cagrilir(self):
        tts = _yukle("tts")
        with tempfile.TemporaryDirectory() as gecici:
            for saglayici, ad in (("gemini_tts", "_gemini_tts"), ("edge", "_edge_tts"),
                                  ("xtts", "_xtts"), ("elevenlabs", "_elevenlabs")):
                with self.subTest(saglayici=saglayici), mock.patch.object(tts, ad) as motor, \
                        mock.patch.object(tts, "_ses_kontrol"):
                    tts.uret("%50 ve 13 km", Path(gecici) / "a.wav", {"ses": {"saglayici": saglayici}})
                    self.assertEqual(motor.call_args[0][0], "Yüzde elli ve on üç kilometre")


if __name__ == "__main__":
    unittest.main()
