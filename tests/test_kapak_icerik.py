"""Kapak içeriği: tek cümlelik 3 satır başlık, sarı vurgu satırı, konuya özel kategori, kapak görseli seçimi."""
import sys
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "motor"))
sys.path.insert(0, str(KOK))

import kapak  # noqa: E402

KONU = "Mum söndürülünce çıkan beyaz duman neden yanar?"


class KapakMetniTestleri(unittest.TestCase):
    def test_tek_soru_basligi_ve_vurgu_satiri_kullanilir(self):
        b = kapak.kapak_metni_hazirla(KONU, [], {"kapak_satirlari": ["SÖNEN MUMUN", "BEYAZ DUMANI", "NEDEN YANAR?"],
                                                 "kapak_vurgu": 2, "kapak_kategori": "Kimya ve Yanma"})
        self.assertEqual(b["satirlar"], ["SÖNEN MUMUN", "BEYAZ DUMANI", "NEDEN YANAR?"])
        self.assertEqual(b["vurgu"], 1)
        self.assertEqual(b["kategori"], "KİMYA & YANMA")

    def test_iki_ayri_soz_reddedilir_konu_sorusu_yazilir(self):
        b = kapak.kapak_metni_hazirla(KONU, [], {"kapak_satirlari": ["BEYAZ DUMAN", "YAKIT MIDIR?", "ALEV İNİYOR"],
                                                 "kapak_vurgu": 3})
        self.assertNotIn("ALEV İNİYOR", b["satirlar"])
        self.assertTrue(b["satirlar"][-1].endswith("?"))
        self.assertEqual(" ".join(b["satirlar"]), kapak.tr_upper(KONU))
        self.assertIsNone(b["vurgu"])

    def test_gecersiz_vurgu_son_satira_duser(self):
        for v in (None, 0, 4, "x"):
            b = kapak.kapak_metni_hazirla(KONU, [], {"kapak_satirlari": ["SÖNEN MUMUN", "BEYAZ DUMANI", "NEDEN YANAR?"],
                                                     "kapak_vurgu": v})
            self.assertIsNone(b["vurgu"])

    def test_kategori_konuya_ozel_ya_da_konudan(self):
        self.assertEqual(kapak.kategori_etiketi_sec("x", "ANATOMİ & AKUSTİK"), "ANATOMİ & AKUSTİK")
        # genel/şablon etiketler kabul edilmez -> konudan seçilir
        self.assertEqual(kapak.kategori_etiketi_sec(KONU, "Bilim ve Teknoloji"), "FİZİK & BİLİM")
        self.assertEqual(kapak.kategori_etiketi_sec(KONU, "KONUYA ÖZEL ALAN ETİKETİ"), "FİZİK & BİLİM")
        # 'yaKAN', 'KANıt', 'KASım' artık İNSAN & BİLİM'e götürmez; gerçek kelimeler götürür
        self.assertEqual(kapak.kategori_etiketi_sec("Yakan kanıt Kasım ayında"), "FİZİK & BİLİM")
        self.assertEqual(kapak.kategori_etiketi_sec("Kan neden kırmızı?"), "İNSAN & BİLİM")
        self.assertEqual(kapak.kategori_etiketi_sec("Ay'ın karanlık yüzü"), "UZAY & EVREN")

    def test_aciklama_metni_kategoriyi_etkilemez(self):
        b = kapak.kapak_metni_hazirla(KONU, [], {"aciklama": "İnsan vücudu ve kalp hakkında.", "kategori": "Eğitim"})
        self.assertEqual(b["kategori"], "FİZİK & BİLİM")


class KapakGorseliSecimTestleri(unittest.TestCase):
    def setUp(self):
        try:
            import uret
        except Exception as e:  # noqa: BLE001
            raise unittest.SkipTest(f"uret yüklenemedi: {type(e).__name__}")
        self.uret = uret
        import tempfile
        from PIL import Image
        self.klasor = tempfile.TemporaryDirectory()
        self.yollar = []
        for i in range(3):
            y = Path(self.klasor.name) / f"s{i + 1}.jpg"
            Image.new("RGB", (108, 192), (40 * i, 20, 20)).save(y)
            self.yollar.append(y)

    def tearDown(self):
        self.klasor.cleanup()

    def _sahte(self, cevap_metni):
        import io, json

        def urlopen(istek, *a, **kw):
            if isinstance(istek, str):
                govde = {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]}]}
            else:
                govde = {"candidates": [{"content": {"parts": [{"text": cevap_metni}]}}]}
            yanit = io.BytesIO(json.dumps(govde).encode())
            yanit.__enter__ = lambda s=yanit: s
            yanit.__exit__ = lambda *a: False
            return yanit
        return urlopen

    def test_anahtar_yoksa_ilk_gorsel(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            self.assertEqual(self.uret._kapak_gorseli_sec("Mum", self.yollar), self.yollar[0])

    def test_secilen_gorsel_kullanilir(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "x"}), mock.patch("builtins.print"), \
                mock.patch("urllib.request.urlopen", self._sahte('{"secim": 3}')):
            self.assertEqual(self.uret._kapak_gorseli_sec("Mum", self.yollar), self.yollar[2])

    def test_bozuk_cevap_ya_da_hata_uretimi_durdurmaz(self):
        for cevap in ('{"secim": 9}', "saçma", '{"secim": "x"}'):
            with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "x"}), mock.patch("builtins.print"), \
                    mock.patch("urllib.request.urlopen", self._sahte(cevap)):
                self.assertEqual(self.uret._kapak_gorseli_sec("Mum", self.yollar), self.yollar[0])
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "x"}), mock.patch("builtins.print"), \
                mock.patch("urllib.request.urlopen", side_effect=OSError("ağ yok")):
            self.assertEqual(self.uret._kapak_gorseli_sec("Mum", self.yollar), self.yollar[0])


if __name__ == "__main__":
    unittest.main()
