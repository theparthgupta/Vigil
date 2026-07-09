"""
FastAPI backend for Vigil (Phase 6).

Serves the single-page UI (app/static) and the agent API.

Endpoints:
    GET  /            — Vigil web UI (static SPA)
    GET  /health      — liveness check
    GET  /sample      — one random case from the TRAIN split (for the UI to load)
    POST /investigate — run a case through the LangGraph agent, return the decision

Run: uvicorn api.main:app --reload
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from agent.costing import TokenUsageHandler
from agent.graph import graph
from agent.state import initial_state
from api import store
from data.schema import BusinessType, Case, Channel, Direction
from monitor.pipeline import process_batch, process_case

load_dotenv()

_ROOT = Path(__file__).parent.parent
_TRAIN = _ROOT / "data" / "cases_train.json"
_STATIC = _ROOT / "app" / "static"


def _corpus_count() -> int:
    """How many chunks are in the pgvector table (0 if it doesn't exist yet)."""
    from rag.retrieve_pg import _TABLE, _connect

    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {_TABLE}")
            return cur.fetchone()[0]
    except Exception:
        return 0


def _ensure_corpus() -> None:
    """
    Make sure the pgvector RAG index exists before serving requests.

    On a fresh deploy the table is empty, so build it with the CocoIndex flow
    (which sets up the table/index and embeds regs/*.pdf). If already populated,
    this is a fast no-op — CocoIndex detects no source changes.
    """
    existing = _corpus_count()
    if existing > 0:
        print(f"RAG corpus ready ({existing} chunks, CocoIndex/pgvector).")
        return

    print("Building RAG corpus via CocoIndex/pgvector...", flush=True)
    from rag.cocoindex_flow import init_cocoindex, vigil_regulatory_corpus

    init_cocoindex()
    vigil_regulatory_corpus.setup()
    vigil_regulatory_corpus.update()
    print(
        f"Building RAG corpus via CocoIndex/pgvector... done ({_corpus_count()} chunks)", flush=True
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the RAG corpus and the case-store tables before serving requests.
    _ensure_corpus()
    store.init_tables()
    yield


app = FastAPI(
    title="Vigil AML Investigation API",
    description="Autonomous AML triage agent for Indian financial institutions (PMLA/FIU-IND).",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
def index() -> FileResponse:
    """Serve the Vigil single-page UI."""
    return FileResponse(_STATIC / "index.html")


class InvestigateRequest(Case):
    """A Case plus optional pre-computed monitor detection (from /detect or the
    triage queue). Backwards-compatible: callers that POST a bare Case still work
    — detection_result defaults to None and the agent runs exactly as before."""

    detection_result: Optional[dict] = None


class InvestigateResponse(BaseModel):
    case_id: str
    decision: str
    confidence: float
    detected_typology: str
    report: str
    investigation_steps: list[str]
    latency_seconds: float
    tokens_used: int = 0
    cost_inr: float = 0.0


class TriageBatchRequest(BaseModel):
    cases: list[Case]


_MAX_BATCH = 500
# Most recent batch triage result, served by GET /triage-queue.
_last_batch_result: Optional[dict] = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "vigil-api"}


@app.get("/sample")
def sample() -> dict:
    """Return one random TRAIN case so the UI has something to load instantly."""
    cases = json.loads(_TRAIN.read_text(encoding="utf-8"))
    return random.choice(cases)


# ── CSV batch upload ──────────────────────────────────────────────────────────

_REQUIRED_CSV_COLS = [
    "customer_name",
    "business_type",
    "monthly_turnover_lakhs",
    "prior_flags",
    "account_opened",
    "txn_date",
    "amount_inr",
    "direction",
    "channel",
    "counterparty",
]
_VALID_CHANNELS = {c.value for c in Channel}
_VALID_DIRECTIONS = {d.value for d in Direction}
_VALID_BTYPES = {b.value for b in BusinessType}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "customer"


@app.post("/parse-csv")
async def parse_csv(file: UploadFile = File(...)) -> dict:
    """
    Parse an uploaded transaction CSV into schema-valid Case objects.

    Rows sharing a customer_name are grouped into one Case. Row-level problems
    (bad amount/direction/channel) are collected as warnings and the row is
    skipped — one bad row never fails the whole upload. Missing columns or a
    file with no data rows are hard 400 errors.
    """
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    headers = reader.fieldnames or []

    missing = [c for c in _REQUIRED_CSV_COLS if c not in headers]
    if missing:
        raise HTTPException(400, f"CSV missing required column(s): {', '.join(missing)}")

    rows = list(reader)
    if not rows:
        raise HTTPException(400, "CSV has no transaction rows")

    warnings: list[str] = []
    grouped: dict[str, dict] = {}
    order: list[str] = []

    for i, row in enumerate(rows, start=2):  # header is line 1; data starts at line 2
        name = (row.get("customer_name") or "").strip()
        if not name:
            warnings.append(f"Row {i}: missing customer_name, skipped")
            continue

        amt_raw = (row.get("amount_inr") or "").strip().replace(",", "")
        try:
            amount = float(amt_raw)
        except ValueError:
            warnings.append(
                f"Row {i} ({name}): non-numeric amount_inr '{row.get('amount_inr')}', skipped"
            )
            continue

        direction = (row.get("direction") or "").strip().lower()
        if direction not in _VALID_DIRECTIONS:
            warnings.append(
                f"Row {i} ({name}): invalid direction '{row.get('direction')}', skipped"
            )
            continue

        channel = (row.get("channel") or "").strip()
        if channel not in _VALID_CHANNELS:
            warnings.append(f"Row {i} ({name}): invalid channel '{row.get('channel')}', skipped")
            continue

        if name not in grouped:
            order.append(name)
            btype = (row.get("business_type") or "").strip().lower()
            if btype not in _VALID_BTYPES:
                warnings.append(
                    f"Row {i} ({name}): unknown business_type '{row.get('business_type')}', defaulted to 'other'"
                )
                btype = "other"
            try:
                turnover = float((row.get("monthly_turnover_lakhs") or "0").strip())
            except ValueError:
                turnover = 0.0
            try:
                flags = int(float((row.get("prior_flags") or "0").strip()))
            except ValueError:
                flags = 0
            opened = (row.get("account_opened") or "").strip() or "2020-01-01"
            slug = _slug(name)
            grouped[name] = {
                "slug": slug,
                "customer": {
                    "id": f"cust_csv_{slug}",
                    "name": name,
                    "business_type": btype,
                    "account_open_date": opened + "T00:00:00",
                    "stated_monthly_turnover_inr": turnover * 1e5,
                    "prior_flags": flags,
                },
                "txns": [],
            }

        g = grouped[name]
        date = (row.get("txn_date") or "").strip() or "2024-01-01"
        g["txns"].append(
            {
                "id": f"txn_csv_{g['slug']}_{len(g['txns'])}",
                "customer_id": g["customer"]["id"],
                "amount_inr": amount,
                "timestamp": date + "T00:00:00",
                "counterparty_name": (row.get("counterparty") or "").strip() or "Unknown",
                "counterparty_account": "".join(random.choices("0123456789", k=14)),
                "direction": direction,
                "channel": channel,
            }
        )

    cases = []
    for idx, name in enumerate(order):
        g = grouped[name]
        if not g["txns"]:
            continue
        cases.append(
            {
                "case_id": f"csv_{g['slug']}_{idx}",
                "customer": g["customer"],
                "transactions": g["txns"],
                "ground_truth_label": "custom",
                "typology": None,
                "notes": "Imported from CSV batch upload.",
            }
        )

    # Round-trip through the Pydantic schema so downstream endpoints accept them as-is.
    validated = [json.loads(Case(**c).model_dump_json()) for c in cases]

    return {
        "cases": validated,
        "customer_count": len(validated),
        "total_transaction_count": sum(len(c["transactions"]) for c in validated),
        "warnings": warnings,
    }


@app.post("/detect")
def detect(case: Case) -> dict:
    """Cheap monitor triage for one case (no LLM). Sub-second."""
    case_dict = json.loads(case.model_dump_json())
    return process_case(case_dict)


@app.post("/triage-batch")
def triage_batch(req: TriageBatchRequest) -> dict:
    """Triage a batch of cases; cache the result for GET /triage-queue."""
    global _last_batch_result
    if len(req.cases) > _MAX_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"Batch too large: {len(req.cases)} cases (max {_MAX_BATCH}).",
        )
    cases = [json.loads(c.model_dump_json()) for c in req.cases]
    _last_batch_result = process_batch(cases)

    # Persist every triaged case so the queue/history survive a refresh (10B).
    try:
        by_id = {c["case_id"]: c for c in cases}
        for r in _last_batch_result["triage_queue"]:
            top = r["typology_flags"][0]["typology"] if r["typology_flags"] else None
            store.save_triage(by_id[r["case_id"]], r["risk_score"], True, top)
        for d in _last_batch_result["dismissed_cases"]:
            store.save_triage(by_id[d["case_id"]], d["risk_score"], False, None)
    except Exception as e:  # persistence must never fail the triage response
        print(f"WARN: case-store persistence failed: {e}")

    return _last_batch_result


@app.get("/triage-queue")
def triage_queue() -> dict:
    """Return the most recent batch triage result (empty if none run yet)."""
    if _last_batch_result is None:
        return {"message": "No batch processed yet", "triage_queue": []}
    return _last_batch_result


# ── Case lifecycle (Phase 10B) ────────────────────────────────────────────────


class ReviewRequest(BaseModel):
    reviewer: str
    action: str  # "approve" | "override"
    rationale: str = ""


@app.get("/dashboard/stats")
def dashboard_stats() -> dict:
    """Aggregate lifecycle counts for the dashboard band."""
    return store.get_stats()


@app.get("/cases")
def cases_list(status: Optional[str] = None, limit: int = 50) -> dict:
    """Most-recent-first persisted cases, optionally filtered by status."""
    return {"cases": store.list_cases(status=status, limit=min(limit, 200))}


@app.get("/cases/{case_id}")
def case_detail(case_id: str) -> dict:
    """Full case record: payload, agent result, review audit trail."""
    try:
        return store.get_case(case_id)
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.post("/cases/{case_id}/review")
def case_review(case_id: str, req: ReviewRequest) -> dict:
    """Record the human decision on an investigated case (the audit trail)."""
    if not req.reviewer.strip():
        raise HTTPException(400, "reviewer name is required")
    try:
        return store.record_review(case_id, req.reviewer.strip(), req.action, req.rationale)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/investigate", response_model=InvestigateResponse)
def investigate(req: InvestigateRequest) -> InvestigateResponse:
    """Run a single case through the agent and return the decision + report.

    If `detection_result` is supplied (case already cleared the monitor gate),
    it is passed into the graph as pre-screening so the Investigator can skip
    redundant tool calls.
    """
    case_dict = json.loads(req.model_dump_json(exclude={"detection_result"}))

    usage = TokenUsageHandler()
    t0 = time.perf_counter()
    result = graph.invoke(
        initial_state(case_dict, detection_result=req.detection_result),
        config={"tags": ["api"], "run_name": f"api-{req.case_id}", "callbacks": [usage]},
    )
    latency = time.perf_counter() - t0
    cost = usage.summary()

    try:
        store.save_investigation(
            case_dict,
            result["decision"],
            result["confidence"],
            result.get("detected_typology", ""),
            result["report"],
            tokens_used=cost["total_tokens"],
            cost_inr=cost["cost_inr"],
        )
    except Exception as e:
        print(f"WARN: case-store persistence failed: {e}")

    return InvestigateResponse(
        case_id=req.case_id,
        decision=result["decision"],
        confidence=round(result["confidence"], 4),
        detected_typology=result.get("detected_typology", ""),
        report=result["report"],
        investigation_steps=result["investigation_steps"],
        latency_seconds=round(latency, 2),
        tokens_used=cost["total_tokens"],
        cost_inr=cost["cost_inr"],
    )


# ── Streaming investigation (Server-Sent Events) ──────────────────────────────
# Emits per-node progress as the LangGraph agent runs, so the UI can show each
# node firing in real time instead of freezing on a ~25s synchronous call.

_RUNNING_MSG = {
    "planner": "Planning the investigation…",
    "investigator": "Gathering evidence: sanctions, patterns, profile…",
    "reasoner": "Reasoning against PMLA / RBI regulation…",
    "reporter": "Drafting the Suspicious Transaction Report…",
}
_ORDER = ["planner", "investigator", "reasoner", "reporter"]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _done_message(node: str, delta: dict, final: dict) -> str:
    """Human-readable 'what this node just did' line, built from the state delta."""
    if node == "planner":
        return "Planner selected tools: " + ", ".join(delta.get("tool_plan", []))
    if node == "investigator":
        san = final.get("evidence", {}).get("sanctions", {})
        hits = len(san.get("hits", []))
        ran = list(final.get("evidence", {}).keys())
        return (
            f"Evidence gathered. Sanctions: {hits} hit(s) of "
            f"{san.get('checked', 0)} screened; ran {', '.join(ran)}"
        )
    if node == "reasoner":
        # name the regulatory sources actually read
        srcs, seen = [], set()
        for p in final.get("retrieved_passages", []):
            short = p["citation"].split(" (")[0]
            if short not in seen:
                seen.add(short)
                srcs.append(short)
        src_str = "; ".join(srcs[:3]) if srcs else "regulatory corpus"
        conf = int(round(delta.get("confidence", 0.0) * 100))
        return f"Read {src_str} → {delta.get('decision', '?')} ({conf}% confidence)"
    if node == "reporter":
        return f"STR drafted ({len(delta.get('report', ''))} characters)"
    return node


@app.post("/investigate/stream")
def investigate_stream(req: InvestigateRequest) -> StreamingResponse:
    """Run the agent and stream per-node progress as SSE, ending with the result.

    Accepts an optional `detection_result` (batch-triage rows already cleared the
    monitor gate) so the same streaming modal serves both sample/custom cases and
    one-click investigations from the triage queue. Backwards-compatible.
    """
    case_dict = json.loads(req.model_dump_json(exclude={"detection_result"}))

    def gen():
        usage = TokenUsageHandler()
        t0 = time.perf_counter()
        final: dict = {}
        # announce the first node as "running"
        yield _sse("status", {"stage": "planner", "message": _RUNNING_MSG["planner"]})

        for update in graph.stream(
            initial_state(case_dict, detection_result=req.detection_result),
            config={
                "tags": ["api", "stream"],
                "run_name": f"api-stream-{req.case_id}",
                "callbacks": [usage],
            },
            stream_mode="updates",
        ):
            for node, delta in update.items():
                final.update(delta)
                if node in _ORDER:
                    yield _sse("node", {"node": node, "message": _done_message(node, delta, final)})
                    idx = _ORDER.index(node)
                    if idx < len(_ORDER) - 1:
                        nxt = _ORDER[idx + 1]
                        yield _sse("status", {"stage": nxt, "message": _RUNNING_MSG[nxt]})

        cost = usage.summary()
        try:
            store.save_investigation(
                case_dict,
                final.get("decision", ""),
                final.get("confidence", 0.0),
                final.get("detected_typology", ""),
                final.get("report", ""),
                tokens_used=cost["total_tokens"],
                cost_inr=cost["cost_inr"],
            )
        except Exception as e:
            print(f"WARN: case-store persistence failed: {e}")

        yield _sse(
            "done",
            {
                "case_id": req.case_id,
                "decision": final.get("decision", ""),
                "confidence": round(final.get("confidence", 0.0), 4),
                "detected_typology": final.get("detected_typology", ""),
                "report": final.get("report", ""),
                "investigation_steps": final.get("investigation_steps", []),
                "latency_seconds": round(time.perf_counter() - t0, 2),
                "tokens_used": cost["total_tokens"],
                "cost_inr": cost["cost_inr"],
            },
        )

    return StreamingResponse(gen(), media_type="text/event-stream")


# Static assets (styles.css, app.js). Mounted last so it never shadows API routes.
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
