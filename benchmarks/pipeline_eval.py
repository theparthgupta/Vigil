"""
Phase 15: END-TO-END pipeline evaluation on SAML-D (gate -> LLM Reasoner).

The number the project lacked: not "how good is the monitor gate" (Phase 11)
but "how good is the DEPLOYED FUNNEL" — the cheap gate filters, the LLM agent
investigates only survivors, and a case is a system-positive iff the Reasoner
returns ESCALATE.

Design decisions (locked before running — this choice IS the metric):
  * LLM positive = Reasoner decision == "ESCALATE" (the real production signal).
  * Precision population = gate SURVIVORS only (the LLM never sees rejects).
  * Recall population    = ALL labeled positives in the sample (a gate miss is a
                          system miss even though the LLM never saw it).
  * Report BOTH stage-wise (gate, LLM) and end-to-end (system) numbers.
  * Precision reported at enriched prevalence AND the true SAML-D base rate
    (0.104%) via P = TPR·p / (TPR·p + FPR·(1-p)). This formula depends only on
    TPR/FPR/prevalence, NOT on the sample's pos:neg ratio — so we STRATIFY the
    survivor sample (fixed #pos + #neg) to guarantee enough positives for a
    usable recall CI, with no bias to precision.
  * Uncertainty: BOOTSTRAP the compound system numbers (resample gate cases and
    the LLM'd pos/neg groups, recompute system_TPR/FPR/precision per iteration,
    take 2.5/97.5 percentiles). Stage-wise Wilson CIs alone understate the real
    error because both stages' errors propagate.
  * Unparseable rule (pre-registered): a case that doesn't yield a clean
    ESCALATE after one retry — exception, empty, or off-vocabulary decision —
    counts as NOT-ESCALATE and is logged with a separate count.

LLM decisions are cached per case_id (resumable; re-runs are free).

    python benchmarks/pipeline_eval.py                    # 100 pos + 100 neg
    python benchmarks/pipeline_eval.py --n-pos 60 --n-neg 60
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.fp_attribution import load_cases

_SEED = 42
_TRUE_BASE_RATE = 0.00104  # SAML-D full-dataset laundering prevalence
_N_BOOT = 5000
_GATE_SCORE_CACHE = Path(__file__).parent / "_saml_gate_scores.json"  # gitignored
_LLM_CACHE = Path(__file__).parent / "_saml_llm_decisions.json"  # gitignored


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def precision_at_prevalence(tpr: float, fpr: float, p: float) -> float:
    denom = tpr * p + fpr * (1 - p)
    return (tpr * p) / denom if denom > 0 else 0.0


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def gate_scores(cases: list[tuple[dict, int]]) -> list[dict]:
    """Score every case through the monitor stack once; cache the result."""
    if _GATE_SCORE_CACHE.exists():
        return json.loads(_GATE_SCORE_CACHE.read_text(encoding="utf-8"))

    from monitor.scorer import run_detection

    print(f"Scoring {len(cases)} cases through the monitor gate...", flush=True)
    t0 = time.perf_counter()
    out = []
    for i, (case, label) in enumerate(cases):
        det = run_detection(case)
        out.append({"case_id": case["case_id"], "label": label, "risk_score": det["risk_score"]})
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(cases)} ({time.perf_counter() - t0:.0f}s)", flush=True)
    _GATE_SCORE_CACHE.write_text(json.dumps(out), encoding="utf-8")
    return out


def _load_llm_cache() -> dict:
    return json.loads(_LLM_CACHE.read_text(encoding="utf-8")) if _LLM_CACHE.exists() else {}


def llm_decision(case: dict, cache: dict) -> str:
    """
    Return 'ESCALATE' | 'DISMISS' | 'UNPARSEABLE' | 'ERROR' for a case.
    Cached per case_id. One retry on exception before giving up.
    """
    cid = case["case_id"]
    if cid in cache:
        return cache[cid]

    from agent.graph import graph
    from agent.state import initial_state
    from monitor.scorer import run_detection

    detection = run_detection(case)  # rides along as pre-screening (mirrors prod)
    verdict = "ERROR"
    for attempt in range(2):
        try:
            result = graph.invoke(
                initial_state(case, detection_result=detection),
                config={"tags": ["pipeline_eval"], "run_name": f"pe-{cid}"},
            )
            decision = (result.get("decision") or "").strip().upper()
            verdict = decision if decision in ("ESCALATE", "DISMISS") else "UNPARSEABLE"
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 1:
                print(f"    ERROR {cid}: {e}", flush=True)
    cache[cid] = verdict
    _LLM_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return verdict


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-pos", type=int, default=100, help="positive survivors to sample")
    parser.add_argument("--n-neg", type=int, default=100, help="negative survivors to sample")
    parser.add_argument("--threshold", type=float, default=0.60)
    args = parser.parse_args()

    cases = load_cases()
    by_id = {c["case_id"]: c for c, _ in cases}
    scores = gate_scores(cases)

    total = len(scores)
    total_pos = sum(s["label"] for s in scores)
    total_neg = total - total_pos

    survivors = [s for s in scores if s["risk_score"] >= args.threshold]
    surv_pos = [s for s in survivors if s["label"] == 1]
    surv_neg = [s for s in survivors if s["label"] == 0]
    gate_tp, gate_fp = len(surv_pos), len(surv_neg)
    gate_recall = gate_tp / total_pos if total_pos else 0.0
    gate_fpr = gate_fp / total_neg if total_neg else 0.0
    gate_prec = gate_tp / len(survivors) if survivors else 0.0

    print(
        f"\nSample: {total} cases ({total_pos} pos / {total_neg} neg, "
        f"{total_pos / total * 100:.1f}% enriched).\n"
        f"Gate @ {args.threshold}: {len(survivors)} survivors "
        f"({gate_tp} pos / {gate_fp} neg); recall {gate_recall:.3f}, FPR {gate_fpr:.3f}.",
        flush=True,
    )

    # Stratified sample: fixed #pos + #neg (no seed gamble on positive count).
    rng = random.Random(_SEED)
    pick_pos = rng.sample(surv_pos, min(args.n_pos, len(surv_pos)))
    pick_neg = rng.sample(surv_neg, min(args.n_neg, len(surv_neg)))
    print(
        f"Running the LLM on {len(pick_pos)} pos + {len(pick_neg)} neg survivors (stratified)...",
        flush=True,
    )

    cache = _load_llm_cache()
    t0 = time.perf_counter()

    def decisions_for(group: list[dict]) -> list[str]:
        out = []
        for j, s in enumerate(group):
            out.append(llm_decision(by_id[s["case_id"]], cache))
            if (j + 1) % 20 == 0:
                print(f"  {j + 1}/{len(group)} ({time.perf_counter() - t0:.0f}s)", flush=True)
        return out

    print("  [positives]", flush=True)
    pos_dec = decisions_for(pick_pos)
    print("  [negatives]", flush=True)
    neg_dec = decisions_for(pick_neg)

    def esc(ds: list[str]) -> list[int]:  # ESCALATE=1, everything else (incl. unparseable)=0
        return [1 if d == "ESCALATE" else 0 for d in ds]

    pos_esc, neg_esc = esc(pos_dec), esc(neg_dec)
    n_pos, n_neg = len(pos_esc), len(neg_esc)
    llm_recall = sum(pos_esc) / n_pos if n_pos else 0.0
    llm_esc_neg = sum(neg_esc) / n_neg if n_neg else 0.0
    unparseable = sum(d == "UNPARSEABLE" for d in pos_dec + neg_dec)
    errored = sum(d == "ERROR" for d in pos_dec + neg_dec)

    # LLM precision on the survivor sample it saw, reweighted to the survivor
    # base rate (stratification makes the raw sample ratio artificial).
    w_pos = gate_tp / (n_pos or 1)
    w_neg = gate_fp / (n_neg or 1)
    llm_prec = (
        (w_pos * sum(pos_esc)) / (w_pos * sum(pos_esc) + w_neg * sum(neg_esc))
        if (sum(pos_esc) + sum(neg_esc))
        else 0.0
    )

    # Point estimates for the compound system numbers.
    system_tpr = gate_recall * llm_recall
    system_fpr = gate_fpr * llm_esc_neg
    p_enriched = total_pos / total
    sys_prec_enriched = precision_at_prevalence(system_tpr, system_fpr, p_enriched)
    sys_prec_true = precision_at_prevalence(system_tpr, system_fpr, _TRUE_BASE_RATE)
    gate_prec_true = precision_at_prevalence(gate_recall, gate_fpr, _TRUE_BASE_RATE)

    # Bootstrap the compound numbers: resample gate cases + LLM pos/neg groups.
    boot = {"tpr": [], "fpr": [], "pe": [], "pt": []}
    labels = [s["label"] for s in scores]
    surv_flags = [1 if s["risk_score"] >= args.threshold else 0 for s in scores]
    for _ in range(_N_BOOT):
        idx = [rng.randrange(total) for _ in range(total)]
        b_pos = sum(labels[i] for i in idx) or 1
        b_neg = (total - sum(labels[i] for i in idx)) or 1
        b_gtp = sum(1 for i in idx if surv_flags[i] and labels[i])
        b_gfp = sum(1 for i in idx if surv_flags[i] and not labels[i])
        g_rec, g_fpr = b_gtp / b_pos, b_gfp / b_neg
        l_rec = sum(pos_esc[rng.randrange(n_pos)] for _ in range(n_pos)) / n_pos if n_pos else 0.0
        l_neg = sum(neg_esc[rng.randrange(n_neg)] for _ in range(n_neg)) / n_neg if n_neg else 0.0
        tpr, fpr = g_rec * l_rec, g_fpr * l_neg
        boot["tpr"].append(tpr)
        boot["fpr"].append(fpr)
        boot["pe"].append(precision_at_prevalence(tpr, fpr, p_enriched))
        boot["pt"].append(precision_at_prevalence(tpr, fpr, _TRUE_BASE_RATE))

    def ci(key: str) -> str:
        return f"[{pct(boot[key], 0.025):.4f}, {pct(boot[key], 0.975):.4f}]"

    rec_lo, rec_hi = wilson(sum(pos_esc), n_pos)
    neg_lo, neg_hi = wilson(sum(neg_esc), n_neg)
    lift = sys_prec_true / gate_prec_true if gate_prec_true else float("nan")

    md = f"""# Phase 15 — end-to-end pipeline evaluation (SAML-D)

Deployed funnel: monitor gate (threshold {args.threshold}) -> LLM Reasoner
(system-positive = decision ESCALATE). Seed {_SEED}. Stratified LLM sample:
{n_pos} positive + {n_neg} negative gate survivors. Unparseable/off-vocabulary
outputs: {unparseable}; hard errors after retry: {errored} (both counted as
NOT-ESCALATE per the pre-registered rule). Compound CIs: {_N_BOOT}-iteration
bootstrap (resampling gate cases + LLM groups).

## Definitions (locked before running)
- LLM positive = Reasoner `decision == "ESCALATE"`.
- Precision population = gate survivors only. Recall population = all {total_pos} labeled positives.

## Stage-wise
| Stage | Precision | Recall | Notes |
|---|---|---|---|
| Gate @ {args.threshold} | {gate_prec:.3f} | {gate_recall:.3f} | full {total}-case sample; FPR {gate_fpr:.3f} |
| LLM on survivors | {llm_prec:.3f} | {llm_recall:.3f} | survivor-base-rate weighted; on {n_pos + n_neg} sampled survivors |

LLM conditional rates (Wilson 95% CI):
- P(ESCALATE | survivor, laundering) = {llm_recall:.3f}  [{rec_lo:.3f}, {rec_hi:.3f}]  (n={n_pos})
- P(ESCALATE | survivor, clean)      = {llm_esc_neg:.3f}  [{neg_lo:.3f}, {neg_hi:.3f}]  (n={n_neg})

## End-to-end system (gate AND LLM, over the whole labeled sample) — bootstrap 95% CI
- System recall (TPR) = gate_recall × P(ESC|surv,pos) = **{system_tpr:.3f}**  {ci("tpr")}
- System FPR          = gate_FPR × P(ESC|surv,neg)   = **{system_fpr:.4f}**  {ci("fpr")}

### Precision at different prevalences (the number reviewers ask for)
| Population | Prevalence | Gate-only precision | Full-system precision | System 95% CI |
|---|---|---|---|---|
| Enriched sample | {p_enriched * 100:.1f}% | {precision_at_prevalence(gate_recall, gate_fpr, p_enriched):.3f} | **{sys_prec_enriched:.3f}** | {ci("pe")} |
| True SAML-D base rate | {_TRUE_BASE_RATE * 100:.3f}% | {gate_prec_true:.4f} | **{sys_prec_true:.4f}** | {ci("pt")} |

## How to read this
The LLM stage's job is to lift precision on the gate's survivors while keeping
recall. At true prevalence, alert precision is structurally tiny for ANY AML
system (0.104% of accounts are positive) — the honest comparison is gate-only
vs full-system precision at the SAME base rate:
**{gate_prec_true:.4f} -> {sys_prec_true:.4f}** ({lift:.1f}× at the point estimate).
The enriched-sample figure ({sys_prec_enriched:.3f}) is the demoable number and
does NOT transfer to production prevalence — reporting both is the entire point.

## Caveats
- Estimate from {n_pos + n_neg} survivors, not all {len(survivors)}; see the bootstrap intervals.
- Independence: system rates multiply gate × LLM conditional rates, assuming the
  LLM's survivor error rate doesn't correlate with how far above threshold a case
  scored. Directionally sound; not exact. The bootstrap does not capture this term.
- SAML-D is simulator-generated and foreign-shaped (India detectors disabled;
  numeric counterparty names mean the sanctions tool never fires) — this measures
  the STRUCTURAL/behavioral pipeline, not sanctions screening.
"""
    out = Path(__file__).parent / "RESULTS_PIPELINE.md"
    out.write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"Wrote {out}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
