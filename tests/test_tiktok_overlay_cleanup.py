import types
import unittest

from crosspost_worker import _TIKTOK_OVERLAY_INIT_JS, _install_tiktok_overlay_cleanup


class FakeContext:
    def __init__(self):
        self.scripts = []

    def add_init_script(self, script):
        self.scripts.append(script)


class FakePage:
    def __init__(self):
        self.context = FakeContext()
        self.evaluated = []

    def evaluate(self, script):
        self.evaluated.append(script)


class TikTokOverlayCleanupTests(unittest.TestCase):
    def test_init_script_hides_joyride_tour(self):
        script = _TIKTOK_OVERLAY_INIT_JS
        self.assertIn("#react-joyride-portal", script)
        self.assertIn("react-joyride__overlay", script)
        self.assertIn('data-test-id="overlay"', script)
        self.assertIn("pointer-events:none!important", script)
        self.assertIn("MutationObserver", script)

    def test_patch_wraps_browser_once_and_installs_script(self):
        page = FakePage()
        calls = []

        def fake_get_browser(*args, **kwargs):
            calls.append(1)
            return page

        module = types.SimpleNamespace(get_browser=fake_get_browser)
        _install_tiktok_overlay_cleanup(module)
        _install_tiktok_overlay_cleanup(module)  # ikinci çağrı çift sarmamalı

        self.assertIs(module.get_browser(), page)
        self.assertEqual(len(calls), 1)
        self.assertEqual(page.context.scripts, [_TIKTOK_OVERLAY_INIT_JS])
        self.assertEqual(page.evaluated, [_TIKTOK_OVERLAY_INIT_JS])

    def test_patch_survives_a_broken_page_without_failing_upload(self):
        class BrokenPage:
            context = FakeContext()

            def evaluate(self, script):
                raise RuntimeError("page closed")

        calls = []

        def fake_get_browser(*args, **kwargs):
            calls.append(1)
            return BrokenPage()

        module = types.SimpleNamespace(get_browser=fake_get_browser)
        _install_tiktok_overlay_cleanup(module)
        self.assertIsInstance(module.get_browser(), BrokenPage)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
