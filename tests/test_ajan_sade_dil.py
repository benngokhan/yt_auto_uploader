import unittest

import ajan_heal as a


class SadeDilTestleri(unittest.TestCase):
    def test_is_adlari_sadelestirilir(self):
        self.assertEqual(a._is_adi("YouTube Drive Uploader"), "Video yükleme")
        self.assertEqual(a._is_adi("Slot Watchdog"), "Yayın nöbetçisi")
        # Tanınmayan ad aynen korunur
        self.assertEqual(a._is_adi("Başka Bir İş"), "Başka Bir İş")

    def test_teknik_hata_sade_turkceye_cevrilir(self):
        sorun, cozum, kim = a._sorun_ozeti("bilinmiyor", "HTTP 401 Unauthorized invalid_grant")
        self.assertIn("bağlantı", sorun.lower())
        self.assertEqual(kim, "sen")

        sorun, _, kim = a._sorun_ozeti("bilinmiyor", "curl: (28) timeout")
        self.assertIn("bağlantı", sorun.lower())
        self.assertEqual(kim, "ajan")

        sorun, _, kim = a._sorun_ozeti("bilinmiyor", "Out of memory: Killed process")
        self.assertIn("belle", sorun.lower())
        self.assertEqual(kim, "sen")

    def test_bilinmeyen_hata_guvenli_mesaj_verir(self):
        sorun, cozum, kim = a._sorun_ozeti("bilinmiyor", "tarifi olmayan bir şey")
        self.assertIn("Tanıdık olmayan", sorun)
        self.assertEqual(kim, "sen")
        self.assertIn("değiştirmedim", cozum)

    def test_html_kacis_ve_kisaltma(self):
        cikti = a._e("<script> & 'x'", 40)
        self.assertNotIn("<", cikti)
        self.assertIn("&lt;", cikti)
        self.assertIn("&amp;", cikti)
        self.assertTrue(a._e("a" * 50, 10).endswith("…"))

    def test_uzun_mesajlar_telegram_sinirinda_kalir(self):
        # _tg 3900 karakterde kesiyor; üretilen raporların bunu aşmadığını doğrula
        for tur in ("model_404", "quota_429", "flaky", "kod_hatasi", "bilinmiyor"):
            sorun, cozum, _ = a._sorun_ozeti(tur, "x" * 10000)
            metin = (
                f"🔴 <b>{a._e(a._is_adi('YouTube Drive Uploader'), 60)}</b>\n\n"
                f"Sorun: {sorun}\nNe yapmalı: {cozum}\n"
                f"{a._e('x' * 200, 200)}\n"
                f"Koşu: {a._kayit_linki('https://github.com/x/y/actions/runs/1')}"
            )
            self.assertLess(len(metin), 3900)


if __name__ == "__main__":
    unittest.main()
