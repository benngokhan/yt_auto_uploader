"""Explicit publication-only test gate. No provider calls or uploads in this runner.
Existing tests retain their original mocks/behavior; this is not a network sandbox.
Run from the repository root: python scripts/publication_tests.py
"""
from pathlib import Path
import sys
import os
import socket
import unittest

PUBLICATION_TESTS = (
    'test_bugun_planla.py',
    'test_crosspost_user_disabled.py',
    'test_delivery_diagnostics.py',
    'test_drive_dosya_koruma.py',
    'test_plan_tablo.py',
    'test_previous_video_immutable.py',
    'test_related_plan.py',
    'test_sequential_queue.py',
    'test_slot_guard.py',
    'test_thumbnail_pipeline.py',
    'test_upload_reporting_integration.py',
    'test_views_baseline_fix.py',
    'test_watchdog_dispatch.py',
    'test_youtube_guvenlik.py',
)


def main(root=None, loader=None, runner=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    tests = root / 'tests'
    if not all((tests / name).is_file() for name in PUBLICATION_TESTS):
        print('Publication gate: required test file missing.', file=sys.stderr)
        return 2
    # Publication regression tests must never call live provider/publishing endpoints.
    for key in list(os.environ):
        if any(mark in key for mark in ('API_KEY', 'GOOGLE_TOKEN', 'GOOGLE_CLIENT', 'TELEGRAM', 'GH_TOKEN', 'GITHUB_TOKEN')):
            os.environ.pop(key, None)
    def deny_network(*args, **kwargs):
        raise AssertionError('Network disabled in publication tests')
    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    sys.path.insert(0, str(root))
    loader = loader if loader is not None else unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in PUBLICATION_TESTS:
        selected = loader.discover(str(tests), pattern=name)
        if not selected.countTestCases():
            print('Publication gate: required file collected zero tests: ' + name, file=sys.stderr)
            return 2
        suite.addTests(selected)
    if not suite.countTestCases():
        print('Publication gate: zero tests collected.', file=sys.stderr)
        return 2
    result = (runner if runner is not None else unittest.TextTestRunner(verbosity=2)).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
