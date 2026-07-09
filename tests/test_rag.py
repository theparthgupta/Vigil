"""
Phase 3 RAG pipeline tests.

Verifies:
 - retrieve() returns results with all required metadata fields
 - PEP definition query hits RBI KYC document
 - PMLA Section 12 (reporting obligations) is retrievable
 - Sanctions reporting (CTR/STR) context is retrievable from RBI
"""

from rag.retrieve_pg import retrieve


_REQUIRED_KEYS = {"text", "citation", "source", "section", "page", "score"}


def test_retrieve_returns_required_fields():
    results = retrieve("suspicious transaction reporting", k=3)
    assert len(results) > 0
    for r in results:
        assert _REQUIRED_KEYS <= r.keys(), f"Missing keys: {_REQUIRED_KEYS - r.keys()}"


def test_retrieve_scores_in_valid_range():
    results = retrieve("money laundering", k=5)
    for r in results:
        assert 0.0 <= r["score"] <= 1.0, f"Score out of range: {r['score']}"


def test_pep_query_hits_rbi_document():
    """PEP definition must come from RBI KYC Master Directions."""
    results = retrieve("politically exposed person definition enhanced due diligence", k=5)
    sources = [r["source"] for r in results]
    assert "169MD.pdf" in sources, (
        f"Expected RBI KYC (169MD.pdf) in top-5 for PEP query. Got: {sources}"
    )
    # Best RBI result should mention PEP or politically exposed
    rbi_results = [r for r in results if r["source"] == "169MD.pdf"]
    assert any(
        "pep" in r["text"].lower() or "politically exposed" in r["text"].lower()
        for r in rbi_results
    )


def test_pmla_section12_retrievable():
    """PMLA Section 12 (reporting entity to maintain records) must be findable."""
    results = retrieve(
        "reporting entity maintain records transactions furnish Director",
        k=5,
        source_filter="A2003-15.pdf",
    )
    assert len(results) > 0
    top = results[0]
    assert "reporting entity" in top["text"].lower() or "maintain" in top["text"].lower()
    assert top["source"] == "A2003-15.pdf"


def test_ctr_str_context_retrievable_from_rbi():
    """CTR/STR reporting context must come from RBI or FIU documents."""
    results = retrieve("cash transaction report CTR suspicious transaction report STR filing", k=5)
    sources = {r["source"] for r in results}
    assert sources & {"169MD.pdf", "Reporting_Format.pdf"}, (
        f"Expected RBI or FIU-IND in top-5 for CTR/STR query. Got: {sources}"
    )


def test_source_filter_restricts_results():
    results = retrieve("money laundering", k=5, source_filter="A2003-15.pdf")
    for r in results:
        assert r["source"] == "A2003-15.pdf"


def test_k_parameter_respected():
    for k in [1, 3, 5]:
        results = retrieve("reporting entity", k=k)
        assert len(results) == k


def test_citation_is_human_readable():
    results = retrieve("KYC due diligence customer", k=3)
    for r in results:
        # Citation should not just be a filename
        assert not r["citation"].endswith(".pdf"), (
            f"Citation looks like a filename: {r['citation']}"
        )
        assert len(r["citation"]) > 10
