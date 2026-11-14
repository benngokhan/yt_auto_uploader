"""Ajanın yeni hata tanıma kuralları için testler.

Gerçek GitHub Actions loglarından alınmış örneklerle, botun tanıdığı hata
türlerini ve log özetleme davranışını doğrular.
"""

import unittest

import ajan_heal as a


class HataTanimaTestleri(unittest.TestCase):
    def test_gercek_log_ornekleri_dogru_taniniyor(self):
        ornekler = {
            "error: cannot pull with rebase: You have unstaged changes.": "git_cakismasi",
            "error: failed to push some refs to 'https://github.com/x/y'": "git_cakismasi",
            "zipfile.BadZipFile: File is not a zip file": "dosya_bozuk",
            "ses doğrulaması başarısız: oran 0.61 (beklenen 0.80)": "ses_hatasi",
            "XTTS-v2 üretimi başarısız: SesHatasi": "ses_hatasi",
            "HTTP Error 429: Too Many Requests": "quota_429",
            "FAILED (failures=1, errors=15)": "test_hatasi",
            "Ran 94 tests in 3.9s\n\nFAILED (failures=2)": "test_hatasi",
            "##[error]Process completed with exit code 1.": "log_yok",
            "Invalid workflow file: .github/workflows/x.yml": "workflow_bozuk",
            "Bad Request: chat not found": "telegram_grup",
            "Request Entity Too Large": "telegram_limit",
            "invalid_grant: Token has been expired or revoked": "yetki_suresi",
            "Resource not accessible by integration (403)": "izin_yok",
            "quotaExceeded: The request cannot be completed because you have "
            "exceeded your quota": "youtube_kota",
            "OSError: [Errno 28] No space left on device": "disk_dolu",
            "Out of memory: Killed process 1234 (python)": "bellek_yetersiz",
            "error: unrecognized arguments: --foo": "arguman_hatasi",
            "Invalid data found when processing input (codec)": "render_hatasi",
            "Input required and not supplied: TELEGRAM_TOKEN": "eksik_ayar",
            "Connection reset by peer": "flaky",
            "404 Not Found: model gemini-1.5 is not found": "model_404",
            "Traceback (most recent call last): SyntaxError": "kod_hatasi",
            "v2 gemini başarısız: HTTPError": "model_hatasi",
            "FileNotFoundError: No such file or directory": "kaynak_yok",
            "tarifi olmayan bir şey oldu": "bilinmiyor",
        }
        for metin, beklenen in ornekler.items():
            with self.subTest(metin=metin[:45]):
                self.assertEqual(a._classify(metin), beklenen)

    def test_son_hata_ipucu_kazanir(self):
        # Sağlayıcı önce 403 verip sonra 429 ile bitebiliyor; son hata seçilmeli.
        log = "403 Forbidden\nardindan tekrar denendi\nHTTP Error 429 Too Many Requests"
        self.assertEqual(a._classify(log), "quota_429")

        # Ters yön: 429'dan sonra 401 gelirse yine son (401) kazanır.
        log = "HTTP 429 rate limit\nsonra yetki hatasi: 401 Unauthorized"
        self.assertEqual(a._classify(log), "yetki_suresi")

    def test_bos_ve_none_guvenli(self):
        self.assertEqual(a._classify(""), "bilinmiyor")
        self.assertEqual(a._classify(None), "bilinmiyor")

    def test_her_tur_icin_sade_turkce_mesaj_var(self):
        turler = [k for k, _ in a._KURALLAR] + [
            "log_yok", "model_404", "bilinmiyor",
        ]
        for kind in turler:
            with self.subTest(kind=kind):
                sorun, cozum, kim = a._sorun_ozeti(kind, "")
                self.assertTrue(sorun.strip(), kind)
                self.assertTrue(cozum.strip(), kind)
                self.assertIn(kim, ("ajan", "sen", "yok"), kind)

    def test_bilinmeyen_hata_sebep_okunamadi_der(self):
        sorun, cozum, kim = a._sorun_ozeti(
            "log_yok", "##[error]Process completed with exit code 1."
        )
        self.assertIn("kayıt", sorun.lower())
        self.assertEqual(kim, "sen")
        self.assertIn("değiştirmedim", cozum)


class LogOzetiTestleri(unittest.TestCase):
    def test_betik_bloklari_atilir_hata_satiri_kalir(self):
        log = "\n".join([
            "2026-11-12T12:00:00.0000000Z ##[group]Run echo 'basliyor'",
            "2026-11-12T12:00:00.0000000Z echo 'basliyor'",
            "2026-11-12T12:00:00.0000000Z if [ -f x ]; then",
            "2026-11-12T12:00:00.0000000Z ##[endgroup]",
            "2026-11-12T12:00:01.0000000Z ses doğrulaması başarısız: oran 0.61",
            "2026-11-12T12:00:02.0000000Z ##[error]Process completed with exit code 1.",
            "2026-11-12T12:00:03.0000000Z Post job cleanup.",
        ])
        ozet = a._log_ozeti(log)
        self.assertIn("ses doğrulaması başarısız", ozet)
        self.assertIn("##[error]", ozet)
        # Betik gövdesi özete girmemeli.
        self.assertNotIn("echo 'basliyor'", ozet)
        self.assertNotIn("if [ -f x ]", ozet)
        # Hata satırından sonrası (temizlik) sebep sayılmaz.
        self.assertNotIn("Post job cleanup", ozet)

    def test_traceback_blogu_butun_alinir(self):
        log = "\n".join([
            "2026-11-12T12:00:00Z ##[group]Run python x.py",
            "2026-11-12T12:00:00Z python x.py",
            "2026-11-12T12:00:00Z ##[endgroup]",
            "2026-11-12T12:00:01Z Traceback (most recent call last):",
            "2026-11-12T12:00:01Z   File \"x.py\", line 3, in <module>",
            "2026-11-12T12:00:01Z     raise RuntimeError('boom')",
            "2026-11-12T12:00:01Z RuntimeError: boom",
        ])
        ozet = a._log_ozeti(log)
        self.assertIn("Traceback", ozet)
        self.assertIn("RuntimeError: boom", ozet)

    def test_ozet_uzunluk_siniri(self):
        log = "\n".join(f"2026-11-12T12:00:0{i}Z error: hata {i}" for i in range(200))
        self.assertLessEqual(len(a._log_ozeti(log, sinir=500)), 500)


if __name__ == "__main__":
    unittest.main()
