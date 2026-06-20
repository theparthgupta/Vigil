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


# ── Phase 10A: CSV batch upload (/parse-csv) ──────────────────────────────────

_HEADER = ("customer_name,business_type,monthly_turnover_lakhs,prior_flags,"
           "account_opened,txn_date,amount_inr,direction,channel,counterparty")


def _csv_upload(text: str):
    return client.post(
        "/parse-csv",
        files={"file": ("batch.csv", text, "text/csv")},
    )


def test_parse_csv_valid():
    # 3 customers, 8 rows total.
    rows = [
        "Alpha Traders,retail,30,0,2020-01-01,2024-04-01,40000,credit,UPI,Customer A",
        "Alpha Traders,retail,30,0,2020-01-01,2024-04-02,55000,debit,NEFT,Supplier A",
        "Alpha Traders,retail,30,0,2020-01-01,2024-04-03,60000,credit,UPI,Customer B",
        "Beta Foods,restaurant,20,0,2021-05-05,2024-04-01,90000,credit,cash,Cash Deposit",
        "Beta Foods,restaurant,20,0,2021-05-05,2024-04-02,30000,debit,UPI,Vendor X",
        "Gamma Logistics,logistics,75,1,2019-09-09,2024-04-01,1200000,debit,RTGS,Partner Z",
        "Gamma Logistics,logistics,75,1,2019-09-09,2024-04-02,150000,credit,NEFT,Client P",
        "Gamma Logistics,logistics,75,1,2019-09-09,2024-04-03,180000,credit,NEFT,Client Q",
    ]
    r = _csv_upload(_HEADER + "\n" + "\n".join(rows))
    assert r.status_code == 200
    body = r.json()
    assert body["customer_count"] == 3
    assert body["total_transaction_count"] == 8
    assert body["warnings"] == []


def test_parse_csv_missing_column():
    bad_header = _HEADER.replace(",channel", "")  # drop "channel"
    r = _csv_upload(bad_header + "\nX,retail,10,0,2020-01-01,2024-01-01,1000,credit,Y")
    assert r.status_code == 400
    assert "channel" in r.json()["detail"]


def test_parse_csv_malformed_row_skipped():
    rows = [
        "Alpha,retail,30,0,2020-01-01,2024-04-01,40000,credit,UPI,A",
        "Alpha,retail,30,0,2020-01-01,2024-04-02,55000,debit,NEFT,B",
        "Alpha,retail,30,0,2020-01-01,2024-04-03,60000,credit,UPI,C",
        "Alpha,retail,30,0,2020-01-01,2024-04-04,70000,debit,NEFT,D",
        "Alpha,retail,30,0,2020-01-01,2024-04-05,80000,credit,UPI,E",
        "Alpha,retail,30,0,2020-01-01,2024-04-06,abc,credit,UPI,F",  # bad amount
    ]
    r = _csv_upload(_HEADER + "\n" + "\n".join(rows))
    assert r.status_code == 200
    body = r.json()
    assert body["total_transaction_count"] == 5
    assert len(body["warnings"]) == 1
    assert "amount_inr" in body["warnings"][0]


def test_parse_csv_empty():
    r = _csv_upload(_HEADER)  # headers only, no data rows
    assert r.status_code == 400
    assert "no transaction rows" in r.json()["detail"].lower()


def test_parse_csv_grouping():
    rows = [
        "CustA,retail,30,0,2020-01-01,2024-04-01,1000,credit,UPI,a1",
        "CustA,retail,30,0,2020-01-01,2024-04-02,2000,credit,UPI,a2",
        "CustA,retail,30,0,2020-01-01,2024-04-03,3000,credit,UPI,a3",
        "CustB,sme,40,0,2020-01-01,2024-04-01,4000,debit,NEFT,b1",
        "CustB,sme,40,0,2020-01-01,2024-04-02,5000,debit,NEFT,b2",
    ]
    r = _csv_upload(_HEADER + "\n" + "\n".join(rows))
    body = r.json()
    assert body["customer_count"] == 2
    cases = {c["customer"]["name"]: c for c in body["cases"]}
    assert len(cases["CustA"]["transactions"]) == 3
    assert len(cases["CustB"]["transactions"]) == 2


def test_parsed_cases_feed_triage_batch():
    rows = [
        "CustA,retail,30,0,2020-01-01,2024-04-01,1000,credit,UPI,a1",
        "CustA,retail,30,0,2020-01-01,2024-04-02,2000,credit,UPI,a2",
        "CustB,sme,40,0,2020-01-01,2024-04-01,4000,debit,NEFT,b1",
    ]
    parsed = _csv_upload(_HEADER + "\n" + "\n".join(rows)).json()
    r = client.post("/triage-batch", json={"cases": parsed["cases"]})
    assert r.status_code == 200
    body = r.json()
    assert body["total_cases"] == 2
    assert body["flagged_for_investigation"] + body["auto_dismissed"] == 2
    assert "triage_queue" in body
