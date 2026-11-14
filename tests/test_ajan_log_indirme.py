import unittest
import urllib.request

import ajan_heal as a


class LogIndirmeTestleri(unittest.TestCase):
    def test_yonlendirmede_yetki_basligi_atilir(self):
        """GitHub log adresi S3'e yönlendiriyor; imzalı adrese Authorization
        başlığı giderse 401 alıyoruz. Yönlendirme sonrası başlık temizlenmeli."""
        istek = urllib.request.Request(
            "https://api.github.com/repos/x/y/actions/jobs/1/logs",
            headers={"Authorization": "Bearer gizli", "User-Agent": "test"},
        )
        yeni = a._NoAuthRedirect().redirect_request(
            istek, None, 302, "Found", {}, "https://s3.example.com/imzali?X-Amz-Signature=abc"
        )
        self.assertIsNotNone(yeni)
        basliklar = {k.lower() for k in yeni.headers}
        self.assertNotIn("authorization", basliklar)
        self.assertIn("user-agent", basliklar)
        self.assertEqual(yeni.full_url, "https://s3.example.com/imzali?X-Amz-Signature=abc")

    def test_log_kuyrugu_siniflandirmayi_besler(self):
        """429 içeren gerçek log 'quota_429' olarak sınıflanmalı (tamir yolu)."""
        log = "--- LOG KUYRUĞU ---\nHTTP 429 Too Many Requests - rate limit exceeded (bilerek uretildi)"
        self.assertEqual(a._classify(log), "quota_429")
        # Log hiç alınamazsa sınıflandırma 'bilinmiyor' kalır (sadece uyarı yolu).
        self.assertEqual(a._classify("Job: x | Başarısız adımlar: ['step']"), "bilinmiyor")


if __name__ == "__main__":
    unittest.main()
