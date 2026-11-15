"""Üretim arşivi, uyarı denetimleri ve açılış regresyon kapısı (mekanizma testleri; ağ kullanmaz)."""
import base64
import io
import json
import os
import re
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

try:
    import uret
except Exception as e:  # noqa: BLE001
    raise unittest.SkipTest(f"uret yüklenemedi: {type(e).__name__}")


class _ArsivOrtami(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.yama = mock.patch.dict(os.environ, {"MOTOR_ARSIV_DIR": self.td.name})
        self.yama.start()
        arsiv._durum.update({"klasor": None, "sira": 0})

    def tearDown(self):
        self.yama.stop()
        arsiv._durum.update({"klasor": None, "sira": 0})
        self.td.cleanup()

    def dosyalar(self, parca=""):
        return sorted(p for p in Path(self.td.name).iterdir() if parca in p.name)


class ArsivTestleri(_ArsivOrtami):
    def test_dosya_adi_sira_ve_zaman_damgasi_tasir(self):
        y = arsiv.yaz("senaryo_1_plan_sonrasi", "metin")
        self.assertRegex(y.name, r"^01_senaryo_1_plan_sonrasi_\d{8}T\d{6}Z\.txt$")
        self.assertEqual(arsiv.yaz_json("x", {"a": 1}).name[:5], "02_x_")

    def test_gizli_bilgi_maskelenir(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "cokgizlianahtar123"}):
            y = arsiv.yaz("t", "adres?key=cokgizlianahtar123 ve ghp_" + "a" * 30)
        metin = y.read_text(encoding="utf-8")
        self.assertNotIn("cokgizlianahtar123", metin)
        self.assertNotIn("ghp_a", metin)

    def test_arsiv_hatasi_uretimi_durdurmaz(self):
        with mock.patch.dict(os.environ, {"MOTOR_ARSIV_DIR": "/proc/yazilamaz/klasor"}):
            arsiv._durum.update({"klasor": None, "sira": 0})
            self.assertIsNone(arsiv.yaz("t", "x"))
            self.assertIsNone(arsiv.pcm_wav_yaz("t", b"\x00\x00"))
            self.assertIsNone(arsiv.baslat("konu"))

    def test_gemini_istegi_bayti_baytina_ve_ham_ses_islenmeden_arsivlenir(self):
        import tts
        import numpy as np
        pcm = (np.sin(np.arange(24000 * 2) * 2 * np.pi * 120 / 24000) * 9000).astype("<i2").tobytes()
        giden = {}

        class _Yanit(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def sahte(istek, *a, **k):
            giden["govde"] = istek.data
            return _Yanit(json.dumps({"candidates": [{"content": {"parts": [
                {"inlineData": {"data": base64.b64encode(pcm).decode()}}]}}]}).encode())

        ayar = json.loads((KOK / "motor" / "ayarlar.json").read_text(encoding="utf-8"))
        cikti = Path(self.td.name) / "calisma" / "vo.wav"
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "sahte-anahtar-0123456789"}), \
                mock.patch("urllib.request.urlopen", sahte), mock.patch("builtins.print"), \
                mock.patch.object(tts, "_ses_kontrol", lambda a: None):
            try:
                tts.uret("Su 100 derecede kaynar. Bu bir denemedir.", cikti, ayar)
            except Exception as h:  # ffmpeg/soundfile yoksa son işleme düşebilir; arşiv ondan önce yazılır
                self.skip_nedeni = repr(h)
        once = self.dosyalar("on_isleme_ONCESI")[0].read_text(encoding="utf-8")
        sonra = self.dosyalar("on_isleme_SONRASI")[0].read_text(encoding="utf-8")
        self.assertIn("100 derecede", once)
        self.assertIn("yüz derecede", sonra)
        self.assertEqual(self.dosyalar("istek_govdesi_KESIN")[0].read_bytes(), giden["govde"])
        self.assertNotIn("sahte-anahtar", self.dosyalar("istek_bilgisi")[0].read_text(encoding="utf-8"))
        import wave
        with wave.open(str(self.dosyalar("ham_tts_gemini")[0])) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (24000, 1, 2))
            self.assertEqual(w.readframes(w.getnframes()), pcm)


class UyariDenetimiTestleri(unittest.TestCase):
    def test_kesin_sayi_isaretlenir_belirsiz_ifade_isaretlenmez(self):
        ifadeler = [s["ifade"] for s in sd.kesin_sayi_bul([
            "Bu duman ortalama beş yüz derece ısıya ulaşır.", "Bunlar 2 mikrometre çapındadır; %30'u yansır.",
            "Birkaç saniye içinde, çok küçük, milyonlarca tanecik, bir saniye bekle."])]
        self.assertIn("beş yüz derece", ifadeler)
        self.assertIn("2 mikrometre", ifadeler)
        self.assertIn("%30", ifadeler)
        self.assertEqual(len(ifadeler), 3)

    def test_terim_tutarsizligi(self):
        self.assertTrue(sd.terim_tutarsizligi_bul(["Parafin zerrecikleri yayılır.", "Küçük damlacıklar oluşur."]))
        self.assertEqual(sd.terim_tutarsizligi_bul(["Parafin zerrecikleri yayılır.", "Bu zerreciğin boyu küçüktür."]), [])
        self.assertEqual(sd.uyarilar(regresyon.URETIM_64), [])
        self.assertEqual(len(sd.uyarilar(regresyon.URETIM_65)), 2)


class RegresyonKapisiTestleri(_ArsivOrtami):
    @staticmethod
    def _duzelten(istem, ayar, sistem=None):
        c = json.loads(re.search(r"cumleler: (\[.*\])\n", istem).group(1))
        b = json.loads(re.search(r"basliklar: (\[.*\])\n", istem).group(1))
        return {"cumleler": [x.replace("tütcen", "tüten") for x in c],
                "basliklar": [["MUM ERİR" if s == "MUM EYİ" else s for s in cift] for cift in b]}

    def test_yazim_denetimi_duzeltirse_hepsi_yesil_ve_kapi_gecer(self):
        with mock.patch.object(uret, "_llm_json", self._duzelten), mock.patch("builtins.print"):
            sonuc = regresyon.calistir({}, uret)
            self.assertEqual([s["kod"] for s in sonuc], ["R1", "R2", "R3", "R4", "R5"])
            self.assertTrue(regresyon.hepsi_yesil(sonuc), regresyon.rapor(sonuc))
            uret._regresyon_kapisi({})
        self.assertIn("5/5 yeşil", self.dosyalar("regresyon_sonuclari")[0].read_text(encoding="utf-8"))

    def test_yazim_denetimi_duzeltmezse_kirmizi_ve_motor_durur(self):
        with mock.patch.object(uret, "_llm_json", return_value={}), mock.patch("builtins.print"):
            sonuc = regresyon.calistir({}, uret)
            self.assertEqual([s["kod"] for s in sonuc if not s["gecti"]], ["R1", "R2"])
            with self.assertRaises(SystemExit) as h:
                uret._regresyon_kapisi({})
        self.assertIn("KIRMIZI", str(h.exception))
        self.assertIn("MOTOR VİDEO ÜRETMEYECEK", self.dosyalar("regresyon_sonuclari")[0].read_text(encoding="utf-8"))

    def test_yapay_zeka_hatasi_da_kirmizidir(self):
        with mock.patch.object(uret, "_llm_json", side_effect=SystemExit("LLM yok")), mock.patch("builtins.print"):
            self.assertFalse(regresyon.hepsi_yesil(regresyon.calistir({}, uret)))

    def test_senaryo_asamalari_arsivlenir(self):
        cevap = {"cumleler": regresyon.URETIM_65[:6] + ["Yani duman yakıtın kendisidir."], "kapak_baslik": ["A", "B"]}
        with mock.patch.object(uret, "_llm_json", return_value=cevap), mock.patch("builtins.print"):
            uret.sahne_plani_v2("Mum dumanı neden yanar?", 7, {})
        ham = self.dosyalar("senaryo_ham_deneme1")[0].read_text(encoding="utf-8")
        self.assertIn("5. Bu duman, alevle temas ettiğinde ortalama beş yüz derece", ham)
        self.assertIn("tekrar yok", ham)


if __name__ == "__main__":
    unittest.main()
