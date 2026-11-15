"""Otomatik kod yaması güvenlik kapısı testleri."""

import tempfile
import unittest
from pathlib import Path

import ajan_heal as a


class YamaKapisiTestleri(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kok = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _yaz(self, yol: str, icerik: str):
        p = self.kok / yol
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(icerik, encoding="utf-8")
        return p

    def test_sozdizimi_hatasi_reddedilir(self):
        self._yaz("bozuk.py", "def x(:\n    pass\n")
        gecti, not_ = a._yama_kapisi("bozuk.py", kok=str(self.kok))
        self.assertFalse(gecti)
        self.assertIn("sözdizimi", not_)

    def test_testsiz_dosya_kabul_edilir(self):
        self._yaz("yalniz.py", "DEGER = 1\n")
        gecti, not_ = a._yama_kapisi("yalniz.py", kok=str(self.kok))
        self.assertTrue(gecti)
        self.assertIn("test yok", not_)

    def test_gecen_test_kabul_edilir(self):
        self._yaz("modul.py", "DEGER = 2\n")
        self._yaz(
            "tests/test_modul.py",
            "import unittest\n"
            "import modul\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_deger(self):\n"
            "        self.assertEqual(modul.DEGER, 2)\n",
        )
        gecti, not_ = a._yama_kapisi("modul.py", kok=str(self.kok))
        self.assertTrue(gecti, not_)
        self.assertIn("testler tamam", not_)

    def test_kalan_test_reddedilir(self):
        self._yaz("modul2.py", "DEGER = 3\n")
        self._yaz(
            "tests/test_modul2.py",
            "import unittest\n"
            "import modul2\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_deger(self):\n"
            "        self.assertEqual(modul2.DEGER, 99)\n",
        )
        gecti, not_ = a._yama_kapisi("modul2.py", kok=str(self.kok))
        self.assertFalse(gecti)
        self.assertIn("testler geçmedi", not_)

    def test_eksik_paket_testleri_atlanir(self):
        self._yaz("modul3.py", "DEGER = 4\n")
        self._yaz(
            "tests/test_modul3.py",
            "import unittest\n"
            "import olmayan_paket_xyz\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_x(self):\n"
            "        self.assertTrue(True)\n",
        )
        gecti, not_ = a._yama_kapisi("modul3.py", kok=str(self.kok))
        self.assertTrue(gecti, not_)
        self.assertIn("atlandı", not_)


class FailedRunsTestleri(unittest.TestCase):
    def test_yuz_kosu_istenir(self):
        import unittest.mock as mock

        with mock.patch.object(a, "_gh", return_value={"workflow_runs": []}) as gh:
            self.assertEqual(a._get_failed_runs(), [])
        url = gh.call_args[0][1]
        self.assertIn("per_page=100", url)


if __name__ == "__main__":
    unittest.main()
