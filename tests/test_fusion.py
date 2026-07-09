"""
Phase 11C Step 2: learned score-fusion tests (monitor/scorer.py + weights JSON).
"""

import json
from pathlib import Path

from monitor.scorer import _FUSION, combine_scores, run_detection

_WEIGHTS = Path(__file__).parent.parent / "benchmarks" / "fusion_weights.json"


# ── 1. Weights file exists, is readable JSON, and the scorer loaded it ────────

def test_fusion_weights_loaded():
    d = json.loads(_WEIGHTS.read_text(encoding="utf-8"))
    assert set(d["coefficients"]) == set(d["feature_names"])
    assert _FUSION is not None
    assert _FUSION["names"] == d["feature_names"]


# ── 2. Legacy path is untouched when flags are omitted ────────────────────────

def test_legacy_path_unchanged():
    assert combine_scores(0.5, 0.4, 0.3, 0.6, has_sanctions=False) == 0.47


# ── 3. Sanctions override survives fusion ─────────────────────────────────────

def test_sanctions_override_after_fusion():
    fused = combine_scores(0.9, 0.5, 0.2, 0.3, has_sanctions=True,
                           flags={"structuring", "sanctions_hit"})
    assert fused == 1.0


# ── 4. Fused scores are bounded, native floats, and deterministic ─────────────

def test_fused_score_bounded_and_deterministic(cases_by_typology):
    out1 = run_detection(cases_by_typology["structuring"][0])
    out2 = run_detection(cases_by_typology["structuring"][0])
    assert isinstance(out1["risk_score"], float)
    assert 0.0 <= out1["risk_score"] <= 1.0
    assert out1["risk_score"] == out2["risk_score"]


# ── 5. Score explanation: contributions are Python-computed and consistent ────

def test_score_explanation_shape(cases_by_typology):
    out = run_detection(cases_by_typology["structuring"][0])
    exp = out["score_explanation"]
    assert exp["mode"] in ("learned_fusion", "hand_tuned")
    assert exp["risk_score"] == out["risk_score"]
    for item in exp["items"]:
        assert set(item) == {"feature", "label", "value", "weight", "contribution"}
        assert item["contribution"] == round(item["value"] * item["weight"], 4)
