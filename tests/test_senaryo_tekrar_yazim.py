"""Senaryo: tekrar eden cümle koruması + seslendirme öncesi yazım denetimi (64. üretimdeki hatalar)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "motor"))
sys.path.insert(0, str(KOK))

try:
    import uret
except Exception as e:  # noqa: BLE001
    raise unittest.SkipTest(f"uret yüklenemedi: {type(e).__name__}")

CTA = "Daha fazla Bilgi Dozu için takip et!"
# 64. üretimin gerçek metni (ilk iki cümle birbirinin tekrarıydı)
URETIM_64 = [
    "Söndürülen mumun tütücen duman kül değil, kolayca tutuşabilen yakıt zerrecikleridir.",
    "Bu tütücen duman kül değil, kolayca tutuşabilen parafin zerrecikleridir.",
    "Mum alevi parafin zerreciklerini havada asılı tutarak dumanın yeniden tutuşmasını sağlar.",
    "Mum söndüğünde parafin zerrecikleri soğuk havada duman şeklinde yayılır.",
    "Bu zerrecikler hala çok küçük ve kolayca tutuşabilir.",
    "Ateş bu zerreciklere değince zincirleme tepkime başlar.",
    "Yanma için sadece ısı değil, yakıt da şarttır değil mi? " + CTA,
]


def _sahneler(cumleler):
    return [{"ses": c, "baslik1": "ALEV SÖNDÜ", "baslik2": "ZERRCİKLER DUMAN", "ikon": "!"} for c in cumleler]


class TekrarTestleri(unittest.TestCase):
    def test_64_uretimdeki_cift_baslangic_yakalanir(self):
        self.assertEqual([(i, j) for i, j, _ in uret._tekrar_eden_cumleler(URETIM_64)], [(1, 2)])

    def test_ayni_konudaki_farkli_cumleler_tekrar_sayilmaz(self):
        self.assertEqual(uret._tekrar_eden_cumleler(URETIM_64[1:]), [])

    def test_plan_tekrar_varsa_yeniden_istenir(self):
        iyi = [URETIM_64[0]] + URETIM_64[2:6] + ["Peki bu duman olmasa alev mumu bulabilir miydi?", "Yanma için yakıt şarttır."]
        cevaplar = [{"cumleler": URETIM_64, "kapak_baslik": ["A", "B"]}, {"cumleler": iyi, "kapak_baslik": ["A", "B"]}]
        istemler = []

        def sahte(istem, ayar, sistem=None):
            istemler.append(istem)
            return cevaplar[min(len(istemler) - 1, 1)]

        with mock.patch.object(uret, "_llm_json", sahte), mock.patch("builtins.print"):
            plan = uret.sahne_plani_v2("Mum dumanı neden yanar?", 7, {})
        self.assertEqual(len(istemler), 2)
        self.assertIn("ÖNCEKİ DENEMEDE", istemler[1])
        self.assertEqual(uret._tekrar_eden_cumleler([p["ses"] for p in plan]), [])

    def test_uzatma_baska_cumleyi_tekrar_ederse_reddedilir(self):
        sahneler = _sahneler(["Sönen mumun dumanı kül değil, kolayca tutuşabilen yakıt zerrecikleridir.", "Duman yanar."])
        with mock.patch.object(uret, "_tek_sahne_uzat", return_value=URETIM_64[1]), mock.patch("builtins.print"):
            uret._anlatimi_uzat("Mum", sahneler, hedef_toplam=400)
        self.assertEqual(sahneler[1]["ses"], "Duman yanar.")

    def test_kurallarda_tekrar_ve_yazim_maddesi_var(self):
        self.assertIn("TEKRAR YOK", uret.TERIM_KURALLARI)
        self.assertIn("YAZIM", uret.TERIM_KURALLARI)


class YazimDenetimiTestleri(unittest.TestCase):
    def _calistir(self, sahneler, cevap):
        with mock.patch.object(uret, "_llm_json", return_value=cevap), mock.patch("builtins.print"):
            return uret._yazim_denetimi(sahneler, {})

    def test_yazim_hatasi_duzeltilir_cta_korunur(self):
        s = _sahneler(URETIM_64)
        yeni = [c.replace(CTA, "").strip().replace("tütücen", "tüten") for c in URETIM_64]
        n = self._calistir(s, {"cumleler": yeni, "basliklar": [["ALEV SÖNDÜ", "ZERRECİKLER DUMAN"]] * 7})
        self.assertEqual(n, 2 + 7)
        self.assertNotIn("tütücen", " ".join(x["ses"] for x in s))
        self.assertTrue(s[-1]["ses"].endswith(CTA))
        self.assertEqual(s[2]["ses"], URETIM_64[2])
        self.assertEqual(s[0]["baslik2"], "ZERRECİKLER DUMAN")

    def test_yeniden_yazma_kabul_edilmez(self):
        s = _sahneler(URETIM_64)
        yeni = ["Bambaşka ve yepyeni bir cümle yazdım, hiç ilgisi yok."] * 7
        self.assertEqual(self._calistir(s, {"cumleler": yeni, "basliklar": [["YENİ BAŞLIK", "BAMBAŞKA SÖZ"]] * 7}), 0)
        self.assertEqual([x["ses"] for x in s], URETIM_64)

    def test_bozuk_cevap_ya_da_hata_uretimi_durdurmaz(self):
        for cevap in ({}, {"cumleler": ["tek"]}, {"cumleler": None, "basliklar": "x"}, []):
            s = _sahneler(URETIM_64)
            self.assertEqual(self._calistir(s, cevap), 0)
            self.assertEqual([x["ses"] for x in s], URETIM_64)
        s = _sahneler(URETIM_64)
        with mock.patch.object(uret, "_llm_json", side_effect=SystemExit("LLM yok")), mock.patch("builtins.print"):
            self.assertEqual(uret._yazim_denetimi(s, {}), 0)


if __name__ == "__main__":
    unittest.main()
