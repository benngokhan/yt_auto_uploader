import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "motor"))

import gorsel_uret  # noqa: E402


def _make_textured_photo(w=1200, h=1800, base_rgb=(45, 70, 95), bright_border=False) -> Image.Image:
    rng = np.random.default_rng(42)
    yy, xx = np.mgrid[0:h, 0:w]
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[..., 0] = base_rgb[0] + 45.0 * np.sin(xx / 35.0) + rng.normal(0, 14, (h, w))
    arr[..., 1] = base_rgb[1] + 45.0 * np.cos(yy / 40.0) + rng.normal(0, 14, (h, w))
    arr[..., 2] = base_rgb[2] + 40.0 * np.sin((xx + yy) / 50.0) + rng.normal(0, 14, (h, w))
    if bright_border:
        arr[:140, :, :] = 250.0
        arr[-140:, :, :] = 250.0
        arr[:, :100, :] = 250.0
        arr[:, -100:, :] = 250.0
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.ellipse((w // 4, h // 4, 3 * w // 4, 3 * h // 4), outline=(220, 190, 110), width=6)
    return im


class PexelsGorselPipelineTests(unittest.TestCase):
    def test_slug_extraction_and_scoring(self):
        slug = gorsel_uret._pexels_slug_kelimeler(
            "https://www.pexels.com/photo/close-up-of-water-droplets-on-glass-1234567/"
        )
        self.assertEqual(slug, "close up of water droplets on glass")

        pexels_hit = {
            "uid": "pexels:101",
            "kaynak": "pexels",
            "id": 101,
            "imageWidth": 2000,
            "imageHeight": 3000,
            "tags": "Close up of water droplets on dark glass",
            "type": "photo",
            "avg_color": "#1E2D3B",
            "likes": 120,
            "downloads": 4000,
        }
        white_cutout = dict(
            pexels_hit,
            uid="pexels:102",
            id=102,
            tags="Water droplet isolated on white background",
            avg_color="#FAFAFA",
        )
        self.assertTrue(gorsel_uret._yeterince_uygun(pexels_hit, "water droplet", "water droplet", gevsek=False))
        self.assertFalse(gorsel_uret._yeterince_uygun(white_cutout, "water droplet", "water droplet", gevsek=False))

    def test_anti_raw_pixel_guard_filters_white_studio_and_accepts_textured(self):
        clean_im = _make_textured_photo(1080, 1620, base_rgb=(40, 65, 88), bright_border=False)
        bad_im = _make_textured_photo(1080, 1620, base_rgb=(120, 120, 120), bright_border=True)

        kusur_clean, neden_clean = gorsel_uret._ham_kusurlu_mu(clean_im)
        kusur_bad, neden_bad = gorsel_uret._ham_kusurlu_mu(bad_im)
        self.assertFalse(kusur_clean, neden_clean)
        self.assertTrue(kusur_bad)
        self.assertIn("beyaz_studyo_kesim", neden_bad)

    def test_dikey_kirp_and_sinematik_isle_tame_bright_raw_photo(self):
        # Parlak gündüz fotoğrafı bile koyu-sinematik pozlamaya çekilmeli
        bright_im = _make_textured_photo(1920, 1080, base_rgb=(175, 182, 188), bright_border=False)
        kirpilmis = gorsel_uret.dikey_kirp(bright_im)
        self.assertEqual(kirpilmis.size, gorsel_uret.HEDEF)

        islenmis = gorsel_uret.sinematik_isle(kirpilmis, tohum=20261101)
        self.assertEqual(islenmis.size, gorsel_uret.HEDEF)
        raw_luma = float(np.asarray(bright_im, dtype=np.float32).mean() / 255.0)
        out_luma = float(np.asarray(islenmis, dtype=np.float32).mean() / 255.0)
        self.assertLess(out_luma, raw_luma - 0.12)

    def test_sahneler_icin_gorseller_prefers_pexels_and_skips_raw_cutout(self):
        with tempfile.TemporaryDirectory() as td:
            hedef = Path(td)
            white_jpg = hedef / "src_white.jpg"
            clean_jpg = hedef / "src_clean.jpg"
            _make_textured_photo(1080, 1620, bright_border=True).save(white_jpg, quality=92)
            _make_textured_photo(1080, 1620, bright_border=False).save(clean_jpg, quality=92)

            sahte_pexels = [
                {
                    "uid": "pexels:1",
                    "kaynak": "pexels",
                    "id": 1,
                    "imageWidth": 1080,
                    "imageHeight": 1620,
                    "tags": "human hand fingers dark lighting",
                    "type": "photo",
                    "avg_color": "#334455",
                    "likes": 120,
                    "downloads": 4000,
                    "indir_url": "https://images.pexels.com/photos/1/white.jpg",
                },
                {
                    "uid": "pexels:2",
                    "kaynak": "pexels",
                    "id": 2,
                    "imageWidth": 1080,
                    "imageHeight": 1620,
                    "tags": "human hand palm macro photography",
                    "type": "photo",
                    "avg_color": "#223344",
                    "likes": 120,
                    "downloads": 4000,
                    "indir_url": "https://images.pexels.com/photos/2/clean.jpg",
                },
            ]

            def sahte_indir(url: str, yol: Path):
                kaynak_dosya = white_jpg if "white" in url else clean_jpg
                yol.write_bytes(kaynak_dosya.read_bytes())

            with mock.patch.dict(os.environ, {"PEXELS_API_KEY": "test_pexels", "PIXABAY_API_KEY": "test_pixabay"}):
                with mock.patch.object(gorsel_uret, "pexels_ara", return_value=sahte_pexels) as m_pex, \
                     mock.patch.object(gorsel_uret, "pixabay_ara") as m_pix, \
                     mock.patch.object(gorsel_uret, "_indir", side_effect=sahte_indir):
                    cikti = gorsel_uret.sahneler_icin_gorseller(
                        [{"gorsel": "human hand", "gorsel_anahtar": "human hand", "ses": "Test"}],
                        hedef / "out",
                    )
                    self.assertEqual(len(cikti), 1)
                    self.assertTrue(cikti[0].exists())
                    m_pex.assert_called()
                    m_pix.assert_not_called()


if __name__ == "__main__":
    unittest.main()
