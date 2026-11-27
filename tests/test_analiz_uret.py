import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import analiz_uret as au  # noqa: E402


def _analiz_dosyasi(kok: Path, adet=2) -> Path:
    veri = {"candidates": [
        {"video_id": f"abcdefghij{k}", "short_handoff": {
            "topic": f"Konu {k} | odak: pre_drop_peak @ {k} sn",
            "source_video_id": f"abcdefghij{k}",
            "source_url": f"https://youtu.be/abcdefghij{k}",
            "evidence": "test",
        }} for k in range(adet)
    ]}
    yol = kok / "yt_analiz.json"
    yol.write_text(json.dumps(veri), encoding="utf-8")
    return yol


def _meta(baslik="Test başlık"):
    return {"baslik": baslik, "aciklama": "a", "hashtag": "h", "etiketler": "e",
            "sabit_yorum": "soru? 🧠", "kategori": "Bilim"}


class AnalizUretTests(unittest.TestCase):
    def test_top_n_handoffs_are_loaded_in_rank_order(self):
        with tempfile.TemporaryDirectory() as td:
            kok = Path(td)
            yol = _analiz_dosyasi(kok, 3)
            handofflar = au.adaylari_yukle(yol, 2)
            self.assertEqual(len(handofflar), 2)
            self.assertIn("Konu 0", handofflar[0]["topic"])

    def test_topic_is_truncated_for_motor(self):
        self.assertEqual(au.konu_metni({"topic": "x" * 1000}).count("x"), 397)
        with self.assertRaises(SystemExit):
            au.konu_metni({"topic": "   "})

    def test_each_output_is_staged_separately(self):
        with tempfile.TemporaryDirectory() as td:
            kok = Path(td)
            gecici = kok / "motor" / "cikti" / "son" / "onay_bekleyen"
            gecici.mkdir(parents=True)
            (gecici / "final.mp4").write_bytes(b"mp4")
            (gecici / "kapak.jpg").write_bytes(b"jpg")
            (gecici / "yayin_bilgisi.json").write_text(json.dumps(_meta()), encoding="utf-8")

            sayac = {"n": 0}

            def sahte_run(komut, **kwargs):
                sayac["n"] += 1
                gecici.mkdir(parents=True, exist_ok=True)
                (gecici / "final.mp4").write_bytes(f"mp4-{sayac['n']}".encode())
                (gecici / "kapak.jpg").write_bytes(b"jpg")
                (gecici / "yayin_bilgisi.json").write_text(json.dumps(_meta("İkinci")), encoding="utf-8")

            with mock.patch.object(au, "KOK", kok), \
                 mock.patch.object(au.subprocess, "run", side_effect=sahte_run):
                bir = au.uret_bir({"topic": "Birinci"}, 1)
                iki = au.uret_bir({"topic": "İkinci"}, 2)

            self.assertNotEqual(bir, iki)
            self.assertEqual((bir / "final.mp4").read_bytes(), b"mp4-1")
            self.assertEqual((iki / "final.mp4").read_bytes(), b"mp4-2")
            self.assertTrue((iki / "kapak.jpg").is_file())

    def test_two_shorts_get_194_and_195_after_approval(self):
        with tempfile.TemporaryDirectory() as td:
            kok = Path(td)
            analiz = _analiz_dosyasi(kok, 2)
            birinci = kok / "aday_01"
            ikinci = kok / "aday_02"
            for klasor in (birinci, ikinci):
                klasor.mkdir()
                (klasor / "final.mp4").write_bytes(b"mp4")
                (klasor / "kapak.jpg").write_bytes(b"jpg")
                (klasor / "yayin_bilgisi.json").write_text(json.dumps(_meta()), encoding="utf-8")

            numaralar = []
            with mock.patch.object(au, "adaylari_yukle", return_value=[{"topic": "A"}, {"topic": "B"}]), \
                 mock.patch.object(au.mpt_uret, "drive_istemci", return_value=object()), \
                 mock.patch.object(au.mpt_uret, "sonraki_numara", return_value=194), \
                 mock.patch.object(au, "uret_bir", side_effect=[birinci, ikinci]), \
                 mock.patch.object(au.telegram_onay, "gonder_onizleme") as onizleme, \
                 mock.patch.object(au.telegram_onay, "bekle_ve_onayla", return_value=True), \
                 mock.patch.object(au.short_teslim, "teslim_et",
                                   side_effect=lambda d, k, n, kaynak: (
                                       numaralar.append(n) or {"dosya": f"video_{n}.mp4"})):
                au.calistir(2, str(analiz), 10, "")

            self.assertEqual(numaralar, [194, 195])
            self.assertEqual(onizleme.call_count, 2)

    def test_dry_run_never_touches_drive_or_telegram(self):
        with tempfile.TemporaryDirectory() as td:
            kok = Path(td)
            analiz = _analiz_dosyasi(kok, 2)
            klasor = kok / "aday_01"
            klasor.mkdir()
            (klasor / "final.mp4").write_bytes(b"mp4")
            (klasor / "kapak.jpg").write_bytes(b"jpg")
            (klasor / "yayin_bilgisi.json").write_text(json.dumps(_meta()), encoding="utf-8")
            with mock.patch.object(au, "adaylari_yukle", return_value=[{"topic": "A"}]), \
                 mock.patch.object(au.mpt_uret, "drive_istemci") as drive, \
                 mock.patch.object(au.mpt_uret, "sonraki_numara") as numara, \
                 mock.patch.object(au, "uret_bir", return_value=klasor), \
                 mock.patch.object(au.telegram_onay, "gonder_onizleme") as onizleme, \
                 mock.patch.object(au.short_teslim, "teslim_et") as teslim:
                au.calistir(1, str(analiz), 10, "", kuru=True)
            drive.assert_not_called()
            numara.assert_not_called()
            onizleme.assert_not_called()
            teslim.assert_not_called()

    def test_without_approval_nothing_is_delivered(self):
        with tempfile.TemporaryDirectory() as td:
            kok = Path(td)
            analiz = _analiz_dosyasi(kok, 2)
            klasor = kok / "aday_01"
            klasor.mkdir()
            (klasor / "final.mp4").write_bytes(b"mp4")
            (klasor / "kapak.jpg").write_bytes(b"jpg")
            (klasor / "yayin_bilgisi.json").write_text(json.dumps(_meta()), encoding="utf-8")
            with mock.patch.object(au, "adaylari_yukle", return_value=[{"topic": "A"}]), \
                 mock.patch.object(au.mpt_uret, "drive_istemci", return_value=object()), \
                 mock.patch.object(au.mpt_uret, "sonraki_numara", return_value=194), \
                 mock.patch.object(au, "uret_bir", return_value=klasor), \
                 mock.patch.object(au.telegram_onay, "gonder_onizleme"), \
                 mock.patch.object(au.telegram_onay, "bekle_ve_onayla", return_value=False), \
                 mock.patch.object(au.short_teslim, "teslim_et") as teslim:
                au.calistir(1, str(analiz), 10, "")
            teslim.assert_not_called()


if __name__ == "__main__":
    unittest.main()
