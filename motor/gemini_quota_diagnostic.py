"""One-call live diagnostic for the current GitHub Actions Gemini Vision secret.

Prints only provider/source details, score or safe Google quota metadata. Never prints
GEMINI_API_KEY, its request URL, or credential contents.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "motor"
if str(MOTOR) not in sys.path:
    sys.path.insert(0, str(MOTOR))

import gorsel_uret as visual  # noqa: E402


def main() -> int:
    os.environ["MOTOR_VISUAL_QA_PASSED"] = "1"
    os.environ.pop("PIXABAY_API_KEY", None)
    pexels_key = (os.getenv("PEXELS_API_KEY") or os.getenv("PEXELS_KEY") or os.getenv("PEXELS_API") or "").strip()
    if not pexels_key:
        raise SystemExit("PEXELS_API_KEY missing in Actions secrets")
    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY missing in Actions secrets")

    query = "pressure gauge"
    scene_text = "A pressure gauge measures pressure in an aircraft cabin and toilet system."
    hits = visual.pexels_ara(query, pexels_key, adet=1)
    if not hits:
        raise SystemExit("Pexels returned no candidates for the diagnostic query")
    hit = hits[0]
    score = visual._visual_text_scores(scene_text, [hit])[0]
    result = {
        "provider": "pexels",
        "query": query,
        "returned_candidates": len(hits),
        "candidate_source_url": str(hit.get("source_page_url") or ""),
        "candidate_image_url": str(hit.get("indir_url") or ""),
        "gemini_model": visual.SEMANTIC_MODEL,
        "semantic_score": score,
        "score_meets_0_62": bool(score is not None and score >= visual.SEMANTIC_THRESHOLD),
        "safe_api_error": hit.get("_vision_error"),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    out = Path(os.getenv("GITHUB_WORKSPACE", ".")) / "gemini_quota_diagnostic.json"
    out.write_text(text + "\n", encoding="utf-8")
    return 0 if score is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
