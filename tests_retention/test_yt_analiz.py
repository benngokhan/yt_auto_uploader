import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import retansiyon_raporu as rr  # noqa: E402
import yt_analiz as ya  # noqa: E402


def _engagement_report():
    headers = ["views", "likes", "comments", "shares", "averageViewPercentage",
               "video", "estimatedMinutesWatched", "averageViewDuration"]
    rows = [
        [1000, 40, 12, 5, 55.0, "abcdefghijk", 200.0, 30.0],
        [300, 3, 1, 0, 40.0, "abcdefghij2", 60.0, 20.0],
    ]
    return {"columnHeaders": [{"name": name} for name in headers], "rows": rows}


def _details():
    return {
        "abcdefghijk": {"title": "Mum neden söner?", "published": "2026-10-01T00:00:00Z", "duration": 300.0},
        "abcdefghij2": {"title": "Kısa klip", "published": "2026-10-02T00:00:00Z", "duration": 45.0},
    }


class PureAnalysisTests(unittest.TestCase):
    def test_normalize_curve_clamps_replay_above_100_but_keeps_raw(self):
        points = [(0.10, 1.23), (0.05, 0.80)]
        got = ya.normalize_curve(points, 100)
        self.assertEqual([row["sec"] for row in got], [5.0, 10.0])
        self.assertEqual(got[1]["pct"], 100.0)
        self.assertEqual(got[1]["raw_pct"], 123.0)

    def test_pre_drop_peak_finds_twist_before_drop(self):
        points = ya.normalize_curve([(0.04, 0.80), (0.08, 0.60), (0.12, 0.55)], 300)
        hit = ya.detect_pre_drop_peak(points, 300)
        self.assertEqual(hit["signal"], "pre_drop_peak")
        self.assertEqual(hit["timestamp_sec"], 12.0)
        self.assertGreaterEqual(hit["drop_pp"], 20.0)

    def test_rebound_wins_when_recovery_is_stronger(self):
        points = ya.normalize_curve([(0.02, 0.70), (0.04, 0.65), (0.10, 0.20), (0.16, 0.80)], 300)
        hit = ya.choose_highlight(points, 300)
        self.assertEqual(hit["signal"], "dip_recovery")
        self.assertEqual(hit["timestamp_sec"], 30.0)

    def test_empty_curve_is_unknown_not_zero(self):
        hit = ya.choose_highlight([], 300)
        self.assertEqual(hit["signal"], "unknown")
        self.assertEqual(hit["confidence"], 0.0)

    def test_scores_are_bounded_and_missing_data_lowers_confidence(self):
        full = ya.engagement_score(1000, 50, 10)
        missing = ya.engagement_score(1000, None, None)
        self.assertGreater(full["score"], missing["score"])
        self.assertIn("like_rate", full)
        self.assertLessEqual(ya.retention_score(80, 40, 300, {"peak_pct": 90}), 1.0)
        trend, growth = ya.trend_score(1000, 100, 800, 100)
        self.assertGreater(trend, 0.0)
        self.assertEqual(growth, 8.0)

    def test_parse_engagement_report_accepts_any_header_order(self):
        rows = ya.parse_engagement_report(_engagement_report())
        self.assertEqual(rows[0]["video_id"], "abcdefghijk")
        self.assertEqual(rows[0]["comments"], 12.0)
        self.assertEqual(rows[0]["missing_fields"], [])
        bad = _engagement_report()
        bad["rows"].append(bad["rows"][0])
        with self.assertRaises(rr.SafeError):
            ya.parse_engagement_report(bad)

    def test_long_filter_and_handoff_contract(self):
        rows = ya.parse_engagement_report(_engagement_report())
        candidates = ya.build_candidates(rows, _details(), {}, {}, 650.0, 30)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        ya.attach_curves(candidates, {"abcdefghijk": [(0.05, 0.9), (0.12, 0.6), (0.20, 0.7)]}, 650.0)
        candidate = candidates[0]
        self.assertNotEqual(candidate["highlight"]["signal"], "unknown")
        handoff = ya.build_handoff(candidate)
        self.assertEqual(handoff["scene_count"], 7)
        self.assertTrue(handoff["cta_added_by_motor"])
        self.assertEqual(handoff["cta"], "Daha fazla Bilgi Dozu için takip et!")

    def test_rank_is_deterministic(self):
        base = {
            "duration_sec": 300.0, "views": 100, "likes": 1, "comments": 1,
            "average_percent": 50.0, "average_seconds": 20.0,
            "views_last7": 10.0, "views_prev7": 5.0, "missing_fields": [],
            "highlight": dict(ya.UNKNOWN_HIGHLIGHT),
        }
        one = dict(base, video_id="aaaaaaaaaaa")
        two = dict(base, video_id="bbbbbbbbbbb")
        ya.score_candidate(one, 100.0)
        ya.score_candidate(two, 100.0)
        first = ya.rank_candidates([two, one])
        second = ya.rank_candidates([one, two])
        self.assertEqual([row["video_id"] for row in first], [row["video_id"] for row in second])
        self.assertEqual([row["rank"] for row in first], [1, 2])


class AnalyzeFlowTests(unittest.TestCase):
    def test_analyze_produces_top_candidate_without_publishing_side_effects(self):
        report = _engagement_report()
        with mock.patch.object(ya, "fetch_engagement", return_value=report), \
             mock.patch.object(ya.rr, "video_details", return_value=_details()), \
             mock.patch.object(ya, "fetch_views_window", side_effect=[{"abcdefghijk": 500.0}, {"abcdefghijk": 100.0}]), \
             mock.patch.object(ya.rr, "acquire_curves",
                               return_value={"abcdefghijk": [(0.05, 0.9), (0.12, 0.6), (0.20, 0.8)]}):
            result = ya.analyze("token", 30, 5, 3)
        self.assertEqual(result["schema"], 1)
        self.assertEqual(result["candidate_count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["video_id"], "abcdefghijk")
        self.assertEqual(candidate["retention"]["curve_status"], "ready")
        self.assertEqual(candidate["short_handoff"]["scene_count"], 7)
        self.assertNotIn("potential_claim", json.dumps(candidate["scores"]))


if __name__ == "__main__":
    unittest.main()
