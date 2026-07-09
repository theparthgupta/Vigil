"""
RAG retrieve for Vigil — pgvector backend (Phase 9A).

Drop-in replacement for rag/retrieve.py: identical retrieve() signature and
return shape, backed by the CocoIndex-maintained pgvector table instead of
Chroma. The document-level citation is mapped from the source filename via the
same _DOCS registry used at ingest (the table itself stores only source).

    from rag.retrieve_pg import retrieve
    results = retrieve("structuring threshold cash transaction India", k=4)
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from rag.ingest import _DOCS  # noqa: E402  (import needs the sys.path bootstrap above)

_TABLE = "vigil_regulatory_chunks"
# Map PDF filename -> human-readable citation (table stores only `source`).
_CITATION_BY_SOURCE = {d["filename"]: d["citation"] for d in _DOCS}

_embedder = None
_init_lock = threading.Lock()


def _connect():
    """Open a fresh libpq connection (handles the URL-encoded password)."""
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _get_embedder():
    global _embedder
    if _embedder is None:
        with _init_lock:
            if _embedder is None:
                from langchain_openai import OpenAIEmbeddings

                _embedder = OpenAIEmbeddings(model="text-embedding-3-small")
    return _embedder


def retrieve(
    query: str,
    k: int = 4,
    source_filter: str | None = None,
) -> list[dict]:
    """
    Semantic search over the regulatory corpus (pgvector cosine similarity).

    Args:
        query:         Natural-language query.
        k:             Number of passages to return.
        source_filter: If set, restrict to a single PDF filename.

    Returns list of dicts:
        text      str   — passage text
        citation  str   — human-readable source (e.g. "PMLA 2002 (Act No. 15 of 2003)")
        source    str   — PDF filename
        section   str   — section header detected in the chunk
        page      int   — page number where the chunk starts
        score     float — cosine similarity, 0–1 (higher = more relevant)
    """
    query_vec = _get_embedder().embed_query(query)
    vec_literal = "[" + ",".join(str(float(x)) for x in query_vec) + "]"

    where = "WHERE source = %s" if source_filter else ""
    params: list = [vec_literal]
    if source_filter:
        params.append(source_filter)
    params += [vec_literal, k]

    sql = (
        f"SELECT text, source, section, page, "
        f"1 - (embedding <=> %s::vector) AS score "
        f"FROM {_TABLE} {where} "
        f"ORDER BY embedding <=> %s::vector LIMIT %s"
    )

    with _connect() as conn, conn.cursor() as cur:
        # HNSW is approximate; the default ef_search (40) drops valid neighbors on
        # this small corpus. 200 gives full recall here (matches exact search) while
        # staying fast. Set per session before the query.
        cur.execute("SET hnsw.ef_search = 200")
        cur.execute(sql, params)
        rows = cur.fetchall()

    passages = []
    for text, source, section, page, score in rows:
        passages.append(
            {
                "text": text,
                "citation": _CITATION_BY_SOURCE.get(source, source),
                "source": source,
                "section": section,
                "page": page,
                "score": round(float(score), 4),
            }
        )
    return passages


def format_passage(p: dict, idx: int) -> str:
    """Pretty-print a single passage for inspection."""
    lines = [
        f"[{idx}] {p['citation']} | {p['section']} | p.{p['page']} | score={p['score']}",
        "-" * 72,
        p["text"][:600] + ("..." if len(p["text"]) > 600 else ""),
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    QUERIES = [
        "structuring threshold cash transaction reporting India",
        "STR filing timeline days suspicious transaction promptly",
        "politically exposed person definition enhanced due diligence",
    ]
    print("=== Vigil RAG sanity test (pgvector) ===\n")
    for query in QUERIES:
        print(f"QUERY: {query}")
        print("=" * 72)
        for i, p in enumerate(retrieve(query, k=5)[:2], 1):
            print(format_passage(p, i))
        print()
