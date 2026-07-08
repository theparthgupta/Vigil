"""
SAML-D benchmark (Phase 11B): run the Vigil monitor stack (Layers 1+2, no LLM)
against an INDEPENDENT public AML dataset and report honest metrics.

Dataset: SAML-D (Oztas et al., IEEE 2023) — 9.5M transactions, 0.104%
laundering, 28 typologies. Downloaded via kagglehub:
    berkanoztas/synthetic-transaction-monitoring-dataset-aml

Mapping decisions (all documented, all deterministic):
  * Account-level cases: for a sampled account, rows where it is the sender
    become debits, rows where it is the receiver become credits.
  * Amounts are GBP; scaled ×100 into INR. Deliberate: SAML-D structures
    around the UK £10K reporting threshold, and ×100 maps that onto the
    Indian ₹10L CTR threshold — preserving the "just under the reporting
    line" semantics the structuring detectors key on.
  * Channels are proxies: Cash Deposit/Withdrawal→cash, Cross-border→RTGS,
    Cheque/ACH→NEFT, Credit/Debit card→UPI.
  * An account is labeled suspicious if it appears in ANY Is_laundering=1 row.

Usage:
    python benchmarks/saml_d.py                # baseline (synthetic-trained IF)
    python benchmarks/saml_d.py --retrain-if   # + Isolation Forest retrained on
                                               #   a SAML-D train split (test half
                                               #   evaluated for both variants)

Writes benchmarks/RESULTS_SAML_D.md and prints the summary.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_DATASET = Path.home() / (
    ".cache/kagglehub/datasets/berkanoztas/"
    "synthetic-transaction-monitoring-dataset-aml/versions/2/SAML-D.csv"
)
_GBP_INR = 100.0          # threshold-semantics scaling (see module docstring)
_SEED = 42
_N_SUSPICIOUS = 500
_N_CLEAN = 2000
_MAX_TXNS_PER_ACCOUNT = 300
_MIN_TXNS_PER_CASE = 3

_CHANNEL_MAP = {
    "Cash Deposit": "cash",
    "Cash Withdrawal": "cash",
    "Cross-border": "RTGS",
    "Cheque": "NEFT",
    "ACH": "NEFT",
    "Credit card": "UPI",
    "Debit card": "UPI",
}


# ── Pass 1: find laundering accounts + reservoir-sample clean accounts ────────

def scan_accounts() -> tuple[set[str], list[str]]:
    rng = random.Random(_SEED)
    sus_accounts: set[str] = set()
    reservoir: list[str] = []
    seen_clean = 0

    with open(_DATASET, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["Is_laundering"] == "1":
                sus_accounts.add(row["Sender_account"])
                sus_accounts.add(row["Receiver_account"])
            else:
                seen_clean += 1
                acct = row["Sender_account"]
                if len(reservoir) < 50_000:
                    reservoir.append(acct)
                else:
                    j = rng.randrange(seen_clean)
                    if j < 50_000:
                        reservoir[j] = acct
    return sus_accounts, reservoir


# ── Pass 2: collect transactions for the sampled accounts ─────────────────────

def collect_transactions(accounts: set[str]) -> dict[str, list[dict]]:
    txns: dict[str, list[dict]] = defaultdict(list)

    def add(acct: str, row: dict, direction: str, counterparty: str) -> None:
        if len(txns[acct]) >= _MAX_TXNS_PER_ACCOUNT:
            return
        txns[acct].append({
            "amount_inr": float(row["Amount"]) * _GBP_INR,
            "timestamp": f"{row['Date']}T{row['Time']}",
            "channel": _CHANNEL_MAP.get(row["Payment_type"], "NEFT"),
            "direction": direction,
            "counterparty_name": counterparty,
        })

    with open(_DATASET, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s, r = row["Sender_account"], row["Receiver_account"]
            if s in accounts:
                add(s, row, "debit", r)
            if r in accounts:
                add(r, row, "credit", s)
    return txns


def build_case(acct: str, transactions: list[dict]) -> dict:
    transactions.sort(key=lambda t: t["timestamp"])
    times = [datetime.fromisoformat(t["timestamp"]) for t in transactions]
    months = max(1.0, (times[-1] - times[0]).days / 30.0)
    volume = sum(t["amount_inr"] for t in transactions)
    return {
        "case_id": f"samld_{acct}",
        "customer": {
            "id": acct,
            "name": f"Account {acct}",
            "business_type": "other",
            "account_open_date": "2019-01-01T00:00:00",
            "stated_monthly_turnover_inr": volume / months,
            "prior_flags": 0,
        },
        "transactions": transactions,
    }


# ── Metrics ────────────────────────────────────────────────────────────────────

def metrics(scored: list[tuple[float, int]], threshold: float) -> dict:
    tp = sum(1 for s, y in scored if s >= threshold and y == 1)
    fp = sum(1 for s, y in scored if s >= threshold and y == 0)
    fn = sum(1 for s, y in scored if s < threshold and y == 1)
    tn = sum(1 for s, y in scored if s < threshold and y == 0)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    return {"threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(f1, 4), "fpr": round(fpr, 4)}


def evaluate(cases: list[tuple[dict, int]], label: str) -> list[dict]:
    from monitor.scorer import run_detection

    scored = []
    t0 = time.perf_counter()
    for i, (case, y) in enumerate(cases):
        scored.append((run_detection(case)["risk_score"], y))
        if (i + 1) % 250 == 0:
            print(f"  [{label}] {i + 1}/{len(cases)} cases "
                  f"({time.perf_counter() - t0:.0f}s)", flush=True)
    rows = [metrics(scored, t / 100) for t in range(30, 95, 5)]
    return rows


def fmt_table(rows: list[dict]) -> str:
    head = "| thr | precision | recall | F1 | FPR | TP/FP/FN/TN |\n|---|---|---|---|---|---|"
    body = "\n".join(
        f"| {r['threshold']:.2f} | {r['precision']:.3f} | {r['recall']:.3f} "
        f"| {r['f1']:.3f} | {r['fpr']:.3f} "
        f"| {r['tp']}/{r['fp']}/{r['fn']}/{r['tn']} |"
        for r in rows
    )
    return head + "\n" + body


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrain-if", action="store_true",
                        help="also evaluate with an Isolation Forest retrained "
                             "on a SAML-D train split")
    args = parser.parse_args()

    if not _DATASET.exists():
        sys.exit(f"Dataset not found: {_DATASET}\nRun kagglehub download first.")

    rng = random.Random(_SEED)
    print("Pass 1: scanning 9.5M rows for laundering + clean accounts...", flush=True)
    sus_accounts, clean_reservoir = scan_accounts()
    print(f"  laundering-involved accounts: {len(sus_accounts)}")

    sus_sample = set(rng.sample(sorted(sus_accounts), min(_N_SUSPICIOUS, len(sus_accounts))))
    clean_pool = [a for a in dict.fromkeys(clean_reservoir) if a not in sus_accounts]
    clean_sample = set(rng.sample(clean_pool, min(_N_CLEAN, len(clean_pool))))

    print("Pass 2: collecting transactions for sampled accounts...", flush=True)
    txns = collect_transactions(sus_sample | clean_sample)

    cases: list[tuple[dict, int]] = []
    for acct, rows in txns.items():
        if len(rows) < _MIN_TXNS_PER_CASE:
            continue
        cases.append((build_case(acct, rows), 1 if acct in sus_sample else 0))
    n_sus = sum(y for _, y in cases)
    print(f"  usable cases: {len(cases)} ({n_sus} suspicious, {len(cases) - n_sus} clean)")

    out = ["# SAML-D benchmark — Vigil monitor stack (no LLM)", "",
           f"Sampled cases: {len(cases)} ({n_sus} suspicious / {len(cases) - n_sus} clean); "
           f"seed {_SEED}; GBP→INR ×{_GBP_INR:.0f}; base rate in full dataset: 0.104%.", ""]

    print("Evaluating baseline (synthetic-trained Isolation Forest)...", flush=True)
    baseline = evaluate(cases, "baseline")
    out += ["## Baseline (IF trained on Vigil synthetic data)", "", fmt_table(baseline), ""]

    if args.retrain_if:
        print("Retraining Isolation Forest on a SAML-D train split...", flush=True)
        import monitor.scorer as scorer
        from monitor.anomaly import extract_features
        from sklearn.ensemble import IsolationForest

        shuffled = cases[:]
        rng.shuffle(shuffled)
        half = len(shuffled) // 2
        train, test = shuffled[:half], shuffled[half:]
        contamination = max(0.01, sum(y for _, y in train) / len(train))
        model = IsolationForest(n_estimators=200, contamination=contamination,
                                random_state=_SEED)
        model.fit([extract_features(c) for c, _ in train])

        original = scorer._ANOMALY_MODEL
        try:
            scorer._ANOMALY_MODEL = model      # swap for this evaluation only
            retrained = evaluate(test, "retrained-IF")
        finally:
            scorer._ANOMALY_MODEL = original   # never touch the app's model

        # Same test half under the baseline model, for a fair comparison.
        base_test = evaluate(test, "baseline-on-test")
        out += [f"## Test half only ({len(test)} cases) — baseline IF", "",
                fmt_table(base_test), "",
                f"## Test half only — IF retrained on SAML-D train split "
                f"(contamination={contamination:.3f})", "", fmt_table(retrained), ""]

    out += ["## Honest caveats", "",
            "- SAML-D is itself synthetic (simulator-generated), but independently "
            "authored — Vigil's detectors were not written against it.",
            "- Channel/currency mappings are proxies (see benchmarks/saml_d.py "
            "docstring); UK geography disables the India-specific detectors "
            "(geographic anomaly, sanctions list), so recall here comes from "
            "structural + behavioral layers only.",
            "- Account histories are capped at 300 transactions; accounts with "
            "<3 transactions are dropped.",
            "- The sample is enriched (20% suspicious vs 0.104% in the wild): "
            "precision here does NOT transfer to production base rates."]

    results = Path(__file__).parent / "RESULTS_SAML_D.md"
    results.write_text("\n".join(out), encoding="utf-8")
    print(f"\nWrote {results}")
    print("\n" + "\n".join(out[4:6]))
    print(fmt_table(baseline))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
