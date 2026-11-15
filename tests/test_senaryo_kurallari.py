"""16.11.2026 kuralları: terim birliği, sayı kuralı, başlık anlam uyarısı, özel ad şüphesi, perde uyarısı, maske.
Ağ kullanmaz; yapay zekâ cevapları sahtedir (kuralların kendisi yapay zekâsız denetlenir)."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "motor"))
sys.path.insert(0, str(KOK))

import arsiv  # noqa: E402
import regresyon  # noqa: E402
import senaryo_denetim as sd  # noqa: E402
import ses_olcum  # noqa: E402

try:
    import uret
except Exception as e:  # noqa: BLE001
    raise unittest.SkipTest(f"uret yüklenemedi: {type(e).__name__}")
try:
    import sozluk
    SOZLUK_VAR = sozluk.hazir_mi()[0]
except Exception:  # noqa: BLE001
    SOZLUK_VAR = False
SOZLUK_GEREK = unittest.skipUnless(SOZLUK_VAR, "zemberek-python kurulu değil (motor iş akışında kuruludur)")


def _sahneler(cumleler):
    return [{"ses": c, "baslik1": "A", "baslik2": "B"} for c in cumleler]


def _llm(cevaplar):
    """istem içindeki anahtar söze göre sahte 'cumleler' cevabı döndürür; çağrıları kaydeder."""
    kayit = []

    def sahte(istem, ayar, sistem=None):
        kayit.append(istem)
        for anahtar, cevap in cevaplar:
            if anahtar in istem:
                return {"cumleler": cevap(istem) if callable(cevap) else cevap}
        return {}
    sahte.kayit = kayit
    return sahte


class SayiBulucuTestleri(unittest.TestCase):
    def test_yaklasik_tek_sayi(self):
        bul = lambda c: [(s["ifade"], s["belirtec"]) for s in sd.yaklasik_tek_sayi_bul([c])]  # noqa: E731
        self.assertEqual(bul("Duman ortalama beş yüz derece ısıya ulaşır."), [("beş yüz derece", "ortalama")])
        self.assertEqual(bul("Çapı yaklaşık 2 mikrometre olur."), [("2 mikrometre", "yaklaşık")])
        self.assertEqual(bul("Sıcaklık beş yüz derece civarında kalır."), [("beş yüz derece", "civarında")])
        self.assertEqual(bul("Işık saniyede üç yüz bin kilometre yol alır."), [])
        self.assertEqual(bul("Ortalama bir insan günde iki litre su içer."), [])
        self.assertEqual(bul("Alev yaklaşık dört yüz seksen ile beş yüz otuz derece arasında ısınır."), [])

    def test_aralik_kesin_sayi_sayilmaz(self):
        for c in ("Alev dört yüz seksen ile beş yüz otuz derece arasında ısınır.", "Alev 480-530 derece olur.",
                  "Bunun %20 ile %30 arası yansır."):
            self.assertEqual(sd.kesin_sayi_bul([c]), [], c)
            self.assertEqual(len(sd.aralik_bul([c])), 1, c)
        self.assertEqual([s["ifade"] for s in sd.kesin_sayi_bul(["Su yüz derecede kaynar, yüzde otuzu buharlaşır."])],
                         ["yüz derecede", "yüzde otuz"])

    def test_isimlendirme_listesi(self):
        liste = sd.isimlendirme_listesi(["Parafin zerrecikleri yayılır.", "Zerreciğin boyu küçüktür."])
        self.assertIn("'zerrecik'", liste)
        self.assertIn("damlacık", liste)
        self.assertEqual(sd.isimlendirme_listesi(["Mum söner."]), "")
        self.assertEqual(sd.ana_terim({"zerrecik": [2, 4, 6], "damlacık": [3]}), "zerrecik")
        self.assertEqual(sd.ana_terim({"damlacık": [3], "tanecik": [1]}), "tanecik")


class TerimBirligiTestleri(unittest.TestCase):
    def test_cift_adlandirma_tek_ada_cevrilir(self):
        s = _sahneler(regresyon.URETIM_65)
        llm = _llm([("'damlacık' kelimesi", ["Mum yandıkça eriyen parafin buharlaşır ve havada küçük zerrecikler oluşturur."])])
        with mock.patch.object(uret, "_llm_json", llm), mock.patch("builtins.print"):
            self.assertEqual(uret._terim_birligi_sagla(s, {}, "test"), 1)
        self.assertEqual(sd.terim_tutarsizligi_bul([x["ses"] for x in s]), [])
        self.assertIn("zerrecikler oluşturur", s[2]["ses"])
        self.assertEqual(len(llm.kayit), 1)                       # yalnız hatalı cümle soruldu
        self.assertTrue(s[6]["ses"].endswith("takip et!"))          # diğer cümleler aynı

    def test_duzelmezse_uretim_durur(self):
        for cevap in (["Mum yandıkça eriyen parafin küçük damlacıklar oluşturur."], ["Mum erir."], [""],
                      ["Mum yandıkça eriyen parafin buharlaşır ve havada küçük tanecikler oluşturur."]):
            s = _sahneler(regresyon.URETIM_65)
            with mock.patch.object(uret, "_llm_json", _llm([("kelimesi", cevap)])), mock.patch("builtins.print"):
                with self.assertRaises(uret.SenaryoDuzeltilemedi, msg=str(cevap)):
                    uret._terim_birligi_sagla(s, {}, "test")

    def test_tek_adli_metinde_yapay_zeka_cagrilmaz(self):
        with mock.patch.object(uret, "_llm_json") as llm, mock.patch("builtins.print"):
            self.assertEqual(uret._terim_birligi_sagla(_sahneler(regresyon.URETIM_64), {}, "test"), 0)
        llm.assert_not_called()

    def test_son_kapi(self):
        with mock.patch("builtins.print"):
            uret._senaryo_son_kapi(_sahneler(regresyon.URETIM_64))
            with self.assertRaises(SystemExit):
                uret._senaryo_son_kapi(_sahneler(regresyon.URETIM_65))
            with self.assertRaises(SystemExit):
                uret._senaryo_son_kapi(_sahneler(["Duman ortalama beş yüz derece ısıya ulaşır."]))

    def test_uzatma_farkli_terim_getirirse_reddedilir(self):
        s = _sahneler(["Parafin zerrecikleri havada asılı kalır.", "Mum söner ve duman çıkar.", "Kibrit yaklaşınca tutuşur."])
        istemler = []

        def sahte_uzat(konu, ses, hedef, baglam="", isimler=""):
            istemler.append(isimler)
            return ses.rstrip(".") + " ve küçük damlacıklar hâlinde yavaşça yükselmeye devam eder."
        with mock.patch.object(uret, "_tek_sahne_uzat", sahte_uzat), mock.patch("builtins.print"):
            uret._anlatimi_uzat("mum", s, hedef_toplam=400)
        self.assertEqual(sd.terim_tutarsizligi_bul([x["ses"] for x in s]), [])
        self.assertTrue(all("'zerrecik'" in i for i in istemler))   # isimlendirme listesi isteme eklendi

    def test_kurallar_istemlerde(self):
        self.assertIn("YAKLAŞIK SAYI KURALI", uret.PROMPT_V2)
        self.assertIn("terim", uret.TERIM_KURALLARI.lower())


class SayiDenetimiTestleri(unittest.TestCase):
    ARALIKLI = "Bu duman, alevle temas ettiğinde dört yüz seksen ile beş yüz otuz derece arasında ısıya ulaşır."

    def test_yaklasik_tek_sayi_araliga_cevrilir(self):
        s = _sahneler(regresyon.URETIM_65)
        llm = _llm([("yaklaşık olarak ama", [self.ARALIKLI])])
        with mock.patch.object(uret, "_llm_json", llm), mock.patch("builtins.print"):
            self.assertEqual(uret._sayi_denetimi(s, {}), 1)
        self.assertEqual(s[4]["ses"], self.ARALIKLI)
        self.assertEqual(len(llm.kayit), 1)        # geriye kesin sayı kalmadığı için hakem sorulmadı

    def test_sayi_cikarilarak_da_duzelir(self):
        s = _sahneler(regresyon.URETIM_65)
        llm = _llm([("yaklaşık olarak ama", ["Bu duman, alevle temas ettiğinde çok yüksek bir sıcaklığa ulaşır."])])
        with mock.patch.object(uret, "_llm_json", llm), mock.patch("builtins.print"):
            self.assertEqual(uret._sayi_denetimi(s, {}), 1)

    def test_duzelmezse_uretim_durur(self):
        for cevap in ([regresyon.URETIM_65[4]], ["Bu duman alevle temas ettiğinde yaklaşık altı yüz derece ısıya ulaşır."],
                      ["Bu duman alevle temas edince beş yüz derece ısıya ulaşır."], []):
            s = _sahneler(regresyon.URETIM_65)
            with mock.patch.object(uret, "_llm_json", _llm([("yaklaşık olarak ama", cevap)])), mock.patch("builtins.print"):
                with self.assertRaises(uret.SenaryoDuzeltilemedi, msg=str(cevap)):
                    uret._sayi_denetimi(s, {})

    def _kesin(self):
        return _sahneler(["Mum alevi beş yüz derece ısıya ulaşır.", "Su yüz derecede kaynar.", "Duman yakıttır."])

    def test_hakem_aralik_derse_cumle_aralikla_yazilir(self):
        s = self._kesin()
        llm = _llm([("TEK kesin sayı olarak verilen", ["ARALIK: 480 ile 530 derece", "KESİN"]),
                    ("oysa bu değer bir", ["Mum alevi dört yüz seksen ile beş yüz otuz derece arasında ısıya ulaşır."])])
        with mock.patch.object(uret, "_llm_json", llm), mock.patch("builtins.print"):
            self.assertEqual(uret._sayi_denetimi(s, {}), 1)
        self.assertIn("dört yüz seksen ile beş yüz otuz derece arasında", s[0]["ses"])
        self.assertEqual(s[1]["ses"], "Su yüz derecede kaynar.")    # KESİN denen sayıya dokunulmadı
        self.assertIn("480 ile 530 derece", llm.kayit[1])

    def test_hakem_aralik_der_ama_duzelmezse_durur(self):
        llm = _llm([("TEK kesin sayı olarak verilen", ["ARALIK: 480 ile 530 derece", "KESİN"]),
                    ("oysa bu değer bir", ["Mum alevi beş yüz derece ısıya ulaşır."])])
        with mock.patch.object(uret, "_llm_json", llm), mock.patch("builtins.print"):
            with self.assertRaises(uret.SenaryoDuzeltilemedi):
                uret._sayi_denetimi(self._kesin(), {})

    def test_hakem_calismazsa_ya_da_emin_degilse_yalniz_uyari_kalir(self):
        for llm in (_llm([("TEK kesin sayı olarak verilen", ["KESİN", "BİLİNMİYOR"])]),
                    _llm([("TEK kesin sayı olarak verilen", ["KESİN"])]),          # eksik karar
                    mock.Mock(side_effect=SystemExit("LLM yok"))):
            s = self._kesin()
            with mock.patch.object(uret, "_llm_json", llm), mock.patch("builtins.print"):
                self.assertEqual(uret._sayi_denetimi(s, {}), 0)
            self.assertEqual(s[0]["ses"], "Mum alevi beş yüz derece ısıya ulaşır.")

    def test_sayisiz_metinde_yapay_zeka_cagrilmaz(self):
        with mock.patch.object(uret, "_llm_json") as llm, mock.patch("builtins.print"):
            self.assertEqual(uret._sayi_denetimi(_sahneler(regresyon.URETIM_64), {}), 0)
        llm.assert_not_called()


class BaslikAnlamTestleri(unittest.TestCase):
    def _s(self):
        return [{"ses": "Söndürülen mumun dumanı yanar.", "baslik1": "DUMAN YANAR MI?", "baslik2": "NEDEN BU KADAR"},
                {"ses": "Bu duman kül değildir.", "baslik1": "KÜL DEĞİL", "baslik2": "YAKIT"}]

    def test_yalniz_uyari_yazar_metne_dokunmaz(self):
        s, once = self._s(), json.dumps(self._s(), ensure_ascii=False)
        llm = _llm([("ANLAMLI", ["SORUNLU: ikinci satır yarım kalmış", "UYGUN"])])
        with mock.patch.object(uret, "_llm_json", llm), mock.patch("builtins.print") as yaz:
            uyarilar = uret._baslik_anlam_denetimi(s, {})
        self.assertEqual(len(uyarilar), 1)
        self.assertIn("DUMAN YANAR MI? / NEDEN BU KADAR", uyarilar[0])
        self.assertIn("yarım kalmış", uyarilar[0])
        self.assertEqual(json.dumps(s, ensure_ascii=False), once)
        self.assertTrue(any("UYARI (başlık anlamı)" in str(c.args[0]) for c in yaz.call_args_list))

    def test_hata_olursa_uretim_durmaz(self):
        for llm in (mock.Mock(side_effect=SystemExit("yok")), mock.Mock(return_value={"cumleler": ["UYGUN"]}),
                    mock.Mock(return_value={})):
            with mock.patch.object(uret, "_llm_json", llm), mock.patch("builtins.print"):
                self.assertEqual(uret._baslik_anlam_denetimi(self._s(), {}), [])


@SOZLUK_GEREK
class OzelAdSuphesiTestleri(unittest.TestCase):
    def test_yalniz_ozel_ad_supheli(self):
        self.assertEqual(sozluk.durum("ZERRCİKLER"), "yalnız özel ad olarak tanınıyor")
        self.assertEqual(sozluk.bilinmeyenler("ZERRCİKLER DUMAN"), ["ZERRCİKLER"])
        self.assertEqual(sozluk.durum("EYİ"), "sözlükte yok")

    def test_onayli_ozel_adlar_ve_siradan_kelimeler_gecer(self):
        for b in ["MARS'TA SU", "MARSTA HAYAT", "NASA'NIN SIRRI", "AY'IN SIRRI", "DÜNYA DÖNER", "TÜRKİYE'DE DEPREM",
                  "SATÜRN'ÜN HALKASI", "GÖKKUŞAĞI", "DOPAMİN", "DNA", "PARAFİN ZERRECİĞİ", "BEYNİN TERMOSTAT"]:
            self.assertEqual(sozluk.bilinmeyenler(b), [], b)

    def test_ek_dosyasindan_cikarilan_ozel_ad_supheli_olur(self):
        with mock.patch.dict(sozluk._durum, {"ek": set()}):
            self.assertEqual(sozluk.bilinmeyenler("İSVEÇTE HAYAT"), ["İSVEÇTE"])
        self.assertEqual(sozluk.bilinmeyenler("İSVEÇTE HAYAT"), [])

    def test_duran_uretimde_kelime_dosyaya_not_dusulur_ama_onaylanmaz(self):
        with tempfile.TemporaryDirectory() as td:
            dosya = Path(td) / "ek.txt"
            dosya.write_text("# yorum\nmars\n", encoding="utf-8")
            sahne = [{"ses": "Zerrecikler yayılır.", "baslik1": "ZERRCİKLER", "baslik2": "DUMAN"}]
            with mock.patch.object(sozluk, "EK_DOSYA", dosya), mock.patch.dict(sozluk._durum, {"ek": None}), \
                    mock.patch.dict(os.environ, {"MOTOR_ARSIV_DIR": td, "GITHUB_RUN_NUMBER": "99"}), \
                    mock.patch.object(uret, "_llm_json", return_value={"cumleler": ["ZERRCİKLER"]}), \
                    mock.patch("builtins.print"):
                for _ in range(2):   # ikinci duruşta aynı not yinelenmez
                    with self.assertRaises(uret.BaslikDuzeltilemedi):
                        uret._baslik_denetimi(sahne, {})
                metin = dosya.read_text(encoding="utf-8")
                self.assertEqual(metin.count("ŞÜPHELİ: zerrcikler "), 1)
                self.assertIn("üretim 99", metin)
                self.assertTrue(all(s.startswith("#") for s in metin.splitlines() if "zerrcikler" in s))
                sozluk._durum["ek"] = None
                self.assertEqual(sozluk.bilinmeyenler("ZERRCİKLER"), ["ZERRCİKLER"])   # not, onay değildir
            sozluk._durum["ek"] = None


class PerdeUyarisiTestleri(unittest.TestCase):
    def test_sapma_esigi(self):
        self.assertTrue(ses_olcum.perde_sapmasi(112.1)["uyari"])          # -11,7 %
        self.assertEqual(ses_olcum.perde_sapmasi(112.1)["sapma_yuzde"], -11.7)
        self.assertFalse(ses_olcum.perde_sapmasi(127.0)["uyari"])
        self.assertFalse(ses_olcum.perde_sapmasi(115.0)["uyari"])         # -9,4 %
        self.assertFalse(ses_olcum.perde_sapmasi(139.0)["uyari"])         # +9,4 %
        self.assertTrue(ses_olcum.perde_sapmasi(141.0)["uyari"])          # +11,0 %
        self.assertEqual((ses_olcum.TABAN_F0_HZ, ses_olcum.SAPMA_ESIGI), (127.0, 0.10))

    def test_kayit_satiri(self):
        o = {"f0_medyan_hz": 112.1, "f0_yuzde10_hz": 77.2, "f0_yuzde90_hz": 172.7, "sure_sn": 36.05}
        with tempfile.TemporaryDirectory() as td:
            yol = Path(td) / "k.csv"
            with mock.patch.dict(os.environ, {"GITHUB_RUN_NUMBER": "70"}):
                self.assertTrue(ses_olcum.perde_kaydet(o, yol))
                self.assertTrue(ses_olcum.perde_kaydet(o, yol))
            satirlar = yol.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(satirlar), 3)
            self.assertTrue(satirlar[0].startswith("tarih_utc,uretim_no,ham_f0_medyan_hz"))
            self.assertIn(",70,112.1,127,-11.7,EVET,", satirlar[1])

    def test_uretim_disinda_depodaki_kayda_yazilmaz(self):
        ortam = {k: v for k, v in os.environ.items() if k not in ("GITHUB_RUN_NUMBER", "MOTOR_PERDE_KAYDI")}
        with mock.patch.dict(os.environ, ortam, clear=True):
            self.assertFalse(ses_olcum.perde_kaydet({"f0_medyan_hz": 1, "f0_yuzde10_hz": 1, "f0_yuzde90_hz": 1, "sure_sn": 1}))

    def test_sapmada_uyari_yazilir_uretim_durmaz(self):
        import tts
        with tempfile.TemporaryDirectory() as td:
            cikti = Path(td) / "vo.wav"
            cikti.write_bytes(b"RIFF")
            olcu = {"dosya": "x", "ornekleme_hz": 24000, "sure_sn": 30.0, "f0_medyan_hz": 112.1, "f0_yuzde10_hz": 77.0,
                    "f0_yuzde90_hz": 172.0, "f0_pencere_sayisi": 800, "parlaklik_hz": 850.0, "rms_db": -14.0}
            arsiv._durum.update({"klasor": None, "sira": 0})
            with mock.patch.dict(os.environ, {"MOTOR_ARSIV_DIR": td, "MOTOR_PERDE_KAYDI": str(Path(td) / "k.csv")}), \
                    mock.patch.dict(tts._SON_HAM_SES, {"yol": str(cikti)}), \
                    mock.patch.object(ses_olcum, "olc", return_value=olcu), mock.patch("builtins.print") as yaz:
                tts._arsiv_ses_olcumu(cikti)          # istisna fırlatmaz = üretim durmaz
            arsiv._durum.update({"klasor": None, "sira": 0})
            cikti_metni = "\n".join(str(c.args[0]) for c in yaz.call_args_list)
        self.assertIn("UYARI: ses perdesi sapması", cikti_metni)
        self.assertIn("sapma=-11.7%", cikti_metni)


class MaskeTestleri(unittest.TestCase):
    def test_groq_kurulus_kimligi_ve_anahtarlar_maskelenir(self):
        ham = ('v2 LLM HTTP 429: {"error":{"message":"Rate limit reached in organization `org_01abcdefghijklmnopqrstuvwx` '
               'key gsk_' + "a" * 40 + ' AIza' + "b" * 35 + ' 1234567890:AA' + "c" * 33 + '"}}')
        temiz = arsiv.maskele(ham)
        for iz in ("org_01abc", "gsk_aaaa", "AIzabbb", "1234567890:AAccc"):
            self.assertNotIn(iz, temiz)
        self.assertIn("Rate limit reached", temiz)

    def test_konsol_ciktisi_maskelenir(self):
        tampon = io.StringIO()
        with mock.patch.object(sys, "stdout", tampon):
            arsiv.cikti_maskele_kur()
            arsiv.cikti_maskele_kur()               # iki kez kurulsa da tek sarmal
            print("hata: organization org_01abcdefghijklmnopqrstuvwx bitti")
            self.assertIsInstance(sys.stdout, arsiv._MaskeliAkis)
            self.assertNotIsInstance(sys.stdout._akis, arsiv._MaskeliAkis)
        self.assertNotIn("org_01abc", tampon.getvalue())
        self.assertIn("hata: organization [MASKELENDI] bitti", tampon.getvalue())


if __name__ == "__main__":
    unittest.main()
