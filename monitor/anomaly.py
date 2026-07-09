"""
Layer 2C of the Vigil monitor: unsupervised anomaly detection via
Isolation Forest.

⚠️ IMPORTANT CALIBRATION CAVEAT:
This model is trained on 160 SYNTHETIC cases with known, cleanly-
separable typologies. Its anomaly scores reflect deviation from the
synthetic training distribution, NOT validated real-world risk.

Before production use at any real institution, this model MUST be
retrained on that institution's actual (anonymized) transaction
history. Treat anomaly_score as a directional signal to be combined
with the other three layers (typology, graph, behavioral) — never as
a standalone decision.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path

import joblib

_MODEL_PATH = Path(__file__).parent / "isolation_forest.pkl"
_DEFAULT_TRAIN = "data/cases_train.json"


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


# ── Step 1: feature extraction ────────────────────────────────────────────────


def extract_features(case: dict) -> list[float]:
    """12 numerical features from a case. Returns [0.0]*12 for no transactions."""
    txns = case.get("transactions", [])
    customer = case.get("customer", {})
    if not txns:
        return [0.0] * 12

    n = len(txns)
    amounts = [t["amount_inr"] for t in txns]
    times = sorted(_dt(t["timestamp"]) for t in txns)

    return [
        float(n),  # 1
        float(sum(amounts)),  # 2
        sum(amounts) / n,  # 3
        float(statistics.pstdev(amounts)) if n > 1 else 0.0,  # 4
        sum(1 for t in txns if t["channel"] == "cash") / n,  # 5
        sum(1 for t in txns if t["channel"] == "UPI") / n,  # 6
        sum(1 for t in txns if t["channel"] in ("RTGS", "NEFT")) / n,  # 7
        sum(1 for t in txns if t["direction"] == "credit") / n,  # 8
        float(len({t["counterparty_name"] for t in txns})),  # 9
        float(max(amounts)),  # 10
        float((times[-1] - times[0]).days) if n > 1 else 0.0,  # 11
        float(customer.get("prior_flags", 0)),  # 12
    ]


# ── Step 2: training ──────────────────────────────────────────────────────────


def train_isolation_forest(train_data_path: str = _DEFAULT_TRAIN):
    """Train an Isolation Forest on the synthetic train split and persist it."""
    from sklearn.ensemble import IsolationForest

    path = Path(train_data_path)
    if not path.is_absolute() and not path.exists():
        path = Path(__file__).parent.parent / train_data_path

    cases = json.loads(path.read_text(encoding="utf-8"))
    features = [extract_features(c) for c in cases]

    model = IsolationForest(
        n_estimators=200,
        contamination=0.25,  # matches the ~25% synthetic suspicious rate
        random_state=42,
    )
    model.fit(features)

    joblib.dump(model, _MODEL_PATH)
    return model


def load_or_train_model():
    """Load the persisted model; train (and persist) it if missing or corrupt."""
    if _MODEL_PATH.exists():
        try:
            return joblib.load(_MODEL_PATH)
        except Exception:
            pass  # corrupted pickle → retrain
    return train_isolation_forest()


# ── Step 3: detection ─────────────────────────────────────────────────────────


def detect_anomaly(case: dict, model=None) -> dict:
    if model is None:
        model = load_or_train_model()

    features = extract_features(case)
    decision_score = float(model.decision_function([features])[0])
    prediction = int(model.predict([features])[0])  # -1 = anomaly, 1 = normal

    anomaly_score = float(max(0.0, min(1.0, 0.5 - decision_score)))
    flagged = bool(prediction == -1)

    return {
        "flagged": flagged,
        "typology": "ml_anomaly",
        "confidence": round(anomaly_score, 4) if flagged else 0.0,
        "evidence": {
            "raw_decision_score": round(float(decision_score), 4),
            "anomaly_score": round(anomaly_score, 4),
            "feature_vector": [round(f, 2) for f in features],
        },
        "anomaly_score": round(anomaly_score, 4),
        "regulatory_ref": (
            "Internal ML model — pattern deviation from training distribution "
            "(synthetic; must be retrained on real data before production use)"
        ),
    }
