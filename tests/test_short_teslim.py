import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import short_teslim as st  # noqa: E402


def _metadata():
    return {
        "baslik": "Mum neden söner?",
        "aciklama": "Bir mumun sönmesi...",
        "hashtag": "#bilgidozu #shorts",
        "etiketler": "mum, bilim",
        "sabit_yorum": "Sizce hangisi şaşırtıcı? 🧠",
        "kategori": "Bilim",
        "kaynak": "https://youtu.be/abcdefghijk",
    }


class ShortTeslimTests(unittest.TestCase):
    def test_row_uses_all_metadata_fields(self):
        satir = st.hazirla_satir(_metadata(), "video_194.mp4")
        self.assertEqual(satir["dosya"], "video_194.mp4")
        self.assertEqual(satir["sabit_yorum"], "Sizce hangisi şaşırtıcı? 🧠")
        self.assertEqual(satir["kategori"], "Bilim")
        self.assertEqual(satir["kaynak"], "https://youtu.be/abcdefghijk")

    def test_empty_required_field_fails_closed(self):
        bozuk = _metadata()
        bozuk["sabit_yorum"] = "  "
        with self.assertRaises(st.TeslimHatasi):
            st.hazirla_satir(bozuk, "video_194.mp4")

    def test_delivery_names_194_and_writes_table(self):
        with tempfile.TemporaryDirectory() as td:
            kok = Path(td)
            (kok / "final.mp4").write_bytes(b"mp4")
            (kok / "kapak.jpg").write_bytes(b"jpg")
            (kok / "yayin_bilgisi.json").write_text(json.dumps(_metadata()), encoding="utf-8")
            sirasi = []

            with mock.patch.object(st.mpt_uret, "drive_yukle",
                                   side_effect=lambda d, y, ad: sirasi.append(("video", ad))) , \
                 mock.patch.object(st, "_kapak_yukle",
                                   side_effect=lambda d, y, ad: sirasi.append(("kapak", ad))), \
                 mock.patch.object(st.mpt_uret, "tablo_satir_ekle",
                                   side_effect=lambda *a: (sirasi.append(("tablo", a[1])) or True)) as tablo:
                satir = st.teslim_et(object(), kok, 194)

            self.assertEqual(sirasi, [("video", "video_194.mp4"),
                                      ("kapak", "kapak_194.jpg"),
                                      ("tablo", "video_194.mp4")])
            self.assertEqual(tablo.call_args.args[2], "Mum neden söner?")
            self.assertEqual(tablo.call_args.args[7], "Bilim")

    def test_failed_table_write_raises(self):
        with tempfile.TemporaryDirectory() as td:
            kok = Path(td)
            (kok / "final.mp4").write_bytes(b"mp4")
            (kok / "kapak.jpg").write_bytes(b"jpg")
            (kok / "yayin_bilgisi.json").write_text(json.dumps(_metadata()), encoding="utf-8")
            with mock.patch.object(st.mpt_uret, "drive_yukle"), \
                 mock.patch.object(st, "_kapak_yukle"), \
                 mock.patch.object(st.mpt_uret, "tablo_satir_ekle", return_value=False):
                with self.assertRaisesRegex(st.TeslimHatasi, "baslik.xlsx"):
                    st.teslim_et(object(), kok, 194)


if __name__ == "__main__":
    unittest.main()
