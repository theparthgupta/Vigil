# Phase 15 — end-to-end pipeline evaluation (SAML-D)

Deployed funnel: monitor gate (threshold 0.6) -> LLM Reasoner
(system-positive = decision ESCALATE). Seed 42. Stratified LLM sample:
100 positive + 100 negative gate survivors. Unparseable/off-vocabulary
outputs: 0; hard errors after retry: 0 (both counted as
NOT-ESCALATE per the pre-registered rule). Compound CIs: 5000-iteration
bootstrap (resampling gate cases + LLM groups).

## Definitions (locked before running)
- LLM positive = Reasoner `decision == "ESCALATE"`.
- Precision population = gate survivors only. Recall population = all 461 labeled positives.

## Stage-wise
| Stage | Precision | Recall | Notes |
|---|---|---|---|
| Gate @ 0.6 | 0.356 | 0.642 | full 2450-case sample; FPR 0.269 |
| LLM on survivors | 0.000 | 0.000 | survivor-base-rate weighted; on 200 sampled survivors |

LLM conditional rates (Wilson 95% CI):
- P(ESCALATE | survivor, laundering) = 0.000  [0.000, 0.037]  (n=100)
- P(ESCALATE | survivor, clean)      = 0.010  [0.002, 0.054]  (n=100)

## End-to-end system (gate AND LLM, over the whole labeled sample) — bootstrap 95% CI
- System recall (TPR) = gate_recall × P(ESC|surv,pos) = **0.000**  [0.0000, 0.0000]
- System FPR          = gate_FPR × P(ESC|surv,neg)   = **0.0027**  [0.0000, 0.0084]

### Precision at different prevalences (the number reviewers ask for)
| Population | Prevalence | Gate-only precision | Full-system precision | System 95% CI |
|---|---|---|---|---|
| Enriched sample | 18.8% | 0.356 | **0.000** | [0.0000, 0.0000] |
| True SAML-D base rate | 0.104% | 0.0025 | **0.0000** | [0.0000, 0.0000] |

## The finding: the LLM stage nullifies the gate's recall on SAML-D
The full-pipeline recall is **0.000** — the LLM Reasoner dismissed all 100
sampled laundering survivors (P(ESCALATE | survivor, laundering) = 0.000,
Wilson CI [0.000, 0.037]) and escalated only 1 of 100 clean ones. So on this
data the LLM stage does not *lift* precision, it *destroys recall*: the gate
catches 64% of launderers cheaply, then the LLM waves them through.

### Root cause (verified on a real case, not a bug)
Example `samld_6233217293` (laundering, gate risk 0.613, flagged via
`round_trip`): the Reasoner ran profile + patterns + sanctions, found 0
sanctions hits and no structuring / rapid-passthrough indicators, and concluded
DISMISS at 0.90 confidence. `unparseable=0, errored=0` — every decision was a
clean ESCALATE/DISMISS, so this is genuine reasoning.

The mechanism is a **vocabulary mismatch**: the gate flags cases using 10
typologies + graph structure (cycles, fan-out) + behavioral baselines, but the
LLM investigator's evidence tools (`analyze_patterns`) and prompt weigh a
narrower set — structuring, rapid pass-through, sanctions. SAML-D's laundering
is dominated by round-trip / cycle / fan-in-out patterns the gate's graph layer
catches but the LLM's tools never surface. So the LLM re-derives suspicion from
scratch on a smaller signal set and finds nothing it recognizes. The gate's own
reason for flagging (`typology_flags`, graph analysis) is passed as
`pre_screening` but is only used to skip sanctions re-runs — it is NOT put in
front of the Reasoner's LLM. That is the actionable gap (see below).

## How to read the precision numbers
At true prevalence, alert precision is structurally tiny for ANY AML system
(0.104% of accounts are positive) — the honest comparison is gate-only vs
full-system precision at the SAME base rate. Here the full system's precision is
**0.000**: with recall at 0, there are essentially no true positives left to be
precise about. The enriched-sample figure does NOT transfer to production
prevalence — reporting both is the entire point, and reporting recall alongside
is what stops a high-precision-via-near-zero-recall number from looking good.

### The fix this measurement identifies (next phase, then re-run this harness)
Surface the gate's `typology_flags` + graph findings into the Reasoner's prompt
so it reasons about *why the gate flagged the case* instead of re-deriving
suspicion from a narrower tool set. This exact harness (deterministic, seed 42,
cached) then re-measures the lift — that is the payoff loop.

## Caveats
- Estimate from 200 survivors, not all 831; see the bootstrap intervals.
- Independence: system rates multiply gate × LLM conditional rates, assuming the
  LLM's survivor error rate doesn't correlate with how far above threshold a case
  scored. Directionally sound; not exact. The bootstrap does not capture this term.
- SAML-D is simulator-generated and foreign-shaped (India detectors disabled;
  numeric counterparty names mean the sanctions tool never fires) — this measures
  the STRUCTURAL/behavioral pipeline, not sanctions screening.
