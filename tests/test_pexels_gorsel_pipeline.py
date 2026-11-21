import atexit
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


def _import_uret_without_persisting_quota_counter():
    import uret
    try:
        import kota_sayac
        atexit.unregister(kota_sayac.yaz)
    except Exception:
        pass
    return uret


def _make_textured_photo(w=1200, h=1800, base_rgb=(145, 170, 190), bright_border=False) -> Image.Image:
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
    def test_visual_judge_retries_a_transient_timeout(self):
        import io
        import json

        response_body = {
            "candidates": [{"content": {"parts": [{"text": "{\"scores\":[0.91]}"}]}}]
        }
        response = io.BytesIO(json.dumps(response_body).encode("utf-8"))

        def fake_download(_url, path):
            Image.new("RGB", (64, 64), (35, 70, 95)).save(path, format="JPEG")

        candidate = {"preview_url": "https://images.example.test/candidate.jpg"}
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fixture-key"}), \
             mock.patch.object(gorsel_uret, "_indir", side_effect=fake_download), \
             mock.patch("urllib.request.urlopen", side_effect=[TimeoutError("fixture timeout"), response]) as call, \
             mock.patch.object(gorsel_uret.time, "sleep") as sleep:
            scores = gorsel_uret._visual_text_scores("A pressure gauge.", [candidate])

        self.assertEqual(scores, [0.91])
        self.assertEqual(call.call_count, 2)
        sleep.assert_called_once_with(2.0)

    def test_scene_own_query_always_precedes_shorter_fallbacks(self):
        adaylar = gorsel_uret._sorgu_adaylari(
            {"gorsel": "retina cell microscope", "gorsel_anahtar": "retina cell microscope"},
            yedek=["mobile phone", "human eye"],
            ana_konu="smartphone glowing screen",
            sahne_sirasi=2,
        )
        self.assertEqual(adaylar, ["retina cell microscope"])
        self.assertNotIn("mobile phone", adaylar)
        self.assertNotIn("human eye", adaylar)  # unrelated supplied fallback is never used

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

    def test_anti_raw_pixel_guard_filters_white_studio_dark_and_accepts_textured(self):
        clean_im = _make_textured_photo(1080, 1620, base_rgb=(150, 170, 190), bright_border=False)
        bad_im = _make_textured_photo(1080, 1620, base_rgb=(120, 120, 120), bright_border=True)
        dark_im = _make_textured_photo(1080, 1620, base_rgb=(12, 18, 25), bright_border=False)

        kusur_clean, neden_clean = gorsel_uret._ham_kusurlu_mu(clean_im)
        kusur_bad, neden_bad = gorsel_uret._ham_kusurlu_mu(bad_im)
        kusur_dark, neden_dark = gorsel_uret._ham_kusurlu_mu(dark_im)
        self.assertFalse(kusur_clean, neden_clean)
        self.assertTrue(kusur_bad)
        self.assertIn("beyaz_studyo_kesim", neden_bad)
        self.assertTrue(kusur_dark)
        self.assertIn("karanlik_gorsel", neden_dark)

    def test_live_gemini_score_gate_rejects_absent_invalid_and_wrong_origin(self):
        self.assertTrue(gorsel_uret._record_score_passes({
            "score_origin": "live_gemini_vision", "semantic_similarity": 0.62,
        }))
        for record in (
            {"score_origin": "live_gemini_vision", "semantic_similarity": 0.6199},
            {"score_origin": "live_gemini_vision", "semantic_similarity": float("nan")},
            {"score_origin": "live_gemini_vision", "semantic_similarity": None},
            {"score_origin": "pexels_metadata_overlap_proxy", "semantic_similarity": 0.99},
        ):
            with self.subTest(record=record):
                self.assertFalse(gorsel_uret._record_score_passes(record))

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
                    "preview_url": "https://images.pexels.com/photos/1/white.jpg",
                    "source_page_url": "https://www.pexels.com/photo/white-cutout-1/",
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
                    "preview_url": "https://images.pexels.com/photos/2/clean.jpg",
                    "source_page_url": "https://www.pexels.com/photo/clean-photo-2/",
                },
            ]

            def sahte_indir(url: str, yol: Path):
                kaynak_dosya = white_jpg if "white" in url else clean_jpg
                yol.write_bytes(kaynak_dosya.read_bytes())

            with mock.patch.dict(os.environ, {"PEXELS_API_KEY": "test_pexels", "PIXABAY_API_KEY": "test_pixabay",
                                              "MOTOR_VISUAL_QA_PASSED": "1"}):
                with mock.patch.object(gorsel_uret, "pexels_ara", return_value=sahte_pexels) as m_pex, \
                     mock.patch.object(gorsel_uret, "pixabay_ara") as m_pix, \
                     mock.patch.object(gorsel_uret, "_visual_text_scores", return_value=[0.66, 0.84]), \
                     mock.patch.object(gorsel_uret, "_indir", side_effect=sahte_indir):
                    cikti = gorsel_uret.sahneler_icin_gorseller(
                        [{"gorsel": "human hand", "gorsel_anahtar": "human hand", "ses": "Test"}],
                        hedef / "out",
                    )
                    self.assertEqual(len(cikti), 1)
                    self.assertTrue(cikti[0].exists())
                    m_pex.assert_called()
                    m_pix.assert_not_called()


    def test_fixed_semantic_regressions_reject_mismatches_and_accept_gauge(self):
        # Scores stand for the deterministic vision-judge fixtures; the image bytes are
        # passed to the judge in production, while this test isolates the fixed threshold gate.
        cases = [
            ("camcı", "sifon", 0.12, False),
            ("motosiklet kadranı", "fizik kanunu", 0.09, False),
            ("sokak satıcıları", "pompa", 0.14, False),
            ("çamurlu su", "vakum hattı", 0.18, False),
            ("süt tankı", "yarım saniye", 0.11, False),
            ("manometre", "basınç", 0.76, True),
        ]
        for visual, scene, score, expected in cases:
            with self.subTest(visual=visual, scene=scene):
                self.assertEqual(gorsel_uret.semantic_score_passes(score), expected)

    def test_all_requested_bad_good_pairs_run_through_selection_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "fixture.jpg"
            _make_textured_photo(1080, 1620).save(source, quality=90)
            pairs = [
                ("glassblower workshop", "toilet siphon flush", 0.08),
                ("motorcycle dashboard speedometer", "law of physics", 0.10),
                ("street vendors carrying bags", "water pump pressure", 0.13),
                ("muddy water", "vacuum line pressure", 0.16),
                ("milk tanker", "half a second flush", 0.12),
                ("pressure gauge manometer", "cabin pressure reading", 0.78),
            ]
            hits = {}
            score_by_scene = {scene: score for _, scene, score in pairs}
            for index, (tags, scene, _) in enumerate(pairs, 1):
                query = f"fixture query {index}"
                hits[query] = [{
                    "uid": f"pexels:{index}", "kaynak": "pexels", "id": index,
                    "imageWidth": 1080, "imageHeight": 1620, "tags": tags,
                    "type": "photo", "avg_color": "#334455",
                    "indir_url": f"https://images.pexels.com/photos/{index}/original.jpg",
                    "preview_url": f"https://images.pexels.com/photos/{index}/medium.jpg",
                    "source_page_url": f"https://www.pexels.com/photo/fixture-{index}/",
                }]
            def fake_search(query, key, adet=8):
                return hits[query]
            def fake_judge(scene_text, candidates):
                return [score_by_scene[scene_text]] * len(candidates)
            def fake_download(url, path):
                path.write_bytes(source.read_bytes())
            scene_inputs = [{"gorsel": f"fixture query {i}", "ses": scene}
                            for i, (_, scene, _) in enumerate(pairs, 1)]
            with mock.patch.dict(os.environ, {"MOTOR_VISUAL_QA_PASSED": "1", "PEXELS_API_KEY": "fixture"}):
                with mock.patch.object(gorsel_uret, "pexels_ara", side_effect=fake_search), \
                     mock.patch.object(gorsel_uret, "_visual_text_scores", side_effect=fake_judge) as judge, \
                     mock.patch.object(gorsel_uret, "_indir", side_effect=fake_download):
                    selected = gorsel_uret.sahneler_icin_gorseller(scene_inputs, root / "out")
            self.assertEqual(selected[:5], [None] * 5)
            self.assertIsNotNone(selected[5])
            self.assertEqual(judge.call_count, 6)

    def test_no_scene_specific_query_produces_plain_scene_and_archived_json(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"MOTOR_VISUAL_QA_PASSED": "1"}):
            root = Path(td)
            result = gorsel_uret.sahneler_icin_gorseller([{"ses": "Vakum hattı basıncı."}], root)
            self.assertEqual(result, [None])
            report = __import__("json").loads((root / "gorsel_secim_raporu.json").read_text(encoding="utf-8"))
            self.assertEqual(report["scenes"][0]["selected"], None)
            self.assertEqual(report["scenes"][0]["fallback"], "plain_background")
            self.assertEqual(report["scenes"][0]["queries"], [])

    def test_empty_query_plan_does_not_inject_general_science_fallbacks(self):
        uret = _import_uret_without_persisting_quota_counter()
        with mock.patch.object(uret, "_llm_json", return_value={}):
            searches, backups = uret._gorsel_aramalari("uçak tuvaleti", ["Vakum hattı."], {})
        self.assertEqual(searches, [{"ana": "", "alternatif": ""}])
        self.assertEqual(backups, [])

    def test_visual_generation_is_locked_without_green_test_gate(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"MOTOR_VISUAL_QA_PASSED": "0"}):
            with self.assertRaises(SystemExit):
                gorsel_uret.sahneler_icin_gorseller([{"gorsel": "pressure gauge", "ses": "pressure"}], Path(td))

    def test_every_returned_candidate_is_semantically_scored_and_full_urls_are_logged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            img = _make_textured_photo(1080, 1620)
            source = root / "candidate.jpg"
            img.save(source, quality=90)
            hit = {
                "uid": "pexels:777", "kaynak": "pexels", "id": 777,
                "imageWidth": 1080, "imageHeight": 1620,
                "tags": "pressure gauge instrument", "type": "photo", "avg_color": "#334455",
                "indir_url": "https://images.pexels.com/photos/777/original.jpg",
                "preview_url": "https://images.pexels.com/photos/777/medium.jpg",
                "source_page_url": "https://www.pexels.com/photo/pressure-gauge-777/",
            }
            def fake_download(url, path):
                path.write_bytes(source.read_bytes())
            with mock.patch.dict(os.environ, {"MOTOR_VISUAL_QA_PASSED": "1", "PEXELS_API_KEY": "test"}):
                with mock.patch.object(gorsel_uret, "pexels_ara", return_value=[hit]), \
                     mock.patch.object(gorsel_uret, "_visual_text_scores", return_value=[0.79]) as judge, \
                     mock.patch.object(gorsel_uret, "_indir", side_effect=fake_download):
                    selected = gorsel_uret.sahneler_icin_gorseller(
                        [{"gorsel": "pressure gauge", "ses": "A manometer measures pressure."}], root / "out")
            self.assertTrue(selected[0] and selected[0].exists())
            judge.assert_called_once()
            import json
            report = json.loads((root / "out" / "gorsel_secim_raporu.json").read_text(encoding="utf-8"))
            choice = report["scenes"][0]["selected"]
            self.assertEqual(choice["provider"], "pexels")
            self.assertEqual(choice["image_url"], hit["indir_url"])
            self.assertEqual(choice["source_page_url"], hit["source_page_url"])
            self.assertEqual(choice["semantic_similarity"], 0.79)

    def test_provider_source_url_must_match_provider_host(self):
        self.assertTrue(gorsel_uret._provider_page_url_ok("pexels", "https://www.pexels.com/photo/a/"))
        self.assertFalse(gorsel_uret._provider_page_url_ok("pexels", "https://notpexels.com/photo/a/"))
        self.assertTrue(gorsel_uret._provider_page_url_ok("pixabay", "https://pixabay.com/photos/a-1/"))
        self.assertFalse(gorsel_uret._provider_page_url_ok("pixabay", "http://pixabay.com/photos/a-1/"))

    def test_unverified_nasa_boeing_source_name_is_suppressed_with_warning(self):
        import uret
        from unittest import mock
        with mock.patch("builtins.print") as log:
            self.assertEqual(uret._kaynak_temizle("", kaynaksiz_etiket="NASA + Boeing Technical Reports"), "")
        self.assertTrue(any("UYARI (kaynak doğrulama)" in str(c.args[0]) for c in log.call_args_list))

    def test_reachable_allowlisted_source_url_can_be_used(self):
        uret = _import_uret_without_persisting_quota_counter()
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def geturl(self): return "https://ntrs.nasa.gov/citations/12345"
        with mock.patch("urllib.request.urlopen", return_value=Response()):
            self.assertEqual(uret._kaynak_temizle("https://ntrs.nasa.gov/citations/12345"),
                             "https://ntrs.nasa.gov/citations/12345")

    def test_source_and_visual_note_defaults_are_blank(self):
        import inspect
        import shorts_pipeline
        params = inspect.signature(shorts_pipeline.build_static_overlay).parameters
        self.assertEqual(params["note1_txt"].default, "")
        self.assertEqual(params["note2_txt"].default, "")
        self.assertEqual(shorts_pipeline._verified_source_url_format("https://ntrs.nasa.gov/citations/123"),
                         "https://ntrs.nasa.gov/citations/123")
        self.assertEqual(shorts_pipeline._verified_source_url_format("https://fake-nasa.gov/source"), "")
        self.assertEqual(shorts_pipeline._verified_source_url_format("NASA + Boeing Technical Reports"), "")


if __name__ == "__main__":
    unittest.main()
