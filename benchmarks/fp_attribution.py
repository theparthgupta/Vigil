"""
False-positive attribution on the SAML-D sample (diagnostic, not committed to CI).

Re-derives the exact Phase-11B sample (seed 42) and answers: for clean cases
scoring >= 0.60, WHICH detector/layer put them over the line? Same for the
true positives, so we can see which signals carry recall vs which only add noise.
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.saml_d import (
    _N_CLEAN,
    _N_SUSPICIOUS,
    _SEED,
    build_case,
    collect_transactions,
    scan_accounts,
)
from monitor.scorer import run_detection

THRESHOLD = 0.60


_CACHE = Path(__file__).parent / "_saml_cases_cache.json"  # gitignored diagnostic cache


def load_cases() -> list[tuple[dict, int]]:
    """The exact Phase-11B sample (seed 42), cached after the first build."""
    import json

    if _CACHE.exists():
        return [(c, y) for c, y in json.loads(_CACHE.read_text(encoding="utf-8"))]

    rng = random.Random(_SEED)
    print("Rebuilding the Phase-11B sample (seed 42)...", flush=True)
    sus_accounts, clean_reservoir = scan_accounts()
    sus_sample = set(rng.sample(sorted(sus_accounts), min(_N_SUSPICIOUS, len(sus_accounts))))
    clean_pool = [a for a in dict.fromkeys(clean_reservoir) if a not in sus_accounts]
    clean_sample = set(rng.sample(clean_pool, min(_N_CLEAN, len(clean_pool))))
    txns = collect_transactions(sus_sample | clean_sample)

    cases = []
    for acct, rows in txns.items():
        if len(rows) < 3:
            continue
        cases.append((build_case(acct, rows), 1 if acct in sus_sample else 0))
    _CACHE.write_text(json.dumps(cases), encoding="utf-8")
    return cases


def main() -> None:
    cases = load_cases()

    fp_typologies: Counter = Counter()
    tp_typologies: Counter = Counter()
    fp_graph: Counter = Counter()
    tp_graph: Counter = Counter()
    fp_layer_driver: Counter = Counter()
    n_fp = n_tp = 0

    for i, (case, y) in enumerate(cases):
        det = run_detection(case)
        if det["risk_score"] < THRESHOLD:
            continue
        is_fp = y == 0
        tcount = fp_typologies if is_fp else tp_typologies
        gcount = fp_graph if is_fp else tp_graph
        for f in det["typology_flags"]:
            tcount[f["typology"]] += 1
        for k in ("structuring_ring", "layering_chain", "fan_out", "centrality"):
            if det["graph_analysis"][k]["flagged"]:
                gcount[det["graph_analysis"][k]["typology"]] += 1
        ls = det["layer_scores"]
        driver = max(
            ls,
            key=lambda k: (
                {"typology": 0.45, "graph": 0.20, "behavioral": 0.15, "anomaly": 0.20}[k] * ls[k]
            ),
        )
        if is_fp:
            n_fp += 1
            fp_layer_driver[driver] += 1
        else:
            n_tp += 1
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(cases)}", flush=True)

    print(f"\n=== Cases >= {THRESHOLD}: {n_tp} TP, {n_fp} FP ===")
    print("\nTypology flags on FALSE POSITIVES (what fires on clean accounts):")
    for t, c in fp_typologies.most_common():
        print(f"  {t:<28} {c:>5}  ({c / max(n_fp, 1) * 100:.0f}% of FPs)")
    print("\nGraph flags on FALSE POSITIVES:")
    for t, c in fp_graph.most_common():
        print(f"  {t:<28} {c:>5}  ({c / max(n_fp, 1) * 100:.0f}% of FPs)")
    print("\nTypology flags on TRUE POSITIVES (what carries recall):")
    for t, c in tp_typologies.most_common():
        print(f"  {t:<28} {c:>5}  ({c / max(n_tp, 1) * 100:.0f}% of TPs)")
    print("\nGraph flags on TRUE POSITIVES:")
    for t, c in tp_graph.most_common():
        print(f"  {t:<28} {c:>5}  ({c / max(n_tp, 1) * 100:.0f}% of TPs)")
    print("\nDominant weighted layer on FALSE POSITIVES:")
    for t, c in fp_layer_driver.most_common():
        print(f"  {t:<28} {c:>5}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
