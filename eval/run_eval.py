"""
Evaluation harness for Vigil (Phase 5).

Runs every case in the TRAIN split through the agent, captures the decision and
diagnostics, saves a results JSON, and prints the metric report. Each run is
tagged in LangSmith (default tag: "baseline") so it is filterable later.

Usage:
    python eval/run_eval.py                                   # baseline, all 160
    python eval/run_eval.py --tag optimized --out eval/results_optimized.json
    python eval/run_eval.py --limit 4                         # smoke test
    python eval/run_eval.py --workers 8

NEVER reads cases_holdout.json (locked until final eval).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from agent.graph import graph
from agent.state import initial_state
from eval.metrics import compute_metrics, format_report

load_dotenv()

_TRAIN = Path(__file__).parent.parent / "data" / "cases_train.json"


def _run_case(case: dict, tag: str) -> dict:
    """Invoke the agent on one case; return a result row."""
    config = {
        "tags": [tag, "phase-5-eval"],
        "run_name": f"eval-{tag}-{case['case_id']}",
        "metadata": {"eval_tag": tag, "case_id": case["case_id"]},
    }
    t0 = time.perf_counter()
    try:
        out = graph.invoke(initial_state(case), config=config)
        latency = time.perf_counter() - t0
        return {
            "case_id": case["case_id"],
            "ground_truth_label": case["ground_truth_label"],
            "ground_truth_typology": case["typology"],
            "decision": out["decision"],
            "confidence": round(out["confidence"], 4),
            "detected_typology": out.get("detected_typology", ""),
            "loop_fired": out["investigation_passes"] > 1,
            "investigation_passes": out["investigation_passes"],
            "latency_s": round(latency, 2),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — record, don't abort the batch
        latency = time.perf_counter() - t0
        return {
            "case_id": case["case_id"],
            "ground_truth_label": case["ground_truth_label"],
            "ground_truth_typology": case["typology"],
            "decision": "ERROR",
            "confidence": 0.0,
            "detected_typology": "",
            "loop_fired": False,
            "investigation_passes": 0,
            "latency_s": round(latency, 2),
            "error": str(exc),
        }


def run_eval(
    tag: str, out_path: Path, workers: int, limit: int | None, cases_path: Path | None = None
) -> dict:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    src = cases_path or _TRAIN
    cases = json.loads(src.read_text(encoding="utf-8"))
    print(f"Source: {src.name}")
    if limit:
        cases = cases[:limit]

    print(f"Running {len(cases)} cases through the agent (tag='{tag}', workers={workers})...")
    t0 = time.perf_counter()

    results: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_case, c, tag): c for c in cases}
        for fut in as_completed(futures):
            results.append(fut.result())
            done += 1
            if done % 10 == 0 or done == len(cases):
                sys.stdout.write(f"  {done}/{len(cases)} done\r")
                sys.stdout.flush()
    print()

    # Stable order by case_id for reproducible diffs
    results.sort(key=lambda r: r["case_id"])

    errors = [r for r in results if r["error"]]
    if errors:
        print(f"WARNING: {len(errors)} case(s) errored:")
        for e in errors[:5]:
            print(f"  {e['case_id']}: {e['error']}")

    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"Saved {len(results)} results -> {out_path}  (wall clock {time.perf_counter() - t0:.1f}s)"
    )

    metrics = compute_metrics([r for r in results if r["error"] is None])
    print()
    print(format_report(metrics, title=f"REPORT — {tag}"))
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="baseline")
    parser.add_argument("--out", default="eval/results_baseline.json")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--cases", default=None, help="Path to a cases JSON (defaults to cases_train.json)"
    )
    args = parser.parse_args()

    run_eval(
        args.tag, Path(args.out), args.workers, args.limit, Path(args.cases) if args.cases else None
    )
