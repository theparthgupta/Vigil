"""
Tests for Layer-2C ML anomaly detection (monitor/anomaly.py).

The Isolation Forest is trained on the synthetic train split. Tests cover
feature extraction, training/loading, detection shape, a soft directional
sanity check, and the four-layer score formula. No LLM, no network.
"""

from monitor import run_detection
from monitor.anomaly import (
    _MODEL_PATH,
    detect_anomaly,
    extract_features,
    load_or_train_model,
    train_isolation_forest,
)
from monitor.scorer import combine_scores


# ── 1. extract_features returns exactly 12 floats ─────────────────────────────


def test_extract_features_twelve_floats(cases_by_typology):
    feats = extract_features(cases_by_typology["structuring"][0])
    assert len(feats) == 12
    assert all(isinstance(f, float) for f in feats)


# ── 2. Empty transactions handled ─────────────────────────────────────────────


def test_extract_features_empty():
    feats = extract_features({"transactions": [], "customer": {"prior_flags": 0}})
    assert feats == [0.0] * 12


# ── 3. Model trains without error ─────────────────────────────────────────────


def test_train_returns_isolation_forest():
    from sklearn.ensemble import IsolationForest

    model = train_isolation_forest()
    assert isinstance(model, IsolationForest)


# ── 4. load_or_train works cold and warm ──────────────────────────────────────


def test_load_or_train_cold_then_warm():
    if _MODEL_PATH.exists():
        _MODEL_PATH.unlink()
    m1 = load_or_train_model()  # cold → trains + writes pkl
    assert _MODEL_PATH.exists()
    m2 = load_or_train_model()  # warm → loads pkl
    assert type(m1) is type(m2)


# ── 5. detect_anomaly shape ───────────────────────────────────────────────────


def test_detect_anomaly_shape(cases_by_typology):
    model = load_or_train_model()
    out = detect_anomaly(cases_by_typology["sanctions_hit"][0], model=model)
    for key in ("flagged", "typology", "confidence", "evidence", "anomaly_score", "regulatory_ref"):
        assert key in out
    assert out["typology"] == "ml_anomaly"


# ── 6. Directional sanity: sanctions cases not less anomalous than clean ───────


def test_directional_anomaly_scores(cases_by_typology):
    model = load_or_train_model()
    clean = [detect_anomaly(c, model=model)["anomaly_score"] for c in cases_by_typology["clean"]]
    sus = [
        detect_anomaly(c, model=model)["anomaly_score"] for c in cases_by_typology["sanctions_hit"]
    ]
    clean_avg = sum(clean) / len(clean)
    sus_avg = sum(sus) / len(sus)
    print(f"\nclean avg anomaly_score={clean_avg:.4f}  sanctions avg={sus_avg:.4f}")
    assert sus_avg >= clean_avg - 0.05  # soft, generous margin (probabilistic)


# ── 7. run_detection includes anomaly_analysis ────────────────────────────────


def test_run_detection_has_anomaly_key(cases_by_typology):
    out = run_detection(cases_by_typology["clean"][0])
    assert "anomaly_analysis" in out
    assert out["anomaly_analysis"]["typology"] == "ml_anomaly"


# ── 8. Four-layer score formula ───────────────────────────────────────────────


def test_combine_scores_four_components():
    # 0.5*0.45 + 0.4*0.20 + 0.3*0.15 + 0.6*0.20 = 0.225 + 0.08 + 0.045 + 0.12 = 0.47
    assert combine_scores(0.5, 0.4, 0.3, 0.6, has_sanctions=False) == 0.47
