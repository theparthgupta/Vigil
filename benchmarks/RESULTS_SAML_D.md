# SAML-D benchmark — Vigil monitor stack (no LLM)

Sampled cases: 2450 (461 suspicious / 1989 clean); seed 42; GBP→INR ×100; base rate in full dataset: 0.104%.

## Phase 11C before/after (full 2,450-case sample)

**Before** = Phase 11B (hand-tuned fusion, original structuring detector).
**After** = Phase 11C (structuring proportionality + clustering, learned balanced-logistic fusion).

| Threshold | Precision (before) | Precision (after) | Recall (before) | Recall (after) | FPR (before) | FPR (after) |
|---|---|---|---|---|---|---|
| 0.30 | 0.310 | 0.298 | 0.954 | 0.876 | 0.492 | 0.478 |
| 0.45 | 0.309 | 0.352 | 0.944 | 0.805 | 0.489 | 0.343 |
| 0.50 | 0.310 | 0.353 | 0.939 | 0.774 | 0.484 | 0.328 |
| 0.55 | 0.308 | 0.344 | 0.928 | 0.725 | 0.484 | 0.321 |
| 0.60 | 0.287 | 0.356 | 0.790 | 0.642 | 0.455 | 0.269 |
| 0.70 | 0.284 | 0.390 | 0.716 | 0.223 | 0.419 | 0.081 |
| 0.75 | 0.282 | 0.482 | 0.705 | 0.147 | 0.417 | 0.037 |

Read at matched recall (~0.79–0.80): before needed threshold 0.60 with FPR 0.455 /
precision 0.287; after reaches it at threshold 0.45 with **FPR 0.343 (−11 points)
and precision 0.352 (+6.5 points)**. The after-curve is also smooth and tunable —
the old version was flat (~0.31 precision everywhere useful) with a cliff at 0.80;
the new one trades recall for precision continuously up to 0.58 precision.

## Current sweep — Phase 11C stack (structuring fix + learned fusion)

| thr | precision | recall | F1 | FPR | TP/FP/FN/TN |
|---|---|---|---|---|---|
| 0.30 | 0.298 | 0.876 | 0.445 | 0.478 | 404/950/57/1039 |
| 0.35 | 0.304 | 0.848 | 0.448 | 0.450 | 391/894/70/1095 |
| 0.40 | 0.315 | 0.833 | 0.457 | 0.420 | 384/836/77/1153 |
| 0.45 | 0.352 | 0.805 | 0.490 | 0.343 | 371/682/90/1307 |
| 0.50 | 0.353 | 0.774 | 0.485 | 0.328 | 357/653/104/1336 |
| 0.55 | 0.344 | 0.725 | 0.466 | 0.321 | 334/638/127/1351 |
| 0.60 | 0.356 | 0.642 | 0.458 | 0.269 | 296/535/165/1454 |
| 0.65 | 0.351 | 0.317 | 0.333 | 0.136 | 146/270/315/1719 |
| 0.70 | 0.390 | 0.223 | 0.284 | 0.081 | 103/161/358/1828 |
| 0.75 | 0.482 | 0.147 | 0.226 | 0.037 | 68/73/393/1916 |
| 0.80 | 0.548 | 0.111 | 0.184 | 0.021 | 51/42/410/1947 |
| 0.85 | 0.582 | 0.100 | 0.170 | 0.017 | 46/33/415/1956 |
| 0.90 | 1.000 | 0.030 | 0.059 | 0.000 | 14/0/447/1989 |

## Honest caveats

- SAML-D is itself synthetic (simulator-generated), but independently authored — Vigil's detectors were not written against it.
- Channel/currency mappings are proxies (see benchmarks/saml_d.py docstring); UK geography disables the India-specific detectors (geographic anomaly, sanctions list), so recall here comes from structural + behavioral layers only.
- Account histories are capped at 300 transactions; accounts with <3 transactions are dropped.
- The sample is enriched (20% suspicious vs 0.104% in the wild): precision here does NOT transfer to production base rates.