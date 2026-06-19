"""
FastAPI endpoint tests (Phase 8E).

Uses TestClient WITHOUT the context-manager form so the lifespan (RAG corpus
build) does not run — these routes are LLM-free and corpus-free.
"""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_detect_shape(train_cases):
    r = client.post("/detect", json=train_cases[0])
    assert r.status_code == 200
    body = r.json()
    assert "risk_score" in body
    assert body["recommended_action"] in ("INVESTIGATE", "AUTO_DISMISS")


# ── Test 7: batch size limit ──────────────────────────────────────────────────

def test_triage_batch_size_limit(train_cases):
    payload = {"cases": [train_cases[0]] * 501}
    r = client.post("/triage-batch", json=payload)
    assert r.status_code == 400


def test_triage_queue_empty_then_populated(train_cases):
    # A small batch updates the cache; the queue endpoint then serves it.
    r = client.post("/triage-batch", json={"cases": train_cases[:5]})
    assert r.status_code == 200
    q = client.get("/triage-queue")
    assert q.status_code == 200
    assert "triage_queue" in q.json()
