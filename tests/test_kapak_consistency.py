import unittest
import tempfile
from pathlib import Path
from PIL import Image
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "motor") not in sys.path:
    sys.path.insert(0, str(ROOT / "motor"))

import kapak


class TestKapakConsistency(unittest.TestCase):
    def test_tr_upper_turkish_chars(self):
        self.assertEqual(kapak.tr_upper("geçici kör ışık"), "GEÇİCİ KÖR IŞIK")

    def test_three_lines_never_split_words_mid_syllable(self):
        lines = kapak.uc_satir_baslik("Gece karanlıkta telefona bakınca gözümüz neden geçici kör olur?")
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertFalse(line.endswith("-"))
            self.assertGreater(len(line), 2)

    def test_bottom_caption_keeps_full_turkish_sentence(self):
        md = {
            "aciklama": (
                "Karanlıkta telefona bakmanın ardından yaşanan geçici görme kaybı, "
                "ekran ışığının retinadaki rodopsin molekülünü aniden tüketmesinden kaynaklanır.\n\n"
                "Daha fazla Bilgi Dozu için..."
            )
        }
        bilgi = kapak.kapak_metni_hazirla("Karanlıkta telefona bakınca neden geçici kör oluruz?", [], md)
        self.assertIn("tüketmesinden kaynaklanır.", bilgi["alt_aciklama"])
        self.assertEqual(bilgi["kategori"], "NÖROBİLİM")

    def test_kapak_uret_renders_1080x1920_rgb_jpeg(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src.jpg"
            out = Path(td) / "kapak.jpg"
            Image.new("RGB", (1200, 1800), (140, 90, 50)).save(src, "JPEG")
            p = kapak.kapak_uret(
                src,
                out,
                satirlar=["KARANLIKTA TELEFONA", "BAKINCA NEDEN", "GEÇİCİ KÖR OLURUZ?"],
                kategori="NÖROBİLİM",
                alt_aciklama="Ekran ışığı retinadaki rodopsin molekülünü saniyeler içinde tüketir.",
            )
            self.assertTrue(p.exists())
            with Image.open(p) as im:
                self.assertEqual(im.size, (1080, 1920))


if __name__ == "__main__":
    unittest.main()
