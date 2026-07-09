"""
Phase 11C Step 2: learn the score-fusion weights from SAML-D (no black box).

Fits a logistic regression on the four layer scores + five typology indicators
over a 70/30 split (seed 42) of the Phase-11B sample, prints every coefficient,
evaluates the held-out 30% for BOTH the hand-tuned formula and the learned one,
and writes the fitted weights to benchmarks/fusion_weights.json — plain,
readable JSON that monitor/scorer.py loads at import (falling back to the
hand-tuned formula if the file is absent).

    python benchmarks/train_fusion.py
"""

from __future__ import annotations

import json
import random
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.fp_attribution import load_cases
from benchmarks.saml_d import fmt_table, metrics

FEATURES = [
    "typology_score",
    "graph_score",
    "behavioral_score",
    "anomaly_score",
    "flag_structuring",
    "flag_fan_out",
    "flag_velocity_spike",
    "flag_sanctions_hit",
    "flag_rapid_passthrough",
]
_SEED = 42
_OUT = Path(__file__).parent / "fusion_weights.json"


def featurize(det: dict) -> list[float]:
    ls = det["layer_scores"]
    fired = {f["typology"] for f in det["typology_flags"]}
    if det["graph_analysis"]["fan_out"]["flagged"]:
        fired.add("fan_out")
    return [
        ls["typology"],
        ls["graph"],
        ls["behavioral"],
        ls["anomaly"],
        float("structuring" in fired),
        float("fan_out" in fired),
        float("velocity_spike" in fired),
        float("sanctions_hit" in fired),
        float("rapid_passthrough" in fired),
    ]


_FEAT_CACHE = Path(__file__).parent / "_saml_features_cache.json"  # gitignored


def _featurize_all() -> tuple[list[list[float]], list[int], list[float]]:
    """Run every cached case through the monitor stack (cached after first run)."""
    from monitor.scorer import run_detection

    if _FEAT_CACHE.exists():
        d = json.loads(_FEAT_CACHE.read_text(encoding="utf-8"))
        return d["X"], d["y"], d["hand_scores"]

    cases = load_cases()
    print(f"Featurizing {len(cases)} cases through the monitor stack...", flush=True)
    t0 = time.perf_counter()
    X, y, hand_scores = [], [], []
    for i, (case, label) in enumerate(cases):
        det = run_detection(case)
        X.append(featurize(det))
        y.append(label)
        hand_scores.append(det["risk_score"])
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(cases)} ({time.perf_counter() - t0:.0f}s)", flush=True)
    _FEAT_CACHE.write_text(
        json.dumps({"X": X, "y": y, "hand_scores": hand_scores}), encoding="utf-8"
    )
    return X, y, hand_scores


def main() -> None:
    from sklearn.linear_model import LogisticRegression

    X, y, hand_scores = _featurize_all()

    idx = list(range(len(y)))
    random.Random(_SEED).shuffle(idx)
    cut = int(len(idx) * 0.7)
    tr, te = idx[:cut], idx[cut:]
    hand_scored = [(hand_scores[i], y[i]) for i in te]

    print(f"\n=== Held-out 30% ({len(te)} cases) — hand-tuned formula ===")
    print(fmt_table([metrics(hand_scored, t / 100) for t in range(30, 95, 5)]))

    # Two variants: plain logistic optimizes accuracy on an 81/19 sample and
    # learns "mostly say no" (high precision, recall collapses). A triage gate's
    # job is recall, so class_weight="balanced" is the operating choice; both
    # are printed so the trade-off is on the record.
    chosen_coefs, chosen_intercept = None, None
    for label, kwargs in [("plain", {}), ("balanced", {"class_weight": "balanced"})]:
        model = LogisticRegression(max_iter=1000, random_state=_SEED, **kwargs)
        model.fit([X[i] for i in tr], [y[i] for i in tr])

        coefs = dict(zip(FEATURES, [round(float(c), 4) for c in model.coef_[0]]))
        intercept = round(float(model.intercept_[0]), 4)
        print(f"\n=== Coefficients — {label} (fully readable) ===")
        for name, c in sorted(coefs.items(), key=lambda kv: -abs(kv[1])):
            print(f"  {name:<24} {c:+.4f}")
        print(f"  {'intercept':<24} {intercept:+.4f}")

        probs = model.predict_proba([X[i] for i in te])[:, 1]
        fused_scored = [(float(p), y[i]) for p, i in zip(probs, te)]
        print(f"\n=== Held-out 30% — learned fusion ({label}) ===")
        print(fmt_table([metrics(fused_scored, t / 100) for t in range(30, 95, 5)]))

        if label == "balanced":
            chosen_coefs, chosen_intercept = coefs, intercept

    _OUT.write_text(
        json.dumps(
            {
                "feature_names": FEATURES,
                "coefficients": chosen_coefs,
                "intercept": chosen_intercept,
                "meta": {
                    "trained_on": "SAML-D sample (Phase 11B, seed 42), 70% train split",
                    "variant": "class_weight=balanced (recall-first: triage-gate operating profile)",
                    "train_cases": len(tr),
                    "test_cases": len(te),
                    "date": date.today().isoformat(),
                    "note": "Logistic regression; scorer falls back to hand-tuned "
                    "weights if this file is missing. Sanctions override to "
                    "1.0 is applied AFTER fusion, in code.",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {_OUT} (balanced variant)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
