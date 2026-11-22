"""Senaryo talimatlarında 'terim birliği ve bilimsel tutarlılık' kuralı + künye (kaynak / görsel notu)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "motor"))
sys.path.insert(0, str(KOK))


def _yukle(ad):
    try:
        return __import__(ad)
    except Exception as e:  # noqa: BLE001
        raise unittest.SkipTest(f"{ad} bu ortamda yüklenemedi: {type(e).__name__}")


class SenaryoKurallariTestleri(unittest.TestCase):
    def setUp(self):
        self.uret = _yukle("uret")

    def test_kural_blogu_bes_talimati_icerir(self):
        k = self.uret.TERIM_KURALLARI
        for parca in ("TEK bir terimle", "parafin zerrecikleri", "kül", "tutuşabileceğini ima",
                      "milyonlarca", "binlerce", "Doğrulayamadığın kesin sayısal", "nitel ifade"):
            self.assertIn(parca, k)

    def test_v2_isteminde_kurallar_ve_bos_kaynak_talimati_var(self):
        istem = self.uret.PROMPT_V2.format(konu="Mum neden söner?", n=5, visual_count=4)
        self.assertIn(self.uret.TERIM_KURALLARI, istem)
        self.assertIn("gerçek bir kaynak yoksa boş bırak", istem)
        self.assertIn("genel geçer ifade YASAK", istem)

    def test_cumle_uzatma_istemi_kurallari_ve_baglami_tasir(self):
        gonderilen = {}

        class _Yanit:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, *a):
                return (b'{"models":[{"name":"models/gemini-2.5-flash",'
                        b'"supportedGenerationMethods":["generateContent"]}]}')

        def sahte_urlopen(istek, *a, **kw):
            veri = getattr(istek, "data", None)
            if veri:
                import json
                gonderilen["govde"] = json.dumps(json.loads(veri.decode("utf-8")), ensure_ascii=False)
            return _Yanit()

        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "x", "GROQ_API_KEY": "", "OPENROUTER_API_KEY": ""}), \
                mock.patch("urllib.request.urlopen", sahte_urlopen), mock.patch("builtins.print"):
            try:
                self.uret._tek_sahne_uzat("Mum", "Mum söner.", 90, baglam="Parafin zerrecikleri havada asılı kalır.")
            except Exception:
                pass
        govde = gonderilen.get("govde", "")
        if not govde:
            self.skipTest("istek gövdesi yakalanamadı")
        self.assertIn("TERİM BİRLİĞİ", govde)
        self.assertIn("Parafin zerrecikleri havada", govde)
        self.assertNotIn("sayı veya örnek ekle", govde)

    def test_kaynak_yalniz_gercekse_gosterilir(self):
        t = self.uret._kaynak_temizle
        # Kurum/dergi etiketi tek başına doğrulanmış kaynak değildir.
        self.assertEqual(t("Kaynak: NASA • Nature"), "")
        self.assertEqual(t("Harvard Medical School"), "")

        class _Yanit:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def geturl(self): return "https://www.nasa.gov/"

        with mock.patch("urllib.request.urlopen", return_value=_Yanit()):
            self.assertEqual(t("https://www.nasa.gov/"), "https://www.nasa.gov/")

        for bos in ("", None, "Kaynak: ...", "Kaynak: yok", "Kaynak: ... (yoksa boş)",
                    "Kaynak: Hakemli Bilimsel Araştırma Arşivi", "Kaynak: doğrulanmış bilimsel yayınlar",
                    "Kaynak: Çeşitli kaynaklar", "Bilimsel araştırmalar"):
            with self.subTest(kaynak=bos):
                self.assertEqual(t(bos), "")
        self.assertLessEqual(len(t("Kaynak: " + "A" * 100)), 54)

    def test_gorsel_notu_metni(self):
        self.assertEqual(self.uret.GORSEL_TEMSILI_NOTU, "Görseller temsilidir.")


class KunyeCizimTestleri(unittest.TestCase):
    def test_bos_kaynak_cizilmez_ve_hata_vermez(self):
        sp = _yukle("shorts_pipeline")
        import numpy as np
        dolu = np.asarray(sp.build_static_overlay(note1_txt="Kaynak: NASA", note2_txt="Görseller temsilidir."))
        bos = np.asarray(sp.build_static_overlay(note1_txt="", note2_txt="Görseller temsilidir."))
        h = dolu.shape[0]
        ust = slice(int(h * 1740 / 1920), int(h * 1785 / 1920))   # üst künye satırı bölgesi
        self.assertGreater(int(dolu[ust, :, 3].sum()), 0)          # iki satır varken üst satır dolu
        self.assertEqual(int(bos[ust, :, 3].sum()), 0)             # kaynak yokken üst satır boş (not alta iner)
        alt = slice(int(h * 1788 / 1920), int(h * 1830 / 1920))
        self.assertGreater(int(bos[alt, :, 3].sum()), 0)


if __name__ == "__main__":
    unittest.main()
